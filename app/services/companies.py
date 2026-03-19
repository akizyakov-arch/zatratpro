import secrets
import string
from dataclasses import dataclass

from aiogram.types import User
from asyncpg.exceptions import UniqueViolationError

from app.config import get_settings
from app.services.database import get_pool


MANAGER_ROLE = "manager"
EMPLOYEE_ROLE = "employee"
MASTER_ROLE = "master"
ADMIN_ROLES = {MANAGER_ROLE}
WORKER_ROLES = {EMPLOYEE_ROLE}
VALID_MEMBER_ROLES = {MANAGER_ROLE, EMPLOYEE_ROLE, MASTER_ROLE}
EMPLOYEE_LIMIT = 10
INVITE_TTL_HOURS = 72


class CompanyAccessError(RuntimeError):
    pass


@dataclass(slots=True)
class Company:
    id: int
    name: str
    status: str
    owner_user_id: int | None = None
    manager_user_id: int | None = None

    @property
    def is_active(self) -> bool:
        return self.status == "active"


@dataclass(slots=True)
class CompanyMember:
    company_id: int
    user_id: int
    role: str
    username: str | None
    first_name: str | None
    last_name: str | None
    telegram_user_id: int
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


class CompanyService:
    async def ensure_platform_user(self, telegram_user: User) -> int:
        pool = get_pool()
        settings = get_settings()
        system_role = "owner" if telegram_user.id == settings.bot_owner_telegram_id and settings.bot_owner_telegram_id else "user"
        async with pool.acquire() as connection:
            return await connection.fetchval(
                """
                INSERT INTO users (telegram_id, username, first_name, last_name, system_role)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (telegram_id) DO UPDATE
                SET username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    system_role = CASE
                        WHEN EXCLUDED.system_role = 'owner' THEN 'owner'
                        ELSE users.system_role
                    END,
                    updated_at = NOW()
                RETURNING id
                """,
                telegram_user.id,
                telegram_user.username,
                telegram_user.first_name,
                telegram_user.last_name,
                system_role,
            )

    async def is_platform_owner(self, telegram_user_id: int) -> bool:
        pool = get_pool()
        async with pool.acquire() as connection:
            role = await connection.fetchval(
                "SELECT system_role FROM users WHERE telegram_id = $1",
                telegram_user_id,
            )
        return role == "owner"

    async def get_user_context(self, telegram_user_id: int) -> UserContext:
        pool = get_pool()
        async with pool.acquire() as connection:
            base_row = await connection.fetchrow(
                "SELECT system_role FROM users WHERE telegram_id = $1",
                telegram_user_id,
            )
            rows = await self._get_active_membership_rows(connection, telegram_user_id)

        system_role = base_row["system_role"] if base_row is not None else "user"
        if not rows:
            return UserContext(system_role=system_role, company=None, member_role=None)

        row = rows[0]
        return UserContext(
            system_role=system_role,
            company=self._build_company(row),
            member_role=row["member_role"],
        )

    async def create_company(self, telegram_user: User, name: str) -> Company:
        owner_user_id = await self.ensure_platform_user(telegram_user)
        if not await self.is_platform_owner(telegram_user.id):
            raise CompanyAccessError("Создавать компании может только владелец бота.")

        normalized_name = name.strip()
        if not normalized_name:
            raise CompanyAccessError("Название компании не должно быть пустым.")

        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO companies (name, owner_user_id)
                VALUES ($1, $2)
                RETURNING id, name, status, owner_user_id, manager_user_id
                """,
                normalized_name,
                owner_user_id,
            )
        return self._company_from_row(row)

    async def create_initial_manager_invite(self, telegram_user: User, company_id: int) -> str:
        await self.ensure_platform_user(telegram_user)
        if not await self.is_platform_owner(telegram_user.id):
            raise CompanyAccessError("Выдавать первый invite руководителю может только владелец бота.")

        pool = get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                company = await connection.fetchrow(
                    """
                    SELECT id, owner_user_id, manager_user_id, status
                    FROM companies
                    WHERE id = $1
                    """,
                    company_id,
                )
                if company is None or company["status"] != "active":
                    raise CompanyAccessError("Компания не найдена или уже архивирована.")
                if company["manager_user_id"] is not None or await self._company_has_active_manager(connection, company_id):
                    raise CompanyAccessError("У компании уже есть активный руководитель.")

                inviter_id = await self._get_user_id_by_telegram_id(connection, telegram_user.id)
                await self._revoke_active_invites(connection, company_id, MANAGER_ROLE)
                return await self._insert_invite(connection, company_id, MANAGER_ROLE, inviter_id)

    async def get_active_company_for_user(self, telegram_user_id: int) -> Company:
        membership = await self._get_active_membership(telegram_user_id)
        return self._build_company(membership)

    async def ensure_member_role(self, telegram_user_id: int) -> str:
        membership = await self._get_active_membership(telegram_user_id)
        return membership["member_role"]

    async def create_invite(self, telegram_user: User, role: str) -> str:
        await self.ensure_platform_user(telegram_user)
        if role not in WORKER_ROLES:
            raise CompanyAccessError("Для invite сотрудников доступна только роль employee.")

        company = await self.get_active_company_for_user(telegram_user.id)
        member_role = await self.ensure_member_role(telegram_user.id)
        if member_role not in ADMIN_ROLES:
            raise CompanyAccessError("Создавать invite может только руководитель компании.")

        pool = get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                employee_count = await self._count_active_workers(connection, company.id)
                if employee_count >= EMPLOYEE_LIMIT:
                    raise CompanyAccessError(f"В компании уже максимальное число сотрудников: {EMPLOYEE_LIMIT}.")

                inviter_id = await self._get_user_id_by_telegram_id(connection, telegram_user.id)
                for worker_role in WORKER_ROLES:
                    await self._revoke_active_invites(connection, company.id, worker_role)
                return await self._insert_invite(connection, company.id, role, inviter_id)

    async def join_company(self, telegram_user: User, code: str) -> Company:
        await self.ensure_platform_user(telegram_user)
        normalized_code = code.strip().upper()
        if not normalized_code:
            raise CompanyAccessError("Invite-код не должен быть пустым.")

        pool = get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await self._expire_outdated_invites(connection)
                invite = await connection.fetchrow(
                    """
                    SELECT ci.id,
                           ci.company_id,
                           ci.role,
                           c.name,
                           c.status,
                           c.owner_user_id,
                           c.manager_user_id
                    FROM company_invites AS ci
                    JOIN companies AS c ON c.id = ci.company_id
                    WHERE ci.code = $1
                      AND ci.status = 'new'
                      AND c.status = 'active'
                      AND (ci.expires_at IS NULL OR ci.expires_at > NOW())
                    """,
                    normalized_code,
                )
                if invite is None:
                    raise CompanyAccessError("Invite-код недействителен или уже использован.")

                user_id = await self._get_user_id_by_telegram_id(connection, telegram_user.id)
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
                if active_company_ids and invite["company_id"] not in active_company_ids:
                    raise CompanyAccessError("Пользователь уже состоит в другой компании. По текущей модели доступна только одна компания.")

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
                          AND status = 'new'
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
        company = await self.get_active_company_for_user(telegram_user_id)
        member_role = await self.ensure_member_role(telegram_user_id)
        if member_role not in ADMIN_ROLES:
            raise CompanyAccessError("Исключать сотрудников может только руководитель компании.")

        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                UPDATE company_members AS cm
                SET status = 'removed',
                    removed_at = NOW()
                FROM users AS u
                WHERE cm.user_id = u.id
                  AND cm.company_id = $1
                  AND cm.user_id = $2
                  AND cm.role = ANY($3::text[])
                  AND cm.status = 'active'
                RETURNING cm.company_id,
                          cm.user_id,
                          cm.role,
                          cm.joined_at,
                          u.username,
                          u.first_name,
                          u.last_name,
                          u.telegram_id AS telegram_user_id
                """,
                company.id,
                member_user_id,
                list(WORKER_ROLES),
            )
        if row is None:
            raise CompanyAccessError("Сотрудник не найден в текущей компании или уже исключен.")
        return self._member_from_row(row)

    async def assign_user_to_company_by_owner(
        self,
        owner_telegram_user_id: int,
        target_user_id: int,
        company_id: int,
        role: str,
    ) -> CompanyMember:
        if role not in {MANAGER_ROLE, EMPLOYEE_ROLE}:
            raise CompanyAccessError("Недопустимая роль для привязки пользователя.")
        await self._ensure_platform_owner(owner_telegram_user_id)

        pool = get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                target_user = await connection.fetchrow(
                    """
                    SELECT id, username, first_name, last_name, telegram_id AS telegram_user_id, system_role
                    FROM users
                    WHERE id = $1
                    """,
                    target_user_id,
                )
                if target_user is None:
                    raise CompanyAccessError("Пользователь не найден.")
                if target_user["system_role"] == "owner":
                    raise CompanyAccessError("Owner не может быть участником компании.")

                company = await connection.fetchrow(
                    """
                    SELECT id, status, manager_user_id
                    FROM companies
                    WHERE id = $1
                    """,
                    company_id,
                )
                if company is None or company["status"] != "active":
                    raise CompanyAccessError("Компания не найдена или уже архивирована.")

                active_membership = await connection.fetchrow(
                    """
                    SELECT company_id, role
                    FROM company_members
                    WHERE user_id = $1
                      AND status = 'new'
                    ORDER BY joined_at DESC, id DESC
                    LIMIT 1
                    """,
                    target_user_id,
                )
                if active_membership is not None and active_membership["company_id"] != company_id:
                    raise CompanyAccessError("Пользователь уже привязан к другой компании. Сначала исключи его из текущей компании.")

                if role in WORKER_ROLES:
                    is_same_active_worker = (
                        active_membership is not None
                        and active_membership["company_id"] == company_id
                        and active_membership["role"] in WORKER_ROLES
                    )
                    employee_count = await self._count_active_workers(connection, company_id)
                    if employee_count >= EMPLOYEE_LIMIT and not is_same_active_worker:
                        raise CompanyAccessError(f"В компании уже максимальное число сотрудников: {EMPLOYEE_LIMIT}.")
                    if company["manager_user_id"] == target_user_id:
                        await connection.execute(
                            """
                            UPDATE companies
                            SET manager_user_id = NULL,
                                updated_at = NOW()
                            WHERE id = $1
                            """,
                            company_id,
                        )
                else:
                    current_manager_user_id = company["manager_user_id"]
                    if current_manager_user_id is not None and current_manager_user_id != target_user_id:
                        raise CompanyAccessError("У компании уже есть активный manager.")
                    await connection.execute(
                        """
                        UPDATE companies
                        SET manager_user_id = $2,
                            updated_at = NOW()
                        WHERE id = $1
                        """,
                        company_id,
                        target_user_id,
                    )

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
                    company_id,
                    target_user_id,
                    role,
                )

                member_row = await connection.fetchrow(
                    """
                    SELECT cm.company_id,
                           cm.user_id,
                           cm.role,
                           cm.joined_at,
                           u.username,
                           u.first_name,
                           u.last_name,
                           u.telegram_id AS telegram_user_id
                    FROM company_members cm
                    JOIN users u ON u.id = cm.user_id
                    WHERE cm.company_id = $1
                      AND cm.user_id = $2
                      AND cm.status = 'active'
                    """,
                    company_id,
                    target_user_id,
                )
        return self._member_from_row(member_row)

    async def remove_user_from_company_by_owner(self, owner_telegram_user_id: int, target_user_id: int) -> CompanyMember:
        await self._ensure_platform_owner(owner_telegram_user_id)

        pool = get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                membership = await connection.fetchrow(
                    """
                    SELECT cm.company_id,
                           cm.user_id,
                           cm.role,
                           cm.joined_at,
                           u.username,
                           u.first_name,
                           u.last_name,
                           u.telegram_id AS telegram_user_id
                    FROM company_members cm
                    JOIN users u ON u.id = cm.user_id
                    WHERE cm.user_id = $1
                      AND cm.status = 'active'
                    ORDER BY cm.joined_at DESC, cm.id DESC
                    LIMIT 1
                    """,
                    target_user_id,
                )
                if membership is None:
                    raise CompanyAccessError("Пользователь не привязан ни к одной активной компании.")

                await connection.execute(
                    """
                    UPDATE company_members
                    SET status = 'removed',
                        removed_at = NOW()
                    WHERE company_id = $1
                      AND user_id = $2
                      AND status = 'new'
                    """,
                    membership["company_id"],
                    target_user_id,
                )
                if membership["role"] == MANAGER_ROLE:
                    await connection.execute(
                        """
                        UPDATE companies
                        SET manager_user_id = NULL,
                            updated_at = NOW()
                        WHERE id = $1
                          AND manager_user_id = $2
                        """,
                        membership["company_id"],
                        target_user_id,
                    )
        return self._member_from_row(membership)

    async def _insert_invite(self, connection, company_id: int, role: str, inviter_id: int) -> str:
        for _ in range(10):
            code = _generate_invite_code()
            try:
                start_token = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(24))
                await connection.execute(
                    """
                    INSERT INTO company_invites (company_id, role, code, status, created_by_user_id, start_token, expires_at)
                    VALUES ($1, $2, $3, 'new', $4, $5, NOW() + make_interval(hours => $6))
                    """,
                    company_id,
                    role,
                    code,
                    inviter_id,
                    start_token,
                    INVITE_TTL_HOURS,
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
              AND status = 'new'
            """,
            company_id,
            role,
        )

    async def _expire_outdated_invites(self, connection) -> None:
        await connection.execute(
            """
            UPDATE company_invites
            SET status = 'expired'
            WHERE status = 'new'
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
            WHERE u.telegram_id = $1
            ORDER BY cm.joined_at DESC, cm.id DESC
            """,
            telegram_user_id,
        )

    async def _count_active_workers(self, connection, company_id: int) -> int:
        return await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM company_members
            WHERE company_id = $1
              AND role = ANY($2::text[])
              AND status = 'new'
            """,
            company_id,
            list(WORKER_ROLES),
        )

    async def _company_has_active_manager(self, connection, company_id: int) -> bool:
        return bool(
            await connection.fetchval(
                """
                SELECT 1
                FROM company_members
                WHERE company_id = $1
                  AND role = $2
                  AND status = 'new'
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

    def _company_from_row(self, row) -> Company:
        return Company(
            id=row["id"],
            name=row["name"],
            status=row["status"],
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
