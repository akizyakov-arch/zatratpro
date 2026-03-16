from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.services.companies import CompanyAccessError, CompanyService
from app.services.documents import DocumentService
from app.services.database import get_pool


@dataclass(slots=True)
class CompanyListItem:
    id: int
    name: str
    status: str
    manager_assigned: bool
    employee_count: int
    project_count: int
    created_at: datetime
    has_active_manager_invite: bool

    @property
    def is_active(self) -> bool:
        return self.status == "active"


@dataclass(slots=True)
class UserListItem:
    user_id: int
    telegram_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    system_role: str
    company_id: int | None
    company_name: str | None
    company_role: str | None
    company_status: str | None
    created_at: datetime

    @property
    def full_name(self) -> str | None:
        parts = [part for part in (self.first_name, self.last_name) if part]
        return " ".join(parts) or None


@dataclass(slots=True)
class UserCard:
    user_id: int
    telegram_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    system_role: str
    company_id: int | None
    company_name: str | None
    company_role: str | None
    company_status: str | None
    joined_at: datetime | None
    created_at: datetime

    @property
    def full_name(self) -> str | None:
        parts = [part for part in (self.first_name, self.last_name) if part]
        return " ".join(parts) or None

    @property
    def has_company(self) -> bool:
        return self.company_id is not None and self.company_status == "active"


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
    status: str
    manager_name: str | None
    manager_assigned: bool
    employee_count: int
    active_project_count: int
    archived_project_count: int
    document_count: int
    created_at: datetime
    invite: InviteView | None

    @property
    def is_active(self) -> bool:
        return self.status == "active"


@dataclass(slots=True)
class MemberCard:
    company_id: int
    user_id: int
    role: str
    username: str | None
    first_name: str | None
    last_name: str | None
    telegram_id: int
    joined_at: datetime | None
    document_count: int

    @property
    def full_name(self) -> str | None:
        parts = [part for part in (self.first_name, self.last_name) if part]
        return " ".join(parts) or None

    @property
    def telegram_user_id(self) -> int:
        return self.telegram_id


@dataclass(slots=True)
class ProjectCard:
    id: int
    company_id: int
    name: str
    status: str
    created_at: datetime | None
    created_by_name: str | None
    document_count: int
    total_amount: Decimal | None

    @property
    def is_archived(self) -> bool:
        return self.status == "archived"


@dataclass(slots=True)
class DocumentRow:
    id: int
    project_name: str
    vendor: str | None
    total_amount: Decimal | None
    document_date: date | datetime | None
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


@dataclass(slots=True)
class ReportSummary:
    period: str
    start_at: datetime
    documents: int
    total_amount: Decimal
    exact_duplicates: int
    probable_duplicates: int


@dataclass(slots=True)
class ProjectReportRow:
    project_id: int
    project_name: str
    document_count: int
    total_amount: Decimal
    exact_duplicate_count: int
    probable_duplicate_count: int


@dataclass(slots=True)
class EmployeeReportRow:
    user_id: int
    employee_name: str | None
    username: str | None
    document_count: int
    total_amount: Decimal
    exact_duplicate_count: int
    probable_duplicate_count: int


@dataclass(slots=True)
class ReportDocumentDetail:
    id: int
    project_name: str
    vendor: str | None
    vendor_inn: str | None
    document_number: str | None
    document_date: date | datetime | None
    total_amount: Decimal | None
    duplicate_status: str
    uploaded_by_name: str | None
    first_item_name: str | None
    created_at: datetime


@dataclass(slots=True)
class ReportItemDetail:
    document_id: int
    line_no: int
    name: str | None
    quantity: Decimal | None
    price: Decimal | None
    line_total: Decimal | None


@dataclass(slots=True)
class DuplicateReportRow:
    id: int
    project_name: str
    vendor: str | None
    vendor_inn: str | None
    document_number: str | None
    document_date: date | datetime | None
    total_amount: Decimal | None
    duplicate_status: str
    duplicate_of_document_id: int | None
    uploaded_by_name: str | None
    base_project_name: str | None
    base_uploaded_by_name: str | None
    base_vendor: str | None
    base_vendor_inn: str | None
    base_document_number: str | None
    base_document_date: date | datetime | None
    base_total_amount: Decimal | None
    created_at: datetime


