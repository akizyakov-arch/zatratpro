"""Durable MAX administration inputs; mutations and confirmations commit together."""
from uuid import uuid4
import hashlib

from app.services.database import get_pool
from app.services.workspace import WorkspaceError, WorkspaceService, _name


class WorkspaceFlow:
    def __init__(self):
        self.workspace = WorkspaceService()

    async def _authorize(self, c, actor, action, company_id=None):
        if action == 'create_company':
            return await self.workspace._owner(c, actor)
        ctx = await self.workspace._manager(c, actor, lock=True)
        if company_id is not None and company_id != ctx['company_id']:
            raise WorkspaceError('Компания изменилась. Начните действие заново.')
        return ctx

    async def start(self, actor, action, target=None):
        if action not in ('create_company', 'create_project', 'rename_project'):
            raise WorkspaceError('Неизвестное действие.')
        async with get_pool().acquire() as c, c.transaction():
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f'max-workspace:{actor}')
            ctx = await self._authorize(c, actor, action)
            if action == 'rename_project' and not await c.fetchval("SELECT 1 FROM projects WHERE id=$1 AND company_id=$2 AND status='active'", target, ctx['company_id']):
                raise WorkspaceError('Проект недоступен.')
            await self.cancel(actor, connection=c)
            return await c.fetchrow("""INSERT INTO max_workspace_flows(id,actor,company_id,action,target,step)
                VALUES($1,$2,$3,$4,$5,'name') RETURNING *""", uuid4().hex, actor, ctx['company_id'], action, target)

    async def current(self, actor):
        return await get_pool().fetchrow("""SELECT * FROM max_workspace_flows WHERE actor=$1
            AND step IN ('name','confirm') AND expires_at>clock_timestamp() ORDER BY created_at DESC LIMIT 1""", actor)

    async def cancel(self, actor, *, connection=None):
        await (connection or get_pool()).execute("UPDATE max_workspace_flows SET step='cancelled' WHERE actor=$1 AND step IN ('name','confirm')", actor)

    async def submit(self, actor, value):
        value = _name(value)
        async with get_pool().acquire() as c, c.transaction():
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f'max-workspace:{actor}')
            row = await c.fetchrow("""SELECT * FROM max_workspace_flows WHERE actor=$1
                AND step IN ('name','confirm') AND expires_at>clock_timestamp() ORDER BY created_at DESC LIMIT 1 FOR UPDATE""", actor)
            if row is None:
                raise WorkspaceError('Ввод завершён или истёк. Начните действие заново.')
            await self._authorize(c, actor, row['action'], row['company_id'])
            return await c.fetchrow("UPDATE max_workspace_flows SET value=$2,step='confirm' WHERE id=$1 RETURNING *", row['id'], value)

    async def save_text(self, actor, value, event_id):
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 256:
            raise WorkspaceError('Не удалось определить сообщение. Отправьте название заново.')
        event_hash = hashlib.sha256(event_id.encode()).hexdigest()
        async with get_pool().acquire() as c, c.transaction():
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f'max-workspace:{actor}')
            previous = await c.fetchval('SELECT id FROM max_workspace_flows WHERE actor=$1 AND input_event=$2', actor, event_hash)
            if previous:
                return await self._confirm(c, actor, previous)
            row = await c.fetchrow("""SELECT * FROM max_workspace_flows WHERE actor=$1
                AND step IN ('name','confirm') AND expires_at>clock_timestamp() ORDER BY created_at DESC LIMIT 1 FOR UPDATE""", actor)
            if row is None:
                return None
            value = _name(value)
            await c.execute("UPDATE max_workspace_flows SET value=$2,input_event=$3,step='confirm' WHERE id=$1", row['id'], value, event_hash)
            return await self._confirm(c, actor, row['id'])

    async def confirm(self, actor, request_id):
        async with get_pool().acquire() as c, c.transaction():
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f'max-workspace:{actor}')
            return await self._confirm(c, actor, request_id)

    async def _confirm(self, c, actor, request_id):
        row = await c.fetchrow('SELECT * FROM max_workspace_flows WHERE id=$1 AND actor=$2 FOR UPDATE', request_id, actor)
        if row is None:
            raise WorkspaceError('Действие недоступно.')
        await self._authorize(c, actor, row['action'], row['company_id'])
        if row['step'] == 'done':
            return dict(row)
        if row['step'] != 'confirm' or not await c.fetchval('SELECT expires_at>clock_timestamp() FROM max_workspace_flows WHERE id=$1', request_id):
            raise WorkspaceError('Действие отменено или истекло. Начните заново.')
        if row['action'] == 'create_company':
            result = await self.workspace.create_company(actor, row['value'], connection=c)
            await self.workspace.manager_invite(actor, result['id'], connection=c)
        elif row['action'] == 'create_project':
            result = await self.workspace.create_project(actor, row['value'], connection=c)
        else:
            result = await self.workspace.rename_project(actor, row['target'], row['value'], connection=c)
        return dict(await c.fetchrow("UPDATE max_workspace_flows SET step='done',result_id=$2 WHERE id=$1 RETURNING *", request_id, result['id']))
