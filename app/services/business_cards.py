"""Business-card payments reimburse no employee cash; one document, one source."""
import re
from datetime import datetime,timezone

from app.services.advances import AdvanceService,AdvanceError,money
from app.services.database import get_pool


class BusinessCardService:
    def __init__(self):
        self.access=AdvanceService()

    async def register(self,actor,name,last4):
        name=name.strip()
        if not name or len(name)>80 or not re.fullmatch(r'[0-9]{4}',last4) or re.search(r'(?:[0-9][ -]?){13,19}',name):
            raise AdvanceError('Укажите название карты и только последние 4 цифры. Полный номер не нужен.')
        async with get_pool().acquire() as c:
            member=await self.access._member(c,actor)
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
                AND NOT EXISTS(SELECT 1 FROM advance_expenses e WHERE e.document_id=d.id)
                AND NOT EXISTS(SELECT 1 FROM card_expenses e WHERE e.document_id=d.id)
                ORDER BY d.id DESC LIMIT 30''',member['company_id'],actor)

    async def submit(self,actor,card_id,document_id):
        async with get_pool().acquire() as c,c.transaction():
            member=await self.access._member(c,actor)
            if not await c.fetchval('SELECT 1 FROM business_cards WHERE id=$1 AND company_id=$2',card_id,member['company_id']):
                raise AdvanceError('Карта недоступна.')
            # The same row lock is used by advance attachment: two funding sources cannot race.
            doc=await c.fetchrow('SELECT * FROM documents WHERE id=$1 AND company_id=$2 AND uploaded_by_user_id=$3 FOR UPDATE',document_id,member['company_id'],actor)
            if doc is None or doc['currency']!='RUB': raise AdvanceError('Нужен ваш сохранённый документ компании в RUB.')
            if await c.fetchval('SELECT 1 FROM advance_expenses WHERE document_id=$1',document_id):
                raise AdvanceError('Чек уже относится к подотчётным деньгам.')
            amount=money(doc['total_amount'])
            eid=await c.fetchval('INSERT INTO card_expenses(card_id,document_id,submitted_by,amount) VALUES($1,$2,$3,$4) ON CONFLICT(document_id) DO NOTHING RETURNING id',card_id,document_id,actor,amount)
            if eid is None:
                old=await c.fetchrow('SELECT id,card_id FROM card_expenses WHERE document_id=$1',document_id)
                if old['card_id']!=card_id: raise AdvanceError('У чека уже выбрана другая карта.')
                return old['id']
            return eid

    async def approve(self,actor,eid):
        async with get_pool().acquire() as c,c.transaction():
            member=await self.access._member(c,actor)
            if member['role']!='manager': raise AdvanceError('Расходы принимает руководитель.')
            row=await c.fetchrow('SELECT e.id FROM card_expenses e JOIN business_cards b ON b.id=e.card_id WHERE e.id=$1 AND b.company_id=$2 FOR UPDATE OF e',eid,member['company_id'])
            if row is None: raise AdvanceError('Расход недоступен.')
            await c.execute('UPDATE card_expenses SET approved_by=$2,approved_at=NOW() WHERE id=$1 AND approved_at IS NULL',eid,actor)

    async def report(self,actor,start,end=None,*,project_id=None,employee_id=None):
        end=end or datetime.now(timezone.utc)
        if start.tzinfo is None or end.tzinfo is None or start>=end: raise AdvanceError('Некорректный период.')
        async with get_pool().acquire() as c:
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
                ORDER BY e.id DESC''',m['company_id'],start,end,project_id,employee_id,m['role']=='manager',actor)