class ViewService:
    def __init__(self) -> None:
        self.company_service = CompanyService()
        self.document_service = DocumentService()

    async def list_companies(self, telegram_user_id: int) -> list[CompanyListItem]:
        context = await self.company_service.get_user_context(telegram_user_id)
        if context.platform_role != "owner":
            raise CompanyAccessError("Действие доступно только owner.")
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT c.id,
                       c.name,
                       c.status,
                       (c.manager_user_id IS NOT NULL) AS manager_assigned,
                       COALESCE(emp.employee_count, 0) AS employee_count,
                       COALESCE(projects.project_count, 0) AS project_count,
                       c.created_at,
                       EXISTS(
                           SELECT 1
                           FROM company_invites ci
                           WHERE ci.company_id = c.id
                             AND ci.role = 'manager'
                             AND ci.status = 'active'
                             AND (ci.expires_at IS NULL OR ci.expires_at > NOW())
                       ) AS has_active_manager_invite
                FROM companies c
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS employee_count
                    FROM company_members
                    WHERE role = 'employee' AND status = 'active'
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

    async def list_users(self, telegram_user_id: int) -> list[UserListItem]:
        context = await self.company_service.get_user_context(telegram_user_id)
        if context.platform_role != "owner":
            raise CompanyAccessError("Действие доступно только owner.")
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT u.id AS user_id,
                       u.telegram_id,
                       u.username,
                       u.first_name,
                       u.last_name,
                       u.system_role,
                       cm.company_id,
                       c.name AS company_name,
                       cm.role AS company_role,
                       c.status AS company_status,
                       u.created_at
                FROM users u
                LEFT JOIN company_members cm
                    ON cm.user_id = u.id
                   AND cm.status = 'active'
                LEFT JOIN companies c
                    ON c.id = cm.company_id
                ORDER BY u.created_at DESC, u.id DESC
                """
            )
        return [UserListItem(**dict(row)) for row in rows]

    async def get_user_card(self, telegram_user_id: int, target_user_id: int) -> UserCard:
        context = await self.company_service.get_user_context(telegram_user_id)
        if context.platform_role != "owner":
            raise CompanyAccessError("Действие доступно только owner.")
        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT u.id AS user_id,
                       u.telegram_id,
                       u.username,
                       u.first_name,
                       u.last_name,
                       u.system_role,
                       cm.company_id,
                       c.name AS company_name,
                       cm.role AS company_role,
                       c.status AS company_status,
                       cm.joined_at,
                       u.created_at
                FROM users u
                LEFT JOIN company_members cm
                    ON cm.user_id = u.id
                   AND cm.status = 'active'
                LEFT JOIN companies c
                    ON c.id = cm.company_id
                WHERE u.id = $1
                """,
                target_user_id,
            )
        if row is None:
            raise CompanyAccessError("Пользователь не найден.")
        return UserCard(**dict(row))

    async def get_company_card(self, telegram_user_id: int, company_id: int) -> CompanyCard:
        context = await self.company_service.get_user_context(telegram_user_id)
        if context.platform_role != "owner":
            raise CompanyAccessError("Действие доступно только owner.")
        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT c.id,
                       c.name,
                       c.status,
                       manager.username AS manager_username,
                       manager.first_name AS manager_first_name,
                       manager.last_name AS manager_last_name,
                       (c.manager_user_id IS NOT NULL) AS manager_assigned,
                       COALESCE(emp.employee_count, 0) AS employee_count,
                       COALESCE(active_projects.active_project_count, 0) AS active_project_count,
                       COALESCE(archived_projects.archived_project_count, 0) AS archived_project_count,
                       COALESCE(docs.document_count, 0) AS document_count,
                       c.created_at
                FROM companies c
                LEFT JOIN users manager ON manager.id = c.manager_user_id
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS employee_count
                    FROM company_members
                    WHERE role = 'employee' AND status = 'active'
                    GROUP BY company_id
                ) emp ON emp.company_id = c.id
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS active_project_count
                    FROM projects WHERE status = 'active' GROUP BY company_id
                ) active_projects ON active_projects.company_id = c.id
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS archived_project_count
                    FROM projects WHERE status = 'archived' GROUP BY company_id
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
                raise CompanyAccessError("Компания не найдена.")
            invite_row = await connection.fetchrow(
                """
                SELECT code, role, expires_at, created_at
                FROM company_invites
                WHERE company_id = $1
                  AND role = 'manager'
                  AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                company_id,
            )
        invite = InviteView(**dict(invite_row)) if invite_row is not None else None
        return CompanyCard(
            id=row["id"],
            name=row["name"],
            status=row["status"],
            manager_name=_display_name(row["manager_first_name"], row["manager_last_name"], row["manager_username"]),
            manager_assigned=row["manager_assigned"],
            employee_count=row["employee_count"],
            active_project_count=row["active_project_count"],
            archived_project_count=row["archived_project_count"],
            document_count=row["document_count"],
            created_at=row["created_at"],
            invite=invite,
        )

    async def list_company_members_for_owner(self, telegram_user_id: int, company_id: int) -> list[MemberCard]:
        context = await self.company_service.get_user_context(telegram_user_id)
        if context.platform_role != "owner":
            raise CompanyAccessError("Действие доступно только owner.")
        return await self._list_members(company_id)

    async def list_employees_for_manager(self, telegram_user_id: int) -> list[MemberCard]:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        role = await self.company_service.ensure_member_role(telegram_user_id)
        if role != "manager":
            raise CompanyAccessError("Действие доступно только manager.")
        return [member for member in await self._list_members(company.id) if member.role == "employee"]

    async def get_employee_card(self, telegram_user_id: int, member_user_id: int) -> MemberCard:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        role = await self.company_service.ensure_member_role(telegram_user_id)
        if role != "manager":
            raise CompanyAccessError("Действие доступно только manager.")
        members = await self._list_members(company.id)
        for member in members:
            if member.user_id == member_user_id and member.role == "employee":
                return member
        raise CompanyAccessError("Сотрудник не найден.")

    async def list_projects_for_manager(self, telegram_user_id: int, archived: bool) -> list[ProjectCard]:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        role = await self.company_service.ensure_member_role(telegram_user_id)
        if role != "manager":
            raise CompanyAccessError("Действие доступно только manager.")
        return await self._list_projects(company.id, status="archived" if archived else "active")

    async def get_project_card(self, telegram_user_id: int, project_id: int) -> ProjectCard:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        role = await self.company_service.ensure_member_role(telegram_user_id)
        if role != "manager":
            raise CompanyAccessError("Действие доступно только manager.")
        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT p.id,
                       p.company_id,
                       p.name,
                       p.status,
                       p.created_at,
                       creator.username AS creator_username,
                       creator.first_name AS creator_first_name,
                       creator.last_name AS creator_last_name,
                       COALESCE(docs.document_count, 0) AS document_count,
                       docs.total_amount
                FROM projects p
                LEFT JOIN users creator ON creator.id = p.created_by_user_id
                LEFT JOIN (
                    SELECT project_id,
                           COUNT(*) AS document_count,
                           COALESCE(SUM(total_amount), 0) AS total_amount
                    FROM documents
                    GROUP BY project_id
                ) docs ON docs.project_id = p.id
                WHERE p.company_id = $1
                  AND p.id = $2
                """,
                company.id,
                project_id,
            )
        if row is None:
            raise CompanyAccessError("Проект не найден.")
        return ProjectCard(
            id=row["id"],
            company_id=row["company_id"],
            name=row["name"],
            status=row["status"],
            created_at=row["created_at"],
            created_by_name=_display_name(row["creator_first_name"], row["creator_last_name"], row["creator_username"]),
            document_count=row["document_count"],
            total_amount=row["total_amount"],
        )

    async def rename_project(self, telegram_user_id: int, project_id: int, name: str) -> None:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        role = await self.company_service.ensure_member_role(telegram_user_id)
        if role != "manager":
            raise CompanyAccessError("Действие доступно только manager.")
        project_name = name.strip()
        if not project_name:
            raise CompanyAccessError("Название проекта не должно быть пустым.")
        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                UPDATE projects
                SET name = $3,
                    updated_at = NOW()
                WHERE company_id = $1
                  AND id = $2
                  AND status = 'active'
                RETURNING id
                """,
                company.id,
                project_id,
                project_name,
            )
        if row is None:
            raise CompanyAccessError("Активный проект не найден.")

    async def list_project_documents(self, telegram_user_id: int, project_id: int) -> list[DocumentRow]:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        role = await self.company_service.ensure_member_role(telegram_user_id)
        if role != "manager":
            raise CompanyAccessError("Действие доступно только manager.")
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT d.id,
                       p.name AS project_name,
                       d.vendor,
                       d.total_amount,
                       d.document_date,
                       d.created_at,
                       uploader.username AS uploader_username,
                       uploader.first_name AS uploader_first_name,
                       uploader.last_name AS uploader_last_name
                FROM documents d
                JOIN projects p ON p.id = d.project_id
                LEFT JOIN users uploader ON uploader.id = d.uploaded_by_user_id
            LEFT JOIN LATERAL (
                SELECT di.name
                FROM document_items di
                WHERE di.document_id = d.id
                ORDER BY di.line_no ASC
                LIMIT 1
            ) first_item ON TRUE
                WHERE d.company_id = $1
                  AND d.project_id = $2
                ORDER BY d.created_at DESC
                LIMIT 20
                """,
                company.id,
                project_id,
            )
        return [
            DocumentRow(
                id=row["id"],
                project_name=row["project_name"],
                vendor=row["vendor"],
                total_amount=row["total_amount"],
                document_date=row["document_date"],
                created_at=row["created_at"],
                uploaded_by_name=_display_name(row["uploader_first_name"], row["uploader_last_name"], row["uploader_username"]),
            )
            for row in rows
        ]

    async def list_my_documents(self, telegram_user_id: int) -> list[DocumentRow]:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        pool = get_pool()
        async with pool.acquire() as connection:
            user_id = await connection.fetchval("SELECT id FROM users WHERE telegram_id = $1", telegram_user_id)
            rows = await connection.fetch(
                """
                SELECT d.id,
                       p.name AS project_name,
                       d.vendor,
                       d.total_amount,
                       d.document_date,
                       d.created_at,
                       uploader.username AS uploader_username,
                       uploader.first_name AS uploader_first_name,
                       uploader.last_name AS uploader_last_name
                FROM documents d
                JOIN projects p ON p.id = d.project_id
                LEFT JOIN users uploader ON uploader.id = d.uploaded_by_user_id
            LEFT JOIN LATERAL (
                SELECT di.name
                FROM document_items di
                WHERE di.document_id = d.id
                ORDER BY di.line_no ASC
                LIMIT 1
            ) first_item ON TRUE
                WHERE d.company_id = $1
                  AND d.uploaded_by_user_id = $2
                ORDER BY d.created_at DESC
                LIMIT 20
                """,
                company.id,
                user_id,
            )
        return [
            DocumentRow(
                id=row["id"],
                project_name=row["project_name"],
                vendor=row["vendor"],
                total_amount=row["total_amount"],
                document_date=row["document_date"],
                created_at=row["created_at"],
                uploaded_by_name=_display_name(row["uploader_first_name"], row["uploader_last_name"], row["uploader_username"]),
            )
            for row in rows
        ]

    async def get_my_company_card(self, telegram_user_id: int) -> CompanyCard:
        return await self.get_company_card_for_manager(telegram_user_id)

    async def get_company_card_for_manager(self, telegram_user_id: int) -> CompanyCard:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        role = await self.company_service.ensure_member_role(telegram_user_id)
        if role != "manager":
            raise CompanyAccessError("Действие доступно только manager.")
        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT c.id,
                       c.name,
                       c.status,
                       manager.username AS manager_username,
                       manager.first_name AS manager_first_name,
                       manager.last_name AS manager_last_name,
                       (c.manager_user_id IS NOT NULL) AS manager_assigned,
                       COALESCE(emp.employee_count, 0) AS employee_count,
                       COALESCE(active_projects.active_project_count, 0) AS active_project_count,
                       COALESCE(archived_projects.archived_project_count, 0) AS archived_project_count,
                       COALESCE(docs.document_count, 0) AS document_count,
                       c.created_at
                FROM companies c
                LEFT JOIN users manager ON manager.id = c.manager_user_id
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS employee_count
                    FROM company_members
                    WHERE role = 'employee' AND status = 'active'
                    GROUP BY company_id
                ) emp ON emp.company_id = c.id
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS active_project_count
                    FROM projects WHERE status = 'active' GROUP BY company_id
                ) active_projects ON active_projects.company_id = c.id
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS archived_project_count
                    FROM projects WHERE status = 'archived' GROUP BY company_id
                ) archived_projects ON archived_projects.company_id = c.id
                LEFT JOIN (
                    SELECT company_id, COUNT(*) AS document_count
                    FROM documents GROUP BY company_id
                ) docs ON docs.company_id = c.id
                WHERE c.id = $1
                """,
                company.id,
            )
        if row is None:
            raise CompanyAccessError("Компания не найдена.")
        return CompanyCard(
            id=row["id"],
            name=row["name"],
            status=row["status"],
            manager_name=_display_name(row["manager_first_name"], row["manager_last_name"], row["manager_username"]),
            manager_assigned=row["manager_assigned"],
            employee_count=row["employee_count"],
            active_project_count=row["active_project_count"],
            archived_project_count=row["archived_project_count"],
            document_count=row["document_count"],
            created_at=row["created_at"],
            invite=None,
        )

    async def get_system_stats(self, telegram_user_id: int) -> SystemStats:
        context = await self.company_service.get_user_context(telegram_user_id)
        if context.platform_role != "owner":
            raise CompanyAccessError("Действие доступно только owner.")
        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT
                    (SELECT COUNT(*) FROM users) AS users,
                    (SELECT COUNT(*) FROM companies) AS companies,
                    (SELECT COUNT(*) FROM companies WHERE status = 'active') AS active_companies,
                    (SELECT COUNT(*) FROM company_members WHERE role = 'manager' AND status = 'active') AS managers,
                    (SELECT COUNT(*) FROM company_members WHERE role = 'employee' AND status = 'active') AS employees,
                    (SELECT COUNT(*) FROM projects) AS projects,
                    (SELECT COUNT(*) FROM documents) AS documents
                """
            )
        return SystemStats(**dict(row))

    async def get_manager_report_summary(self, telegram_user_id: int, period: str) -> ReportSummary:
        company, start_at = await self._get_manager_company_and_period(telegram_user_id, period)
        pool = get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT COUNT(*) AS documents,
                       COALESCE(SUM(d.total_amount), 0) AS total_amount,
                       COUNT(*) FILTER (WHERE d.duplicate_status = 'exact') AS exact_duplicates,
                       COUNT(*) FILTER (WHERE d.duplicate_status = 'probable') AS probable_duplicates
                FROM documents d
                WHERE d.company_id = $1
                  AND d.created_at >= $2
                """,
                company.id,
                start_at,
            )
        return ReportSummary(
            period=period,
            start_at=start_at,
            documents=row['documents'],
            total_amount=row['total_amount'],
            exact_duplicates=row['exact_duplicates'],
            probable_duplicates=row['probable_duplicates'],
        )

    async def list_report_projects(self, telegram_user_id: int, period: str) -> list[ProjectReportRow]:
        company, start_at = await self._get_manager_company_and_period(telegram_user_id, period)
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT p.id AS project_id,
                       p.name AS project_name,
                       COUNT(d.id) AS document_count,
                       COALESCE(SUM(d.total_amount), 0) AS total_amount,
                       COUNT(*) FILTER (WHERE d.duplicate_status = 'exact') AS exact_duplicate_count,
                       COUNT(*) FILTER (WHERE d.duplicate_status = 'probable') AS probable_duplicate_count
                FROM projects p
                LEFT JOIN documents d
                    ON d.project_id = p.id
                   AND d.company_id = $1
                   AND d.created_at >= $2
                WHERE p.company_id = $1
                GROUP BY p.id, p.name
                HAVING COUNT(d.id) > 0
                ORDER BY total_amount DESC, document_count DESC, p.name
                """,
                company.id,
                start_at,
            )
        return [ProjectReportRow(**dict(row)) for row in rows]

    async def list_report_employees(self, telegram_user_id: int, period: str) -> list[EmployeeReportRow]:
        company, start_at = await self._get_manager_company_and_period(telegram_user_id, period)
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT u.id AS user_id,
                       u.username,
                       u.first_name,
                       u.last_name,
                       COUNT(d.id) AS document_count,
                       COALESCE(SUM(d.total_amount), 0) AS total_amount,
                       COUNT(*) FILTER (WHERE d.duplicate_status = 'exact') AS exact_duplicate_count,
                       COUNT(*) FILTER (WHERE d.duplicate_status = 'probable') AS probable_duplicate_count
                FROM company_members cm
                JOIN users u ON u.id = cm.user_id
                LEFT JOIN documents d
                    ON d.uploaded_by_user_id = u.id
                   AND d.company_id = $1
                   AND d.created_at >= $2
                WHERE cm.company_id = $1
                  AND cm.role = 'employee'
                  AND cm.status = 'active'
                GROUP BY u.id, u.username, u.first_name, u.last_name
                HAVING COUNT(d.id) > 0
                ORDER BY total_amount DESC, document_count DESC, u.id
                """,
                company.id,
                start_at,
            )
        result: list[EmployeeReportRow] = []
        for row in rows:
            result.append(EmployeeReportRow(
                user_id=row['user_id'],
                employee_name=_display_name(row['first_name'], row['last_name'], row['username']),
                username=row['username'],
                document_count=row['document_count'],
                total_amount=row['total_amount'],
                exact_duplicate_count=row['exact_duplicate_count'],
                probable_duplicate_count=row['probable_duplicate_count'],
            ))
        return result

    async def get_project_report_detail(self, telegram_user_id: int, period: str, project_id: int) -> tuple[ProjectCard, list[ReportDocumentDetail]]:
        project = await self.get_project_card(telegram_user_id, project_id)
        company, start_at = await self._get_manager_company_and_period(telegram_user_id, period)
        documents = await self._list_report_documents(company.id, start_at, project_id=project_id)
        return project, documents

    async def get_employee_report_detail(self, telegram_user_id: int, period: str, member_user_id: int) -> tuple[MemberCard, list[ReportDocumentDetail]]:
        member = await self.get_employee_card(telegram_user_id, member_user_id)
        company, start_at = await self._get_manager_company_and_period(telegram_user_id, period)
        documents = await self._list_report_documents(company.id, start_at, uploaded_by_user_id=member_user_id)
        return member, documents

    async def get_report_document_items(
        self,
        telegram_user_id: int,
        period: str,
        document_id: int,
        project_id: int | None = None,
        uploaded_by_user_id: int | None = None,
    ) -> tuple[ReportDocumentDetail, list[ReportItemDetail]]:
        company, start_at = await self._get_manager_company_and_period(telegram_user_id, period)
        document = await self._get_report_document(company.id, start_at, document_id, project_id=project_id, uploaded_by_user_id=uploaded_by_user_id)
        items = await self._list_report_items(company.id, start_at, document_id=document_id, project_id=project_id, uploaded_by_user_id=uploaded_by_user_id)
        return document, items

    async def list_duplicate_report_rows(self, telegram_user_id: int, period: str) -> list[DuplicateReportRow]:
        await self.document_service.cleanup_broken_duplicate_links(telegram_user_id)
        company, start_at = await self._get_manager_company_and_period(telegram_user_id, period)
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT d.id,
                       p.name AS project_name,
                       d.vendor,
                       d.vendor_inn,
                       COALESCE(NULLIF(d.external_document_number, ''), NULLIF(d.incoming_number, '')) AS document_number,
                       d.document_date,
                       d.total_amount,
                       d.duplicate_status,
                       d.duplicate_of_document_id,
                       d.created_at,
                       uploader.username AS uploader_username,
                       uploader.first_name AS uploader_first_name,
                       uploader.last_name AS uploader_last_name,
                       base_project.name AS base_project_name,
                       base_doc.vendor AS base_vendor,
                       base_doc.vendor_inn AS base_vendor_inn,
                       COALESCE(NULLIF(base_doc.external_document_number, ''), NULLIF(base_doc.incoming_number, '')) AS base_document_number,
                       base_doc.document_date AS base_document_date,
                       base_doc.total_amount AS base_total_amount,
                       base_uploader.username AS base_uploader_username,
                       base_uploader.first_name AS base_uploader_first_name,
                       base_uploader.last_name AS base_uploader_last_name
                FROM documents d
                JOIN projects p ON p.id = d.project_id
                LEFT JOIN users uploader ON uploader.id = d.uploaded_by_user_id
                LEFT JOIN documents base_doc ON base_doc.id = d.duplicate_of_document_id
                LEFT JOIN projects base_project ON base_project.id = base_doc.project_id
                LEFT JOIN users base_uploader ON base_uploader.id = base_doc.uploaded_by_user_id
                WHERE d.company_id = $1
                  AND d.created_at >= $2
                  AND d.duplicate_status IN ('exact', 'probable')
                ORDER BY d.created_at DESC, d.id DESC
                """,
                company.id,
                start_at,
            )
        return [
            DuplicateReportRow(
                id=row['id'],
                project_name=row['project_name'],
                vendor=row['vendor'],
                vendor_inn=row['vendor_inn'],
                document_number=row['document_number'],
                document_date=row['document_date'],
                total_amount=row['total_amount'],
                duplicate_status=row['duplicate_status'],
                duplicate_of_document_id=row['duplicate_of_document_id'],
                uploaded_by_name=_display_name(row['uploader_first_name'], row['uploader_last_name'], row['uploader_username']),
                base_project_name=row['base_project_name'],
                base_uploaded_by_name=_display_name(row['base_uploader_first_name'], row['base_uploader_last_name'], row['base_uploader_username']),
                base_vendor=row['base_vendor'],
                base_vendor_inn=row['base_vendor_inn'],
                base_document_number=row['base_document_number'],
                base_document_date=row['base_document_date'],
                base_total_amount=row['base_total_amount'],
                created_at=row['created_at'],
            )
            for row in rows
        ]

    async def get_duplicate_report_row(self, telegram_user_id: int, period: str, duplicate_id: int) -> DuplicateReportRow:
        rows = await self.list_duplicate_report_rows(telegram_user_id, period)
        for row in rows:
            if row.id == duplicate_id:
                return row
        raise CompanyAccessError('Дубль не найден в отчете за выбранный период.')

    async def list_report_documents_for_company(self, telegram_user_id: int, period: str) -> list[ReportDocumentDetail]:
        company, start_at = await self._get_manager_company_and_period(telegram_user_id, period)
        return await self._list_report_documents(company.id, start_at)

    async def list_report_items_for_company(self, telegram_user_id: int, period: str) -> list[ReportItemDetail]:
        company, start_at = await self._get_manager_company_and_period(telegram_user_id, period)
        return await self._list_report_items(company.id, start_at)

    async def _get_manager_company_and_period(self, telegram_user_id: int, period: str):
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        role = await self.company_service.ensure_member_role(telegram_user_id)
        if role != 'manager':
            raise CompanyAccessError('Действие доступно только manager.')
        return company, _report_period_start(period)

    async def _list_report_documents(
        self,
        company_id: int,
        start_at: datetime,
        project_id: int | None = None,
        uploaded_by_user_id: int | None = None,
    ) -> list[ReportDocumentDetail]:
        pool = get_pool()
        conditions = ['d.company_id = $1', 'd.created_at >= $2']
        params: list[object] = [company_id, start_at]
        index = 3
        if project_id is not None:
            conditions.append(f'd.project_id = ${index}')
            params.append(project_id)
            index += 1
        if uploaded_by_user_id is not None:
            conditions.append(f'd.uploaded_by_user_id = ${index}')
            params.append(uploaded_by_user_id)
        query = f"""
            SELECT d.id,
                   p.name AS project_name,
                   d.vendor,
                   d.vendor_inn,
                   COALESCE(NULLIF(d.external_document_number, ''), NULLIF(d.incoming_number, '')) AS document_number,
                   d.document_date,
                   d.total_amount,
                   d.duplicate_status,
                   first_item.name AS first_item_name,
                   d.created_at,
                   uploader.username AS uploader_username,
                   uploader.first_name AS uploader_first_name,
                   uploader.last_name AS uploader_last_name
            FROM documents d
            JOIN projects p ON p.id = d.project_id
            LEFT JOIN users uploader ON uploader.id = d.uploaded_by_user_id
            LEFT JOIN LATERAL (
                SELECT di.name
                FROM document_items di
                WHERE di.document_id = d.id
                ORDER BY di.line_no ASC
                LIMIT 1
            ) first_item ON TRUE
            WHERE {' AND '.join(conditions)}
            ORDER BY d.created_at DESC, d.id DESC
            LIMIT 50
        """
        async with pool.acquire() as connection:
            rows = await connection.fetch(query, *params)
        return [
            ReportDocumentDetail(
                id=row['id'],
                project_name=row['project_name'],
                vendor=row['vendor'],
                vendor_inn=row['vendor_inn'],
                document_number=row['document_number'],
                document_date=row['document_date'],
                total_amount=row['total_amount'],
                duplicate_status=row['duplicate_status'],
                uploaded_by_name=_display_name(row['uploader_first_name'], row['uploader_last_name'], row['uploader_username']),
                first_item_name=row['first_item_name'],
                created_at=row['created_at'],
            )
            for row in rows
        ]

    async def _get_report_document(
        self,
        company_id: int,
        start_at: datetime,
        document_id: int,
        project_id: int | None = None,
        uploaded_by_user_id: int | None = None,
    ) -> ReportDocumentDetail:
        pool = get_pool()
        conditions = ['d.company_id = $1', 'd.created_at >= $2', 'd.id = $3']
        params: list[object] = [company_id, start_at, document_id]
        index = 4
        if project_id is not None:
            conditions.append(f'd.project_id = ${index}')
            params.append(project_id)
            index += 1
        if uploaded_by_user_id is not None:
            conditions.append(f'd.uploaded_by_user_id = ${index}')
            params.append(uploaded_by_user_id)
        query = f"""
            SELECT d.id,
                   p.name AS project_name,
                   d.vendor,
                   d.vendor_inn,
                   COALESCE(NULLIF(d.external_document_number, ''), NULLIF(d.incoming_number, '')) AS document_number,
                   d.document_date,
                   d.total_amount,
                   d.duplicate_status,
                   first_item.name AS first_item_name,
                   d.created_at,
                   uploader.username AS uploader_username,
                   uploader.first_name AS uploader_first_name,
                   uploader.last_name AS uploader_last_name
            FROM documents d
            JOIN projects p ON p.id = d.project_id
            LEFT JOIN users uploader ON uploader.id = d.uploaded_by_user_id
            LEFT JOIN LATERAL (
                SELECT di.name
                FROM document_items di
                WHERE di.document_id = d.id
                ORDER BY di.line_no ASC
                LIMIT 1
            ) first_item ON TRUE
            WHERE {' AND '.join(conditions)}
            LIMIT 1
        """
        async with pool.acquire() as connection:
            row = await connection.fetchrow(query, *params)
        if row is None:
            raise CompanyAccessError('Документ отчета не найден.')
        return ReportDocumentDetail(
            id=row['id'],
            project_name=row['project_name'],
            vendor=row['vendor'],
            vendor_inn=row['vendor_inn'],
            document_number=row['document_number'],
            document_date=row['document_date'],
            total_amount=row['total_amount'],
            duplicate_status=row['duplicate_status'],
            uploaded_by_name=_display_name(row['uploader_first_name'], row['uploader_last_name'], row['uploader_username']),
            created_at=row['created_at'],
        )

    async def _list_report_items(
        self,
        company_id: int,
        start_at: datetime,
        document_id: int | None = None,
        project_id: int | None = None,
        uploaded_by_user_id: int | None = None,
    ) -> list[ReportItemDetail]:
        pool = get_pool()
        conditions = ['d.company_id = $1', 'd.created_at >= $2']
        params: list[object] = [company_id, start_at]
        index = 3
        if document_id is not None:
            conditions.append(f'd.id = ${index}')
            params.append(document_id)
            index += 1
        if project_id is not None:
            conditions.append(f'd.project_id = ${index}')
            params.append(project_id)
            index += 1
        if uploaded_by_user_id is not None:
            conditions.append(f'd.uploaded_by_user_id = ${index}')
            params.append(uploaded_by_user_id)
        query = f"""
            SELECT di.document_id,
                   di.line_no,
                   di.name,
                   di.quantity,
                   di.price,
                   di.line_total
            FROM document_items di
            JOIN documents d ON d.id = di.document_id
            WHERE {' AND '.join(conditions)}
            ORDER BY di.document_id DESC, di.line_no ASC
            LIMIT 300
        """
        async with pool.acquire() as connection:
            rows = await connection.fetch(query, *params)
        return [ReportItemDetail(**dict(row)) for row in rows]

    async def archive_company(self, telegram_user_id: int, company_id: int) -> None:
        context = await self.company_service.get_user_context(telegram_user_id)
        if context.platform_role != "owner":
            raise CompanyAccessError("Действие доступно только owner.")
        pool = get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    UPDATE companies
                    SET status = 'archived',
                        archived_at = NOW(),
                        updated_at = NOW(),
                        manager_user_id = NULL
                    WHERE id = $1
                      AND status = 'active'
                    RETURNING id
                    """,
                    company_id,
                )
                if row is None:
                    raise CompanyAccessError("Компания не найдена или уже архивирована.")
                await connection.execute(
                    """
                    UPDATE company_members
                    SET status = 'removed',
                        removed_at = NOW()
                    WHERE company_id = $1
                      AND status = 'active'
                    """,
                    company_id,
                )
                await connection.execute(
                    """
                    UPDATE company_invites
                    SET status = 'revoked'
                    WHERE company_id = $1
                      AND status = 'active'
                    """,
                    company_id,
                )

    async def revoke_manager_invite(self, telegram_user_id: int, company_id: int) -> bool:
        context = await self.company_service.get_user_context(telegram_user_id)
        if context.platform_role != "owner":
            raise CompanyAccessError("Действие доступно только owner.")
        pool = get_pool()
        async with pool.acquire() as connection:
            result = await connection.execute(
                """
                UPDATE company_invites
                SET status = 'revoked'
                WHERE company_id = $1
                  AND role = 'manager'
                  AND status = 'active'
                """,
                company_id,
            )
        return not result.endswith("0")

    async def _list_members(self, company_id: int) -> list[MemberCard]:
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT cm.company_id,
                       cm.user_id,
                       cm.role,
                       u.username,
                       u.first_name,
                       u.last_name,
                       u.telegram_id,
                       cm.joined_at,
                       COALESCE(docs.document_count, 0) AS document_count
                FROM company_members cm
                JOIN users u ON u.id = cm.user_id
                LEFT JOIN (
                    SELECT uploaded_by_user_id, COUNT(*) AS document_count
                    FROM documents
                    GROUP BY uploaded_by_user_id
                ) docs ON docs.uploaded_by_user_id = cm.user_id
                WHERE cm.company_id = $1
                  AND cm.status = 'active'
                ORDER BY cm.role, cm.joined_at, cm.id
                """,
                company_id,
            )
        return [
            MemberCard(
                company_id=row["company_id"],
                user_id=row["user_id"],
                role=row["role"],
                username=row["username"],
                first_name=row["first_name"],
                last_name=row["last_name"],
                telegram_id=row["telegram_id"],
                joined_at=row["joined_at"],
                document_count=row["document_count"],
            )
            for row in rows
        ]

    async def _list_projects(self, company_id: int, status: str) -> list[ProjectCard]:
        pool = get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT p.id,
                       p.company_id,
                       p.name,
                       p.status,
                       p.created_at,
                       creator.username AS creator_username,
                       creator.first_name AS creator_first_name,
                       creator.last_name AS creator_last_name,
                       COALESCE(docs.document_count, 0) AS document_count,
                       docs.total_amount
                FROM projects p
                LEFT JOIN users creator ON creator.id = p.created_by_user_id
                LEFT JOIN (
                    SELECT project_id,
                           COUNT(*) AS document_count,
                           COALESCE(SUM(total_amount), 0) AS total_amount
                    FROM documents
                    GROUP BY project_id
                ) docs ON docs.project_id = p.id
                WHERE p.company_id = $1
                  AND p.status = $2
                ORDER BY p.created_at DESC, p.id DESC
                """,
                company_id,
                status,
            )
        return [
            ProjectCard(
                id=row["id"],
                company_id=row["company_id"],
                name=row["name"],
                status=row["status"],
                created_at=row["created_at"],
                created_by_name=_display_name(row["creator_first_name"], row["creator_last_name"], row["creator_username"]),
                document_count=row["document_count"],
                total_amount=row["total_amount"],
            )
            for row in rows
        ]


def _report_period_start(period: str) -> datetime:
    now = datetime.now(timezone.utc)
    if period == 'week':
        start_date = (now - timedelta(days=now.weekday())).date()
    elif period == 'month':
        start_date = date(now.year, now.month, 1)
    elif period == 'quarter':
        quarter_month = ((now.month - 1) // 3) * 3 + 1
        start_date = date(now.year, quarter_month, 1)
    elif period == 'half_year':
        half_year_month = 1 if now.month <= 6 else 7
        start_date = date(now.year, half_year_month, 1)
    elif period == 'year':
        start_date = date(now.year, 1, 1)
    else:
        raise CompanyAccessError('Неизвестный период отчета.')
    return datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)



def _display_name(first_name: str | None, last_name: str | None, username: str | None) -> str | None:
    parts = [part for part in (first_name, last_name) if part]
    if parts:
        return " ".join(parts)
    return username
