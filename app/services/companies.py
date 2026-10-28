from __future__ import annotations
import secrets
import string
from dataclasses import dataclass

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from aiogram.types import User
from asyncpg.exceptions import UniqueViolationError

from app.config import get_settings
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


class CompanyService(CompanyInvitations):
    async def ensure_platform_user(self, telegram_user: User) -> int:
        pool = get_pool()
        settings = get_settings()
        system_role = "owner" if telegram_user.id == settings.bot_owner_telegram_id and settings.bot_owner_telegram_id else "user"
        async with pool.acquire() as connection, connection.transaction():
            await connection.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f'external:telegram:{telegram_user.id}')
            linked = await connection.fetchrow(
                """SELECT account.user_id,u.telegram_id,u.is_active FROM external_accounts account
                   JOIN users u ON u.id=account.user_id
                   WHERE account.platform='telegram' AND account.external_id=$1
                   FOR NO KEY UPDATE OF u""", str(telegram_user.id),
            )
            if linked is not None:
                if not linked['is_active']:
                    raise CompanyAccessError('Учётная запись отключена.')
                if linked['telegram_id'] not in (None, telegram_user.id):
                    raise CompanyAccessError('Обнаружена несовместимая привязка аккаунта. Нужна проверка владельцем.')
                await connection.execute(
                    'UPDATE users SET telegram_id=COALESCE(telegram_id,$2),username=$3,first_name=$4,last_name=$5,system_role=$6,updated_at=NOW() WHERE id=$1',
                    linked['user_id'], telegram_user.id, telegram_user.username,
                    telegram_user.first_name, telegram_user.last_name, system_role,
                )
                return linked['user_id']
            if await connection.fetchval("""SELECT 1 FROM account_link_requests
                WHERE target_platform='telegram' AND target_external_id=$1
                AND status='claimed' AND expires_at>clock_timestamp()""", str(telegram_user.id)):
                raise CompanyAccessError('Подтвердите подключение этого Telegram-аккаунта в исходном MAX-профиле. До подтверждения новый профиль не создаётся.')
            user_id = await connection.fetchval(
                """
                INSERT INTO users (telegram_id, username, first_name, last_name, system_role)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (telegram_id) DO UPDATE
                SET username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    system_role = EXCLUDED.system_role,
                    updated_at = NOW()
                WHERE users.is_active
                RETURNING id
                """,
                telegram_user.id, telegram_user.username, telegram_user.first_name,
                telegram_user.last_name, system_role,
            )
            if user_id is None:
                raise CompanyAccessError('Учётная запись отключена.')
            await connection.execute(
                "INSERT INTO external_accounts(user_id,platform,external_id) VALUES($1,'telegram',$2) ON CONFLICT DO NOTHING",
                user_id, str(telegram_user.id),
            )
            linked_id = await connection.fetchval(
                "SELECT user_id FROM external_accounts WHERE platform='telegram' AND external_id=$1",
                str(telegram_user.id),
            )
            if linked_id != user_id:
                raise CompanyAccessError('Аккаунт уже привязан к другому пользователю.')
            return user_id

    async def is_platform_owner(self, telegram_user_id: int) -> bool:
        if not telegram_user_id or telegram_user_id != get_settings().bot_owner_telegram_id:
            return False
        async with get_pool().acquire() as connection:
            return bool(await connection.fetchval(
                """SELECT 1 FROM external_accounts account JOIN users u ON u.id=account.user_id
                   WHERE account.platform='telegram' AND account.external_id=$1 AND u.is_active
                     AND u.telegram_id=$2""", str(telegram_user_id), telegram_user_id,
            ))

    async def get_user_context(self, telegram_user_id: int) -> UserContext:
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await self._get_active_membership_rows(connection, telegram_user_id)
        system_role = "owner" if await self.is_platform_owner(telegram_user_id) else "user"
        if not rows:
            return UserContext(system_role=system_role, company=None, member_role=None)
        row = rows[0]
        return UserContext(system_role=system_role, company=self._build_company(row), member_role=row["member_role"])

    async def create_company(self, telegram_user: User, name: str) -> Company:
        from app.services.workspace import WorkspaceError, WorkspaceService
        actor = await self.ensure_platform_user(telegram_user)
        try:
            row = await WorkspaceService().create_company(actor, name)
        except WorkspaceError as exc:
            raise CompanyAccessError(str(exc)) from exc
        return self._company_from_row(row)

    async def create_initial_manager_invite(self, telegram_user: User, company_id: int) -> str:
        from app.services.workspace import WorkspaceError, WorkspaceService
        actor = await self.ensure_platform_user(telegram_user)
        try:
            invite = await WorkspaceService().manager_invite(actor, company_id, code_factory=_generate_invite_code)
        except WorkspaceError as exc:
            raise CompanyAccessError(str(exc)) from exc
        return invite['code']

    async def get_active_company_for_user(self, telegram_user_id: int) -> Company:
        membership = await self._get_active_membership(telegram_user_id)
        return self._build_company(membership)

    async def ensure_member_role(self, telegram_user_id: int) -> str:
        membership = await self._get_active_membership(telegram_user_id)
        return membership["member_role"]

    async def create_invite(self, telegram_user: User, role: str) -> str:
        from app.services.workspace import WorkspaceError, WorkspaceService
        actor = await self.ensure_platform_user(telegram_user)
        if role != EMPLOYEE_ROLE:
            raise CompanyAccessError('Для приглашения сотрудников доступна только роль employee.')
        try:
            invite = await WorkspaceService().invite_employee(actor, code_factory=_generate_invite_code)
        except WorkspaceError as exc:
            raise CompanyAccessError(str(exc)) from exc
        return invite['code']

    async def join_company(self, telegram_user: User, code: str) -> Company:
        user_id = await self.ensure_platform_user(telegram_user)
        return await self.join_company_by_user_id(user_id, code)


    async def list_company_members(self, telegram_user_id: int) -> list[CompanyMember]:
        company = await self.get_active_company_for_user(telegram_user_id)
        member_role = await self.ensure_member_role(telegram_user_id)
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

    async def remove_employee(self, telegram_user_id: int, member_user_id: int) -> CompanyMember:
        from app.services.workspace import WorkspaceError, WorkspaceService
        actor = await self._workspace_actor(telegram_user_id)
        try:
            result = await WorkspaceService().remove_employee(actor, member_user_id)
        except WorkspaceError as exc:
            raise CompanyAccessError(str(exc)) from exc
        return await self._workspace_member(result['company_id'], member_user_id)

    async def assign_user_to_company_by_owner(self, owner_telegram_user_id: int, target_user_id: int, company_id: int, role: str) -> CompanyMember:
        from app.services.workspace import WorkspaceError, WorkspaceService
        actor = await self._workspace_actor(owner_telegram_user_id)
        try:
            await WorkspaceService().assign_user(actor, target_user_id, company_id, role)
        except WorkspaceError as exc:
            raise CompanyAccessError(str(exc)) from exc
        return await self._workspace_member(company_id, target_user_id)

    async def remove_user_from_company_by_owner(self, owner_telegram_user_id: int, target_user_id: int) -> CompanyMember:
        from app.services.workspace import WorkspaceError, WorkspaceService
        actor = await self._workspace_actor(owner_telegram_user_id)
        try:
            result = await WorkspaceService().remove_user(actor, target_user_id)
        except WorkspaceError as exc:
            raise CompanyAccessError(str(exc)) from exc
        return await self._workspace_member(result['company_id'], target_user_id)

    async def _workspace_actor(self, telegram_user_id: int) -> int:
        async with get_pool().acquire() as connection:
            actor = await connection.fetchval("SELECT a.user_id FROM external_accounts a JOIN users u ON u.id=a.user_id WHERE a.platform='telegram' AND a.external_id=$1 AND u.is_active", str(telegram_user_id))
        if actor is None:
            raise CompanyAccessError('Учётная запись недоступна.')
        return actor

    async def _workspace_member(self, company_id: int, user_id: int) -> CompanyMember:
        async with get_pool().acquire() as connection:
            row = await connection.fetchrow("SELECT cm.company_id,cm.user_id,cm.role,cm.joined_at,u.username,u.first_name,u.last_name,u.telegram_id AS telegram_user_id FROM company_members cm JOIN users u ON u.id=cm.user_id WHERE cm.company_id=$1 AND cm.user_id=$2", company_id,user_id)
        return self._member_from_row(row)


    async def _insert_invite(self, connection, company_id: int, role: str, inviter_id: int) -> str:
        for _ in range(10):
            code = _generate_invite_code()
            try:
                async with connection.transaction():
                    await connection.execute(
                        """
                        INSERT INTO company_invites (company_id, role, code, status, created_by_user_id, expires_at)
                        VALUES ($1, $2, $3, 'active', $4, NOW() + make_interval(hours => $5))
                        """,
                        company_id, role, code, inviter_id, INVITE_TTL_HOURS,
                    )
                return code
            except UniqueViolationError:
                continue
        raise CompanyAccessError("Не удалось сгенерировать уникальный invite-код. Повтори попытку.")

    async def _revoke_active_invites(self, connection, company_id: int, role: str) -> None:
        await connection.execute(
            """
            UPDATE company_invites
            SET status = 'revoked'
            WHERE company_id = $1
              AND role = $2
              AND status = 'active'
            """,
            company_id,
            role,
        )

    async def _expire_outdated_invites(self, connection) -> None:
        await connection.execute(
            """
            UPDATE company_invites
            SET status = 'expired'
            WHERE status = 'active'
              AND expires_at IS NOT NULL
              AND expires_at <= NOW()
            """
        )

    async def _get_active_membership(self, telegram_user_id: int):
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await self._get_active_membership_rows(connection, telegram_user_id)

        if not rows:
            raise CompanyAccessError("У тебя пока нет доступа ни к одной компании. Нужен invite от администратора.")

        company_ids = {row["company_id"] for row in rows}
        if len(company_ids) > 1:
            raise CompanyAccessError("У пользователя найдено несколько активных компаний. Это противоречит текущей продуктовой модели.")

        return rows[0]

    async def _get_active_membership_rows(self, connection, telegram_user_id: int):
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
            WHERE u.telegram_id = $1 AND u.is_active
            ORDER BY cm.joined_at DESC, cm.id DESC
            """,
            telegram_user_id,
        )


    async def _company_has_active_manager(self, connection, company_id: int) -> bool:
        return bool(
            await connection.fetchval(
                """
                SELECT 1
                FROM company_members
                WHERE company_id = $1
                  AND role = $2
                  AND status = 'active'
                LIMIT 1
                """,
                company_id,
                MANAGER_ROLE,
            )
        )

    async def _ensure_platform_owner(self, telegram_user_id: int) -> None:
        if not await self.is_platform_owner(telegram_user_id):
            raise CompanyAccessError("Действие доступно только owner.")

    async def _get_user_id_by_telegram_id(self, connection, telegram_user_id: int) -> int:
        user_id = await connection.fetchval(
            "SELECT id FROM users WHERE telegram_id = $1",
            telegram_user_id,
        )
        if user_id is None:
            raise CompanyAccessError("Пользователь не найден в системе.")
        return user_id

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
