import secrets
import string
from dataclasses import dataclass
import re

from aiogram.types import User

from app.config import get_settings
from app.services.database import get_pool


ADMIN_ROLES = {"company_owner", "company_admin"}
VALID_MEMBER_ROLES = {"company_owner", "company_admin", "employee"}


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
            return self.member_role
        return "employee"

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
        query = """
            SELECT u.platform_role,
                   c.id AS company_id,
                   c.name AS company_name,
                   c.slug AS company_slug,
                   c.is_active AS company_is_active,
                   cm.role AS member_role
            FROM users AS u
            LEFT JOIN company_members AS cm
                ON cm.user_id = u.id AND cm.is_active = TRUE
            LEFT JOIN companies AS c
                ON c.id = cm.company_id AND c.is_active = TRUE
            WHERE u.telegram_user_id = $1
            ORDER BY cm.joined_at NULLS LAST, cm.id
        """
        async with pool.acquire() as connection:
            rows = await connection.fetch(query, telegram_user_id)
        if not rows:
            return UserContext(platform_role="user", company=None, member_role=None)

        active_rows = [row for row in rows if row["company_id"] is not None]
        if len(active_rows) > 1:
            raise CompanyAccessError("Пока поддерживается одна активная компания на пользователя. Следующий шаг — явный выбор компании.")

        row = rows[0]
        if active_rows:
            row = active_rows[0]
            company = Company(
                id=row["company_id"],
                name=row["company_name"],
                slug=row["company_slug"],
                is_active=row["company_is_active"],
            )
            member_role = row["member_role"]
        else:
            company = None
            member_role = None

        return UserContext(platform_role=row["platform_role"], company=company, member_role=member_role)

    async def create_company(self, telegram_user: User, name: str) -> Company:
        await self.ensure_platform_user(telegram_user)
        if not await self.is_platform_owner(telegram_user.id):
            raise CompanyAccessError("Создавать компании может только владелец бота.")

        pool = get_pool()
        slug = await self._generate_unique_slug(name)

        async with pool.acquire() as connection:
            async with connection.transaction():
                user_id = await connection.fetchval(
                    "SELECT id FROM users WHERE telegram_user_id = $1",
                    telegram_user.id,
                )
                row = await connection.fetchrow(
                    """
                    INSERT INTO companies (name, slug)
                    VALUES ($1, $2)
                    RETURNING id, name, slug, is_active
                    """,
                    name,
                    slug,
                )
                await connection.execute(
                    """
                    INSERT INTO company_members (company_id, user_id, role, is_active, invited_by_user_id, joined_at)
                    VALUES ($1, $2, 'company_owner', TRUE, $2, NOW())
                    ON CONFLICT (company_id, user_id) DO UPDATE
                    SET role = 'company_owner',
                        is_active = TRUE,
                        joined_at = COALESCE(company_members.joined_at, NOW())
                    """,
                    row["id"],
                    user_id,
                )
                await self._seed_default_projects(connection, row["id"])
        return Company(id=row["id"], name=row["name"], slug=row["slug"], is_active=row["is_active"])

    async def get_active_company_for_user(self, telegram_user_id: int) -> Company:
        context = await self.get_user_context(telegram_user_id)
        if context.company is None:
            raise CompanyAccessError("У тебя пока нет доступа ни к одной компании. Нужен invite от администратора.")
        return context.company

    async def ensure_member_role(self, telegram_user_id: int) -> str:
        context = await self.get_user_context(telegram_user_id)
        if context.member_role is None:
            raise CompanyAccessError("У тебя нет активной роли в компании.")
        return context.member_role

    async def create_invite(self, telegram_user: User, role: str) -> str:
        await self.ensure_platform_user(telegram_user)
        if role not in VALID_MEMBER_ROLES - {"company_owner"}:
            raise CompanyAccessError("Для invite доступны только роли company_admin и employee.")

        company = await self.get_active_company_for_user(telegram_user.id)
        member_role = await self.ensure_member_role(telegram_user.id)
        if member_role not in ADMIN_ROLES:
            raise CompanyAccessError("Создавать invite может только owner или admin компании.")

        code = _generate_invite_code()
        pool = get_pool()
        async with pool.acquire() as connection:
            inviter_id = await connection.fetchval(
                "SELECT id FROM users WHERE telegram_user_id = $1",
                telegram_user.id,
            )
            await connection.execute(
                """
                INSERT INTO company_invites (company_id, code, role, created_by_user_id, is_active)
                VALUES ($1, $2, $3, $4, TRUE)
                """,
                company.id,
                code,
                role,
                inviter_id,
            )
        return code

    async def join_company(self, telegram_user: User, code: str) -> Company:
        await self.ensure_platform_user(telegram_user)
        normalized_code = code.strip().upper()
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
            raise CompanyAccessError("Просматривать участников может только owner или admin компании.")

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

    async def _seed_default_projects(self, connection, company_id: int) -> None:
        for name in ("Основной объект", "Офис", "Склад"):
            await connection.execute(
                """
                INSERT INTO projects (company_id, name)
                VALUES ($1, $2)
                ON CONFLICT (company_id, name) DO NOTHING
                """,
                company_id,
                name,
            )


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if slug:
        return slug
    return f"company-{secrets.token_hex(4)}"


def _generate_invite_code(length: int = 10) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
