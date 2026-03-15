from dataclasses import dataclass

from app.services.database import get_pool


@dataclass(slots=True)
class Project:
    id: int
    name: str
    is_archived: bool


class ProjectService:
    async def list_active_projects(self) -> list[Project]:
        pool = get_pool()
        query = """
            SELECT id, name, is_archived
            FROM projects
            WHERE is_archived = FALSE
            ORDER BY created_at, id
        """
        async with pool.acquire() as connection:
            rows = await connection.fetch(query)
        return [Project(id=row["id"], name=row["name"], is_archived=row["is_archived"]) for row in rows]
