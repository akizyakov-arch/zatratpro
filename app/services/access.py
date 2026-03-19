from dataclasses import dataclass

from aiogram.types import User

from app.services.companies import ADMIN_ROLES, Company, CompanyService, EMPLOYEE_ROLE, MANAGER_ROLE
from app.services.database import get_pool


@dataclass(slots=True)
class AccessContext:
    platform_user_id: int
    telegram_id: int
    system_role: str
    company: Company | None
    company_role: str | None

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
        platform_user_id = await self.company_service.ensure_platform_user(telegram_user)
        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT u.telegram_id,
                       u.system_role,
                       active.company_id,
                       active.company_name,
                       active.company_status,
                       active.owner_user_id,
                       active.manager_user_id,
                       active.company_role
                FROM users AS u
                LEFT JOIN LATERAL (
                    SELECT c.id AS company_id,
                           c.name AS company_name,
                           c.status AS company_status,
                           c.owner_user_id,
                           c.manager_user_id,
                           cm.role AS company_role
                    FROM company_members AS cm
                    JOIN companies AS c
                      ON c.id = cm.company_id
                     AND c.status = 'active'
                    WHERE cm.user_id = u.id
                      AND cm.status = 'active'
                    ORDER BY cm.joined_at DESC, cm.id DESC
                    LIMIT 1
                ) AS active ON TRUE
                WHERE u.id = $1
                """,
                platform_user_id,
            )

        company = None
        company_role = None
        if row is not None and row["company_id"] is not None:
            company = Company(
                id=row["company_id"],
                name=row["company_name"],
                status=row["company_status"],
                owner_user_id=row["owner_user_id"],
                manager_user_id=row["manager_user_id"],
            )
            company_role = row["company_role"]

        return AccessContext(
            platform_user_id=platform_user_id,
            telegram_id=telegram_user.id,
            system_role=row["system_role"] if row is not None else "user",
            company=company,
            company_role=company_role,
        )
