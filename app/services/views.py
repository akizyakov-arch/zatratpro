from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.services.companies import CompanyAccessError, CompanyService
from app.services.database import get_pool


@dataclass(slots=True)
class CompanyListItem:
    id: int
    name: str
    is_active: bool
    manager_assigned: bool
    employee_count: int
    project_count: int
    created_at: datetime
    has_active_manager_invite: bool


@dataclass(slots=True)
class InviteView:
    code: str
    role: str
    expires_at: datetime | None
    created_at: datetime


@dataclass(slots=True)
class CompanyCard:
    id: int
    name: str
    is_active: bool
    manager_name: str | None
    manager_assigned: bool
    employee_count: int
    active_project_count: int
    archived_project_count: int
    document_count: int
    created_at: datetime
    invite: InviteView | None


@dataclass(slots=True)
class MemberCard:
    company_id: int
    user_id: int
    role: str
    username: str | None
    full_name: str | None
    telegram_id: int
    joined_at: datetime | None
    document_count: int


@dataclass(slots=True)
class ProjectCard:
    id: int
    company_id: int
    name: str
    is_archived: bool
    created_at: datetime | None
    created_by_name: str | None
    document_count: int
    total_amount: Decimal | None


@dataclass(slots=True)
class DocumentRow:
    id: int
    project_name: str
    vendor: str | None
    total_amount: Decimal | None
    document_date: date | None
    created_at: datetime
    uploaded_by_name: str | None


@dataclass(slots=True)
class SystemStats:
    users: int
    companies: int
    active_companies: int
    managers: int
    employees: int
    projects: int
    documents: int


