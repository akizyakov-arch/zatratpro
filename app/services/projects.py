from dataclasses import dataclass

from app.services.companies import ADMIN_ROLES, CompanyAccessError, CompanyService
from app.services.database import get_pool


@dataclass(slots=True)
class Project:
    id: int
    company_id: int
    name: str
    status: str

    @property
    def is_archived(self) -> bool:
        return self.status == "archived"


class ProjectService:
    def __init__(self) -> None:
        self.company_service = CompanyService()

    async def list_active_projects(self, telegram_user_id: int) -> list[Project]:
        return await self._list_projects(telegram_user_id, status="active")

    async def list_archived_projects(self, telegram_user_id: int) -> list[Project]:
        member_role = await self.company_service.ensure_member_role(telegram_user_id)
        if member_role not in ADMIN_ROLES:
            raise CompanyAccessError("Просматривать архив проектов может только руководитель компании.")
        return await self._list_projects(telegram_user_id, status="archived")

    async def _list_projects(self, telegram_user_id: int, status: str) -> list[Project]:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT id, company_id, name, status
                FROM projects
                WHERE company_id = $1
                  AND status = $2
                ORDER BY created_at, id
                """,
                company.id,
                status,
            )
        return [Project(id=row["id"], company_id=row["company_id"], name=row["name"], status=row["status"]) for row in rows]

    async def get_active_project(self, telegram_user_id: int, project_id: int) -> Project | None:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT id, company_id, name, status
                FROM projects
                WHERE id = $1
                  AND company_id = $2
                  AND status = 'active'
                """,
                project_id,
                company.id,
            )
        if row is None:
            return None
        return Project(id=row["id"], company_id=row["company_id"], name=row["name"], status=row["status"])

    async def create_project(self, telegram_user_id: int, name: str) -> Project:
        member_role = await self.company_service.ensure_member_role(telegram_user_id)
        if member_role not in ADMIN_ROLES:
            raise CompanyAccessError("Создавать проекты может только руководитель компании.")

        project_name = name.strip()
        if not project_name:
            raise CompanyAccessError("Название проекта не должно быть пустым.")

        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        pool = get_pool()
        async with pool.acquire() as connection:
            created_by_user_id = await connection.fetchval(
                "SELECT id FROM users WHERE telegram_id = $1",
                telegram_user_id,
            )
            if created_by_user_id is None:
                raise CompanyAccessError("Пользователь не найден в системе.")
            try:
                row = await connection.fetchrow(
                    """
                    INSERT INTO projects (company_id, name, status, created_by_user_id)
                    VALUES ($1, $2, 'active', $3)
                    RETURNING id, company_id, name, status
                    """,
                    company.id,
                    project_name,
                    created_by_user_id,
                )
            except Exception as exc:  # noqa: BLE001
                raise CompanyAccessError(f"Не удалось создать проект: {exc}") from exc

        return Project(id=row["id"], company_id=row["company_id"], name=row["name"], status=row["status"])

    async def archive_project(self, telegram_user_id: int, project_id: int) -> Project:
        return await self._set_status(
            telegram_user_id=telegram_user_id,
            project_id=project_id,
            target_status="archived",
            current_status="active",
            not_found_message="Проект не найден в текущей компании или уже архивирован.",
            access_message="Архивировать проекты может только руководитель компании.",
        )

    async def restore_project(self, telegram_user_id: int, project_id: int) -> Project:
        return await self._set_status(
            telegram_user_id=telegram_user_id,
            project_id=project_id,
            target_status="active",
            current_status="archived",
            not_found_message="Проект не найден в архиве текущей компании.",
            access_message="Деархивировать проекты может только руководитель компании.",
        )

    async def _set_status(
        self,
        telegram_user_id: int,
        project_id: int,
        target_status: str,
        current_status: str,
        not_found_message: str,
        access_message: str,
    ) -> Project:
        member_role = await self.company_service.ensure_member_role(telegram_user_id)
        if member_role not in ADMIN_ROLES:
            raise CompanyAccessError(access_message)

        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                UPDATE projects
                SET status = $3,
                    archived_at = CASE WHEN $3 = 'archived' THEN NOW() ELSE NULL END,
                    updated_at = NOW()
                WHERE id = $1
                  AND company_id = $2
                  AND status = $4
                RETURNING id, company_id, name, status
                """,
                project_id,
                company.id,
                target_status,
                current_status,
            )
        if row is None:
            raise CompanyAccessError(not_found_message)
        return Project(id=row["id"], company_id=row["company_id"], name=row["name"], status=row["status"])
