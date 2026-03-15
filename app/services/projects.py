from dataclasses import dataclass

from app.config import get_settings
from app.services.database import get_pool


@dataclass(slots=True)
class Project:
    id: int
    company_id: int
    name: str
    is_archived: bool


class ProjectService:
    async def list_active_projects(self) -> list[Project]:
        settings = get_settings()
        pool = get_pool()
        query = """
            SELECT p.id, p.company_id, p.name, p.is_archived
            FROM projects AS p
            JOIN companies AS c ON c.id = p.company_id
            WHERE c.slug = $1
              AND c.is_active = TRUE
              AND p.is_archived = FALSE
            ORDER BY p.created_at, p.id
        """
        async with pool.acquire() as connection:
            rows = await connection.fetch(query, settings.default_company_slug)
        return [
            Project(
                id=row["id"],
                company_id=row["company_id"],
                name=row["name"],
                is_archived=row["is_archived"],
            )
            for row in rows
        ]

    async def get_active_project(self, project_id: int) -> Project | None:
        settings = get_settings()
        pool = get_pool()
        query = """
            SELECT p.id, p.company_id, p.name, p.is_archived
            FROM projects AS p
            JOIN companies AS c ON c.id = p.company_id
            WHERE p.id = $1
              AND c.slug = $2
              AND c.is_active = TRUE
              AND p.is_archived = FALSE
        """
        async with pool.acquire() as connection:
            row = await connection.fetchrow(query, project_id, settings.default_company_slug)
        if row is None:
            return None
        return Project(
            id=row["id"],
            company_id=row["company_id"],
            name=row["name"],
            is_archived=row["is_archived"],
        )
