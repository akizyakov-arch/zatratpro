from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


MANAGER_REPORTS_MENU_CALLBACK = "manager:reports:menu"
MANAGER_REPORTS_PROJECTS_CALLBACK = "manager:reports:projects"
MANAGER_REPORTS_EMPLOYEES_CALLBACK = "manager:reports:employees"
MANAGER_REPORTS_DUPLICATES_CALLBACK = "manager:reports:duplicates"
MANAGER_REPORTS_EXPORT_CALLBACK = "manager:reports:export"
MANAGER_REPORTS_PERIOD_PREFIX = "manager:reports:period:"
MANAGER_REPORTS_PROJECT_DETAIL_PREFIX = "manager:reports:project_detail:"
MANAGER_REPORTS_EMPLOYEE_DETAIL_PREFIX = "manager:reports:employee_detail:"

REPORT_KIND_PROJECTS = "projects"
REPORT_KIND_EMPLOYEES = "employees"
REPORT_KIND_DUPLICATES = "duplicates"
REPORT_KIND_EXPORT = "export"

REPORT_PERIOD_WEEK = "week"
REPORT_PERIOD_MONTH = "month"
REPORT_PERIOD_QUARTER = "quarter"
REPORT_PERIOD_HALF_YEAR = "half_year"
REPORT_PERIOD_YEAR = "year"

REPORT_PERIOD_LABELS = {
    REPORT_PERIOD_WEEK: "Неделя",
    REPORT_PERIOD_MONTH: "Месяц",
    REPORT_PERIOD_QUARTER: "Квартал",
    REPORT_PERIOD_HALF_YEAR: "Полугодие",
    REPORT_PERIOD_YEAR: "Год",
}


def build_reports_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="По проектам", callback_data=MANAGER_REPORTS_PROJECTS_CALLBACK)],
            [InlineKeyboardButton(text="По сотрудникам", callback_data=MANAGER_REPORTS_EMPLOYEES_CALLBACK)],
            [InlineKeyboardButton(text="Дубли документов", callback_data=MANAGER_REPORTS_DUPLICATES_CALLBACK)],
            [InlineKeyboardButton(text="Excel выгрузка", callback_data=MANAGER_REPORTS_EXPORT_CALLBACK)],
            [InlineKeyboardButton(text="Назад", callback_data="nav:main")],
        ]
    )


def build_report_period_keyboard(report_kind: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"{MANAGER_REPORTS_PERIOD_PREFIX}{report_kind}:{period}")]
        for period, label in REPORT_PERIOD_LABELS.items()
    ]
    rows.append([InlineKeyboardButton(text="Назад", callback_data=MANAGER_REPORTS_MENU_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_project_report_keyboard(period: str, rows: list[Any]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=_project_row_text(row), callback_data=f"{MANAGER_REPORTS_PROJECT_DETAIL_PREFIX}{period}:{row.project_id}")]
        for row in rows[:20]
    ]
    buttons.append([InlineKeyboardButton(text="Назад к периодам", callback_data=f"{MANAGER_REPORTS_PERIOD_PREFIX}{REPORT_KIND_PROJECTS}:_back")])
    buttons.append([InlineKeyboardButton(text="Назад к отчетам", callback_data=MANAGER_REPORTS_MENU_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_employee_report_keyboard(period: str, rows: list[Any]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=_employee_row_text(row), callback_data=f"{MANAGER_REPORTS_EMPLOYEE_DETAIL_PREFIX}{period}:{row.user_id}")]
        for row in rows[:20]
    ]
    buttons.append([InlineKeyboardButton(text="Назад к периодам", callback_data=f"{MANAGER_REPORTS_PERIOD_PREFIX}{REPORT_KIND_EMPLOYEES}:_back")])
    buttons.append([InlineKeyboardButton(text="Назад к отчетам", callback_data=MANAGER_REPORTS_MENU_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_duplicate_report_keyboard(period: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Excel выгрузка за период", callback_data=f"{MANAGER_REPORTS_PERIOD_PREFIX}{REPORT_KIND_EXPORT}:{period}")],
            [InlineKeyboardButton(text="Назад к периодам", callback_data=f"{MANAGER_REPORTS_PERIOD_PREFIX}{REPORT_KIND_DUPLICATES}:_back")],
            [InlineKeyboardButton(text="Назад к отчетам", callback_data=MANAGER_REPORTS_MENU_CALLBACK)],
        ]
    )


def build_report_detail_back_keyboard(report_kind: str, period: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад к отчету", callback_data=f"{MANAGER_REPORTS_PERIOD_PREFIX}{report_kind}:{period}")],
            [InlineKeyboardButton(text="Назад к отчетам", callback_data=MANAGER_REPORTS_MENU_CALLBACK)],
        ]
    )


def _project_row_text(row: Any) -> str:
    total_amount = getattr(row, "total_amount", 0) or 0
    return f"{row.project_name} | {row.document_count} док. | {total_amount}"


def _employee_row_text(row: Any) -> str:
    employee_name = getattr(row, "employee_name", None) or getattr(row, "username", None) or f"user:{getattr(row, 'user_id', '?')}"
    total_amount = getattr(row, "total_amount", 0) or 0
    return f"{employee_name} | {row.document_count} док. | {total_amount}"
