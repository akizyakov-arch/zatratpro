from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


MANAGER_REPORTS_MENU_CALLBACK = "manager:reports:menu"
MANAGER_REPORTS_PROJECTS_CALLBACK = "manager:reports:projects"
MANAGER_REPORTS_EMPLOYEES_CALLBACK = "manager:reports:employees"
MANAGER_REPORTS_DUPLICATES_CALLBACK = "manager:reports:duplicates"
MANAGER_REPORTS_EXPORT_CALLBACK = "manager:reports:export"
MANAGER_REPORTS_PERIOD_PREFIX = "manager:reports:period:"
MANAGER_REPORTS_PROJECT_DETAIL_PREFIX = "manager:reports:project_detail:"
MANAGER_REPORTS_EMPLOYEE_SELECT_PREFIX = "manager:reports:employee_select:"
MANAGER_REPORTS_EMPLOYEE_PERIOD_PREFIX = "manager:reports:employee_period:"
MANAGER_REPORTS_EMPLOYEE_DETAIL_PREFIX = "manager:reports:employee_detail:"
MANAGER_REPORTS_DOCUMENT_DETAIL_PREFIX = "manager:reports:document_detail:"
MANAGER_REPORTS_DOCUMENT_ITEMS_PREFIX = "manager:reports:document_items:"
MANAGER_REPORTS_DUPLICATE_VIEW_PREFIX = "manager:reports:duplicate:view:"
MANAGER_REPORTS_DUPLICATE_DELETE_PREFIX = "manager:reports:duplicate:delete:"
MANAGER_REPORTS_DUPLICATE_DELETE_CONFIRM_PREFIX = "manager:reports:duplicate:delete_confirm:"
MANAGER_REPORTS_DUPLICATE_DELETE_SOURCE_PREFIX = "manager:reports:duplicate:delete_source:"
MANAGER_REPORTS_DUPLICATE_DELETE_SOURCE_CONFIRM_PREFIX = "manager:reports:duplicate:delete_source_confirm:"
MANAGER_REPORTS_DUPLICATE_OPEN_PREFIX = "manager:reports:duplicate:open:"
MANAGER_REPORTS_DUPLICATE_OPEN_SOURCE_PREFIX = "manager:reports:duplicate:open_source:"
MANAGER_REPORTS_DUPLICATE_ITEMS_PREFIX = "manager:reports:duplicate:items:"
MANAGER_REPORTS_DUPLICATE_SOURCE_ITEMS_PREFIX = "manager:reports:duplicate:source_items:"
MANAGER_REPORTS_DUPLICATE_DOCUMENT_VIEW_PREFIX = "manager:reports:duplicate:document:"
MANAGER_REPORTS_DUPLICATE_SOURCE_DOCUMENT_VIEW_PREFIX = "manager:reports:duplicate:source_document:"

REPORT_KIND_PROJECTS = "projects"
REPORT_KIND_EMPLOYEES = "employees"
REPORT_KIND_DUPLICATES = "duplicates"
REPORT_KIND_EXPORT = "export"

REPORT_PERIOD_WEEK = "week"
REPORT_PERIOD_MONTH = "month"
REPORT_PERIOD_QUARTER = "quarter"
REPORT_PERIOD_HALF_YEAR = "half_year"
REPORT_PERIOD_YEAR = "year"
REPORT_PERIOD_ALL = "all_time"

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


