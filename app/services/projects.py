
from app.services.companies import ADMIN_ROLES, CompanyAccessError, CompanyDirectory
from app.services.database import get_pool


from app.schemas.project import Project


class ProjectDirectory:
    def __init__(self) -> None:
        self.company_service = CompanyDirectory()

    async def list_active_projects(self, actor_id: int) -> list[Project]:
        return await self._list_projects(actor_id, status="active")

    async def list_archived_projects(self, actor_id: int) -> list[Project]:
        member_role = await self.company_service.ensure_member_role(actor_id)
        if member_role not in ADMIN_ROLES:
            raise CompanyAccessError("Просматривать архив проектов может только руководитель компании.")
        return await self._list_projects(actor_id, status="archived")

    async def _list_projects(self, actor_id: int, status: str) -> list[Project]:
        company = await self.company_service.get_active_company_for_user(actor_id)
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

    async def get_active_project(self, actor_id: int, project_id: int) -> Project | None:
        company = await self.company_service.get_active_company_for_user(actor_id)
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

    async def create_project(self, actor_id: int, name: str) -> Project:
        from app.services.workspace import WorkspaceError, WorkspaceService
        actor = await self.company_service._workspace_actor(actor_id)
        try:
            row = await WorkspaceService().create_project(actor, name)
        except WorkspaceError as exc:
            raise CompanyAccessError(str(exc)) from exc
        return Project(id=row['id'], company_id=row['company_id'], name=row['name'], status=row['status'])

    async def archive_project(self, actor_id: int, project_id: int) -> Project:
        return await self._set_status(
            actor_id=actor_id,
            project_id=project_id,
            target_status="archived",
            current_status="active",
            not_found_message="Проект не найден в текущей компании или уже архивирован.",
            access_message="Архивировать проекты может только руководитель компании.",
        )

    async def restore_project(self, actor_id: int, project_id: int) -> Project:
        return await self._set_status(
            actor_id=actor_id,
            project_id=project_id,
            target_status="active",
            current_status="archived",
            not_found_message="Проект не найден в архиве текущей компании.",
            access_message="Деархивировать проекты может только руководитель компании.",
        )

    async def _set_status(self, actor_id: int, project_id: int, target_status: str, current_status: str, not_found_message: str, access_message: str) -> Project:
        from app.services.workspace import WorkspaceError, WorkspaceService
        actor = await self.company_service._workspace_actor(actor_id)
        try:
            service = WorkspaceService()
            row = await (service.archive_project(actor, project_id) if target_status == 'archived' else service.restore_project(actor, project_id))
        except WorkspaceError as exc:
            raise CompanyAccessError(str(exc)) from exc
        return Project(id=row['id'], company_id=row['company_id'], name=row['name'], status=row['status'])
