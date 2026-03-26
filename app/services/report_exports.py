from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.config import TMP_DIR
from app.services.companies import CompanyAccessError, CompanyService
from app.services.excel_report_builder import ManagerExcelReportBuilder
from app.services.report_data_builder import ManagerReportDataBuilder, ManagerReportParams
from app.ui.reports import REPORT_PERIOD_ALL, REPORT_PERIOD_HALF_YEAR, REPORT_PERIOD_MONTH, REPORT_PERIOD_QUARTER, REPORT_PERIOD_WEEK, REPORT_PERIOD_YEAR


@dataclass(slots=True)
class ManagerReportExportResult:
    file_path: Path
    filename: str
    caption: str


class ManagerReportExportService:
    def __init__(self) -> None:
        self.company_service = CompanyService()
        self.data_builder = ManagerReportDataBuilder()
        self.excel_builder = ManagerExcelReportBuilder()

    async def build_for_manager(
        self,
        telegram_user_id: int,
        *,
        period: str = REPORT_PERIOD_ALL,
        project_id: int | None = None,
        employee_user_id: int | None = None,
    ) -> ManagerReportExportResult:
        company = await self.company_service.get_active_company_for_user(telegram_user_id)
        role = await self.company_service.ensure_member_role(telegram_user_id)
        if role != 'manager':
            raise CompanyAccessError('Действие доступно только manager.')

        params, file_label = _resolve_report_params(
            company_id=company.id,
            period=period,
            project_id=project_id,
            employee_user_id=employee_user_id,
        )
        report = await self.data_builder.build(params)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = TMP_DIR / f'manager-report-{company.id}-{uuid4().hex}.xlsx'
        self.excel_builder.build(report, output_path)
        filename = f'manager_report_company_{company.id}_{file_label}_{timestamp}.xlsx'
        caption = f'Управленческий Excel-отчет готов. {params.period_label}. {params.filter_caption}.'
        return ManagerReportExportResult(output_path, filename, caption)


def _resolve_report_params(
    *,
    company_id: int,
    period: str,
    project_id: int | None,
    employee_user_id: int | None,
) -> tuple[ManagerReportParams, str]:
    now = datetime.now(timezone.utc)
    today = now.date()
    if period == REPORT_PERIOD_ALL:
        return (
            ManagerReportParams(
                company_id=company_id,
                mode='all_time',
                project_id=project_id,
                employee_user_id=employee_user_id,
                period_label='Все время',
            ),
            'all_time',
        )
    if period == REPORT_PERIOD_WEEK:
        start = today - timedelta(days=today.weekday())
        return _period_params(company_id, 'Неделя', 'week', start, today, project_id, employee_user_id)
    if period == REPORT_PERIOD_MONTH:
        start = date(today.year, today.month, 1)
        return _period_params(company_id, 'Месяц', f'month_{today.year}_{today.month:02d}', start, today, project_id, employee_user_id)
    if period == REPORT_PERIOD_QUARTER:
        start_month = ((today.month - 1) // 3) * 3 + 1
        start = date(today.year, start_month, 1)
        quarter_no = ((today.month - 1) // 3) + 1
        return _period_params(company_id, f'Квартал {quarter_no} {today.year}', f'quarter_{today.year}_q{quarter_no}', start, today, project_id, employee_user_id)
    if period == REPORT_PERIOD_HALF_YEAR:
        start_month = 1 if today.month <= 6 else 7
        start = date(today.year, start_month, 1)
        half_no = 1 if today.month <= 6 else 2
        return _period_params(company_id, f'Полугодие {half_no} {today.year}', f'half_year_{today.year}_h{half_no}', start, today, project_id, employee_user_id)
    if period == REPORT_PERIOD_YEAR:
        start = date(today.year, 1, 1)
        return _period_params(company_id, f'Текущий год ({today.year})', f'year_{today.year}', start, today, project_id, employee_user_id)
    raise ValueError(f'Unsupported report period: {period}')


def _period_params(
    company_id: int,
    period_label: str,
    file_label: str,
    date_from: date,
    date_to: date,
    project_id: int | None,
    employee_user_id: int | None,
) -> tuple[ManagerReportParams, str]:
    return (
        ManagerReportParams(
            company_id=company_id,
            mode='period',
            date_from=date_from,
            date_to=date_to,
            project_id=project_id,
            employee_user_id=employee_user_id,
            period_label=period_label,
        ),
        file_label,
    )