def build_employee_report_selector_keyboard(rows: list[Any]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=_employee_row_text(row), callback_data=f"{MANAGER_REPORTS_EMPLOYEE_SELECT_PREFIX}{row.user_id}")]
        for row in rows[:20]
    ]
    buttons.append([InlineKeyboardButton(text="Назад к отчетам", callback_data=MANAGER_REPORTS_MENU_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_employee_report_period_keyboard(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"{MANAGER_REPORTS_EMPLOYEE_PERIOD_PREFIX}{user_id}:{period}")]
        for period, label in REPORT_PERIOD_LABELS.items()
    ]
    rows.append([InlineKeyboardButton(text="Назад к сотрудникам", callback_data=MANAGER_REPORTS_EMPLOYEES_CALLBACK)])
    rows.append([InlineKeyboardButton(text="Назад к отчетам", callback_data=MANAGER_REPORTS_MENU_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_project_report_keyboard(period: str, rows: list[Any]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=_project_row_text(row), callback_data=f"{MANAGER_REPORTS_PROJECT_DETAIL_PREFIX}{period}:{row.project_id}")]
        for row in rows[:20]
    ]
    if period != REPORT_PERIOD_ALL:
        buttons.append([InlineKeyboardButton(text="Назад к периодам", callback_data=f"{MANAGER_REPORTS_PERIOD_PREFIX}{REPORT_KIND_PROJECTS}:_back")])
    buttons.append([InlineKeyboardButton(text="Назад к отчетам", callback_data=MANAGER_REPORTS_MENU_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_duplicate_report_keyboard(period: str, rows: list[Any]) -> InlineKeyboardMarkup:
    inline_rows = [
        [InlineKeyboardButton(text=_duplicate_row_text(row), callback_data=f"{MANAGER_REPORTS_DUPLICATE_VIEW_PREFIX}{period}:{row.id}")]
        for row in rows[:20]
    ]
    inline_rows.append([InlineKeyboardButton(text="Excel выгрузка за период", callback_data=f"{MANAGER_REPORTS_PERIOD_PREFIX}{REPORT_KIND_EXPORT}:{period}")])
    if period != REPORT_PERIOD_ALL:
        inline_rows.append([InlineKeyboardButton(text="Назад к периодам", callback_data=f"{MANAGER_REPORTS_PERIOD_PREFIX}{REPORT_KIND_DUPLICATES}:_back")])
    inline_rows.append([InlineKeyboardButton(text="Назад к отчетам", callback_data=MANAGER_REPORTS_MENU_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=inline_rows)


def build_duplicate_card_keyboard(period: str, duplicate_id: int, source_document_id: int | None) -> InlineKeyboardMarkup:
    rows = []
    if source_document_id is not None:
        rows.append([InlineKeyboardButton(text="Открыть исходный", callback_data=f"{MANAGER_REPORTS_DUPLICATE_OPEN_SOURCE_PREFIX}{period}:{source_document_id}")])
    rows.append([InlineKeyboardButton(text="Открыть дубликат", callback_data=f"{MANAGER_REPORTS_DUPLICATE_OPEN_PREFIX}{period}:{duplicate_id}")])
    rows.append([InlineKeyboardButton(text="Удалить дубликат", callback_data=f"{MANAGER_REPORTS_DUPLICATE_DELETE_PREFIX}{period}:{duplicate_id}")])
    if source_document_id is not None:
        rows.append([InlineKeyboardButton(text="Удалить исходный", callback_data=f"{MANAGER_REPORTS_DUPLICATE_DELETE_SOURCE_PREFIX}{period}:{duplicate_id}")])
    rows.append([InlineKeyboardButton(text="Назад к дублям", callback_data=f"{MANAGER_REPORTS_PERIOD_PREFIX}{REPORT_KIND_DUPLICATES}:{period}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_duplicate_delete_confirm_keyboard(period: str, duplicate_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подтвердить удаление", callback_data=f"{MANAGER_REPORTS_DUPLICATE_DELETE_CONFIRM_PREFIX}{period}:{duplicate_id}")],
            [InlineKeyboardButton(text="Назад к карточке дубля", callback_data=f"{MANAGER_REPORTS_DUPLICATE_VIEW_PREFIX}{period}:{duplicate_id}")],
        ]
    )


def build_duplicate_delete_source_confirm_keyboard(period: str, duplicate_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подтвердить удаление исходной", callback_data=f"{MANAGER_REPORTS_DUPLICATE_DELETE_SOURCE_CONFIRM_PREFIX}{period}:{duplicate_id}")],
            [InlineKeyboardButton(text="Назад к карточке дубля", callback_data=f"{MANAGER_REPORTS_DUPLICATE_VIEW_PREFIX}{period}:{duplicate_id}")],
        ]
    )


def build_report_documents_keyboard(report_kind: str, period: str, target_id: int, documents: list[Any]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=_document_row_text(document),
                callback_data=f"{MANAGER_REPORTS_DOCUMENT_DETAIL_PREFIX}{report_kind}:{period}:{target_id}:{document.id}",
            )
        ]
        for document in documents[:20]
    ]
    rows.append([InlineKeyboardButton(text="Назад к отчету", callback_data=_back_to_report_callback(report_kind, period))])
    rows.append([InlineKeyboardButton(text="Назад к отчетам", callback_data=MANAGER_REPORTS_MENU_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_report_document_card_keyboard(report_kind: str, period: str, target_id: int, document_id: int) -> InlineKeyboardMarkup:
    if report_kind == REPORT_KIND_PROJECTS:
        back_callback = f"{MANAGER_REPORTS_PROJECT_DETAIL_PREFIX}{period}:{target_id}"
    else:
        back_callback = f"{MANAGER_REPORTS_EMPLOYEE_PERIOD_PREFIX}{target_id}:{period}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Состав документа", callback_data=f"{MANAGER_REPORTS_DOCUMENT_ITEMS_PREFIX}{report_kind}:{period}:{target_id}:{document_id}")],
            [InlineKeyboardButton(text="Назад к документам", callback_data=back_callback)],
            [InlineKeyboardButton(text="Назад к отчетам", callback_data=MANAGER_REPORTS_MENU_CALLBACK)],
        ]
    )


def build_report_document_items_back_keyboard(report_kind: str, period: str, target_id: int, document_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад к карточке", callback_data=f"{MANAGER_REPORTS_DOCUMENT_DETAIL_PREFIX}{report_kind}:{period}:{target_id}:{document_id}")],
            [InlineKeyboardButton(text="Назад к отчетам", callback_data=MANAGER_REPORTS_MENU_CALLBACK)],
        ]
    )


def _project_row_text(row: Any) -> str:
    total_amount = getattr(row, "total_amount", 0) or 0
    return f"{row.project_name} | {row.document_count} док. | {total_amount}"


def _employee_row_text(row: Any) -> str:
    employee_name = getattr(row, "employee_name", None) or getattr(row, "username", None) or f"user:{getattr(row, 'user_id', '?')}"
    if getattr(row, 'role', None) == 'manager':
        employee_name = f"Руководитель: {employee_name}"
    if getattr(row, 'member_status', None) == 'blocked':
        employee_name = f"{employee_name} [заблокирован]"
    total_amount = getattr(row, "total_amount", 0) or 0
    return f"{employee_name} | {row.document_count} док. | {total_amount}"
def _document_row_text(document: Any) -> str:
    number = getattr(document, 'document_number', None) or 'без номера'
    date_value = getattr(document, 'document_date', None)
    date_line = date_value.strftime('%d.%m.%Y') if hasattr(date_value, 'strftime') else 'без даты'
    total_amount = getattr(document, 'total_amount', 0) or 0
    uploader = getattr(document, 'uploaded_by_name', None) or 'не указан'
    return f"{date_line} | {number} | {total_amount:,.2f} | {uploader}".replace(',', ' ')


def _back_to_report_callback(report_kind: str, period: str) -> str:
    return f"{MANAGER_REPORTS_PERIOD_PREFIX}{report_kind}:{period}"




def _duplicate_row_text(row: Any) -> str:
    current_project = getattr(row, "project_name", None) or "Без проекта"
    base_project = getattr(row, "base_project_name", None) or "Без исходной записи"
    return f"{current_project} | {base_project}"

