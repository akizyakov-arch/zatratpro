from dataclasses import dataclass

from aiogram.types import User

from app.services.companies import (
    ACTIVE_MEMBER_STATUS,
    ADMIN_ROLES,
    BLOCKED_MEMBER_STATUS,
    Company,
    CompanyService,
    EMPLOYEE_ROLE,
    MANAGER_ROLE,
)
from app.services.database import get_pool


@dataclass(slots=True)
class AccessContext:
    platform_user_id: int
    telegram_id: int
    system_role: str
    company: Company | None
    company_role: str | None
    membership_status: str | None = None
    is_membership_blocked: bool = False

    @property
    def platform_role(self) -> str:
        return self.system_role

    @property
    def menu_kind(self) -> str:
        if self.system_role == "owner":
            return "platform_owner"
        if self.company_role in ADMIN_ROLES:
            return MANAGER_ROLE
        return EMPLOYEE_ROLE

    @property
    def has_company(self) -> bool:
        return self.company is not None

    @property
    def can_manage_company(self) -> bool:
        return self.company_role in ADMIN_ROLES

    @property
    def can_view_reports(self) -> bool:
        return self.company_role in ADMIN_ROLES


class AccessService:
    def __init__(self) -> None:
        self.company_service = CompanyService()

    async def get_access_context(self, telegram_user: User) -> AccessContext:
        row = await self._fetch_access_row(telegram_user.id)
        if row is None:
            await self.company_service.ensure_platform_user(telegram_user)
            row = await self._fetch_access_row(telegram_user.id)
        return self._build_access_context(row, telegram_user.id)

    async def get_access_context_by_telegram_id(self, telegram_user_id: int) -> AccessContext:
        row = await self._fetch_access_row(telegram_user_id)
        return self._build_access_context(row, telegram_user_id)

    async def _fetch_access_row(self, telegram_user_id: int):
        pool = get_pool()
        async with pool.acquire() as connection:
            return await connection.fetchrow(
                """
                SELECT u.id AS platform_user_id,
                       u.telegram_id,
                       u.system_role,
                       membership.company_id,
                       membership.company_name,
                       membership.company_status,
                       membership.owner_user_id,
                       membership.manager_user_id,
                       membership.company_role,
                       membership.membership_status
                FROM users AS u
                LEFT JOIN LATERAL (
                    SELECT c.id AS company_id,
                           c.name AS company_name,
                           c.status AS company_status,
                           c.owner_user_id,
                           c.manager_user_id,
                           cm.role AS company_role,
                           cm.status AS membership_status
                    FROM company_members AS cm
                    JOIN companies AS c
                      ON c.id = cm.company_id
                     AND c.status = 'active'
                    WHERE cm.user_id = u.id
                      AND cm.status IN ('active', 'blocked')
                    ORDER BY CASE cm.status WHEN 'active' THEN 0 WHEN 'blocked' THEN 1 ELSE 2 END,
                             cm.joined_at DESC,
                             cm.id DESC
                    LIMIT 1
                ) AS membership ON TRUE
                WHERE u.telegram_id = $1
                """,
                telegram_user_id,
            )

    def _build_access_context(self, row, telegram_user_id: int) -> AccessContext:
        membership_status = row["membership_status"] if row is not None else None
        company = None
        company_role = None
        if row is not None and row["company_id"] is not None and membership_status == ACTIVE_MEMBER_STATUS:
            company = Company(
                id=row["company_id"],
                name=row["company_name"],
                status=row["company_status"],
                owner_user_id=row["owner_user_id"],
                manager_user_id=row["manager_user_id"],
            )
            company_role = row["company_role"]

        return AccessContext(
            platform_user_id=row["platform_user_id"] if row is not None else 0,
            telegram_id=telegram_user_id,
            system_role=row["system_role"] if row is not None else "user",
            company=company,
            company_role=company_role,
            membership_status=membership_status,
            is_membership_blocked=membership_status == BLOCKED_MEMBER_STATUS,
        )
