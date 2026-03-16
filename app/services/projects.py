from dataclasses import dataclass

from app.services.companies import ADMIN_ROLES, CompanyAccessError, CompanyService
from app.services.database import get_pool


@dataclass(slots=True)
class Project:
    id: int
    company_id: int
    name: str
    is_archived: bool


class ProjectService:
    def __init__(self) -> None:
        self.company_service = CompanyService()

    async def list_active_projects(self, telegram_user_id: int) -> list[Project]:
        return await self._list_projects(telegram_user_id, is_archived=False)

    async def list_archived_projects(self, telegram_user_id: int) -> list[Project]:
        member_role = await self.company_service.ensure_member_role(telegram_user_id)
        if member_role not in ADMIN_ROLES:
            raise CompanyAccessError("Просматривать архив проектов может только руководитель компании.")
        return await self._list_projects(telegram_user_id, is_archived=True)

    async def _list_projects(self, telegram_user_id: int, is_archived: bool) -> list[Project]:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        pool = get_pool()
        query = """
            SELECT id, company_id, name, is_archived
            FROM projects
            WHERE company_id = $1
              AND is_archived = $2
            ORDER BY created_at, id
        """
        async with pool.acquire() as connection:
            rows = await connection.fetch(query, company.id, is_archived)
        return [
            Project(
                id=row["id"],
                company_id=row["company_id"],
                name=row["name"],
                is_archived=row["is_archived"],
            )
            for row in rows
        ]

    async def get_active_project(self, telegram_user_id: int, project_id: int) -> Project | None:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        pool = get_pool()
        query = """
            SELECT id, company_id, name, is_archived
            FROM projects
            WHERE id = $1
              AND company_id = $2
              AND is_archived = FALSE
        """
        async with pool.acquire() as connection:
            row = await connection.fetchrow(query, project_id, company.id)
        if row is None:
            return None
        return Project(
            id=row["id"],
            company_id=row["company_id"],
            name=row["name"],
            is_archived=row["is_archived"],
        )

    async def create_project(self, telegram_user_id: int, name: str) -> Project:
        member_role = await self.company_service.ensure_member_role(telegram_user_id)
        if member_role not in ADMIN_ROLES:
            raise CompanyAccessError("Создавать проекты может только руководитель компании.")

        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        pool = get_pool()
        query = """
            INSERT INTO projects (company_id, name)
            VALUES ($1, $2)
            RETURNING id, company_id, name, is_archived
        """
        try:
            async with pool.acquire() as connection:
                row = await connection.fetchrow(query, company.id, name)
        except Exception as exc:  # noqa: BLE001
            raise CompanyAccessError(f"Не удалось создать проект: {exc}") from exc

        return Project(
            id=row["id"],
            company_id=row["company_id"],
            name=row["name"],
            is_archived=row["is_archived"],
        )

    async def archive_project(self, telegram_user_id: int, project_id: int) -> Project:
        return await self._set_archive_state(
            telegram_user_id=telegram_user_id,
            project_id=project_id,
            is_archived=True,
            not_found_message="Проект не найден в текущей компании или уже архивирован.",
            access_message="Архивировать проекты может только руководитель компании.",
        )

    async def restore_project(self, telegram_user_id: int, project_id: int) -> Project:
        return await self._set_archive_state(
            telegram_user_id=telegram_user_id,
            project_id=project_id,
            is_archived=False,
            not_found_message="Проект не найден в архиве текущей компании.",
            access_message="Деархивировать проекты может только руководитель компании.",
        )

    async def _set_archive_state(
        self,
        telegram_user_id: int,
        project_id: int,
        is_archived: bool,
        not_found_message: str,
        access_message: str,
    ) -> Project:
        member_role = await self.company_service.ensure_member_role(telegram_user_id)
        if member_role not in ADMIN_ROLES:
            raise CompanyAccessError(access_message)

        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        pool = get_pool()
        query = """
            UPDATE projects
            SET is_archived = $3
            WHERE id = $1
              AND company_id = $2
              AND is_archived = $4
            RETURNING id, company_id, name, is_archived
        """
        async with pool.acquire() as connection:
            row = await connection.fetchrow(query, project_id, company.id, is_archived, not is_archived)
        if row is None:
            raise CompanyAccessError(not_found_message)

        return Project(
            id=row["id"],
            company_id=row["company_id"],
            name=row["name"],
            is_archived=row["is_archived"],
        )
