"""Canonical-user document views and complete reports shared by all interfaces.

Dates select document upload time and financial confirmation time respectively.
Amounts of different currencies are never combined into the RUB total.
"""
import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from weakref import WeakKeyDictionary

from app.services.advances import AdvanceError, AdvanceService
from app.services.database import get_pool
from app.services.money_reports import CASH_FIELDS, cash_and_employee_debt, build_money_report
from app.services.report_periods import report_period_start
from app.services.report_exports import build_manager_report_workbook
from app.services.async_work import run_blocking


_DOCUMENT_QUERY = """
    SELECT {document_columns}, p.name AS project_name, p.status AS project_status,
           COALESCE(NULLIF(d.external_document_number,''),NULLIF(d.incoming_number,'')) AS document_number,
           COALESCE(NULLIF(concat_ws(' ',u.first_name,u.last_name),''),u.username,'Сотрудник №'||u.id) AS uploaded_by_name,
           u.username AS uploaded_by_username,
           (SELECT role FROM company_members cm WHERE cm.company_id=d.company_id AND cm.user_id=u.id) AS member_role,
           (SELECT name FROM document_items di WHERE di.document_id=d.id ORDER BY di.line_no,di.id LIMIT 1) AS first_item_name,
           base_p.name AS base_project_name, base_doc.vendor AS base_vendor,
           base_doc.vendor_inn AS base_vendor_inn,base_doc.document_date AS base_document_date,
           base_doc.total_amount AS base_total_amount,
           COALESCE(NULLIF(base_doc.external_document_number,''),NULLIF(base_doc.incoming_number,'')) AS base_document_number,
           COALESCE(NULLIF(concat_ws(' ',base_u.first_name,base_u.last_name),''),base_u.username) AS base_uploaded_by_name,
           CASE WHEN ae.id IS NOT NULL THEN 'advance'
                WHEN ce.id IS NOT NULL THEN 'card' ELSE NULL END AS payment_source,
           ae.advance_id, ce.card_id,
           COALESCE(ae.approved_at,ce.approved_at) AS expense_approved_at,
           COALESCE(ae.id,ce.id) AS funding_expense_id
    FROM documents d
    JOIN projects p ON p.id=d.project_id AND p.company_id=d.company_id
    JOIN users u ON u.id=d.uploaded_by_user_id
    LEFT JOIN documents base_doc ON base_doc.id=d.duplicate_of_document_id AND base_doc.company_id=d.company_id
    LEFT JOIN projects base_p ON base_p.id=base_doc.project_id AND base_p.company_id=d.company_id
    LEFT JOIN users base_u ON base_u.id=base_doc.uploaded_by_user_id
    LEFT JOIN advance_expenses ae ON ae.document_id=d.id AND ae.rejected_at IS NULL
    LEFT JOIN card_expenses ce ON ce.document_id=d.id AND ce.rejected_at IS NULL
"""


# Only the detail/full-record path asks for OCR/preview bodies.
_DOCUMENT_SELECT = _DOCUMENT_QUERY.format(document_columns='d.*')
_DOCUMENT_COMPACT_COLUMNS = (
    'd.id,d.company_id,d.project_id,d.uploaded_by_user_id,d.document_type,d.source_type,'
    'd.external_document_number,d.incoming_number,d.vendor,d.vendor_inn,d.vendor_kpp,'
    'd.document_date,d.currency,d.total_amount,d.duplicate_status,'
    'd.duplicate_of_document_id,d.created_at,d.is_fiscalized,d.duplicate_checked_at'
)
_DOCUMENT_COMPACT_SELECT = _DOCUMENT_QUERY.format(document_columns=_DOCUMENT_COMPACT_COLUMNS)
_EXPORT_SLOTS = WeakKeyDictionary()


def _export_slots():
    loop = asyncio.get_running_loop()
    if loop not in _EXPORT_SLOTS:
        _EXPORT_SLOTS[loop] = asyncio.Semaphore(2)
    return _EXPORT_SLOTS[loop]


