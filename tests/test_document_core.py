"""Shared document behavior, MAX adapter, safe downloads and core boundaries."""
import asyncio
from contextlib import asynccontextmanager
from io import BytesIO
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from PIL import Image

from db_fixture import DatabaseFixture
from test_max_adapter import message
from test_pdf import make_pdf
from app.max_bot.handler import MaxHandler
from app.max_bot.menu import MenuButton
from app.max_bot.files import download, public_url
from app.services.account_links import AccountLinkService
from app.services.document_flow import DocumentFlow, DocumentFlowError
from app.services.document_processing import recognize_document
from app.services.documents import DocumentValidationError
from app.services.pdf_files import PDFError
from app.services.max_onboarding import MaxOnboardingService
from app.services.recognition import set_provider_for_user
from app.services import document_drafts as drafts
from app.services.database import close_db, init_db


def photo_bytes():
    output = BytesIO()
    Image.new('RGB', (400, 600), 'white').save(output, 'JPEG')
    return output.getvalue()


class CoreBoundaryTests(unittest.TestCase):
    def test_core_import_and_instantiation_do_not_import_messenger_sdks(self):
        script = """import builtins
original=builtins.__import__
def guard(name,*args,**kwargs):
    if name=='aiogram' or name.startswith('aiogram.'):
        raise AssertionError(name)
    return original(name,*args,**kwargs)
builtins.__import__=guard
from app.services.document_flow import DocumentFlow
DocumentFlow()
"""
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class FileBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_network_urls_and_credentials_are_rejected(self):
        loop = asyncio.get_running_loop()
        for url in ('http://cdn.example/file', 'https://user:password@cdn.example/file', 'https://cdn.example:8080/file'):
            with self.assertRaises(DocumentValidationError):
                await public_url(url)
        with patch.object(loop, 'getaddrinfo', AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1',443))])):
            with self.assertRaises(DocumentValidationError):
                await public_url('https://cdn.example/file')

    async def test_bounded_stream_and_redirects_do_not_send_bot_credentials(self):
        requests = []
        def server(request):
            requests.append(request)
            if request.url.path == '/first':
                return httpx.Response(302, headers={'Location':'https://storage.example/file'})
            return httpx.Response(200, content=b'12345')
        original = httpx.AsyncClient
        factory = lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(server))
        with patch('app.max_bot.files.public_url', AsyncMock()) as validate, patch('app.max_bot.files.httpx.AsyncClient', side_effect=factory):
            self.assertEqual(await download('https://cdn.example/first', 5), b'12345')
            self.assertEqual(validate.await_count, 2)
            with self.assertRaises(DocumentValidationError):
                await download('https://storage.example/file', 4)
        self.assertTrue(all('authorization' not in request.headers for request in requests))

    async def test_real_pdf_conversion_keeps_quality_page_order_and_cleanup(self):
        from app.services import pdf_files
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'input.pdf'
            make_pdf(path, 2)
            seen = []
            async def ocr(page):
                with Image.open(page) as image:
                    seen.append((page.name, max(image.size), image.format))
                return 'Кассовый чек ' + page.stem
            service = SimpleNamespace(extract_text=ocr)
            document = {'document_type':'cash_receipt','vendor':'Vendor','total':100,'items':[{'name':'Purchase','quantity':1,'price':100,'line_total':100}]}
            with patch.object(pdf_files, 'TMP_DIR', Path(folder)), patch('app.services.document_processing.create_recognizer', return_value=service), patch('app.services.document_processing.DeepSeekService.extract_document', AsyncMock(return_value=document)):
                text, result = await recognize_document(path.read_bytes(), 'pdf', 'deepseek', 'все')
            self.assertEqual(seen, [('1.jpg',1800,'JPEG'),('2.jpg',1800,'JPEG')])
            self.assertLess(text.index('Страница 1'),text.index('Страница 2'))
            self.assertEqual(result.total,100)
            self.assertEqual(list(Path(folder).iterdir()),[path])


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS') == '1', 'PostgreSQL tests disabled')
class SharedDocumentTests(DatabaseFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.core = DocumentFlow()
        self.ocr = SimpleNamespace(extract_text=AsyncMock(return_value='Кассовый чек'))
        self.recognizer = patch('app.services.document_processing.create_recognizer', return_value=self.ocr)
        self.factory = self.recognizer.start()
        self.addCleanup(self.recognizer.stop)
        self.extraction = patch('app.services.document_processing.DeepSeekService.extract_document', AsyncMock(return_value=self.document.model_dump()))
        self.extractor = self.extraction.start()
        self.addCleanup(self.extraction.stop)

    async def link(self, user, sender=9001):
        links = AccountLinkService()
        code = await links.issue('telegram', str(user.id), 'max')
        await links.claim('max', str(sender), code['code'])
        return await links.confirm('telegram', str(user.id), code['id'])

    def attachment(self, sender=9001, kind='image', filename=None, caption='', mid=None):
        event = message(sender, caption)
        event['message']['body']['mid'] = mid or uuid4().hex
        attachment = {'type':kind, 'payload':{'url':'https://storage.example/document'}}
        if filename:
            attachment.update(filename=filename, size=100)
        event['message']['body']['attachments'] = [attachment]
        return event

    async def receive(self, actor, mid=None, platform='max'):
        return await self.core.receive(actor,platform,mid or uuid4().hex,'photo',AsyncMock(return_value=photo_bytes()))

    async def select(self, actor, view, name='project', value=None):
        return await self.core.action(actor,name,view.upload_id,str(value or self.project.id) if name=='project' else '')

    async def test_max_first_employee_photo_to_shared_costs_without_telegram(self):
        code = await self.service.create_invite(self.manager,'employee')
        actor = (await MaxOnboardingService().join(9001,code))['user_id']
        self.assertIsNone(await self.pool.fetchval('SELECT telegram_id FROM users WHERE id=$1',actor))
        event = self.attachment()
        with patch('app.max_bot.files.download',AsyncMock(return_value=photo_bytes())):
            reply = (await MaxHandler().handle(event))[1]
        self.assertEqual(reply.buttons[0][0],self.project.name)
        self.assertEqual(await self.document_count(),0)
        result = (await MaxHandler().handle(message(9001,reply.buttons[0][0])))[1]
        self.assertIn('сохранён',result)
        row = await self.pool.fetchrow('SELECT * FROM documents')
        self.assertEqual(row['uploaded_by_user_id'],actor)
        self.assertEqual(row['company_id'],self.company.id)
        self.assertEqual(row['ocr_provider'],'deepseek')
        self.assertEqual(row['total_amount'],100)

    async def test_provider_choice_and_same_upload_retry_do_not_repeat_ocr(self):
        actor = await self.link(self.employee)
        await set_provider_for_user(actor,'ocr_space')
        event = self.attachment(mid='same-max-file')
        with patch('app.max_bot.files.download',AsyncMock(return_value=photo_bytes())) as load:
            first = (await MaxHandler().handle(event))[1]
            again = (await MaxHandler().handle(event))[1]
            self.assertEqual(first,again)
            await MaxHandler().handle(message(9001,first.buttons[0][0]))
            self.assertIn('сохранён',(await MaxHandler().handle(event))[1])
        self.assertEqual(load.await_count,1)
        self.assertEqual(self.extractor.await_count,1)
        self.factory.assert_called_once_with('ocr_space')
        self.assertEqual(await self.pool.fetchval('SELECT ocr_provider FROM documents'),'ocr_space')

    async def test_max_pdf_uses_shared_pipeline_and_caption(self):
        await self.link(self.employee)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'pdf'
            make_pdf(path,2)
            with patch('app.max_bot.files.download',AsyncMock(return_value=path.read_bytes())):
                reply = (await MaxHandler().handle(self.attachment(kind='file',filename='scan.PDF',caption='2')))[1]
        self.assertEqual(self.ocr.extract_text.await_count,1)
        self.assertEqual(reply.buttons[0][0],self.project.name)
        await MaxHandler().handle(message(9001,reply.buttons[0][0]))
        self.assertEqual(await self.pool.fetchval('SELECT source_type FROM documents'),'pdf')

    async def test_pdf_without_range_bad_file_and_processing_failure_leave_no_cost(self):
        await self.link(self.employee)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'pdf'
            make_pdf(path,2)
            for data in (path.read_bytes(),b'%PDF-broken'):
                with patch('app.max_bot.files.download',AsyncMock(return_value=data)):
                    reply = (await MaxHandler().handle(self.attachment(kind='file',filename='file.pdf')))[1]
                self.assertNotIn('сохранён',reply)
                self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM pending_document_flows'),0)
        self.assertEqual(await self.document_count(),0)

    async def test_pending_document_survives_restart_and_is_shared_between_adapters(self):
        actor = await self.link(self.employee)
        preview = await self.receive(actor,platform='max')
        await close_db()
        self.pool = await init_db()
        from app.handlers.documents import process_project_selection
        from app.ui.projects import PROJECT_CALLBACK_PREFIX
        await process_project_selection(self.callback(f'{PROJECT_CALLBACK_PREFIX}{self.project.id}:{preview.upload_id}'))
        self.assertEqual(await self.document_count(),1)
        self.assertIsNone(await drafts.get_pending_document(actor))

    async def test_duplicate_in_archived_project_needs_explicit_confirmation(self):
        actor = await self.link(self.employee)
        first = await self.receive(actor)
        await self.select(actor,first)
        await self.pool.execute("UPDATE projects SET status='archived' WHERE id=$1",self.project.id)
        pid = await self.pool.fetchval('INSERT INTO projects(company_id,name,created_by_user_id) VALUES($1,$2,$3) RETURNING id',self.company.id,'Other project',actor)
        second = await self.receive(actor)
        warning = await self.select(actor,second,value=pid)
        self.assertIn('дубль',warning.text)
        self.assertIn(self.project.name,warning.text)
        self.assertEqual(await self.document_count(),1)
        result = await self.select(actor,second,name='duplicate_save')
        self.assertIsNotNone(result.document_id)
        self.assertEqual(await self.document_count(),2)
        self.assertEqual(await self.pool.fetchval('SELECT duplicate_status FROM documents ORDER BY id DESC LIMIT 1'),'exact')

    async def test_arithmetic_review_cannot_bypass_duplicate_gate(self):
        actor = await self.link(self.employee)
        original = await self.receive(actor)
        await self.select(actor,original)
        bad = self.document.model_copy(deep=True)
        bad.items[0].quantity = 5
        self.extractor.return_value = bad.model_dump()
        second = await self.receive(actor)
        await self.select(actor,second)
        early = await self.select(actor,second,name='review')
        self.assertIn('дубль',early.text)
        review = await self.select(actor,second,name='duplicate_save')
        self.assertIn('Сверьте',review.text)
        self.assertEqual(await self.document_count(),1)
        await self.select(actor,second,name='review')
        self.assertEqual(await self.document_count(),2)

    async def test_foreign_actor_project_and_old_buttons_cannot_save_or_cancel(self):
        actor = await self.link(self.employee)
        other = await self.link(self.manager,9002)
        view = await self.receive(actor)
        with self.assertRaises(DocumentFlowError):
            await self.core.action(other,'cancel',view.upload_id)
        with self.assertRaises(DocumentFlowError):
            await self.core.action(actor,'cancel','stale-upload')
        co = await self.service.create_company(self.owner,'Private company')
        pid = await self.pool.fetchval('INSERT INTO projects(company_id,name,created_by_user_id) VALUES($1,$2,$3) RETURNING id',co.id,'Private project',actor)
        with self.assertRaises(DocumentFlowError):
            await self.select(actor,view,value=pid)
        self.assertIsNotNone(await drafts.get_pending_document(actor))
        self.assertEqual(await self.document_count(),0)

    async def test_disable_or_archive_during_recognition_prevents_persisting_preview(self):
        actor = await self.link(self.employee)
        async def load():
            await self.pool.execute('UPDATE users SET is_active=false WHERE id=$1',actor)
            return photo_bytes()
        with self.assertRaises(Exception):
            await self.core.receive(actor,'max','disabled','photo',load)
        self.assertEqual(await self.pool.fetchval('SELECT count(*) FROM pending_document_flows'),0)
        self.assertEqual(await self.document_count(),0)

    async def test_cancel_expiry_and_concurrent_selection_are_idempotent(self):
        actor = await self.link(self.employee)
        view = await self.receive(actor)
        await self.core.action(actor,'cancel',view.upload_id)
        with self.assertRaises(DocumentFlowError):
            await self.select(actor,view)
        view = await self.receive(actor)
        await self.pool.execute("UPDATE pending_document_flows SET expires_at=clock_timestamp()-interval '1 second'")
        with self.assertRaises(DocumentFlowError):
            await self.select(actor,view)
        view = await self.receive(actor)
        result = await asyncio.gather(*(self.select(actor,view) for _ in range(3)))
        self.assertEqual(len({r.document_id for r in result}),1)
        self.assertEqual(await self.document_count(),1)

    async def test_shared_new_project_and_resume_pending_document(self):
        actor = await self.link(self.manager)
        view = await self.receive(actor)
        await self.core.action(actor,'create_project',view.upload_id)
        view = await self.core.project_name(actor,'New project from document')
        self.assertIn('New project from document',[a.label for a in view.actions])
        self.assertFalse((await drafts.get_pending_document(actor)).awaiting_project_name)
        employee = await self.link(self.employee,9002)
        view = await self.receive(employee)
        with self.assertRaises(DocumentFlowError):
            await self.core.action(employee,'create_project',view.upload_id)

    async def test_failed_save_rolls_back_and_keeps_ready_draft(self):
        actor = await self.link(self.employee)
        view = await self.receive(actor)
        with patch.object(self.core.documents,'save_for_user',AsyncMock(side_effect=ConnectionError('db unavailable'))):
            with self.assertRaises(ConnectionError):
                await self.select(actor,view)
        self.assertIsNotNone(await drafts.get_pending_document(actor))
        await self.select(actor,view)
        self.assertEqual(await self.document_count(),1)

    async def test_migration_preserves_live_telegram_draft_and_existing_costs(self):
        actor = await self.link(self.employee)
        from app.adapters.telegram.documents import DocumentService
        await DocumentService().save_document(self.employee,self.project,'preview',self.document,upload_id='before-migration')
        pending = drafts.PendingDocument('text','preview',extracted_document=self.document,upload_id='old-live-upload')
        await self.pool.execute('DROP TABLE pending_document_flows')
        await self.pool.execute('DROP TABLE document_upload_events')
        await self.pool.execute('CREATE TABLE pending_document_flows(telegram_user_id BIGINT PRIMARY KEY,upload_id TEXT NOT NULL,data JSONB,expires_at TIMESTAMPTZ NOT NULL)')
        await self.pool.execute("INSERT INTO pending_document_flows VALUES($1,$2,$3::jsonb,clock_timestamp()+interval '10 minutes')",self.employee.id,pending.upload_id,drafts._adapter.dump_json(pending).decode())
        migration = Path(__file__).resolve().parent.parent/'db/migrations/022_canonical_document_flows.sql'
        async with self.pool.acquire() as c, c.transaction():
            await c.execute(migration.read_text())
        restored = await drafts.get_pending_document(actor)
        self.assertEqual(restored.upload_id,pending.upload_id)
        self.assertEqual(await self.document_count(),1)
        warning = await self.select(actor,restored)
        self.assertIn('дубль',warning.text)
        self.assertEqual(await self.document_count(),1)

    async def test_transfer_invalidates_old_upload_but_allows_new_company_document(self):
        actor = await self.link(self.employee)
        view = await self.receive(actor)
        owner = await self.pool.fetchval('SELECT id FROM users WHERE telegram_id=$1',self.owner.id)
        from app.services.workspace import WorkspaceService
        other = await self.service.create_company(self.owner,'Transfer target')
        await WorkspaceService().remove_user(owner,actor)
        await WorkspaceService().assign_user(owner,actor,other.id,'employee')
        with self.assertRaises(DocumentFlowError):
            await self.select(actor,view)
        fresh = await self.receive(actor)
        self.assertNotEqual(fresh.upload_id,view.upload_id)
        self.assertNotIn(self.project.name,[a.label for a in fresh.actions])
