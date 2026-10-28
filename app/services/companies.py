from __future__ import annotations
import secrets
import string
from dataclasses import dataclass

from asyncpg.exceptions import UniqueViolationError

from app.config import get_owner_telegram_id
from app.services.database import get_pool
from app.schemas.company import Company
from app.services.company_invitations import CompanyInvitations


from app.services.company_policy import (
    MANAGER_ROLE, EMPLOYEE_ROLE, MASTER_ROLE, ADMIN_ROLES, WORKER_ROLES,
    VALID_MEMBER_ROLES, EMPLOYEE_LIMIT, INVITE_TTL_HOURS, CompanyAccessError,
)


@dataclass(slots=True)
class CompanyMember:
    company_id: int
    user_id: int
    role: str
    username: str | None
    first_name: str | None
    last_name: str | None
    telegram_user_id: int | None
    joined_at: object | None = None

    @property
    def full_name(self) -> str | None:
        parts = [part for part in (self.first_name, self.last_name) if part]
        return " ".join(parts) or None


@dataclass(slots=True)
class UserContext:
    system_role: str
    company: Company | None
    member_role: str | None

    @property
    def platform_role(self) -> str:
        return self.system_role

    @property
    def menu_kind(self) -> str:
        if self.system_role == "owner":
            return "platform_owner"
        if self.member_role in ADMIN_ROLES:
            return MANAGER_ROLE
        return EMPLOYEE_ROLE

    @property
    def has_company(self) -> bool:
        return self.company is not None

    @property
    def can_manage_company(self) -> bool:
        return self.member_role in ADMIN_ROLES

    @property
    def can_view_reports(self) -> bool:
        return self.member_role in ADMIN_ROLES


