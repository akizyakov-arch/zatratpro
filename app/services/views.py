from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import Decimal

from app.services.company_policy import CompanyAccessError
from app.services.report_periods import report_period_start


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
    role: str
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
    is_fiscalized: bool | None = None
    currency: str = 'RUB'


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


def _dto(kind, row):
    return kind(**{field.name: row.get(field.name) for field in fields(kind)})


class ViewService:
    """Canonical-user report projections; interface identity conversion is external."""
    async def _actor(self, actor_id):
        from app.services.companies import CompanyDirectory
        return await CompanyDirectory()._workspace_actor(actor_id)

    async def _report(self, actor_id, period, **scope):
        from app.services.reporting import ReportService
        from app.services.advances import AdvanceError
        try:
            return await ReportService().period_report(await self._actor(actor_id), period, **scope)
        except AdvanceError as exc:
            raise CompanyAccessError(str(exc)) from exc


    async def _summary(self, actor_id, period, **scope):
        from app.services.reporting import ReportService
        from app.services.advances import AdvanceError
        try:
            return await ReportService().period_summary(await self._actor(actor_id), period, **scope)
        except AdvanceError as exc:
            raise CompanyAccessError(str(exc)) from exc


    async def get_employee_card(self, actor_id: int, member_user_id: int) -> MemberCard:
        from app.services.reporting import ReportService
        from app.services.advances import AdvanceError
        try:
            return _dto(MemberCard, await ReportService().employee(await self._actor(actor_id), member_user_id))
        except AdvanceError as exc:
            raise CompanyAccessError(str(exc)) from exc


    async def get_project_card(self, actor_id: int, project_id: int) -> ProjectCard:
        from app.services.workspace import WorkspaceService, WorkspaceError
        try:
            return _dto(ProjectCard, await WorkspaceService().project(await self._actor(actor_id), project_id))
        except WorkspaceError as exc:
            raise CompanyAccessError(str(exc)) from exc


    async def list_my_documents(self, actor_id: int) -> list[DocumentRow]:
        from app.services.member_directory import MemberDirectory
        from app.services.membership import MembershipError
        try:
            rows, _ = await MemberDirectory().documents(await self._actor(actor_id), per_page=20)
            return [_dto(DocumentRow, row) for row in rows]
        except MembershipError as exc:
            raise CompanyAccessError(str(exc)) from exc


    async def get_manager_report_summary(self, actor_id: int, period: str) -> ReportSummary:
        data = await self._summary(actor_id, period)
        return ReportSummary(period=period, **{key: data['summary'][key] for key in ('start_at','documents','total_amount','exact_duplicates','probable_duplicates')})

    async def get_duplicate_report_summary(self, actor_id: int, period: str) -> ReportSummary:
        data = await self._summary(actor_id, period)
        return ReportSummary(period=period, **{key: data['duplicate_summary'][key] for key in ('start_at','documents','total_amount','exact_duplicates','probable_duplicates')})

    async def get_employee_report_summary(self, actor_id: int, period: str) -> ReportSummary:
        return await self.get_manager_report_summary(actor_id, period)

    async def list_report_projects(self, actor_id: int, period: str) -> list[ProjectReportRow]:
        data = await self._summary(actor_id, period)
        return [_dto(ProjectReportRow, row) for row in sorted(data['projects'], key=lambda row: (-row['total_amount'], -row['document_count'], row['project_name']))]

    async def list_report_employees(self, actor_id: int, period: str) -> list[EmployeeReportRow]:
        data = await self._summary(actor_id, period)
        return [_dto(EmployeeReportRow, row) for row in sorted(data['employees'], key=lambda row: (-row['total_amount'], -row['document_count'], row['user_id']))]

    async def get_project_report_detail(self, actor_id: int, period: str, project_id: int) -> tuple[ProjectCard, list[ReportDocumentDetail]]:
        project = await self.get_project_card(actor_id, project_id)
        data = await self._report(actor_id, period, project_id=project_id)
        return project, [_dto(ReportDocumentDetail, row) for row in data['documents']]

    async def get_employee_report_detail(self, actor_id: int, period: str, member_user_id: int) -> tuple[MemberCard, list[ReportDocumentDetail]]:
        member = await self.get_employee_card(actor_id, member_user_id)
        data = await self._report(actor_id, period, employee_id=member_user_id)
        return member, [_dto(ReportDocumentDetail, row) for row in data['documents']]

    async def get_report_document_items(
        self,
        actor_id: int,
        period: str,
        document_id: int,
        project_id: int | None = None,
        uploaded_by_user_id: int | None = None,
    ) -> tuple[ReportDocumentDetail, list[ReportItemDetail]]:
        data = await self._report(actor_id, period, project_id=project_id, employee_id=uploaded_by_user_id)
        document = next((row for row in data['documents'] if row['id']==document_id), None)
        if document is None:
            raise CompanyAccessError('Документ отчета не найден.')
        return _dto(ReportDocumentDetail, document), [_dto(ReportItemDetail, row) for row in data['items'] if row['document_id']==document_id]

    async def list_duplicate_report_rows(self, actor_id: int, period: str) -> list[DuplicateReportRow]:
        data = await self._summary(actor_id, period, include_duplicates=True)
        return [_dto(DuplicateReportRow, row) for row in sorted(data['duplicates'], key=lambda row: (row['created_at'], row['id']), reverse=True)]

    async def get_duplicate_report_row(self, actor_id: int, period: str, duplicate_id: int) -> DuplicateReportRow:
        rows = await self.list_duplicate_report_rows(actor_id, period)
        for row in rows:
            if row.id == duplicate_id:
                return row
        raise CompanyAccessError('Дубль больше не актуален: исходная запись удалена, статус снят.')

    async def list_report_documents_for_company(self, actor_id: int, period: str) -> list[ReportDocumentDetail]:
        return [_dto(ReportDocumentDetail, row) for row in (await self._report(actor_id, period))['documents']]

    async def list_report_items_for_company(self, actor_id: int, period: str) -> list[ReportItemDetail]:
        return [_dto(ReportItemDetail, row) for row in (await self._report(actor_id, period))['items']]


def _report_period_start(period: str) -> datetime:
    try:
        return report_period_start(period)
    except ValueError as exc:
        raise CompanyAccessError(str(exc)) from exc


def _display_name(first_name: str | None, last_name: str | None, username: str | None) -> str | None:
    parts = [part for part in (first_name, last_name) if part]
    if parts:
        return " ".join(parts)
    return username