class ViewService:
    def __init__(self) -> None:
        self.company_service = CompanyService()

    async def list_companies(self, telegram_user_id: int) -> list[CompanyListItem]:
        context = await self.company_service.get_user_context(telegram_user_id)
        if context.platform_role != 'owner':
            raise CompanyAccessError('Действие доступно только owner.')
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT c.id,
                       c.name,
                       c.is_active,
                       EXISTS(
                           SELECT 1 FROM company_members cm
                           WHERE cm.company_id = c.id AND cm.role = 'manager' AND cm.is_active = TRUE
                       ) AS manager_assigned,
                       COALESCE(emp.employee_count, 0) AS employee_count,
                       COALESCE(projects.project_count, 0) AS project_count,
                       c.created_at,
                       EXISTS(
                           SELECT 1 FROM company_invites ci
                           WHERE ci.company_id = c.id
                             AND ci.role = 'manager'
                             AND ci.is_active = TRUE
                             AND (ci.expires_at IS NULL OR ci.expires_at > NOW())
                       ) AS has_active_manager_invite
                FROM companies c
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS employee_count
                    FROM company_members
                    WHERE role = 'employee' AND is_active = TRUE
                    GROUP BY company_id
                ) emp ON emp.company_id = c.id
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS project_count
                    FROM projects
                    GROUP BY company_id
                ) projects ON projects.company_id = c.id
                ORDER BY c.created_at DESC, c.id DESC
                """
            )
        return [CompanyListItem(**dict(row)) for row in rows]

    async def get_company_card(self, telegram_user_id: int, company_id: int) -> CompanyCard:
        context = await self.company_service.get_user_context(telegram_user_id)
        if context.platform_role != 'owner':
            raise CompanyAccessError('Действие доступно только owner.')
        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT c.id,
                       c.name,
                       c.is_active,
                       manager.username AS manager_username,
                       manager.full_name AS manager_full_name,
                       EXISTS(
                           SELECT 1 FROM company_members cm
                           WHERE cm.company_id = c.id AND cm.role = 'manager' AND cm.is_active = TRUE
                       ) AS manager_assigned,
                       COALESCE(emp.employee_count, 0) AS employee_count,
                       COALESCE(active_projects.active_project_count, 0) AS active_project_count,
                       COALESCE(archived_projects.archived_project_count, 0) AS archived_project_count,
                       COALESCE(docs.document_count, 0) AS document_count,
                       c.created_at
                FROM companies c
                LEFT JOIN users manager ON manager.id = (
                    SELECT cm.user_id FROM company_members cm
                    WHERE cm.company_id = c.id AND cm.role = 'manager' AND cm.is_active = TRUE
                    ORDER BY cm.joined_at DESC NULLS LAST, cm.id DESC LIMIT 1
                )
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS employee_count
                    FROM company_members
                    WHERE role = 'employee' AND is_active = TRUE
                    GROUP BY company_id
                ) emp ON emp.company_id = c.id
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS active_project_count
                    FROM projects WHERE is_archived = FALSE GROUP BY company_id
                ) active_projects ON active_projects.company_id = c.id
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS archived_project_count
                    FROM projects WHERE is_archived = TRUE GROUP BY company_id
                ) archived_projects ON archived_projects.company_id = c.id
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS document_count
                    FROM documents GROUP BY company_id
                ) docs ON docs.company_id = c.id
                WHERE c.id = $1
                """,
                company_id,
            )
            if row is None:
                raise CompanyAccessError('Компания не найдена.')
            invite_row = await connection.fetchrow(
                """
                SELECT code, role, expires_at, created_at
                FROM company_invites
                WHERE company_id = $1 AND role = 'manager' AND is_active = TRUE
                ORDER BY created_at DESC LIMIT 1
                """,
                company_id,
            )
        invite = InviteView(**dict(invite_row)) if invite_row is not None else None
        return CompanyCard(
            id=row['id'],
            name=row['name'],
            is_active=row['is_active'],
            manager_name=row['manager_full_name'] or row['manager_username'],
            manager_assigned=row['manager_assigned'],
            employee_count=row['employee_count'],
            active_project_count=row['active_project_count'],
            archived_project_count=row['archived_project_count'],
            document_count=row['document_count'],
            created_at=row['created_at'],
            invite=invite,
        )

    async def list_company_members_for_owner(self, telegram_user_id: int, company_id: int) -> list[MemberCard]:
        context = await self.company_service.get_user_context(telegram_user_id)
        if context.platform_role != 'owner':
            raise CompanyAccessError('Действие доступно только owner.')
        return await self._list_members(company_id)

    async def list_employees_for_manager(self, telegram_user_id: int) -> list[MemberCard]:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        role = await self.company_service.ensure_member_role(telegram_user_id)
        if role != 'manager':
            raise CompanyAccessError('Действие доступно только manager.')
        return [member for member in await self._list_members(company.id) if member.role == 'employee']

    async def get_employee_card(self, telegram_user_id: int, member_user_id: int) -> MemberCard:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        role = await self.company_service.ensure_member_role(telegram_user_id)
        if role != 'manager':
            raise CompanyAccessError('Действие доступно только manager.')
        members = await self._list_members(company.id)
        for member in members:
            if member.user_id == member_user_id:
                return member
        raise CompanyAccessError('Сотрудник не найден.')

    async def list_projects_for_manager(self, telegram_user_id: int, archived: bool) -> list[ProjectCard]:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        role = await self.company_service.ensure_member_role(telegram_user_id)
        if role != 'manager':
            raise CompanyAccessError('Действие доступно только manager.')
        return await self._list_projects(company.id, archived)

    async def get_project_card(self, telegram_user_id: int, project_id: int) -> ProjectCard:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        role = await self.company_service.ensure_member_role(telegram_user_id)
        if role != 'manager':
            raise CompanyAccessError('Действие доступно только manager.')
        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT p.id,
                       p.company_id,
                       p.name,
                       p.is_archived,
                       p.created_at,
                       creator.full_name AS creator_full_name,
                       creator.username AS creator_username,
                       COALESCE(docs.document_count, 0) AS document_count,
                       docs.total_amount
                FROM projects p
                LEFT JOIN users creator ON creator.id = p.created_by_user_id
                LEFT JOIN (
                    SELECT project_id, COUNT(*) AS document_count, COALESCE(SUM(total), 0) AS total_amount
                    FROM documents GROUP BY project_id
                ) docs ON docs.project_id = p.id
                WHERE p.company_id = $1 AND p.id = $2
                """,
                company.id,
                project_id,
            )
        if row is None:
            raise CompanyAccessError('Проект не найден.')
        return ProjectCard(
            id=row['id'], company_id=row['company_id'], name=row['name'], is_archived=row['is_archived'],
            created_at=row['created_at'], created_by_name=row['creator_full_name'] or row['creator_username'],
            document_count=row['document_count'], total_amount=row['total_amount'],
        )

    async def rename_project(self, telegram_user_id: int, project_id: int, name: str) -> None:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        role = await self.company_service.ensure_member_role(telegram_user_id)
        if role != 'manager':
            raise CompanyAccessError('Действие доступно только manager.')
        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                'UPDATE projects SET name = $3 WHERE company_id = $1 AND id = $2 AND is_archived = FALSE RETURNING id',
                company.id,
                project_id,
                name.strip(),
            )
        if row is None:
            raise CompanyAccessError('Активный проект не найден.')

    async def list_project_documents(self, telegram_user_id: int, project_id: int) -> list[DocumentRow]:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        role = await self.company_service.ensure_member_role(telegram_user_id)
        if role != 'manager':
            raise CompanyAccessError('Действие доступно только manager.')
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT d.id,
                       p.name AS project_name,
                       d.vendor,
                       d.total,
                       d.document_date,
                       d.created_at,
                       uploader.full_name AS uploader_full_name,
                       uploader.username AS uploader_username
                FROM documents d
                JOIN projects p ON p.id = d.project_id
                LEFT JOIN users uploader ON uploader.id = d.user_id
                WHERE d.company_id = $1 AND d.project_id = $2
                ORDER BY d.created_at DESC
                LIMIT 20
                """,
                company.id,
                project_id,
            )
        return [DocumentRow(
            id=row['id'], project_name=row['project_name'], vendor=row['vendor'], total_amount=row['total'],
            document_date=row['document_date'], created_at=row['created_at'],
            uploaded_by_name=row['uploader_full_name'] or row['uploader_username'],
        ) for row in rows]

    async def list_my_documents(self, telegram_user_id: int) -> list[DocumentRow]:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        pool = get_pool()
        async with pool.acquire() as connection:
            user_id = await connection.fetchval('SELECT id FROM users WHERE telegram_user_id = $1', telegram_user_id)
            rows = await connection.fetch(
                """
                SELECT d.id,
                       p.name AS project_name,
                       d.vendor,
                       d.total,
                       d.document_date,
                       d.created_at,
                       uploader.full_name AS uploader_full_name,
                       uploader.username AS uploader_username
                FROM documents d
                JOIN projects p ON p.id = d.project_id
                LEFT JOIN users uploader ON uploader.id = d.user_id
                WHERE d.company_id = $1 AND d.user_id = $2
                ORDER BY d.created_at DESC
                LIMIT 20
                """,
                company.id,
                user_id,
            )
        return [DocumentRow(
            id=row['id'], project_name=row['project_name'], vendor=row['vendor'], total_amount=row['total'],
            document_date=row['document_date'], created_at=row['created_at'],
            uploaded_by_name=row['uploader_full_name'] or row['uploader_username'],
        ) for row in rows]

    async def get_my_company_card(self, telegram_user_id: int) -> CompanyCard:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        return await self.get_company_card_for_manager(company.id)

    async def get_company_card_for_manager(self, company_id: int) -> CompanyCard:
        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT c.id,
                       c.name,
                       c.is_active,
                       manager.username AS manager_username,
                       manager.full_name AS manager_full_name,
                       TRUE AS manager_assigned,
                       COALESCE(emp.employee_count, 0) AS employee_count,
                       COALESCE(active_projects.active_project_count, 0) AS active_project_count,
                       COALESCE(archived_projects.archived_project_count, 0) AS archived_project_count,
                       COALESCE(docs.document_count, 0) AS document_count,
                       c.created_at
                FROM companies c
                LEFT JOIN users manager ON manager.id = (
                    SELECT cm.user_id FROM company_members cm
                    WHERE cm.company_id = c.id AND cm.role = 'manager' AND cm.is_active = TRUE
                    ORDER BY cm.joined_at DESC NULLS LAST, cm.id DESC LIMIT 1
                )
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS employee_count
                    FROM company_members
                    WHERE role = 'employee' AND is_active = TRUE
                    GROUP BY company_id
                ) emp ON emp.company_id = c.id
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS active_project_count
                    FROM projects WHERE is_archived = FALSE GROUP BY company_id
                ) active_projects ON active_projects.company_id = c.id
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS archived_project_count
                    FROM projects WHERE is_archived = TRUE GROUP BY company_id
                ) archived_projects ON archived_projects.company_id = c.id
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS document_count
                    FROM documents GROUP BY company_id
                ) docs ON docs.company_id = c.id
                WHERE c.id = $1
                """,
                company_id,
            )
        return CompanyCard(
            id=row['id'], name=row['name'], is_active=row['is_active'],
            manager_name=row['manager_full_name'] or row['manager_username'], manager_assigned=True,
            employee_count=row['employee_count'], active_project_count=row['active_project_count'],
            archived_project_count=row['archived_project_count'], document_count=row['document_count'],
            created_at=row['created_at'], invite=None,
        )

    async def get_system_stats(self, telegram_user_id: int) -> SystemStats:
        context = await self.company_service.get_user_context(telegram_user_id)
        if context.platform_role != 'owner':
            raise CompanyAccessError('Действие доступно только owner.')
        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT
                    (SELECT COUNT(*) FROM users) AS users,
                    (SELECT COUNT(*) FROM companies) AS companies,
                    (SELECT COUNT(*) FROM companies WHERE is_active = TRUE) AS active_companies,
                    (SELECT COUNT(*) FROM company_members WHERE role = 'manager' AND is_active = TRUE) AS managers,
                    (SELECT COUNT(*) FROM company_members WHERE role = 'employee' AND is_active = TRUE) AS employees,
                    (SELECT COUNT(*) FROM projects) AS projects,
                    (SELECT COUNT(*) FROM documents) AS documents
                """
            )
        return SystemStats(**dict(row))

    async def archive_company(self, telegram_user_id: int, company_id: int) -> None:
        context = await self.company_service.get_user_context(telegram_user_id)
        if context.platform_role != 'owner':
            raise CompanyAccessError('Действие доступно только owner.')
        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow('UPDATE companies SET is_active = FALSE WHERE id = $1 AND is_active = TRUE RETURNING id', company_id)
            if row is None:
                raise CompanyAccessError('Компания не найдена или уже архивирована.')
            await connection.execute('UPDATE company_invites SET is_active = FALSE WHERE company_id = $1 AND is_active = TRUE', company_id)

    async def revoke_manager_invite(self, telegram_user_id: int, company_id: int) -> bool:
        context = await self.company_service.get_user_context(telegram_user_id)
        if context.platform_role != 'owner':
            raise CompanyAccessError('Действие доступно только owner.')
        pool = get_pool()
        async with pool.acquire() as connection:
            result = await connection.execute(
                "UPDATE company_invites SET is_active = FALSE WHERE company_id = $1 AND role = 'manager' AND is_active = TRUE",
                company_id,
            )
        return not result.endswith('0')

    async def _list_members(self, company_id: int) -> list[MemberCard]:
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT cm.company_id,
                       cm.user_id,
                       cm.role,
                       u.username,
                       u.full_name,
                       u.telegram_user_id,
                       cm.joined_at,
                       COALESCE(docs.document_count, 0) AS document_count
                FROM company_members cm
                JOIN users u ON u.id = cm.user_id
                LEFT JOIN (
                    SELECT user_id, COUNT(*) AS document_count
                    FROM documents GROUP BY user_id
                ) docs ON docs.user_id = cm.user_id
                WHERE cm.company_id = $1 AND cm.is_active = TRUE
                ORDER BY cm.role, cm.joined_at NULLS LAST, cm.id
                """,
                company_id,
            )
        return [MemberCard(
            company_id=row['company_id'], user_id=row['user_id'], role=row['role'], username=row['username'],
            full_name=row['full_name'], telegram_id=row['telegram_user_id'], joined_at=row['joined_at'],
            document_count=row['document_count'],
        ) for row in rows]

    async def _list_projects(self, company_id: int, archived: bool) -> list[ProjectCard]:
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT p.id,
                       p.company_id,
                       p.name,
                       p.is_archived,
                       p.created_at,
                       creator.full_name AS creator_full_name,
                       creator.username AS creator_username,
                       COALESCE(docs.document_count, 0) AS document_count,
                       docs.total_amount
                FROM projects p
                LEFT JOIN users creator ON creator.id = p.created_by_user_id
                LEFT JOIN (
                    SELECT project_id, COUNT(*) AS document_count, COALESCE(SUM(total), 0) AS total_amount
                    FROM documents GROUP BY project_id
                ) docs ON docs.project_id = p.id
                WHERE p.company_id = $1 AND p.is_archived = $2
                ORDER BY p.created_at DESC, p.id DESC
                """,
                company_id,
                archived,
            )
        return [ProjectCard(
            id=row['id'], company_id=row['company_id'], name=row['name'], is_archived=row['is_archived'],
            created_at=row['created_at'], created_by_name=row['creator_full_name'] or row['creator_username'],
            document_count=row['document_count'], total_amount=row['total_amount'],
        ) for row in rows]
