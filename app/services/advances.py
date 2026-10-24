"""Purchasing advances. Uses internal user IDs and Decimal, independent of Telegram."""
import json
from decimal import Decimal, InvalidOperation

from app.services.database import get_pool


class AdvanceError(ValueError):
    pass


def money(value) -> Decimal:
    try:
        amount = Decimal(str(value).replace(',', '.'))
        if not amount.is_finite() or amount <= 0 or amount >= Decimal('1000000000000') or amount != amount.quantize(Decimal('.01')):
            raise ValueError
        return amount.quantize(Decimal('.01'))
    except (InvalidOperation, ValueError):
        raise AdvanceError('Сумма должна быть положительной, не более двух знаков после запятой.') from None


class AdvanceService:
    async def _member(self, c, actor):
        row = await c.fetchrow("SELECT cm.company_id,cm.role FROM company_members cm JOIN companies co ON co.id=cm.company_id WHERE cm.user_id=$1 AND cm.status='active' AND co.status='active'", actor)
        if row is None:
            raise AdvanceError('Нет доступа к активной компании.')
        return row

    async def _access(self, c, actor, aid, manager=False):
        member = await self._member(c, actor)
        row = await c.fetchrow('SELECT * FROM advances WHERE id=$1 AND company_id=$2 FOR UPDATE', aid, member['company_id'])
        if row is None or (manager and member['role'] != 'manager') or (member['role'] != 'manager' and row['employee_id'] != actor):
            raise AdvanceError('Выдача недоступна.')
        return row

    async def _event(self, c, aid, actor, kind, **details):
        await c.execute('INSERT INTO advance_events(advance_id,actor_id,kind,details) VALUES($1,$2,$3,$4::jsonb)', aid, actor, kind, json.dumps(details, default=str))

    async def issue(self, actor, employee, project, amount, purpose, key):
        amount = money(amount)
        if not purpose.strip() or not key:
            raise AdvanceError('Укажите назначение и идентификатор операции.')
        async with get_pool().acquire() as c, c.transaction():
            m = await self._member(c, actor)
            if m['role'] != 'manager':
                raise AdvanceError('Выдавать деньги может руководитель.')
            if not await c.fetchval("SELECT 1 FROM company_members WHERE user_id=$1 AND company_id=$2 AND role='employee' AND status='active'", employee, m['company_id']):
                raise AdvanceError('Сотрудник не найден в компании.')
            if not await c.fetchval("SELECT 1 FROM projects WHERE id=$1 AND company_id=$2 AND status='active'", project, m['company_id']):
                raise AdvanceError('Проект недоступен.')
            aid = await c.fetchval('INSERT INTO advances(company_id,employee_id,project_id,issued_by,amount,purpose,request_key) VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(request_key) DO NOTHING RETURNING id', m['company_id'], employee, project, actor, amount, purpose.strip(), key)
            if aid is None:
                old = await c.fetchrow('SELECT * FROM advances WHERE request_key=$1', key)
                if (old['issued_by'],old['employee_id'],old['project_id'],old['amount'],old['purpose']) != (actor,employee,project,amount,purpose.strip()):
                    raise AdvanceError('Идентификатор операции уже использован.')
                return old['id']
            await self._event(c, aid, actor, 'issued', amount=amount)
            return aid

    async def receive(self, actor, aid):
        async with get_pool().acquire() as c, c.transaction():
            row = await self._access(c, actor, aid)
            if row['employee_id'] != actor:
                raise AdvanceError('Получение подтверждает сотрудник.')
            if row['received_at'] is None:
                await c.execute('UPDATE advances SET received_at=NOW() WHERE id=$1', aid)
                await self._event(c, aid, actor, 'received')

    async def attach(self, actor, aid, document):
        async with get_pool().acquire() as c, c.transaction():
            row = await self._access(c, actor, aid)
            if row['employee_id'] != actor or row['received_at'] is None:
                raise AdvanceError('Сначала сотрудник должен подтвердить получение.')
            doc = await c.fetchrow('SELECT * FROM documents WHERE id=$1 AND company_id=$2 AND project_id=$3 AND uploaded_by_user_id=$4 FOR UPDATE', document, row['company_id'],row['project_id'],actor)
            if doc is None or doc['currency'] != 'RUB':
                raise AdvanceError('Нужен ваш документ этого проекта в RUB.')
            amount = money(doc['total_amount'])
            eid = await c.fetchval('INSERT INTO advance_expenses(advance_id,document_id,amount) VALUES($1,$2,$3) ON CONFLICT(document_id) DO NOTHING RETURNING id', aid,document,amount)
            if eid is None:
                old = await c.fetchrow('SELECT id,advance_id FROM advance_expenses WHERE document_id=$1',document)
                if old['advance_id'] != aid:
                    raise AdvanceError('Документ уже привязан к другой выдаче.')
                return old['id']
            await self._event(c, aid, actor, 'expense_submitted', expense_id=eid, document_id=document, amount=amount)
            return eid

    async def approve_expense(self, actor, aid, eid):
        async with get_pool().acquire() as c, c.transaction():
            await self._access(c,actor,aid,manager=True)
            row = await c.fetchrow('SELECT * FROM advance_expenses WHERE id=$1 AND advance_id=$2',eid,aid)
            if row is None:
                raise AdvanceError('Расход не найден.')
            if row['approved_at'] is None:
                await c.execute('UPDATE advance_expenses SET approved_at=NOW(),approved_by=$2 WHERE id=$1',eid,actor)
                await self._event(c,aid,actor,'expense_approved',expense_id=eid,amount=row['amount'])

    async def _balance(self,c,aid):
        return await c.fetchval('SELECT amount-COALESCE((SELECT SUM(amount) FROM advance_expenses WHERE advance_id=a.id AND approved_at IS NOT NULL),0)-COALESCE((SELECT SUM(amount) FROM advance_returns WHERE advance_id=a.id AND approved_at IS NOT NULL),0) FROM advances a WHERE id=$1',aid)

    async def request_return(self,actor,aid,amount,key):
        amount=money(amount)
        async with get_pool().acquire() as c,c.transaction():
            row=await self._access(c,actor,aid)
            if row['employee_id'] != actor or row['received_at'] is None:
                raise AdvanceError('Возврат оформляет сотрудник после получения.')
            rid=await c.fetchval('INSERT INTO advance_returns(advance_id,amount,request_key) VALUES($1,$2,$3) ON CONFLICT(request_key) DO NOTHING RETURNING id',aid,amount,key)
            if rid is None:
                old=await c.fetchrow('SELECT * FROM advance_returns WHERE request_key=$1',key)
                if old['advance_id'] != aid or old['amount'] != amount:
                    raise AdvanceError('Идентификатор операции уже использован.')
                return old['id']
            await self._event(c,aid,actor,'return_submitted',return_id=rid,amount=amount)
            return rid

    async def approve_return(self,actor,aid,rid):
        async with get_pool().acquire() as c,c.transaction():
            await self._access(c,actor,aid,manager=True)
            row=await c.fetchrow('SELECT * FROM advance_returns WHERE id=$1 AND advance_id=$2',rid,aid)
            if row is None:
                raise AdvanceError('Возврат не найден.')
            if row['approved_at'] is None:
                if row['amount'] > await self._balance(c,aid):
                    raise AdvanceError('Возврат превышает остаток.')
                await c.execute('UPDATE advance_returns SET approved_at=NOW(),approved_by=$2 WHERE id=$1',rid,actor)
                await self._event(c,aid,actor,'return_approved',return_id=rid,amount=row['amount'])

    async def list(self,actor):
        async with get_pool().acquire() as c:
            m=await self._member(c,actor)
            return await c.fetch("SELECT a.*, p.name AS project_name,u.first_name AS employee_name FROM advances a JOIN projects p ON p.id=a.project_id JOIN users u ON u.id=a.employee_id WHERE a.company_id=$1 AND ($2::boolean OR a.employee_id=$3) ORDER BY a.id DESC LIMIT 30",m['company_id'],m['role']=='manager',actor)

    async def card(self,actor,aid):
        async with get_pool().acquire() as c,c.transaction():
            row=await self._access(c,actor,aid)
            return dict(row,balance=await self._balance(c,aid),expenses=await c.fetch('SELECT * FROM advance_expenses WHERE advance_id=$1 ORDER BY id',aid),returns=await c.fetch('SELECT * FROM advance_returns WHERE advance_id=$1 ORDER BY id',aid))

    async def balances(self, actor):
        """Company-wide or personal RUB balance; unreceived advances are separate."""
        async with get_pool().acquire() as c:
            member = await self._member(c, actor)
            return await c.fetch('''
                WITH expenses AS (
                    SELECT advance_id, SUM(amount) AS amount FROM advance_expenses
                    WHERE approved_at IS NOT NULL GROUP BY advance_id
                ), returns AS (
                    SELECT advance_id, SUM(amount) AS amount FROM advance_returns
                    WHERE approved_at IS NOT NULL GROUP BY advance_id
                ), totals AS (
                    SELECT a.employee_id,
                        SUM(CASE WHEN a.received_at IS NOT NULL THEN a.amount ELSE 0 END) AS received,
                        SUM(CASE WHEN a.received_at IS NULL THEN a.amount ELSE 0 END) AS pending,
                        SUM(COALESCE(e.amount,0)) AS spent,
                        SUM(COALESCE(r.amount,0)) AS returned
                    FROM advances a
                    LEFT JOIN expenses e ON e.advance_id=a.id
                    LEFT JOIN returns r ON r.advance_id=a.id
                    WHERE a.company_id=$1 AND ($2::boolean OR a.employee_id=$3)
                    GROUP BY a.employee_id
                )
                SELECT t.*,u.first_name,u.last_name,
                    t.received-t.spent-t.returned AS balance
                FROM totals t JOIN users u ON u.id=t.employee_id
                ORDER BY u.first_name NULLS LAST,t.employee_id
            ''', member['company_id'], member['role']=='manager', actor)
