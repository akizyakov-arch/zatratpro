"""One canonical document workflow for messenger and application adapters."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hashlib
import logging
from secrets import token_urlsafe

from app.services.database import get_pool
from app.services.document_drafts import PendingDocument, _adapter
from app.services.document_checks import document_warnings, review_fingerprint, warning_text
from app.services.document_processing import recognize_document
from app.services.documents import DocumentService, DocumentValidationError
from app.services.json_formatter import format_document_preview
from app.services.membership import require_member
from app.services.recognition import get_provider_for_user, PROVIDERS
from app.services.workspace import WorkspaceService

logger = logging.getLogger(__name__)


class DocumentFlowError(ValueError):
    pass


@dataclass
class DocumentAction:
    label: str
    name: str
    value: str = ''


@dataclass
class DocumentView:
    text: str
    upload_id: str = ''
    actions: list[DocumentAction] = field(default_factory=list)
    document_id: int | None = None


class DocumentFlow:
    def __init__(self):
        self.documents = DocumentService()

    @asynccontextmanager
    async def transaction(self, actor):
        async with get_pool().acquire() as c, c.transaction():
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f'document:{actor}')
            member = await require_member(c, actor)
            await c.fetchval('SELECT id FROM companies WHERE id=$1 FOR UPDATE', member['company_id'])
            await c.fetchval('SELECT id FROM users WHERE id=$1 AND is_active FOR NO KEY UPDATE', actor)
            current = await require_member(c, actor)
            if current['company_id'] != member['company_id']:
                raise DocumentFlowError('Компания изменилась. Отправьте документ заново.')
            yield c, current

    async def _row(self, c, actor, member, upload_id=None):
        row = await c.fetchrow('SELECT * FROM pending_document_flows WHERE actor_id=$1 FOR UPDATE', actor)
        if (row is None or row['company_id'] != member['company_id']
                or (upload_id is not None and row['upload_id'] != upload_id)
                or not await c.fetchval('SELECT expires_at>clock_timestamp() FROM pending_document_flows WHERE actor_id=$1', actor)):
            raise DocumentFlowError('Эта загрузка завершена или истекла. Отправьте документ заново.')
        return row

    async def _store(self, c, actor, pending):
        await c.execute('UPDATE pending_document_flows SET data=$2::jsonb,expires_at=clock_timestamp()+interval \'15 minutes\' WHERE actor_id=$1', actor, _adapter.dump_json(pending).decode())

    async def _projects(self, c, actor, member, pending, page=1):
        rows = await c.fetch("SELECT id,name FROM projects WHERE company_id=$1 AND status='active' ORDER BY created_at,id", member['company_id'])
        page = max(1, min(page, max(1, (len(rows)+19)//20)))
        actions = [DocumentAction(row['name'], 'project', str(row['id'])) for row in rows[(page-1)*20:page*20]]
        for target in (page-1, page+1):
            if 0 < target <= (len(rows)+19)//20:
                actions.append(DocumentAction('←' if target < page else '→', 'projects', str(target)))
        if member['role'] == 'manager':
            actions.append(DocumentAction('Создать новый проект', 'create_project'))
        actions.append(DocumentAction('🛑 Отменить', 'cancel'))
        preview = pending.normalized_text if pending else 'Обработка документа ещё не завершена.'
        text = preview + '\n\nПроверьте количества, суммы и реквизиты, затем выберите проект для сохранения.'
        if not rows:
            text += '\nАктивных проектов пока нет.'
        return DocumentView(text, pending.upload_id, actions)

    async def receive(self, actor, platform, event_id, source_type, download, caption='', notify=None):
        if platform not in ('telegram', 'max', 'web') or not isinstance(event_id, str) or not 1 <= len(event_id) <= 256:
            raise DocumentFlowError('Не удалось определить загрузку. Отправьте файл заново.')
        event_hash = hashlib.sha256(event_id.encode()).hexdigest()
        async with self.transaction(actor) as (c, member):
            previous = await c.fetchval('SELECT upload_id FROM document_upload_events WHERE actor_id=$1 AND platform=$2 AND event_hash=$3', actor, platform, event_hash)
            if previous:
                saved = await self._saved(c, actor, member, previous)
                if saved:
                    return saved
                row = await self._row(c, actor, member, previous)
                if row['data'] is not None:
                    return await self._projects(c, actor, member, _adapter.validate_json(row['data']))
                return DocumentView('Документ уже принят. Дождитесь результата; если обработка прервалась, отмените загрузку и отправьте файл заново.', previous, [DocumentAction('Отменить', 'cancel')])
            await c.execute('DELETE FROM pending_document_flows WHERE actor_id=$1 AND expires_at<=clock_timestamp()', actor)
            active = await c.fetchrow('SELECT * FROM pending_document_flows WHERE actor_id=$1', actor)
            if active and active['company_id'] != member['company_id']:
                await c.execute('DELETE FROM pending_document_flows WHERE actor_id=$1', actor)
                active = None
            if active:
                return DocumentView('Есть незавершённый документ. Завершите его перед загрузкой нового.', active['upload_id'], [DocumentAction('Продолжить', 'resume'), DocumentAction('Отменить', 'cancel')])
            upload_id = token_urlsafe(16)
            await c.execute("INSERT INTO pending_document_flows(actor_id,company_id,upload_id,data,expires_at) VALUES($1,$2,$3,NULL,clock_timestamp()+interval '15 minutes')", actor, member['company_id'], upload_id)
            await c.execute('INSERT INTO document_upload_events(actor_id,platform,event_hash,upload_id) VALUES($1,$2,$3,$4)', actor, platform, event_hash, upload_id)
            company_id = member['company_id']
        provider = await get_provider_for_user(actor)
        try:
            if notify:
                await notify(f'Документ получен. Распознавание: {PROVIDERS[provider]}.')
            async with asyncio.timeout(750):
                data = await download()
                text, document = await recognize_document(data, source_type, provider, caption, notify)
            pending = PendingDocument(text, format_document_preview(document), source_type=source_type,
                                      extracted_document=document, upload_id=upload_id, provider=provider)
            async with self.transaction(actor) as (c, member):
                if member['company_id'] != company_id:
                    raise DocumentFlowError('Компания изменилась. Отправьте документ заново.')
                await self._row(c, actor, member, upload_id)
                await self._store(c, actor, pending)
                return await self._projects(c, actor, member, pending)
        except BaseException as exc:
            await get_pool().execute('DELETE FROM pending_document_flows WHERE actor_id=$1 AND upload_id=$2', actor, upload_id)
            logger.warning('document_processing_failed upload=%s provider=%s error_type=%s', upload_id, provider, type(exc).__name__)
            raise

    async def _saved(self, c, actor, member, upload_id):
        row = await c.fetchrow('SELECT d.id,p.name FROM documents d JOIN projects p ON p.id=d.project_id WHERE d.upload_id=$1 AND d.uploaded_by_user_id=$2 AND d.company_id=$3', upload_id, actor, member['company_id'])
        return DocumentView(f'Документ сохранён в проект «{row["name"]}».', upload_id, document_id=row['id']) if row else None

    async def action(self, actor, name, upload_id, value=''):
        async with self.transaction(actor) as (c, member):
            saved = await self._saved(c, actor, member, upload_id)
            if saved:
                return saved
            row = await self._row(c, actor, member, upload_id)
            if name == 'cancel':
                await c.execute('DELETE FROM pending_document_flows WHERE actor_id=$1 AND upload_id=$2', actor, upload_id)
                return DocumentView('Подготовка документа отменена.')
            if row['data'] is None:
                return DocumentView('Обработка документа ещё не завершена.', upload_id, [DocumentAction('Отменить', 'cancel')])
            pending = _adapter.validate_json(row['data'])
            if name in ('resume', 'projects'):
                return await self._projects(c, actor, member, pending, int(value or '1'))
            if name == 'create_project':
                if member['role'] != 'manager':
                    raise DocumentFlowError('Создавать проекты может руководитель.')
                pending.awaiting_project_name = True
                await self._store(c, actor, pending)
                return DocumentView('Отправь название нового проекта.', upload_id, [DocumentAction('Отменить', 'cancel')])
            if name == 'project':
                if not value.isascii() or not value.isdigit() or not 0 < int(value) < 2**63:
                    raise DocumentFlowError('Проект недоступен.')
                if pending.selected_project_id != int(value):
                    pending.duplicate_confirmed = False
                    pending.reviewed_fingerprint = None
                pending.selected_project_id = int(value)
                pending.awaiting_project_name = False
            if name not in ('project', 'duplicate_save', 'review') or pending.selected_project_id is None:
                raise DocumentFlowError('Выберите проект заново.')
            project = await c.fetchrow("SELECT id,name FROM projects WHERE id=$1 AND company_id=$2 AND status='active'", pending.selected_project_id, member['company_id'])
            if project is None:
                raise DocumentFlowError('Проект недоступен или архивирован. Выберите другой проект.')
            check = await self.documents.find_duplicate_for_user(actor, project['id'], pending.extracted_document, pending.normalized_text, connection=c)
            old = pending.duplicate_check
            if old is None or (old.status, old.duplicate_document_id) != (check.status, check.duplicate_document_id):
                pending.duplicate_confirmed = False
            pending.duplicate_check = check
            if name == 'duplicate_save':
                pending.duplicate_confirmed = True
            if check.status in ('exact', 'probable') and not pending.duplicate_confirmed:
                await self._store(c, actor, pending)
                duplicate = await c.fetchrow('SELECT p.name,d.vendor,d.document_date,d.total_amount FROM documents d JOIN projects p ON p.id=d.project_id WHERE d.id=$1 AND d.company_id=$2', check.duplicate_document_id, member['company_id'])
                text = ('Точный дубль' if check.status == 'exact' else 'Вероятный дубль') + '. В компании эти затраты уже учтены.'
                if duplicate:
                    text += f"\nПроект: {duplicate['name']}\nКонтрагент: {duplicate['vendor'] or 'не указан'}\nДата: {duplicate['document_date']}\nСумма: {duplicate['total_amount']}"
                return DocumentView(text + '\nОтменить загрузку или всё равно добавить документ?', upload_id, [DocumentAction('Отменить', 'cancel'), DocumentAction('Все равно добавить', 'duplicate_save')])
            if name == 'review':
                pending.reviewed_fingerprint = review_fingerprint(pending.extracted_document)
            if document_warnings(pending.extracted_document) and pending.reviewed_fingerprint != review_fingerprint(pending.extracted_document):
                await self._store(c, actor, pending)
                return DocumentView(warning_text(pending.extracted_document) + '\nСверьте выделенные строки с оригиналом.', upload_id, [DocumentAction('Проверил по оригиналу — сохранить', 'review'), DocumentAction('Отменить', 'cancel')])
            await self.documents.save_for_user(actor, project['id'], pending.normalized_text, pending.extracted_document,
                source_type=pending.source_type, upload_id=upload_id, provider=pending.provider, connection=c)
            await c.execute('DELETE FROM pending_document_flows WHERE actor_id=$1 AND upload_id=$2', actor, upload_id)
            return await self._saved(c, actor, member, upload_id)

    async def project_name(self, actor, text):
        if not await get_pool().fetchval("SELECT 1 FROM pending_document_flows WHERE actor_id=$1 AND expires_at>clock_timestamp() AND data->>'awaiting_project_name'='true'", actor):
            return None
        async with self.transaction(actor) as (c, member):
            row = await c.fetchrow('SELECT * FROM pending_document_flows WHERE actor_id=$1 AND expires_at>clock_timestamp() FOR UPDATE', actor)
            if not row or row['data'] is None:
                return None
            pending = _adapter.validate_json(row['data'])
            if not pending.awaiting_project_name:
                return None
            await self._row(c, actor, member, row['upload_id'])
            await WorkspaceService().create_project(actor, text, connection=c)
            pending.awaiting_project_name = False
            await self._store(c, actor, pending)
            return await self._projects(c, actor, member, pending)
