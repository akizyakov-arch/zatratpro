import re
import secrets
import string
from dataclasses import dataclass

from aiogram.types import User

from app.config import get_settings
from app.services.database import get_pool


MANAGER_ROLE = "manager"
EMPLOYEE_ROLE = "employee"
EMPLOYEE_LIMIT = 10
ADMIN_ROLES = {MANAGER_ROLE}
VALID_MEMBER_ROLES = {EMPLOYEE_ROLE}


class CompanyAccessError(RuntimeError):
    pass


@dataclass(slots=True)
class Company:
    id: int
    name: str
    slug: str
    is_active: bool


@dataclass(slots=True)
class CompanyMember:
    company_id: int
    user_id: int
    role: str
    username: str | None
    full_name: str | None
    telegram_user_id: int


@dataclass(slots=True)
class UserContext:
    platform_role: str
    company: Company | None
    member_role: str | None

    @property
    def menu_kind(self) -> str:
        if self.platform_role == "owner":
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


class CompanyService:
    async def ensure_platform_user(self, telegram_user: User) -> int:
        pool = get_pool()
        settings = get_settings()
        platform_role = "owner" if telegram_user.id == settings.bot_owner_telegram_id and settings.bot_owner_telegram_id else "user"
        async with pool.acquire() as connection:
            return await connection.fetchval(
                """
                INSERT INTO users (telegram_user_id, username, full_name, platform_role)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (telegram_user_id) DO UPDATE
                SET username = EXCLUDED.username,
                    full_name = EXCLUDED.full_name,
                    platform_role = CASE
                        WHEN EXCLUDED.platform_role = 'owner' THEN 'owner'
                        ELSE users.platform_role
                    END
                RETURNING id
                """,
                telegram_user.id,
                telegram_user.username,
                telegram_user.full_name,
                platform_role,
            )

    async def is_platform_owner(self, telegram_user_id: int) -> bool:
        pool = get_pool()
        async with pool.acquire() as connection:
            role = await connection.fetchval(
                "SELECT platform_role FROM users WHERE telegram_user_id = $1",
                telegram_user_id,
            )
        return role == "owner"

    async def get_user_context(self, telegram_user_id: int) -> UserContext:
        pool = get_pool()
        async with pool.acquire() as connection:
            base_row = await connection.fetchrow(
                "SELECT platform_role FROM users WHERE telegram_user_id = $1",
                telegram_user_id,
            )
            rows = await self._get_active_membership_rows(connection, telegram_user_id)

        platform_role = base_row["platform_role"] if base_row is not None else "user"
        if not rows:
            return UserContext(platform_role=platform_role, company=None, member_role=None)

        row = rows[0]
        return UserContext(
            platform_role=platform_role,
            company=self._build_company(row),
            member_role=row["member_role"],
        )

    async def create_company(self, telegram_user: User, name: str) -> Company:
        await self.ensure_platform_user(telegram_user)
        if not await self.is_platform_owner(telegram_user.id):
            raise CompanyAccessError("Создавать компании может только владелец бота.")

        normalized_name = name.strip()
        if not normalized_name:
            raise CompanyAccessError("Название компании не должно быть пустым.")

        pool = get_pool()
        slug = await self._generate_unique_slug(normalized_name)

        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO companies (name, slug)
                VALUES ($1, $2)
                RETURNING id, name, slug, is_active
                """,
                normalized_name,
                slug,
            )
        return Company(id=row["id"], name=row["name"], slug=row["slug"], is_active=row["is_active"])

    async def create_initial_manager_invite(self, telegram_user: User, company_id: int) -> str:
        await self.ensure_platform_user(telegram_user)
        if not await self.is_platform_owner(telegram_user.id):
            raise CompanyAccessError("Выдавать первый invite руководителю может только владелец бота.")

        pool = get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                exists = await connection.fetchval(
                    "SELECT 1 FROM companies WHERE id = $1 AND is_active = TRUE",
                    company_id,
                )
                if not exists:
                    raise CompanyAccessError("Компания не найдена или уже архивирована.")

                if await self._company_has_active_manager(connection, company_id):
                    raise CompanyAccessError("У компании уже есть активный руководитель.")

                inviter_id = await connection.fetchval(
                    "SELECT id FROM users WHERE telegram_user_id = $1",
                    telegram_user.id,
                )
                return await self._insert_invite(connection, company_id, MANAGER_ROLE, inviter_id)

    async def get_active_company_for_user(self, telegram_user_id: int) -> Company:
        membership = await self._get_active_membership(telegram_user_id)
        return self._build_company(membership)

    async def ensure_member_role(self, telegram_user_id: int) -> str:
        membership = await self._get_active_membership(telegram_user_id)
        return membership["member_role"]

    async def create_invite(self, telegram_user: User, role: str) -> str:
        await self.ensure_platform_user(telegram_user)
        if role not in VALID_MEMBER_ROLES:
            raise CompanyAccessError("Для invite сотрудников доступна только роль employee.")

        company = await self.get_active_company_for_user(telegram_user.id)
        member_role = await self.ensure_member_role(telegram_user.id)
        if member_role not in ADMIN_ROLES:
            raise CompanyAccessError("Создавать invite может только руководитель компании.")

        pool = get_pool()
        async with pool.acquire() as connection:
            employee_count = await self._count_active_employees(connection, company.id)
            if employee_count >= EMPLOYEE_LIMIT:
                raise CompanyAccessError(f"В компании уже максимальное число сотрудников: {EMPLOYEE_LIMIT}.")

            inviter_id = await connection.fetchval(
                "SELECT id FROM users WHERE telegram_user_id = $1",
                telegram_user.id,
            )
            return await self._insert_invite(connection, company.id, role, inviter_id)

    async def join_company(self, telegram_user: User, code: str) -> Company:
        await self.ensure_platform_user(telegram_user)
        normalized_code = code.strip().upper()
        if not normalized_code:
            raise CompanyAccessError("Invite-код не должен быть пустым.")

        pool = get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                invite = await connection.fetchrow(
                    """
                    SELECT ci.id, ci.company_id, ci.role, c.name, c.slug, c.is_active
                    FROM company_invites AS ci
                    JOIN companies AS c ON c.id = ci.company_id
                    WHERE ci.code = $1
                      AND ci.is_active = TRUE
                      AND c.is_active = TRUE
                      AND (ci.expires_at IS NULL OR ci.expires_at > NOW())
                    """,
                    normalized_code,
                )
                if invite is None:
                    raise CompanyAccessError("Invite-код недействителен или уже использован.")

                user_id = await connection.fetchval(
                    "SELECT id FROM users WHERE telegram_user_id = $1",
                    telegram_user.id,
                )
                active_memberships = await connection.fetch(
                    """
                    SELECT cm.company_id, cm.role
                    FROM company_members AS cm
                    WHERE cm.user_id = $1
                      AND cm.is_active = TRUE
                    ORDER BY cm.joined_at DESC NULLS LAST, cm.id DESC
                    """,
                    user_id,
                )
                active_company_ids = {row["company_id"] for row in active_memberships}
                if len(active_company_ids) > 1:
                    raise CompanyAccessError("У пользователя найдено несколько активных компаний. Нужно очистить состояние в БД.")
                if active_company_ids and invite["company_id"] not in active_company_ids:
                    raise CompanyAccessError("Пользователь уже состоит в другой компании. По текущей модели доступна только одна компания.")

                if invite["role"] == MANAGER_ROLE:
                    if await self._company_has_active_manager(connection, invite["company_id"]):
                        same_company_manager = any(
                            row["company_id"] == invite["company_id"] and row["role"] == MANAGER_ROLE
                            for row in active_memberships
                        )
                        if not same_company_manager:
                            raise CompanyAccessError("У компании уже есть активный руководитель.")
                else:
                    same_company_employee = any(
                        row["company_id"] == invite["company_id"] and row["role"] == EMPLOYEE_ROLE
                        for row in active_memberships
                    )
                    employee_count = await self._count_active_employees(connection, invite["company_id"])
                    if employee_count >= EMPLOYEE_LIMIT and not same_company_employee:
                        raise CompanyAccessError(f"В компании уже максимальное число сотрудников: {EMPLOYEE_LIMIT}.")

                await connection.execute(
                    """
                    INSERT INTO company_members (company_id, user_id, role, is_active, joined_at)
                    VALUES ($1, $2, $3, TRUE, NOW())
                    ON CONFLICT (company_id, user_id) DO UPDATE
                    SET role = EXCLUDED.role,
                        is_active = TRUE,
                        joined_at = COALESCE(company_members.joined_at, NOW())
                    """,
                    invite["company_id"],
                    user_id,
                    invite["role"],
                )
                await connection.execute(
                    """
                    UPDATE company_invites
                    SET is_active = FALSE,
                        used_by_user_id = $2,
                        used_at = NOW()
                    WHERE id = $1
                    """,
                    invite["id"],
                    user_id,
                )
        return Company(id=invite["company_id"], name=invite["name"], slug=invite["slug"], is_active=invite["is_active"])

    async def list_company_members(self, telegram_user_id: int) -> list[CompanyMember]:
        company = await self.get_active_company_for_user(telegram_user_id)
        member_role = await self.ensure_member_role(telegram_user_id)
        if member_role not in ADMIN_ROLES:
            raise CompanyAccessError("Просматривать участников может только руководитель компании.")

        pool = get_pool()
        query = """
            SELECT cm.company_id,
                   cm.user_id,
                   cm.role,
                   u.username,
                   u.full_name,
                   u.telegram_user_id
            FROM company_members AS cm
            JOIN users AS u ON u.id = cm.user_id
            WHERE cm.company_id = $1
              AND cm.is_active = TRUE
            ORDER BY cm.role, u.full_name NULLS LAST, u.telegram_user_id
        """
        async with pool.acquire() as connection:
            rows = await connection.fetch(query, company.id)
        return [
            CompanyMember(
                company_id=row["company_id"],
                user_id=row["user_id"],
                role=row["role"],
                username=row["username"],
                full_name=row["full_name"],
                telegram_user_id=row["telegram_user_id"],
            )
            for row in rows
        ]

    async def remove_employee(self, telegram_user_id: int, member_user_id: int) -> CompanyMember:
        company = await self.get_active_company_for_user(telegram_user_id)
        member_role = await self.ensure_member_role(telegram_user_id)
        if member_role not in ADMIN_ROLES:
            raise CompanyAccessError("Исключать сотрудников может только руководитель компании.")

        pool = get_pool()
        query = """
            UPDATE company_members AS cm
            SET is_active = FALSE
            FROM users AS u
            WHERE cm.user_id = u.id
              AND cm.company_id = $1
              AND cm.user_id = $2
              AND cm.role = 'employee'
              AND cm.is_active = TRUE
            RETURNING cm.company_id, cm.user_id, cm.role, u.username, u.full_name, u.telegram_user_id
        """
        async with pool.acquire() as connection:
            row = await connection.fetchrow(query, company.id, member_user_id)
        if row is None:
            raise CompanyAccessError("Сотрудник не найден в текущей компании или уже исключен.")

        return CompanyMember(
            company_id=row["company_id"],
            user_id=row["user_id"],
            role=row["role"],
            username=row["username"],
            full_name=row["full_name"],
            telegram_user_id=row["telegram_user_id"],
        )

    async def _generate_unique_slug(self, name: str) -> str:
        pool = get_pool()
        base_slug = _slugify(name)
        async with pool.acquire() as connection:
            slug = base_slug
            suffix = 1
            while await connection.fetchval("SELECT 1 FROM companies WHERE slug = $1", slug):
                suffix += 1
                slug = f"{base_slug}-{suffix}"
        return slug

    async def _insert_invite(self, connection, company_id: int, role: str, inviter_id: int | None) -> str:
        code = _generate_invite_code()
        await connection.execute(
            """
            INSERT INTO company_invites (company_id, code, role, created_by_user_id, is_active)
            VALUES ($1, $2, $3, $4, TRUE)
            """,
            company_id,
            code,
            role,
            inviter_id,
        )
        return code

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
                   c.slug AS company_slug,
                   c.is_active AS company_is_active,
                   cm.role AS member_role
            FROM users AS u
            JOIN company_members AS cm
                ON cm.user_id = u.id AND cm.is_active = TRUE
            JOIN companies AS c
                ON c.id = cm.company_id AND c.is_active = TRUE
            WHERE u.telegram_user_id = $1
            ORDER BY cm.joined_at DESC NULLS LAST, cm.id DESC
            """,
            telegram_user_id,
        )

    async def _count_active_employees(self, connection, company_id: int) -> int:
        return await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM company_members
            WHERE company_id = $1
              AND role = $2
              AND is_active = TRUE
            """,
            company_id,
            EMPLOYEE_ROLE,
        )

    async def _company_has_active_manager(self, connection, company_id: int) -> bool:
        return bool(
            await connection.fetchval(
                """
                SELECT 1
                FROM company_members
                WHERE company_id = $1
                  AND role = $2
                  AND is_active = TRUE
                LIMIT 1
                """,
                company_id,
                MANAGER_ROLE,
            )
        )

    def _build_company(self, row) -> Company:
        return Company(
            id=row["company_id"],
            name=row["company_name"],
            slug=row["company_slug"],
            is_active=row["company_is_active"],
        )


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if slug:
        return slug
    return f"company-{secrets.token_hex(4)}"


def _generate_invite_code(length: int = 10) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))