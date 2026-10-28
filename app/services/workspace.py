"""Company administration for authenticated internal users, shared by adapters.

No messenger SDK objects enter this service. PostgreSQL locks and settlement
guards apply equally to the browser and the older Telegram adapter.
"""
import json
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import asyncpg

from app.config import get_owner_telegram_id
from app.services.database import get_pool


class WorkspaceError(ValueError):
    pass


def _name(value, label='Название'):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
        raise WorkspaceError(f'{label}: укажите от 1 до 200 символов.')
    return value.strip()


def _page(page, per_page):
    if not isinstance(page, int) or not isinstance(per_page, int) or page < 1 or not 1 <= per_page <= 100:
        raise WorkspaceError('Некорректная страница списка.')
    return (page - 1) * per_page


def _order(sort, id_column, name_expression):
    # Both SQL expressions are fixed by each service method, never by callers.
    if not isinstance(sort, str) or sort not in ('newest', 'oldest', 'name'):
        raise WorkspaceError('Неизвестная сортировка списка.')
    return {
        'newest': id_column + ' DESC',
        'oldest': id_column + ' ASC',
        'name': name_expression + ' ASC,' + id_column + ' ASC',
    }[sort]


def _person(row):
    result = dict(row)
    result['name'] = ' '.join(filter(None, (result.get('first_name'), result.get('last_name')))) or result.get('username') or f"Пользователь №{result.get('id', result.get('user_id'))}"
    return result


async def ensure_settled(connection, company_id, *, employee_id=None, project_id=None):
    """Caller holds the company lock; balance nets projects only within a person."""
    await connection.fetchval('SELECT id FROM companies WHERE id=$1 FOR UPDATE', company_id)
    if await connection.fetchval('SELECT workspace_has_open_settlements($1,$2,$3)', company_id, employee_id, project_id):
        raise WorkspaceError('Сначала завершите расчёты и проверьте ожидающие операции.')


@asynccontextmanager
async def workspace_transaction(connection=None):
    if connection is not None:
        yield connection
    else:
        async with get_pool().acquire() as c, c.transaction():
            yield c


