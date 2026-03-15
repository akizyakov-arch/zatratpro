from dataclasses import dataclass

from app.services.companies import CompanyService
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
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        pool = get_pool()
        query = """
            SELECT id, company_id, name, is_archived
            FROM projects
            WHERE company_id = $1
              AND is_archived = FALSE
            ORDER BY created_at, id
        """
        async with pool.acquire() as connection:
            rows = await connection.fetch(query, company.id)
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