async def _build_export(*args, **kwargs):
    return await run_blocking(build_manager_report_workbook, *args, **kwargs)


def _period(start, end):
    if (not isinstance(start, datetime) or not isinstance(end, datetime)
            or start.tzinfo is None or end.tzinfo is None or start >= end):
        raise AdvanceError('Укажите корректный период с часовым поясом.')


def _page(page, per_page):
    if (isinstance(page, bool) or isinstance(per_page, bool)
            or not isinstance(page, int) or not isinstance(per_page, int)
            or page < 1 or not 1 <= per_page <= 100):
        raise AdvanceError('Некорректная страница списка.')


class ReportService:
    async def _manager(self, connection, actor, *, lock=False):
        access = AdvanceService()
        member = await (access._lock_member(connection, actor) if lock else access._member(connection, actor))
        if member['role'] != 'manager':
            raise AdvanceError('Панель документов доступна руководителю компании.')
        return member['company_id']

    @staticmethod
    async def _scope(connection, company, project_id, employee_id):
        # Historical participants remain selectable even after removal.
        if project_id is not None and not await connection.fetchval(
                'SELECT 1 FROM projects WHERE id=$1 AND company_id=$2', project_id, company):
            raise AdvanceError('Проект недоступен.')
        if employee_id is not None and not await connection.fetchval(
                'SELECT 1 FROM company_members WHERE user_id=$1 AND company_id=$2', employee_id, company):
            raise AdvanceError('Сотрудник недоступен.')

    @staticmethod
    def _conditions(company, *, q='', project_id=None, employee_id=None,
                    duplicate_status=None, payment_source=None, start=None, end=None,
                    document_type=None):
        if not isinstance(q, str) or len(q) > 200:
            raise AdvanceError('Поисковый запрос должен быть не длиннее 200 символов.')
        clauses, values = ['d.company_id=$1'], [company]

        def add(sql, value):
            values.append(value)
            clauses.append(sql.replace('?', f'${len(values)}'))

        if q.strip():
            add("(d.vendor ILIKE ? OR d.external_document_number ILIKE ? OR d.incoming_number ILIKE ?)", '%' + q.strip() + '%')
        if project_id is not None:
            add('d.project_id=?', project_id)
        if employee_id is not None:
            add('d.uploaded_by_user_id=?', employee_id)
        if duplicate_status is not None:
            if duplicate_status not in ('none', 'exact', 'probable', 'not_checked', 'flagged'):
                raise AdvanceError('Неизвестный статус дубля.')
            if duplicate_status == 'flagged':
                clauses.append("d.duplicate_status IN ('exact','probable')")
            else:
                add('d.duplicate_status=?', duplicate_status)
        if payment_source is not None:
            if payment_source == 'advance':
                clauses.append('ae.id IS NOT NULL')
            elif payment_source == 'card':
                clauses.append('ce.id IS NOT NULL')
            elif payment_source in ('unassigned', 'none'):
                clauses.append('ae.id IS NULL AND ce.id IS NULL')
            else:
                raise AdvanceError('Неизвестный источник оплаты.')
        if start is not None:
            if not isinstance(start, datetime) or start.tzinfo is None:
                raise AdvanceError('Начало периода должно содержать часовой пояс.')
            add('d.created_at>=?', start)
        if end is not None:
            if not isinstance(end, datetime) or end.tzinfo is None:
                raise AdvanceError('Конец периода должен содержать часовой пояс.')
            add('d.created_at<?', end)
        if start is not None and end is not None:
            _period(start, end)
        if document_type is not None:
            add('d.document_type=?', document_type)
        return ' AND '.join(clauses), values

    async def documents(self, actor, *, page=1, per_page=25, q='', project_id=None,
                        employee_id=None, duplicate_status=None, payment_source=None,
                        start=None, end=None, document_type=None, sort='newest'):
        _page(page, per_page)
        orders = {
            'newest': 'd.created_at DESC,d.id DESC',
            'oldest': 'd.created_at ASC,d.id ASC',
            'amount_desc': 'd.total_amount DESC NULLS LAST,d.id DESC',
            'amount_asc': 'd.total_amount ASC NULLS LAST,d.id ASC',
            'vendor': 'd.vendor ASC NULLS LAST,d.id ASC',
            'name': 'd.vendor ASC NULLS LAST,d.id ASC',
        }
        if sort not in orders:
            raise AdvanceError('Неизвестный порядок сортировки документов.')
        async with get_pool().acquire() as c, c.transaction(isolation='repeatable_read', readonly=True):
            company = await self._manager(c, actor)
            await self._scope(c, company, project_id, employee_id)
            where, params = self._conditions(
                company, q=q, project_id=project_id, employee_id=employee_id,
                duplicate_status=duplicate_status, payment_source=payment_source,
                start=start, end=end, document_type=document_type,
            )
            query = _DOCUMENT_COMPACT_SELECT + ' WHERE ' + where
            total = await c.fetchval('SELECT count(*) FROM (' + query + ') selected', *params)
            rows = await c.fetch(query + f' ORDER BY {orders[sort]} LIMIT ${len(params)+1} OFFSET ${len(params)+2}',
                                 *params, per_page, (page - 1) * per_page)
            return {'items': [dict(row) for row in rows], 'total': total, 'page': page, 'per_page': per_page}

    async def document(self, actor, document_id):
        async with get_pool().acquire() as c, c.transaction(isolation='repeatable_read', readonly=True):
            company = await self._manager(c, actor)
            row = await c.fetchrow(_DOCUMENT_SELECT + ' WHERE d.company_id=$1 AND d.id=$2', company, document_id)
            if row is None:
                raise AdvanceError('Документ недоступен.')
            result = dict(row)
            result['items'] = [dict(item) for item in await c.fetch(
                'SELECT id,document_id,line_no,name,quantity,price,line_total FROM document_items WHERE document_id=$1 ORDER BY line_no,id', document_id)]
            result['funding_history'] = [dict(item) for item in await c.fetch("""
                SELECT 'advance' AS source,e.id,e.advance_id AS source_id,e.amount,e.created_at,
                       e.approved_at,e.rejected_at,e.rejection_reason FROM advance_expenses e WHERE e.document_id=$1
                UNION ALL SELECT 'card',e.id,e.card_id,e.amount,e.created_at,e.approved_at,e.rejected_at,e.rejection_reason
                FROM card_expenses e WHERE e.document_id=$1 ORDER BY created_at,id
            """, document_id)]
            return result

    async def duplicate_keep(self, actor, document_id):
        async with get_pool().acquire() as c, c.transaction():
            company = await self._manager(c, actor, lock=True)
            row = await c.fetchrow('SELECT id,duplicate_status FROM documents WHERE id=$1 AND company_id=$2 FOR UPDATE', document_id, company)
            if row is None:
                raise AdvanceError('Документ недоступен.')
            if row['duplicate_status'] == 'none':
                return {'id': document_id, 'duplicate_status': 'none'}
            await c.execute("UPDATE documents SET duplicate_status='none',duplicate_of_document_id=NULL,duplicate_checked_at=clock_timestamp() WHERE id=$1", document_id)
            await self._audit(c, actor, company, 'document.duplicate_keep', document_id)
            return {'id': document_id, 'duplicate_status': 'none'}

    async def duplicate_delete(self, actor, document_id, source=False):
        async with get_pool().acquire() as c, c.transaction():
            company = await self._manager(c, actor, lock=True)
            original = await c.fetchrow('SELECT id,duplicate_status,duplicate_of_document_id FROM documents WHERE id=$1 AND company_id=$2', document_id, company)
            if original is None or original['duplicate_status'] not in ('exact', 'probable'):
                raise AdvanceError('Дубликат недоступен или уже обработан.')
            target = original['duplicate_of_document_id'] if source else document_id
            if target is None:
                raise AdvanceError('Исходная запись для дубля не найдена.')
            locked = await c.fetch('SELECT id,duplicate_status,duplicate_of_document_id FROM documents WHERE id=ANY($1::bigint[]) AND company_id=$2 ORDER BY id FOR UPDATE', sorted({document_id, target}), company)
            rows = {row['id']: row for row in locked}
            current = rows.get(document_id)
            if (target not in rows or current is None
                    or current['duplicate_status'] not in ('exact', 'probable')
                    or (source and current['duplicate_of_document_id'] != target)):
                raise AdvanceError('Состояние дубля изменилось. Обновите список.')
            if await c.fetchval('SELECT EXISTS(SELECT 1 FROM advance_expenses WHERE document_id=$1) OR EXISTS(SELECT 1 FROM card_expenses WHERE document_id=$1)', target):
                raise AdvanceError('Документ связан с финансовой историей и не может быть удалён.')
            await c.execute("UPDATE documents SET duplicate_status='none',duplicate_of_document_id=NULL,duplicate_checked_at=clock_timestamp() WHERE company_id=$1 AND duplicate_of_document_id=$2", company, target)
            await c.execute('DELETE FROM documents WHERE id=$1 AND company_id=$2', target, company)
            await self._audit(c, actor, company, 'document.duplicate_delete', target)
            return {'id': target, 'deleted': True}

    @staticmethod
    async def _audit(c, actor, company, action, document_id):
        # Table and shared event schema are created by the workspace migration.
        await c.execute("INSERT INTO workspace_events(actor_id,company_id,action,entity_type,entity_id,details) VALUES($1,$2,$3,'document',$4,'{}'::jsonb)", actor, company, action, document_id)

    @staticmethod
    async def _money(c, actor, start, end, *, project_id=None, employee_id=None):
        return await build_money_report(c, actor, start, end, project_id=project_id, employee_id=employee_id)

    async def overview(self, actor, start, end):
        """Dashboard aggregates avoid loading document bodies or line items."""
        _period(start, end)
        async with get_pool().acquire() as c, c.transaction(isolation='repeatable_read', readonly=True):
            company = await self._manager(c, actor)
            currencies = await c.fetch("""
                SELECT currency,count(*) AS document_count,COALESCE(sum(total_amount),0) AS total_amount,
                    count(*) FILTER (WHERE duplicate_status='exact') AS exact_duplicates,
                    count(*) FILTER (WHERE duplicate_status='probable') AS probable_duplicates
                FROM documents WHERE company_id=$1 AND created_at>=$2 AND created_at<$3
                GROUP BY currency
            """, company, start, end)
            # Unresolved duplicate warnings must survive period changes and project archival.
            duplicate_review = dict(await c.fetchrow("""
                SELECT count(*) AS total,
                    count(*) FILTER (WHERE d.duplicate_status='exact') AS exact,
                    count(*) FILTER (WHERE d.duplicate_status='probable') AS probable,
                    count(*) FILTER (WHERE p.status='archived' OR source_p.status='archived') AS involving_archived_projects
                FROM documents d JOIN projects p ON p.id=d.project_id AND p.company_id=d.company_id
                LEFT JOIN documents source ON source.id=d.duplicate_of_document_id AND source.company_id=d.company_id
                LEFT JOIN projects source_p ON source_p.id=source.project_id AND source_p.company_id=d.company_id
                WHERE d.company_id=$1 AND d.duplicate_status IN ('exact','probable')
            """, company))
            money = await self._money(c, actor, start, end)
            projects = await c.fetch("SELECT id,name FROM projects WHERE company_id=$1 AND status='active' ORDER BY lower(name),id", company)
            project_documents = await c.fetch('''SELECT d.project_id,d.currency,count(*) AS document_count,
                COALESCE(sum(d.total_amount),0) AS total_amount
                FROM documents d JOIN projects p ON p.id=d.project_id AND p.company_id=d.company_id
                WHERE d.company_id=$1 AND p.status='active' AND d.created_at>=$2 AND d.created_at<$3
                GROUP BY d.project_id,d.currency''', company, start, end)
            employee_count = await c.fetchval("SELECT count(*) FROM company_members WHERE company_id=$1 AND role='employee' AND status='active'", company)
            generated_at = await c.fetchval('SELECT clock_timestamp()')
        open_projects = []
        cash_by_project, cards_by_project, docs_by_project = defaultdict(list), defaultdict(list), defaultdict(list)
        for row in money['rows']:
            cash_by_project[row['project_id']].append(row)
        for row in money['card_rows']:
            cards_by_project[row['project_id']].append(row)
        for row in project_documents:
            docs_by_project[row['project_id']].append(row)
        for project in projects:
            cash_rows = cash_by_project[project['id']]
            card_rows = cards_by_project[project['id']]
            docs = docs_by_project[project['id']]
            row = {'project_id': project['id'], 'project_name': project['name'],
                   'document_count': sum(d['document_count'] for d in docs),
                   'document_total': sum((d['total_amount'] for d in docs if d['currency'] == 'RUB'), Decimal(0)),
                   'totals_by_currency': {d['currency']: d['total_amount'] for d in docs},
                   **{key: sum((r[key] for r in cash_rows), Decimal(0)) for key in CASH_FIELDS}}
            row['cash'], row['debt'] = cash_and_employee_debt({'rows': cash_rows})
            row['card_spent'] = sum((r['amount'] for r in card_rows if r['accepted']), Decimal(0))
            row['card_pending'] = sum((r['amount'] for r in card_rows if not r['accepted']), Decimal(0))
            row['review_total'] = row['pending_expenses'] + row['pending_returns'] + row['card_pending']
            open_projects.append(row)
        currency_totals = {row['currency']: row['total_amount'] for row in currencies}
        rub_total = currency_totals.get('RUB', Decimal(0))
        count = sum(row['document_count'] for row in currencies)
        return {
            'start': start, 'end': end, 'start_at': start, 'end_at': end, 'generated_at': generated_at,
            'document_count': count, 'documents': count, 'document_total': rub_total,
            'project_count': len(projects), 'employee_count': employee_count,
            'open_projects': open_projects,
            'total_amount': rub_total, 'currency': 'RUB', 'totals_by_currency': currency_totals,
            'exact_duplicates': sum(row['exact_duplicates'] for row in currencies),
            'probable_duplicates': sum(row['probable_duplicates'] for row in currencies),
            'duplicate_review': duplicate_review,
            **money['totals'], 'card_spent': money['card_spent'], 'card_pending': money['card_pending'],
            'cash': money['cash_on_hand'], 'debt': money['employee_debt'], 'money': money,
        }

    async def employee(self, actor, employee_id):
        """Company-scoped report subject, including former employees and managers."""
        async with get_pool().acquire() as c:
            company = await self._manager(c, actor)
            row = await c.fetchrow("""SELECT cm.company_id,cm.user_id,cm.role,cm.joined_at,
                u.first_name,u.last_name,u.username,u.telegram_id,
                (SELECT count(*) FROM documents d WHERE d.company_id=cm.company_id AND d.uploaded_by_user_id=u.id) AS document_count
                FROM company_members cm JOIN users u ON u.id=cm.user_id
                WHERE cm.company_id=$1 AND cm.user_id=$2""", company, employee_id)
            if row is None:
                raise AdvanceError('Сотрудник недоступен.')
            return dict(row)

    async def subjects(self, actor, *, page=1, per_page=20):
        """Report subjects include managers and former/zero-document employees."""
        _page(page, per_page)
        async with get_pool().acquire() as c, c.transaction(isolation='repeatable_read', readonly=True):
            company = await self._manager(c, actor)
            total = await c.fetchval("SELECT count(*) FROM company_members WHERE company_id=$1 AND role IN ('manager','employee')", company)
            rows = await c.fetch('''SELECT u.id,u.id AS user_id,u.first_name,u.last_name,u.username,
                cm.role,cm.status,
                COALESCE(NULLIF(concat_ws(' ',u.first_name,u.last_name),''),u.username,'Сотрудник №'||u.id) AS name
                FROM company_members cm JOIN users u ON u.id=cm.user_id
                WHERE cm.company_id=$1 AND cm.role IN ('manager','employee')
                ORDER BY lower(COALESCE(NULLIF(concat_ws(' ',u.first_name,u.last_name),''),u.username,'')),u.id
                LIMIT $2 OFFSET $3''', company, per_page, (page-1)*per_page)
            return {'items': [dict(row) for row in rows], 'total': total, 'page': page, 'per_page': per_page}

    async def period_summary(self, actor, period, **scope):
        try:
            start = report_period_start(period)
        except ValueError as exc:
            raise AdvanceError(str(exc)) from exc
        return await self.summary(actor, start, datetime.now(timezone.utc), **scope)

    async def summary(self, actor, start, end, *, project_id=None, employee_id=None, include_duplicates=False):
        """SQL aggregates only; no document bodies or line items cross the wire."""
        _period(start, end)
        async with get_pool().acquire() as c, c.transaction(isolation='repeatable_read', readonly=True):
            company = await self._manager(c, actor)
            await self._scope(c, company, project_id, employee_id)
            where, params = self._conditions(company, start=start, end=end,
                                              project_id=project_id, employee_id=employee_id)
            currencies = await c.fetch('''SELECT d.currency,count(*) AS document_count,
                COALESCE(sum(d.total_amount),0) AS total_amount,
                count(*) FILTER(WHERE d.duplicate_status='exact') AS exact_duplicate_count,
                count(*) FILTER(WHERE d.duplicate_status='probable') AS probable_duplicate_count,
                COALESCE(sum(d.total_amount) FILTER(WHERE d.duplicate_status IN ('exact','probable')),0) AS duplicate_total
                FROM documents d WHERE ''' + where + ' GROUP BY d.currency', *params)
            project_rows = await c.fetch('''SELECT d.project_id AS id,p.name AS project_name,d.currency,min(d.id) AS first_document_id,
                count(*) AS document_count,COALESCE(sum(d.total_amount),0) AS total_amount,
                count(*) FILTER(WHERE d.duplicate_status='exact') AS exact_duplicate_count,
                count(*) FILTER(WHERE d.duplicate_status='probable') AS probable_duplicate_count
                FROM documents d JOIN projects p ON p.id=d.project_id AND p.company_id=d.company_id
                WHERE ''' + where + ' GROUP BY d.project_id,p.name,d.currency ORDER BY min(d.id),d.currency', *params)
            employee_rows = await c.fetch('''SELECT u.id,min(d.id) AS first_document_id,
                COALESCE(NULLIF(concat_ws(' ',u.first_name,u.last_name),''),u.username,'Сотрудник №'||u.id) AS employee_name,
                u.username,cm.role,d.currency,count(*) AS document_count,
                COALESCE(sum(d.total_amount),0) AS total_amount,
                count(*) FILTER(WHERE d.duplicate_status='exact') AS exact_duplicate_count,
                count(*) FILTER(WHERE d.duplicate_status='probable') AS probable_duplicate_count
                FROM documents d JOIN users u ON u.id=d.uploaded_by_user_id
                LEFT JOIN company_members cm ON cm.user_id=u.id AND cm.company_id=d.company_id
                WHERE ''' + where + ' GROUP BY u.id,u.first_name,u.last_name,u.username,cm.role,d.currency ORDER BY min(d.id),d.currency', *params)
            duplicates = [dict(row) for row in await c.fetch(_DOCUMENT_COMPACT_SELECT + ' WHERE ' + where + " AND d.duplicate_status IN ('exact','probable') ORDER BY d.created_at DESC,d.id DESC", *params)] if include_duplicates else None
            cash = await self._money(c, actor, start, end, project_id=project_id, employee_id=employee_id)
            generated_at = await c.fetchval('SELECT clock_timestamp()')
        currency_totals = {r['currency']: r['total_amount'] for r in currencies}
        summary = {
            'start_at': start, 'end_at': end,
            'documents': sum(r['document_count'] for r in currencies),
            'document_count': sum(r['document_count'] for r in currencies),
            'total_amount': currency_totals.get('RUB', Decimal(0)), 'currency': 'RUB',
            'totals_by_currency': currency_totals,
            'exact_duplicates': sum(r['exact_duplicate_count'] for r in currencies),
            'probable_duplicates': sum(r['probable_duplicate_count'] for r in currencies),
        }
        duplicate_totals = {r['currency']: r['duplicate_total'] for r in currencies
                            if r['exact_duplicate_count'] or r['probable_duplicate_count']}
        duplicate_summary = dict(summary, documents=summary['exact_duplicates']+summary['probable_duplicates'],
            document_count=summary['exact_duplicates']+summary['probable_duplicates'],
            total_amount=duplicate_totals.get('RUB', Decimal(0)), totals_by_currency=duplicate_totals)
        result = {'start': start, 'end': end, 'generated_at': generated_at,
                'filters': {'project_id': project_id, 'employee_id': employee_id},
                'summary': summary, 'overview': summary, 'duplicate_summary': duplicate_summary,
                'projects': self._aggregate_groups(project_rows, 'project_id'),
                'employees': self._aggregate_groups(employee_rows, 'uploaded_by_user_id'), 'money': cash}
        if duplicates is not None:
            result['duplicates'] = duplicates
        return result

    @staticmethod
    def _aggregate_groups(rows, field):
        groups = {}
        for r in rows:
            key = r['id']
            if key not in groups:
                groups[key] = {
                    'id': key, 'project_id': key if field == 'project_id' else None,
                    'project_name': r['project_name'] if field == 'project_id' else None,
                    'user_id': key if field == 'uploaded_by_user_id' else None,
                    'employee_name': r['employee_name'] if field == 'uploaded_by_user_id' else None,
                    'username': r['username'] if field == 'uploaded_by_user_id' else None,
                    'role': r['role'] if field == 'uploaded_by_user_id' else None,
                    'document_count': 0, 'total_amount': Decimal(0), 'currency': 'RUB',
                    'totals_by_currency': {}, 'exact_duplicate_count': 0, 'probable_duplicate_count': 0,
                }
            group = groups[key]
            group['document_count'] += r['document_count']
            group['totals_by_currency'][r['currency']] = r['total_amount']
            if r['currency'] == 'RUB':
                group['total_amount'] += r['total_amount']
            group['exact_duplicate_count'] += r['exact_duplicate_count']
            group['probable_duplicate_count'] += r['probable_duplicate_count']
        return list(groups.values())

    async def period_report(self, actor, period, **scope):
        try:
            start = report_period_start(period)
        except ValueError as exc:
            raise AdvanceError(str(exc)) from exc
        return await self.report(actor, start, datetime.now(timezone.utc), **scope)

    async def report(self, actor, start, end, *, project_id=None, employee_id=None, include_document_bodies=True):
        _period(start, end)
        async with get_pool().acquire() as c, c.transaction(isolation='repeatable_read', readonly=True):
            company = await self._manager(c, actor)
            await self._scope(c, company, project_id, employee_id)
            where, params = self._conditions(company, start=start, end=end,
                                              project_id=project_id, employee_id=employee_id)
            document_query = _DOCUMENT_SELECT if include_document_bodies else _DOCUMENT_COMPACT_SELECT
            documents = [dict(row) for row in await c.fetch(document_query + ' WHERE ' + where + ' ORDER BY d.id', *params)]
            # No display limit is applied to reports or exports.
            items = [dict(row) for row in await c.fetch('SELECT di.* FROM document_items di JOIN documents d ON d.id=di.document_id WHERE ' + where + ' ORDER BY di.document_id,di.line_no,di.id', *params)]
            cash = await self._money(c, actor, start, end, project_id=project_id, employee_id=employee_id)
            generated_at = await c.fetchval('SELECT clock_timestamp()')

        currency_totals = defaultdict(Decimal)
        for doc in documents:
            currency_totals[doc['currency']] += doc['total_amount'] or Decimal(0)
        summary = {
            'start_at': start, 'end_at': end, 'document_count': len(documents), 'documents': len(documents),
            'total_amount': currency_totals.get('RUB', Decimal(0)), 'currency': 'RUB',
            'totals_by_currency': dict(currency_totals),
            'exact_duplicates': sum(d['duplicate_status'] == 'exact' for d in documents),
            'probable_duplicates': sum(d['duplicate_status'] == 'probable' for d in documents),
        }
        projects = self._group(documents, 'project_id')
        employees = self._group(documents, 'uploaded_by_user_id')
        return {
            'company_id': company,
            'start': start, 'end': end, 'generated_at': generated_at,
            'filters': {'project_id': project_id, 'employee_id': employee_id},
            'summary': summary, 'overview': summary, 'projects': projects, 'employees': employees,
            'documents': documents, 'items': items,
            'duplicates': [d for d in documents if d['duplicate_status'] in ('exact', 'probable')],
            'money': cash,
        }

    @staticmethod
    def _group(documents, field):
        groups = {}
        for d in documents:
            key = d[field]
            if key not in groups:
                groups[key] = {
                    'id': key, 'project_id': d['project_id'] if field == 'project_id' else None,
                    'project_name': d['project_name'] if field == 'project_id' else None,
                    'user_id': d['uploaded_by_user_id'] if field == 'uploaded_by_user_id' else None,
                    'employee_name': d['uploaded_by_name'] if field == 'uploaded_by_user_id' else None,
                    'username': d['uploaded_by_username'] if field == 'uploaded_by_user_id' else None,
                    'role': d['member_role'] if field == 'uploaded_by_user_id' else None,
                    'document_count': 0, 'total_amount': Decimal(0), 'currency': 'RUB',
                    'totals_by_currency': defaultdict(Decimal),
                    'exact_duplicate_count': 0, 'probable_duplicate_count': 0,
                }
            row = groups[key]
            row['document_count'] += 1
            row['totals_by_currency'][d['currency']] += d['total_amount'] or Decimal(0)
            if d['currency'] == 'RUB':
                row['total_amount'] += d['total_amount'] or Decimal(0)
            row['exact_duplicate_count'] += d['duplicate_status'] == 'exact'
            row['probable_duplicate_count'] += d['duplicate_status'] == 'probable'
        for row in groups.values():
            row['totals_by_currency'] = dict(row['totals_by_currency'])
        return list(groups.values())

    async def export(self, actor, start, end, *, project_id=None, employee_id=None):
        async with _export_slots():
            return await self._export(actor, start, end, project_id=project_id, employee_id=employee_id)

    async def _export(self, actor, start, end, *, project_id=None, employee_id=None):
        result = await self.report(actor, start, end, project_id=project_id, employee_id=employee_id, include_document_bodies=False)
        summary = SimpleNamespace(**result['summary'])
        as_objects = lambda values: [SimpleNamespace(**row) for row in values]
        _, payload = await _build_export(
            f'{start:%Y-%m-%d} — {end:%Y-%m-%d} UTC (конец не включён)', summary,
            as_objects(result['projects']), as_objects(result['employees']),
            as_objects(result['duplicates']), as_objects(result['documents']),
            as_objects(result['items']), money_report=result['money'],
            metadata={'end': end, 'generated_at': result['generated_at'],
                      'project_id': project_id, 'employee_id': employee_id},
        )
        async with get_pool().acquire() as c:
            company = await self._manager(c, actor)
            if company != result['company_id']:
                raise AdvanceError('Компания изменилась. Сформируйте выгрузку заново.')
        return f'fiinops-report-{start:%Y%m%d}-{end:%Y%m%d}.xlsx', payload
