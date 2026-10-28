"""Business-card payments reimburse no employee cash; one document, one source."""
import re
from contextlib import AsyncExitStack
from datetime import datetime,timezone

from app.services.advances import AdvanceService,AdvanceError,money,decision_reason
from app.services.database import get_pool
from app.services.workspace import workspace_transaction


class BusinessCardService:
    def __init__(self):
        self.access=AdvanceService()

    async def register(self,actor,name,last4,*,connection=None):
        name=name.strip()
        if not name or len(name)>80 or not re.fullmatch(r'[0-9]{4}',last4) or re.search(r'(?:[0-9][ -]?){13,19}',name):
            raise AdvanceError('Укажите название карты и только последние 4 цифры. Полный номер не нужен.')
        async with workspace_transaction(connection) as c:
            member=await self.access._lock_member(c,actor)
            if member['role']!='manager': raise AdvanceError('Карты добавляет руководитель.')
            return await c.fetchval('INSERT INTO business_cards(company_id,name,last4,created_by) VALUES($1,$2,$3,$4) ON CONFLICT(company_id,name,last4) DO UPDATE SET name=EXCLUDED.name RETURNING id',member['company_id'],name,last4,actor)

    async def cards(self,actor):
        async with get_pool().acquire() as c:
            member=await self.access._member(c,actor)
            return await c.fetch('SELECT id,name,last4 FROM business_cards WHERE company_id=$1 ORDER BY id',member['company_id'])

    async def documents(self,actor):
        async with get_pool().acquire() as c:
            member=await self.access._member(c,actor)
            return await c.fetch('''SELECT d.id,d.vendor,d.total_amount,p.name AS project_name FROM documents d
                JOIN projects p ON p.id=d.project_id WHERE d.company_id=$1 AND d.uploaded_by_user_id=$2 AND d.currency='RUB'
                AND NOT EXISTS(SELECT 1 FROM advance_expenses e WHERE e.document_id=d.id AND e.rejected_at IS NULL)
                AND NOT EXISTS(SELECT 1 FROM card_expenses e WHERE e.document_id=d.id AND e.rejected_at IS NULL)
                ORDER BY d.id DESC LIMIT 30''',member['company_id'],actor)

    async def submit(self,actor,card_id,document_id):
        """Record card payment immediately; approved_* are legacy posting fields."""
        async with get_pool().acquire() as c,c.transaction():
            member=await self.access._lock_member(c,actor)
            if not await c.fetchval('SELECT 1 FROM business_cards WHERE id=$1 AND company_id=$2',card_id,member['company_id']):
                raise AdvanceError('Карта недоступна.')
            # The same row lock is used by advance attachment: two funding sources cannot race.
            doc=await c.fetchrow('SELECT * FROM documents WHERE id=$1 AND company_id=$2 AND uploaded_by_user_id=$3 FOR UPDATE',document_id,member['company_id'],actor)
            if doc is None or doc['currency']!='RUB': raise AdvanceError('Нужен ваш сохранённый документ компании в RUB.')
            if await c.fetchval('SELECT 1 FROM advance_expenses WHERE document_id=$1 AND rejected_at IS NULL',document_id):
                raise AdvanceError('Чек уже относится к подотчётным деньгам.')
            amount=money(doc['total_amount'])
            eid=await c.fetchval('INSERT INTO card_expenses(card_id,document_id,submitted_by,amount,approved_by,approved_at) VALUES($1,$2,$3,$4,$3,clock_timestamp()) ON CONFLICT(document_id) WHERE rejected_at IS NULL DO NOTHING RETURNING id',card_id,document_id,actor,amount)
            if eid is None:
                old=await c.fetchrow('SELECT id,card_id FROM card_expenses WHERE document_id=$1 AND rejected_at IS NULL',document_id)
                if old['card_id']!=card_id: raise AdvanceError('У чека уже выбрана другая карта.')
                return old['id']
            return eid

    async def approve(self,actor,eid):
        """Compatibility route; already recorded card payments are unchanged."""
        async with get_pool().acquire() as c,c.transaction():
            member=await self.access._lock_member(c,actor)
            if member['role']!='manager': raise AdvanceError('Расходы принимает руководитель.')
            row=await c.fetchrow('SELECT e.* FROM card_expenses e JOIN business_cards b ON b.id=e.card_id WHERE e.id=$1 AND b.company_id=$2 FOR UPDATE OF e',eid,member['company_id'])
            if row is None: raise AdvanceError('Расход недоступен.')
            if row['rejected_at'] is not None: raise AdvanceError('Расход уже отклонён. Нужна исправленная заявка.')
            await c.execute('UPDATE card_expenses SET approved_by=$2,approved_at=clock_timestamp() WHERE id=$1 AND approved_at IS NULL',eid,actor)

    async def reject(self, actor, eid, reason, *, connection=None):
        reason = decision_reason(reason)
        async with workspace_transaction(connection) as c:
            member = await self.access._lock_member(c, actor)
            if member['role'] != 'manager':
                raise AdvanceError('Расходы проверяет руководитель.')
            row = await c.fetchrow('SELECT e.* FROM card_expenses e JOIN business_cards b ON b.id=e.card_id WHERE e.id=$1 AND b.company_id=$2 FOR UPDATE OF e', eid, member['company_id'])
            if row is None:
                raise AdvanceError('Расход недоступен.')
            if row['approved_at'] is not None:
                raise AdvanceError('Учтённый расход отклонить нельзя.')
            if row['rejected_at'] is not None:
                if row['rejection_reason'] != reason:
                    raise AdvanceError('Расход уже отклонён с другой причиной.')
                return
            await c.execute('UPDATE card_expenses SET rejected_at=clock_timestamp(),rejected_by=$2,rejection_reason=$3 WHERE id=$1', eid, actor, reason)

    async def ledger(self, actor, *, page=1, per_page=30, search='', employee_id=None,
                     project_id=None, status=None, start=None, end=None, card_id=None, sort='newest'):
        if not isinstance(page, int) or not isinstance(per_page, int) or page < 1 or not 1 <= per_page <= 100:
            raise AdvanceError('Некорректная страница.')
        states = {'pending': 'e.approved_at IS NULL AND e.rejected_at IS NULL',
                  'approved': 'e.approved_at IS NOT NULL', 'rejected': 'e.rejected_at IS NOT NULL'}
        if status and status not in states:
            raise AdvanceError('Неизвестное состояние расхода.')
        orders = {
            'newest': 'e.created_at DESC,e.id DESC',
            'oldest': 'e.created_at ASC,e.id ASC',
            'amount_desc': 'e.amount DESC,e.id DESC',
            'amount_asc': 'e.amount ASC,e.id DESC',
            'employee': "lower(concat_ws(' ',u.first_name,u.last_name,u.username)) ASC,e.id DESC",
        }
        if not isinstance(sort, str) or sort not in orders:
            raise AdvanceError('Неизвестная сортировка расходов.')
        async with get_pool().acquire() as c, c.transaction(isolation='repeatable_read', readonly=True):
            member = await self.access._member(c, actor)
            params = [member['company_id'], member['role'] == 'manager', actor]
            filters = ['b.company_id=$1', '($2::boolean OR e.submitted_by=$3)']
            for field, value in (('e.submitted_by',employee_id), ('d.project_id',project_id), ('e.card_id',card_id)):
                if value is not None:
                    params.append(value)
                    filters.append(f'{field}=${len(params)}')
            if search:
                params.append('%' + str(search)[:200] + '%')
                i = len(params)
                filters.append(f"(e.document_id::text ILIKE ${i} OR b.name ILIKE ${i} OR d.vendor ILIKE ${i} OR p.name ILIKE ${i} OR concat_ws(' ',u.first_name,u.last_name,u.username) ILIKE ${i})")
            for op, value in (('>=',start), ('<',end)):
                if value is not None:
                    params.append(value)
                    filters.append(f'e.created_at{op}${len(params)}')
            if status:
                filters.append(states[status])
            source = 'FROM card_expenses e JOIN business_cards b ON b.id=e.card_id JOIN documents d ON d.id=e.document_id JOIN projects p ON p.id=d.project_id JOIN users u ON u.id=e.submitted_by WHERE ' + ' AND '.join(filters)
            total = await c.fetchval('SELECT count(*) ' + source, *params)
            params.extend([per_page,(page-1)*per_page])
            rows = await c.fetch("SELECT e.*,b.name AS card_name,b.last4,d.project_id,p.name AS project_name,d.vendor,concat_ws(' ',u.first_name,u.last_name) AS employee_name " + source + f' ORDER BY {orders[sort]} LIMIT ${len(params)-1} OFFSET ${len(params)}', *params)
            return {'items':[dict(r) for r in rows], 'total':total, 'page':page, 'per_page':per_page}

    async def report(self,actor,start,end=None,*,project_id=None,employee_id=None,connection=None):
        end=end or datetime.now(timezone.utc)
        if start.tzinfo is None or end.tzinfo is None or start>=end: raise AdvanceError('Некорректный период.')
        async with AsyncExitStack() as stack:
            c = connection if connection is not None else await stack.enter_async_context(get_pool().acquire())
            m=await self.access._member(c,actor)
            if m['role']!='manager' and employee_id not in (None,actor): raise AdvanceError('Нет доступа.')
            return await c.fetch('''SELECT e.*,b.name AS card_name,b.last4,d.project_id,p.name AS project_name,
                u.first_name,u.last_name,d.vendor,d.document_date,
                (e.approved_at IS NOT NULL AND e.approved_at<$3) AS accepted
                FROM card_expenses e JOIN business_cards b ON b.id=e.card_id JOIN documents d ON d.id=e.document_id
                JOIN projects p ON p.id=d.project_id JOIN users u ON u.id=e.submitted_by
                WHERE b.company_id=$1 AND ($4::bigint IS NULL OR d.project_id=$4)
                AND ($5::bigint IS NULL OR e.submitted_by=$5) AND ($6::boolean OR e.submitted_by=$7)
                AND ((e.approved_at>=$2 AND e.approved_at<$3) OR (e.created_at<$3 AND (e.approved_at IS NULL OR e.approved_at>=$3)))
                AND (e.rejected_at IS NULL OR e.rejected_at>=$3)
                ORDER BY e.id DESC''',m['company_id'],start,end,project_id,employee_id,m['role']=='manager',actor)
