"""Durable advance issue commands using one draft per canonical user."""
import hashlib
from app.services.database import get_pool
from app.services.membership import require_member
from app.services.advances import AdvanceService, AdvanceError, money, optional_purpose


class AdvanceIssueFlow:
    async def apply(self, actor, platform, event_id, action, value=None, draft_id=None):
        if platform not in ('telegram', 'max', 'web') or not isinstance(event_id, str) or not 1 <= len(event_id) <= 256:
            raise AdvanceError('Не удалось определить сообщение. Отправьте команду заново.')
        event_hash = hashlib.sha256(event_id.encode()).hexdigest()
        async with get_pool().acquire() as c, c.transaction():
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f'conversation:{actor}')
            member = await require_member(c, actor)
            await c.fetchval('SELECT id FROM companies WHERE id=$1 FOR UPDATE', member['company_id'])
            current = await require_member(c, actor)
            if current['company_id'] != member['company_id']:
                raise AdvanceError('Компания изменилась. Начните выдачу заново.')
            member = current
            if member['role'] != 'manager':
                raise AdvanceError('Выдавать деньги может руководитель.')
            previous = await c.fetchrow('SELECT draft_id FROM advance_issue_inputs WHERE actor=$1 AND platform=$2 AND event_hash=$3', actor, platform, event_hash)
            if previous:
                row = await c.fetchrow('SELECT * FROM advance_issue_drafts WHERE id=$1', previous['draft_id'])
                if row['company_id'] != member['company_id']:
                    raise AdvanceError('Компания изменилась. Начните выдачу заново.')
                return dict(row)
            row = await c.fetchrow('SELECT * FROM advance_issue_drafts WHERE actor=$1 ORDER BY id DESC LIMIT 1 FOR UPDATE', actor)
            if action == 'start':
                await c.execute("UPDATE workspace_flows SET step='cancelled' WHERE actor=$1 AND step IN ('name','confirm')", actor)
                await c.execute("UPDATE advance_issue_drafts SET step='cancelled' WHERE actor=$1 AND step NOT IN ('done','cancelled')", actor)
                row = await c.fetchrow("INSERT INTO advance_issue_drafts(actor,platform,company_id,step) VALUES($1,$2,$3,'employee') RETURNING *", actor, platform, member['company_id'])
            else:
                if row is None or (draft_id is not None and row['id'] != draft_id):
                    raise AdvanceError('Это старая кнопка. Откройте текущую выдачу или начните новую.')
                if row['company_id'] != member['company_id']:
                    raise AdvanceError('Компания изменилась. Начните выдачу заново.')
                if action == 'confirm' and row['step'] == 'done':
                    return dict(row)
                if row['step'] in ('done','cancelled') or not await c.fetchval('SELECT expires_at>clock_timestamp() FROM advance_issue_drafts WHERE id=$1', row['id']):
                    raise AdvanceError('Заявка завершена или истекла. Начните выдачу заново.')
                if action == 'cancel':
                    await c.execute("UPDATE advance_issue_drafts SET step='cancelled' WHERE id=$1", row['id'])
                elif action == 'employee' and row['step'] == 'employee':
                    if not await c.fetchval("SELECT 1 FROM company_members m JOIN users u ON u.id=m.user_id WHERE m.company_id=$1 AND m.user_id=$2 AND m.role='employee' AND m.status='active' AND u.is_active", member['company_id'], value):
                        raise AdvanceError('Сотрудник недоступен.')
                    await c.execute("UPDATE advance_issue_drafts SET employee_id=$2,step='project' WHERE id=$1", row['id'], value)
                elif action == 'project' and row['step'] == 'project':
                    if not await c.fetchval("SELECT 1 FROM projects WHERE id=$1 AND company_id=$2 AND status='active'", value, member['company_id']):
                        raise AdvanceError('Проект недоступен.')
                    await c.execute("UPDATE advance_issue_drafts SET project_id=$2,step='amount' WHERE id=$1", row['id'], value)
                elif action == 'text' and row['step'] == 'amount':
                    await c.execute("UPDATE advance_issue_drafts SET amount=$2,step='purpose' WHERE id=$1", row['id'], money(value))
                elif action in ('text', 'skip_purpose') and row['step'] == 'purpose':
                    purpose = optional_purpose('' if action == 'skip_purpose' else value)
                    await c.execute("UPDATE advance_issue_drafts SET purpose=$2,step='confirm' WHERE id=$1", row['id'], purpose)
                elif action == 'confirm' and row['step'] == 'confirm':
                    aid = await AdvanceService().issue(actor, row['employee_id'], row['project_id'], row['amount'], row['purpose'], f'issue-draft:{row["id"]}', connection=c)
                    await c.execute("UPDATE advance_issue_drafts SET advance_id=$2,step='done' WHERE id=$1", row['id'], aid)
                elif action != 'view':
                    raise AdvanceError('Этот шаг уже завершён. Продолжите текущую заявку.')
                row = await c.fetchrow('SELECT * FROM advance_issue_drafts WHERE id=$1', row['id'])
            await c.execute('INSERT INTO advance_issue_inputs VALUES($1,$2,$3,$4)', actor, platform, event_hash, row['id'])
            return dict(row)

    async def current(self, actor):
        async with get_pool().acquire() as c:
            return await c.fetchrow("SELECT * FROM advance_issue_drafts WHERE actor=$1 AND step NOT IN ('done','cancelled') AND expires_at>clock_timestamp() ORDER BY id DESC LIMIT 1", actor)

    async def cancel(self, actor):
        async with get_pool().acquire() as c, c.transaction():
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f'conversation:{actor}')
            await c.execute("UPDATE advance_issue_drafts SET step='cancelled' WHERE actor=$1 AND step NOT IN ('done','cancelled')", actor)