class WorkspaceService:
    async def _context(self, c, actor):
        owner_id = get_owner_telegram_id()
        row = await c.fetchrow('''SELECT u.id,u.first_name,u.last_name,u.username,u.is_active,
            EXISTS(SELECT 1 FROM external_accounts a WHERE a.user_id=u.id
              AND a.platform='telegram' AND a.external_id=$2 AND u.telegram_id=$3 AND $3<>0) AS owner,
            cm.company_id,cm.role,c.name AS company_name,c.status AS company_status
            FROM users u LEFT JOIN company_members cm ON cm.user_id=u.id AND cm.status='active'
            LEFT JOIN companies c ON c.id=cm.company_id WHERE u.id=$1''', actor,
            str(owner_id), owner_id)
        if row is None or not row['is_active']:
            raise WorkspaceError('Учётная запись недоступна.')
        result = _person(row)
        if row['owner']:
            result.update(role='owner', company_id=None, company_name=None)
        elif row['role'] != 'manager' or row['company_status'] != 'active':
            raise WorkspaceError('Действие выполняет только руководитель активной компании или владелец системы.')
        return {key: result[key] for key in ('id', 'name', 'role', 'company_id', 'company_name')}

    async def context(self, actor):
        async with get_pool().acquire() as c:
            return await self._context(c, actor)

    async def _manager(self, c, actor, *, lock=False):
        ctx = await self._context(c, actor)
        if ctx['role'] != 'manager':
            raise WorkspaceError('Действие доступно руководителю своей компании.')
        if lock:
            await c.fetchval('SELECT id FROM companies WHERE id=$1 FOR UPDATE', ctx['company_id'])
            current = await self._context(c, actor)
            if current['role'] != 'manager' or current['company_id'] != ctx['company_id']:
                raise WorkspaceError('Доступ к компании изменился. Обновите страницу и повторите действие.')
            ctx = current
        return ctx

    async def _owner(self, c, actor):
        ctx = await self._context(c, actor)
        if ctx['role'] != 'owner':
            raise WorkspaceError('Действие доступно владельцу системы.')
        return ctx

    async def _audit(self, c, actor, action, entity, entity_id, company=None, reason=None, **details):
        await c.execute('''INSERT INTO workspace_events(actor_id,company_id,entity_type,entity_id,action,reason,details)
            VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)''', actor, company, entity, entity_id, action, reason, json.dumps(details, default=str))

    async def _list(self, c, query, params, page, per_page, *, people=False):
        offset = _page(page, per_page)
        total = await c.fetchval('SELECT count(*) FROM (' + query + ') result', *params)
        rows = await c.fetch(query + f' LIMIT ${len(params)+1} OFFSET ${len(params)+2}', *params, per_page, offset)
        return {'items': [(_person(row) if people else dict(row)) for row in rows], 'total': total, 'page': page, 'per_page': per_page}

    async def projects(self, actor, archived=False, *, page=1, per_page=25, q='', sort='newest'):
        order = _order(sort, 'p.id', 'lower(p.name)')
        async with get_pool().acquire() as c:
            ctx = await self._manager(c, actor)
            return await self._list(c, '''SELECT p.*,
                (SELECT count(*) FROM documents d WHERE d.project_id=p.id) AS document_count,
                COALESCE((SELECT sum(total_amount) FROM documents d WHERE d.project_id=p.id AND d.currency='RUB'),0) AS total_amount
                FROM projects p WHERE p.company_id=$1 AND p.status=$2 AND p.name ILIKE $3 ORDER BY ''' + order,
                [ctx['company_id'], 'archived' if archived else 'active', '%' + q[:200] + '%'], page, per_page)

    async def project(self, actor, project_id):
        async with get_pool().acquire() as c:
            ctx = await self._manager(c, actor)
            row = await c.fetchrow('SELECT * FROM projects WHERE id=$1 AND company_id=$2', project_id, ctx['company_id'])
            if row is None:
                raise WorkspaceError('Проект недоступен.')
            result = dict(row)
            result['document_count'] = await c.fetchval('SELECT count(*) FROM documents WHERE project_id=$1', project_id)
            result['total_amount'] = await c.fetchval("SELECT COALESCE(sum(total_amount),0) FROM documents WHERE project_id=$1 AND currency='RUB'", project_id)
            result['created_by_name'] = await c.fetchval("SELECT COALESCE(NULLIF(concat_ws(' ',first_name,last_name),''),username) FROM users WHERE id=$1", row['created_by_user_id'])
            result['has_open_settlements'] = await c.fetchval('SELECT workspace_has_open_settlements($1,NULL,$2)', ctx['company_id'], project_id)
            return result

    async def project_documents(self, actor, project_id):
        async with get_pool().acquire() as c:
            ctx = await self._manager(c, actor)
            if not await c.fetchval('SELECT 1 FROM projects WHERE id=$1 AND company_id=$2', project_id, ctx['company_id']):
                raise WorkspaceError('Проект недоступен.')
            return await c.fetch('SELECT vendor,total_amount,currency FROM documents WHERE project_id=$1 AND company_id=$2 ORDER BY created_at DESC,id DESC', project_id, ctx['company_id'])

    async def create_project(self, actor, name, *, connection=None):
        name = _name(name)
        async with workspace_transaction(connection) as c:
            ctx = await self._manager(c, actor, lock=True)
            try:
                row = await c.fetchrow('INSERT INTO projects(company_id,name,created_by_user_id) VALUES($1,$2,$3) RETURNING *', ctx['company_id'], name, actor)
            except asyncpg.UniqueViolationError:
                raise WorkspaceError('Проект с таким названием уже существует.') from None
            await self._audit(c, actor, 'created', 'project', row['id'], ctx['company_id'], name=name)
            return dict(row)

    async def rename_project(self, actor, project_id, name, *, connection=None):
        name = _name(name)
        async with workspace_transaction(connection) as c:
            ctx = await self._manager(c, actor, lock=True)
            try:
                row = await c.fetchrow("UPDATE projects SET name=$3 WHERE id=$1 AND company_id=$2 AND status='active' RETURNING *", project_id, ctx['company_id'], name)
            except asyncpg.UniqueViolationError:
                raise WorkspaceError('Проект с таким названием уже существует.') from None
            if row is None:
                raise WorkspaceError('Проект недоступен.')
            await self._audit(c, actor, 'renamed', 'project', project_id, ctx['company_id'], name=name)
            return dict(row)

    async def _project_status(self, actor, project_id, status):
        async with get_pool().acquire() as c, c.transaction():
            ctx = await self._manager(c, actor, lock=True)
            old = await c.fetchrow('SELECT * FROM projects WHERE id=$1 AND company_id=$2', project_id, ctx['company_id'])
            if old is None:
                raise WorkspaceError('Проект недоступен.')
            if old['status'] == status:
                return dict(old)
            if status == 'archived':
                await ensure_settled(c, ctx['company_id'], project_id=project_id)
            row = await c.fetchrow("UPDATE projects SET status=$2,archived_at=CASE WHEN $2='archived' THEN clock_timestamp() ELSE NULL END WHERE id=$1 RETURNING *", project_id, status)
            await self._audit(c, actor, status, 'project', project_id, ctx['company_id'])
            return dict(row)

    async def archive_project(self, actor, project_id):
        return await self._project_status(actor, project_id, 'archived')

    async def restore_project(self, actor, project_id):
        return await self._project_status(actor, project_id, 'active')

    async def employees(self, actor, *, page=1, per_page=25, q='', status=None, sort='newest'):
        order = _order(sort, 'u.id', "lower(concat_ws(' ',u.first_name,u.last_name,u.username))")
        if status not in (None, 'active', 'removed'):
            raise WorkspaceError('Некорректный статус сотрудника.')
        async with get_pool().acquire() as c:
            ctx = await self._manager(c, actor)
            return await self._list(c, '''SELECT u.id,u.id AS user_id,u.first_name,u.last_name,u.username,u.is_active,
                cm.role,cm.status,cm.joined_at,
                (SELECT count(*) FROM documents d WHERE d.company_id=cm.company_id AND d.uploaded_by_user_id=u.id) AS document_count,
                COALESCE((SELECT sum(CASE WHEN a.received_at IS NOT NULL THEN a.amount ELSE 0 END)
                  -COALESCE(sum((SELECT sum(e.amount) FROM advance_expenses e WHERE e.advance_id=a.id AND e.approved_at IS NOT NULL)),0)
                  -COALESCE(sum((SELECT sum(r.amount) FROM advance_returns r WHERE r.advance_id=a.id AND r.approved_at IS NOT NULL)),0)
                  FROM advances a WHERE a.company_id=cm.company_id AND a.employee_id=u.id AND a.canceled_at IS NULL),0) AS balance,
                COALESCE((SELECT sum(a.amount) FROM advances a WHERE a.company_id=cm.company_id AND a.employee_id=u.id
                   AND a.received_at IS NULL AND a.canceled_at IS NULL),0) AS pending
                FROM company_members cm JOIN users u ON u.id=cm.user_id WHERE cm.company_id=$1 AND cm.role='employee'
                  AND ($2::text IS NULL OR cm.status=$2)
                  AND concat_ws(' ',u.first_name,u.last_name,u.username,u.id::text) ILIKE $3
                ORDER BY ''' + order, [ctx['company_id'], status, '%' + q[:200] + '%'], page, per_page, people=True)

    async def employee(self, actor, employee_id):
        async with get_pool().acquire() as c:
            ctx = await self._manager(c, actor)
            row = await c.fetchrow('''SELECT u.id,u.first_name,u.last_name,u.username,u.is_active,cm.role,cm.status,cm.joined_at
                FROM users u JOIN company_members cm ON cm.user_id=u.id WHERE u.id=$1 AND cm.company_id=$2''', employee_id, ctx['company_id'])
            if row is None or row['role'] != 'employee':
                raise WorkspaceError('Сотрудник недоступен.')
            result = _person(row)
            result['has_open_settlements'] = await c.fetchval('SELECT workspace_has_open_settlements($1,$2,NULL)', ctx['company_id'], employee_id)
            result['document_count'] = await c.fetchval('SELECT count(*) FROM documents WHERE company_id=$1 AND uploaded_by_user_id=$2', ctx['company_id'], employee_id)
            return result

    async def _invite(self, c, actor, company_id, role, *, code_factory=None):
        company = await c.fetchrow("SELECT * FROM companies WHERE id=$1 AND status='active' FOR UPDATE", company_id)
        if company is None:
            raise WorkspaceError('Активная компания не найдена.')
        if role == 'manager' and (company['manager_user_id'] is not None or await c.fetchval("SELECT 1 FROM company_members WHERE company_id=$1 AND role='manager' AND status='active'", company_id)):
            raise WorkspaceError('У компании уже есть руководитель.')
        if role == 'employee' and await c.fetchval("SELECT count(*) FROM company_members WHERE company_id=$1 AND role='employee' AND status='active'", company_id) >= 10:
            raise WorkspaceError('В компании уже 10 сотрудников.')
        await c.execute("UPDATE company_invites SET status='revoked' WHERE company_id=$1 AND role=$2 AND status='active'", company_id, role)
        for _ in range(10):
            code = code_factory() if code_factory is not None else secrets.token_hex(6).upper()
            try:
                async with c.transaction():
                    row = await c.fetchrow("INSERT INTO company_invites(company_id,role,code,created_by_user_id,expires_at) VALUES($1,$2,$3,$4,clock_timestamp()+interval '72 hours') RETURNING id,code,expires_at,role", company_id, role, code, actor)
                break
            except asyncpg.UniqueViolationError:
                continue
        else:
            raise WorkspaceError('Не удалось создать уникальное приглашение. Повторите позже.')
        await self._audit(c, actor, 'invite_created', 'company', company_id, company_id, role=role)
        return dict(row)

    async def invite_employee(self, actor, *, code_factory=None):
        async with get_pool().acquire() as c, c.transaction():
            ctx = await self._manager(c, actor, lock=True)
            return await self._invite(c, actor, ctx['company_id'], 'employee', code_factory=code_factory)

    async def _remove(self, c, actor, user_id, company_id, *, employee_only=False):
        await c.fetchval('SELECT id FROM companies WHERE id=$1 FOR UPDATE', company_id)
        member = await c.fetchrow("SELECT * FROM company_members WHERE company_id=$1 AND user_id=$2 AND status='active'", company_id, user_id)
        if member is None or (employee_only and member['role'] != 'employee'):
            raise WorkspaceError('Участник не найден или уже исключён.')
        await ensure_settled(c, company_id, employee_id=user_id)
        await c.execute("UPDATE company_members SET status='removed',removed_at=clock_timestamp() WHERE company_id=$1 AND user_id=$2", company_id, user_id)
        if member['role'] == 'manager':
            await c.execute('UPDATE companies SET manager_user_id=NULL WHERE id=$1 AND manager_user_id=$2', company_id, user_id)
        await self._audit(c, actor, 'member_removed', 'user', user_id, company_id)
        return {'id': user_id, 'user_id': user_id, 'company_id': company_id, 'status': 'removed'}

    async def remove_employee(self, actor, user_id):
        async with get_pool().acquire() as c, c.transaction():
            ctx = await self._manager(c, actor, lock=True)
            return await self._remove(c, actor, user_id, ctx['company_id'], employee_only=True)

    async def company(self, actor):
        async with get_pool().acquire() as c:
            ctx = await self._manager(c, actor)
            return await self._company(c, ctx['company_id'])

    async def _company(self, c, company_id):
        row = await c.fetchrow('''SELECT c.*,u.first_name AS manager_first_name,u.last_name AS manager_last_name,
            (SELECT count(*) FROM company_members cm WHERE cm.company_id=c.id AND cm.role='employee' AND cm.status='active') AS employee_count,
            (SELECT count(*) FROM projects p WHERE p.company_id=c.id AND p.status='active') AS project_count,
            (SELECT count(*) FROM projects p WHERE p.company_id=c.id AND p.status='archived') AS archived_project_count,
            (SELECT count(*) FROM documents d WHERE d.company_id=c.id) AS document_count
            FROM companies c LEFT JOIN users u ON u.id=c.manager_user_id WHERE c.id=$1''', company_id)
        if row is None:
            raise WorkspaceError('Компания не найдена.')
        result = dict(row)
        result['employee_limit'] = 10
        return result

    async def companies(self, actor, *, page=1, per_page=25, q='', status=None, sort='newest'):
        order = _order(sort, 'c.id', 'lower(c.name)')
        if status not in (None, 'active', 'archived'):
            raise WorkspaceError('Некорректный статус компании.')
        async with get_pool().acquire() as c:
            await self._owner(c, actor)
            return await self._list(c, '''SELECT c.*,concat_ws(' ',u.first_name,u.last_name) AS manager_name,
                (SELECT count(*) FROM company_members cm WHERE cm.company_id=c.id AND cm.role='employee' AND cm.status='active') AS employee_count
                FROM companies c LEFT JOIN users u ON u.id=c.manager_user_id
                WHERE c.name ILIKE $1 AND ($2::text IS NULL OR c.status=$2) ORDER BY ''' + order,
                ['%' + q[:200] + '%', status], page, per_page)

    async def create_company(self, actor, name, *, connection=None):
        name = _name(name)
        async with workspace_transaction(connection) as c:
            await self._owner(c, actor)
            row = await c.fetchrow('INSERT INTO companies(name,owner_user_id) VALUES($1,$2) RETURNING *', name, actor)
            await self._audit(c, actor, 'created', 'company', row['id'], row['id'], name=name)
            return dict(row)

    async def company_detail(self, actor, company_id):
        async with get_pool().acquire() as c:
            await self._owner(c, actor)
            result = await self._company(c, company_id)
            result['members'] = [_person(r) for r in await c.fetch('''SELECT u.id,u.first_name,u.last_name,u.username,u.is_active,cm.role,cm.status
                FROM company_members cm JOIN users u ON u.id=cm.user_id WHERE cm.company_id=$1 ORDER BY cm.status,cm.role,u.id''', company_id)]
            invite = await c.fetchrow("SELECT id,code,role,expires_at FROM company_invites WHERE company_id=$1 AND role='manager' AND status='active' AND expires_at>clock_timestamp() ORDER BY id DESC LIMIT 1", company_id)
            result['invite'] = dict(invite) if invite else None
            return result

    async def users(self, actor, *, page=1, per_page=25, q='', status=None, sort='newest'):
        order = _order(sort, 'u.id', "lower(concat_ws(' ',u.first_name,u.last_name,u.username))")
        if status not in (None, 'active', 'suspended'):
            raise WorkspaceError('Некорректный статус пользователя.')
        async with get_pool().acquire() as c:
            await self._owner(c, actor)
            return await self._list(c, '''SELECT u.id,u.first_name,u.last_name,u.username,u.is_active,u.created_at,
                cm.company_id,CASE WHEN u.id=$3 THEN 'owner' ELSE cm.role END AS role,c.name AS company_name
                FROM users u LEFT JOIN company_members cm ON cm.user_id=u.id AND cm.status='active'
                LEFT JOIN companies c ON c.id=cm.company_id
                WHERE concat_ws(' ',u.first_name,u.last_name,u.username,u.id::text) ILIKE $1
                AND ($2::boolean IS NULL OR u.is_active=$2) ORDER BY ''' + order,
                ['%' + q[:200] + '%', None if status is None else status == 'active', actor], page, per_page, people=True)

    async def user(self, actor, user_id):
        async with get_pool().acquire() as c:
            await self._owner(c, actor)
            row = await c.fetchrow("""SELECT u.id,u.first_name,u.last_name,u.username,u.is_active,
                cm.company_id,cm.role,c.name AS company_name FROM users u
                LEFT JOIN company_members cm ON cm.user_id=u.id AND cm.status='active'
                LEFT JOIN companies c ON c.id=cm.company_id WHERE u.id=$1""", user_id)
            if row is None:
                raise WorkspaceError('Пользователь не найден.')
            result = _person(row)
            if user_id == actor:
                result['role'] = 'owner'
            return result

    async def assign_user(self, actor, user_id, company_id, role):
        if role not in ('manager', 'employee'):
            raise WorkspaceError('Допустимые роли: manager, employee.')
        async with get_pool().acquire() as c, c.transaction():
            await self._owner(c, actor)
            company = await c.fetchrow("SELECT * FROM companies WHERE id=$1 AND status='active' FOR UPDATE", company_id)
            if company is None:
                raise WorkspaceError('Активная компания не найдена.')
            user = await c.fetchrow('SELECT id,is_active FROM users WHERE id=$1 FOR UPDATE', user_id)
            if user is None or not user['is_active']:
                raise WorkspaceError('Активный пользователь не найден.')
            if user_id == actor:
                raise WorkspaceError('Владелец системы не может быть участником компании.')
            old = await c.fetchrow("SELECT * FROM company_members WHERE user_id=$1 AND status='active'", user_id)
            if old and old['company_id'] != company_id:
                raise WorkspaceError('Сначала исключите пользователя из прежней компании.')
            if old and old['role'] != role:
                await ensure_settled(c, company_id, employee_id=user_id)
            if role == 'manager':
                if company['manager_user_id'] not in (None, user_id):
                    raise WorkspaceError('У компании уже есть руководитель.')
                await c.execute('UPDATE companies SET manager_user_id=$2 WHERE id=$1', company_id, user_id)
            else:
                count = await c.fetchval("SELECT count(*) FROM company_members WHERE company_id=$1 AND role='employee' AND status='active'", company_id)
                if count >= 10 and not (old and old['role'] == 'employee'):
                    raise WorkspaceError('В компании уже 10 сотрудников.')
                await c.execute('UPDATE companies SET manager_user_id=NULL WHERE id=$1 AND manager_user_id=$2', company_id, user_id)
            try:
                row = await c.fetchrow("""INSERT INTO company_members(company_id,user_id,role) VALUES($1,$2,$3)
                    ON CONFLICT(company_id,user_id) DO UPDATE SET role=EXCLUDED.role,status='active',removed_at=NULL
                    RETURNING *""", company_id, user_id, role)
            except asyncpg.UniqueViolationError:
                raise WorkspaceError('Пользователь или роль уже назначены другим запросом.') from None
            await self._audit(c, actor, 'member_assigned', 'user', user_id, company_id, role=role)
            return dict(row)

    async def remove_user(self, actor, user_id):
        async with get_pool().acquire() as c, c.transaction():
            await self._owner(c, actor)
            company_id = await c.fetchval("SELECT company_id FROM company_members WHERE user_id=$1 AND status='active'", user_id)
            if company_id is None:
                raise WorkspaceError('Пользователь не состоит в активной компании.')
            return await self._remove(c, actor, user_id, company_id)

    async def suspend_user(self, actor, user_id, active, reason):
        if not isinstance(active, bool):
            raise WorkspaceError('Укажите состояние доступа.')
        if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 1000:
            raise WorkspaceError('Причина: укажите от 1 до 1000 символов.')
        reason = reason.strip()
        async with get_pool().acquire() as c, c.transaction():
            await self._owner(c, actor)
            if user_id == actor:
                raise WorkspaceError('Нельзя приостановить доступ владельца системы.')
            row = await c.fetchrow('UPDATE users SET is_active=$2 WHERE id=$1 RETURNING id,is_active', user_id, active)
            if row is None:
                raise WorkspaceError('Пользователь не найден.')
            if not active:
                # A consumer locks its request until its new session is committed.
                # Wait for those consumers before taking the revocation snapshot,
                # otherwise a just-created session could survive suspension.
                await c.execute("UPDATE web_login_requests SET status='denied',decided_at=clock_timestamp() WHERE user_id=$1 AND status IN ('waiting','approved')", user_id)
                sessions = await c.fetch('UPDATE web_sessions SET revoked_at=clock_timestamp() WHERE user_id=$1 AND revoked_at IS NULL RETURNING id', user_id)
                for session in sessions:
                    await c.execute("INSERT INTO web_auth_events(user_id,session_id,kind) VALUES($1,$2,'access_suspended')", user_id, session['id'])
            await self._audit(c, actor, 'access_resumed' if active else 'access_suspended', 'user', user_id, reason=reason)
            return dict(row)

    async def manager_invite(self, actor, company_id, *, code_factory=None, connection=None):
        async with workspace_transaction(connection) as c:
            await self._owner(c, actor)
            return await self._invite(c, actor, company_id, 'manager', code_factory=code_factory)

    async def revoke_invite(self, actor, company_id):
        async with get_pool().acquire() as c, c.transaction():
            await self._owner(c, actor)
            if not await c.fetchval('SELECT id FROM companies WHERE id=$1 FOR UPDATE', company_id):
                raise WorkspaceError('Компания не найдена.')
            result = await c.execute("UPDATE company_invites SET status='revoked' WHERE company_id=$1 AND role='manager' AND status='active'", company_id)
            await self._audit(c, actor, 'invite_revoked', 'company', company_id, company_id)
            return {'ok': True, 'revoked': result != 'UPDATE 0'}

    async def archive_company(self, actor, company_id):
        async with get_pool().acquire() as c, c.transaction():
            await self._owner(c, actor)
            row = await c.fetchrow('SELECT * FROM companies WHERE id=$1 FOR UPDATE', company_id)
            if row is None:
                raise WorkspaceError('Компания не найдена.')
            if row['status'] == 'archived':
                return dict(row)
            await ensure_settled(c, company_id)
            row = await c.fetchrow("UPDATE companies SET status='archived',manager_user_id=NULL,archived_at=clock_timestamp() WHERE id=$1 RETURNING *", company_id)
            await c.execute("UPDATE company_members SET status='removed',removed_at=clock_timestamp() WHERE company_id=$1 AND status='active'", company_id)
            await c.execute("UPDATE company_invites SET status='revoked' WHERE company_id=$1 AND status='active'", company_id)
            await self._audit(c, actor, 'archived', 'company', company_id, company_id)
            return dict(row)

    async def stats(self, actor):
        async with get_pool().acquire() as c:
            await self._owner(c, actor)
            row = await c.fetchrow('''SELECT (SELECT count(*) FROM users) AS users,
                (SELECT count(*) FROM companies) AS companies,
                (SELECT count(*) FROM companies WHERE status='active') AS active_companies,
                (SELECT count(*) FROM company_members WHERE role='manager' AND status='active') AS managers,
                (SELECT count(*) FROM company_members WHERE role='employee' AND status='active') AS employees,
                (SELECT count(*) FROM projects) AS projects,(SELECT count(*) FROM documents) AS documents''')
            return dict(row)

    async def overview(self, actor, start, end):
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise WorkspaceError('Некорректный период.')
        async with get_pool().acquire() as c, c.transaction(isolation='repeatable_read', readonly=True):
            ctx = await self._manager(c, actor)
            row = await c.fetchrow('''SELECT count(*) AS document_count,
                COALESCE(sum(total_amount) FILTER(WHERE currency='RUB'),0) AS document_total
                FROM documents WHERE company_id=$1 AND created_at>=$2 AND created_at<$3''', ctx['company_id'], start, end)
            result = dict(row)
            result.update(start=start, end=end)
            result['project_count'] = await c.fetchval("SELECT count(*) FROM projects WHERE company_id=$1 AND status='active'", ctx['company_id'])
            result['employee_count'] = await c.fetchval("SELECT count(*) FROM company_members WHERE company_id=$1 AND role='employee' AND status='active'", ctx['company_id'])
            return result