class CompanyDirectory(CompanyInvitations):

    async def is_platform_owner(self, actor_id: int) -> bool:
        owner = get_owner_telegram_id()
        return bool(owner and await get_pool().fetchval("""SELECT 1 FROM users u JOIN external_accounts a ON a.user_id=u.id
            WHERE u.id=$1 AND u.is_active AND u.telegram_id=$2 AND a.platform='telegram' AND a.external_id=$3""",actor_id,owner,str(owner)))

    async def get_user_context(self, actor_id: int) -> UserContext:
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await self._get_active_membership_rows(connection, actor_id)
        system_role = "owner" if await self.is_platform_owner(actor_id) else "user"
        if not rows:
            return UserContext(system_role=system_role, company=None, member_role=None)
        row = rows[0]
        return UserContext(system_role=system_role, company=self._build_company(row), member_role=row["member_role"])

    async def create_company(self, actor: int, name: str) -> Company:
        from app.services.workspace import WorkspaceError, WorkspaceService
        actor = await self._workspace_actor(actor)
        try:
            row = await WorkspaceService().create_company(actor, name)
        except WorkspaceError as exc:
            raise CompanyAccessError(str(exc)) from exc
        return self._company_from_row(row)

    async def create_initial_manager_invite(self, actor: int, company_id: int) -> str:
        from app.services.workspace import WorkspaceError, WorkspaceService
        actor = await self._workspace_actor(actor)
        try:
            invite = await WorkspaceService().manager_invite(actor, company_id, code_factory=_generate_invite_code)
        except WorkspaceError as exc:
            raise CompanyAccessError(str(exc)) from exc
        return invite['code']

    async def get_active_company_for_user(self, actor_id: int) -> Company:
        membership = await self._get_active_membership(actor_id)
        return self._build_company(membership)

    async def ensure_member_role(self, actor_id: int) -> str:
        membership = await self._get_active_membership(actor_id)
        return membership["member_role"]

    async def create_invite(self, actor: int, role: str) -> str:
        from app.services.workspace import WorkspaceError, WorkspaceService
        actor = await self._workspace_actor(actor)
        if role != EMPLOYEE_ROLE:
            raise CompanyAccessError('Для приглашения сотрудников доступна только роль employee.')
        try:
            invite = await WorkspaceService().invite_employee(actor, code_factory=_generate_invite_code)
        except WorkspaceError as exc:
            raise CompanyAccessError(str(exc)) from exc
        return invite['code']

    async def join_company(self, actor: int, code: str) -> Company:
        user_id = await self._workspace_actor(actor)
        return await self.join_company_by_user_id(user_id, code)


    async def list_company_members(self, actor_id: int) -> list[CompanyMember]:
        company = await self.get_active_company_for_user(actor_id)
        member_role = await self.ensure_member_role(actor_id)
        if member_role not in ADMIN_ROLES:
            raise CompanyAccessError("Просматривать участников может только руководитель компании.")

        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT cm.company_id,
                       cm.user_id,
                       cm.role,
                       cm.joined_at,
                       u.username,
                       u.first_name,
                       u.last_name,
                       u.telegram_id AS telegram_user_id
                FROM company_members AS cm
                JOIN users AS u ON u.id = cm.user_id
                WHERE cm.company_id = $1
                  AND cm.status = 'active'
                ORDER BY cm.role, cm.joined_at, cm.id
                """,
                company.id,
            )
        return [self._member_from_row(row) for row in rows]

    async def remove_employee(self, actor_id: int, member_user_id: int) -> CompanyMember:
        from app.services.workspace import WorkspaceError, WorkspaceService
        actor = await self._workspace_actor(actor_id)
        try:
            result = await WorkspaceService().remove_employee(actor, member_user_id)
        except WorkspaceError as exc:
            raise CompanyAccessError(str(exc)) from exc
        return await self._workspace_member(result['company_id'], member_user_id)

    async def assign_user_to_company_by_owner(self, owner_actor_id: int, target_user_id: int, company_id: int, role: str) -> CompanyMember:
        from app.services.workspace import WorkspaceError, WorkspaceService
        actor = await self._workspace_actor(owner_actor_id)
        try:
            await WorkspaceService().assign_user(actor, target_user_id, company_id, role)
        except WorkspaceError as exc:
            raise CompanyAccessError(str(exc)) from exc
        return await self._workspace_member(company_id, target_user_id)

    async def remove_user_from_company_by_owner(self, owner_actor_id: int, target_user_id: int) -> CompanyMember:
        from app.services.workspace import WorkspaceError, WorkspaceService
        actor = await self._workspace_actor(owner_actor_id)
        try:
            result = await WorkspaceService().remove_user(actor, target_user_id)
        except WorkspaceError as exc:
            raise CompanyAccessError(str(exc)) from exc
        return await self._workspace_member(result['company_id'], target_user_id)

    async def _workspace_actor(self, actor_id: int) -> int:
        if not await get_pool().fetchval('SELECT id FROM users WHERE id=$1 AND is_active',actor_id):
            raise CompanyAccessError('Учётная запись недоступна.')
        return actor_id

    async def _workspace_member(self, company_id: int, user_id: int) -> CompanyMember:
        async with get_pool().acquire() as connection:
            row = await connection.fetchrow("SELECT cm.company_id,cm.user_id,cm.role,cm.joined_at,u.username,u.first_name,u.last_name,u.telegram_id AS telegram_user_id FROM company_members cm JOIN users u ON u.id=cm.user_id WHERE cm.company_id=$1 AND cm.user_id=$2", company_id,user_id)
        return self._member_from_row(row)





    async def _get_active_membership(self, actor_id: int):
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await self._get_active_membership_rows(connection, actor_id)

        if not rows:
            raise CompanyAccessError("У тебя пока нет доступа ни к одной компании. Нужен invite от администратора.")

        company_ids = {row["company_id"] for row in rows}
        if len(company_ids) > 1:
            raise CompanyAccessError("У пользователя найдено несколько активных компаний. Это противоречит текущей продуктовой модели.")

        return rows[0]

    async def _get_active_membership_rows(self, connection, actor_id: int):
        return await connection.fetch(
            """
            SELECT c.id AS company_id,
                   c.name AS company_name,
                   c.status AS company_status,
                   c.owner_user_id,
                   c.manager_user_id,
                   cm.role AS member_role
            FROM users AS u
            JOIN company_members AS cm
                ON cm.user_id = u.id AND cm.status = 'active'
            JOIN companies AS c
                ON c.id = cm.company_id AND c.status = 'active'
            WHERE u.id = $1 AND u.is_active
            ORDER BY cm.joined_at DESC, cm.id DESC
            """,
            actor_id,
        )





    def _build_company(self, row) -> Company:
        return Company(
            id=row["company_id"],
            name=row["company_name"],
            status=row["company_status"],
            owner_user_id=row["owner_user_id"],
            manager_user_id=row["manager_user_id"],
        )


    def _member_from_row(self, row) -> CompanyMember:
        return CompanyMember(
            company_id=row["company_id"],
            user_id=row["user_id"],
            role=row["role"],
            username=row["username"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            telegram_user_id=row["telegram_user_id"],
            joined_at=row["joined_at"],
        )


def _generate_invite_code(length: int = 10) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
