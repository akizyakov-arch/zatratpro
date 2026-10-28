"""Canonical company invitation acceptance. Does not depend on messenger SDKs."""
from contextlib import AsyncExitStack
from app.config import get_owner_telegram_id
from app.schemas.company import Company
from app.services.company_policy import ADMIN_ROLES, WORKER_ROLES, MANAGER_ROLE, EMPLOYEE_LIMIT, CompanyAccessError
from app.services.database import get_pool


class CompanyInvitations:
    async def join_company_by_user_id(self, user_id: int, code: str, *, connection=None, allow_retry=False) -> Company:
        """Canonical invite acceptance shared by adapters; role comes from the invite."""
        if not isinstance(code, str) or not code.strip() or len(code) > 128:
            raise CompanyAccessError('Укажите корректный invite-код.')
        async with AsyncExitStack() as stack:
            c = connection if connection is not None else await stack.enter_async_context(get_pool().acquire())
            await stack.enter_async_context(c.transaction())
            return await self._accept_invite(c, user_id, code.strip().upper(), allow_retry=allow_retry)

    async def _accept_invite(self, connection, user_id, normalized_code, *, allow_retry):
        # Lock the company before consuming its invite; this also serializes
        # the employee-limit check against owner assignments and new invites.
        company_id = await connection.fetchval(
            "SELECT company_id FROM company_invites WHERE code=$1", normalized_code,
        )
        if company_id is None:
            raise CompanyAccessError("Invite-код недействителен или уже использован.")
        await self._lock_company(connection, company_id)
        invite = await connection.fetchrow(
            """
            SELECT ci.id,
                   ci.company_id,
                   ci.role,
                   ci.status AS invite_status,
                   ci.used_by_user_id,
                   c.name,
                   c.status,
                   c.owner_user_id,
                   c.manager_user_id
            FROM company_invites AS ci
            JOIN companies AS c ON c.id = ci.company_id
            WHERE ci.code = $1
              AND ((ci.status = 'active' AND (ci.expires_at IS NULL OR ci.expires_at > clock_timestamp()))
              OR ($2::boolean AND ci.status='used' AND ci.used_by_user_id=$3))
              AND c.status = 'active'
            FOR UPDATE OF ci
            """,
            normalized_code, allow_retry, user_id,
        )
        if invite is None:
            raise CompanyAccessError("Invite-код недействителен или уже использован.")

        user = await connection.fetchrow('SELECT is_active,system_role,telegram_id FROM users WHERE id=$1 FOR NO KEY UPDATE', user_id)
        if user is None or not user['is_active']:
            raise CompanyAccessError('Учётная запись отключена или не найдена.')
        owner_id = get_owner_telegram_id()
        if ((owner_id > 0 and user['telegram_id'] == owner_id)
                or (owner_id == 0 and user['system_role'] == 'owner')):
            raise CompanyAccessError('Owner не может быть участником компании.')
        active_memberships = await connection.fetch(
            """
            SELECT cm.company_id, cm.role
            FROM company_members AS cm
            WHERE cm.user_id = $1
              AND cm.status = 'active'
            ORDER BY cm.joined_at DESC, cm.id DESC
            """,
            user_id,
        )
        active_company_ids = {row["company_id"] for row in active_memberships}
        if len(active_company_ids) > 1:
            raise CompanyAccessError("У пользователя найдено несколько активных компаний. Нужно очистить состояние в БД.")
        if invite['role'] not in ADMIN_ROLES | WORKER_ROLES:
            raise CompanyAccessError('Роль приглашения недоступна.')
        if invite['invite_status'] == 'used':
            if any(row['company_id'] == invite['company_id'] and row['role'] == invite['role'] for row in active_memberships):
                return Company(invite['company_id'], invite['name'], invite['status'], invite['owner_user_id'], invite['manager_user_id'])
            raise CompanyAccessError('Invite-код недействителен или уже использован.')
        if active_company_ids and invite["company_id"] not in active_company_ids:
            raise CompanyAccessError("Пользователь уже состоит в другой компании. По текущей модели доступна только одна компания.")
        if any(row['role'] == MANAGER_ROLE for row in active_memberships) and invite['role'] != MANAGER_ROLE:
            raise CompanyAccessError('Роль руководителя нельзя сменить через invite сотрудника.')

        if invite["role"] == MANAGER_ROLE:
            current_manager_id = invite["manager_user_id"]
            if current_manager_id is not None and current_manager_id != user_id:
                raise CompanyAccessError("У компании уже есть активный руководитель.")
        else:
            same_company_worker = any(
                row["company_id"] == invite["company_id"] and row["role"] in WORKER_ROLES
                for row in active_memberships
            )
            employee_count = await self._count_active_workers(connection, invite["company_id"])
            if employee_count >= EMPLOYEE_LIMIT and not same_company_worker:
                raise CompanyAccessError(f"В компании уже максимальное число сотрудников: {EMPLOYEE_LIMIT}.")

        await connection.execute(
            """
            INSERT INTO company_members (company_id, user_id, role, status, joined_at, removed_at)
            VALUES ($1, $2, $3, 'active', NOW(), NULL)
            ON CONFLICT (company_id, user_id) DO UPDATE
            SET role = EXCLUDED.role,
                status = 'active',
                removed_at = NULL,
                joined_at = COALESCE(company_members.joined_at, NOW())
            """,
            invite["company_id"],
            user_id,
            invite["role"],
        )

        if invite["role"] == MANAGER_ROLE:
            updated = await connection.fetchval(
                """
                UPDATE companies
                SET manager_user_id = $2,
                    updated_at = NOW()
                WHERE id = $1
                  AND status = 'active'
                  AND (manager_user_id IS NULL OR manager_user_id = $2)
                RETURNING id
                """,
                invite["company_id"],
                user_id,
            )
            if updated is None:
                raise CompanyAccessError("У компании уже есть активный руководитель.")

        await connection.execute(
            """
            UPDATE company_invites
            SET status = 'used',
                used_by_user_id = $2,
                used_at = NOW()
            WHERE id = $1
            """,
            invite["id"],
            user_id,
        )

        company_row = await connection.fetchrow(
            """
            SELECT id, name, status, owner_user_id, manager_user_id
            FROM companies
            WHERE id = $1
            """,
            invite["company_id"],
        )
        return self._company_from_row(company_row)

    async def _lock_company(self, connection, company_id: int) -> None:
        row = await connection.fetchrow(
            "SELECT id FROM companies WHERE id=$1 AND status='active' FOR UPDATE", company_id,
        )
        if row is None:
            raise CompanyAccessError("Компания не найдена или уже архивирована.")

    async def _count_active_workers(self, connection, company_id: int) -> int:
        return await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM company_members
            WHERE company_id = $1
              AND role = ANY($2::text[])
              AND status = 'active'
            """,
            company_id,
            list(WORKER_ROLES),
        )

    def _company_from_row(self, row) -> Company:
        return Company(
            id=row["id"],
            name=row["name"],
            status=row["status"],
            owner_user_id=row["owner_user_id"],
            manager_user_id=row["manager_user_id"],
        )
