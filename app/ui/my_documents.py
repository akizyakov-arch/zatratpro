from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.ui.company import NAV_MAIN_CALLBACK

MY_DOCUMENTS_FILTER_MENU_CALLBACK = "my_documents:filters"
MY_DOCUMENTS_LIST_CALLBACK = "my_documents:list"
MY_DOCUMENTS_LIST_PREFIX = "my_documents:list:"
MY_DOCUMENTS_PROJECTS_CALLBACK = "my_documents:projects"
MY_DOCUMENTS_VIEW_PREFIX = "my_documents:view:"
MY_DOCUMENTS_ITEMS_PREFIX = "my_documents:items:"
MY_DOCUMENTS_OPEN_PREFIX = "my_documents:open:"

MY_DOCUMENTS_SCOPE_MONTH = "month"
MY_DOCUMENTS_SCOPE_ALL = "all"


def build_my_documents_filter_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="За месяц", callback_data=build_my_documents_list_callback(MY_DOCUMENTS_SCOPE_MONTH))],
            [InlineKeyboardButton(text="Все", callback_data=build_my_documents_list_callback(MY_DOCUMENTS_SCOPE_ALL))],
            [InlineKeyboardButton(text="По проектам", callback_data=MY_DOCUMENTS_PROJECTS_CALLBACK)],
            [InlineKeyboardButton(text="Назад", callback_data=NAV_MAIN_CALLBACK)],
        ]
    )


def build_my_documents_projects_keyboard(projects: list[Any]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_project_button_text(project), callback_data=build_my_documents_list_callback(build_my_documents_project_scope(project.id)))]
        for project in projects
    ]
    rows.append([InlineKeyboardButton(text="Назад к фильтрам", callback_data=MY_DOCUMENTS_FILTER_MENU_CALLBACK)])
    rows.append([InlineKeyboardButton(text="Назад", callback_data=NAV_MAIN_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_my_documents_keyboard(documents: list[Any], scope_token: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_document_button_text(document), callback_data=f"{MY_DOCUMENTS_VIEW_PREFIX}{scope_token}:{document.id}")]
        for document in documents
    ]
    rows.append([InlineKeyboardButton(text="Назад к фильтрам", callback_data=MY_DOCUMENTS_FILTER_MENU_CALLBACK)])
    rows.append([InlineKeyboardButton(text="Назад", callback_data=NAV_MAIN_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_my_document_card_keyboard(document_id: int, scope_token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть документ", callback_data=f"{MY_DOCUMENTS_OPEN_PREFIX}{scope_token}:{document_id}")],
            [InlineKeyboardButton(text="Состав документа", callback_data=f"{MY_DOCUMENTS_ITEMS_PREFIX}{scope_token}:{document_id}")],
            [InlineKeyboardButton(text="Назад к документам", callback_data=build_my_documents_list_callback(scope_token))],
            [InlineKeyboardButton(text="Назад к фильтрам", callback_data=MY_DOCUMENTS_FILTER_MENU_CALLBACK)],
            [InlineKeyboardButton(text="Назад", callback_data=NAV_MAIN_CALLBACK)],
        ]
    )


def build_my_document_items_keyboard(document_id: int, scope_token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад к карточке", callback_data=f"{MY_DOCUMENTS_VIEW_PREFIX}{scope_token}:{document_id}")],
            [InlineKeyboardButton(text="Назад к документам", callback_data=build_my_documents_list_callback(scope_token))],
            [InlineKeyboardButton(text="Назад к фильтрам", callback_data=MY_DOCUMENTS_FILTER_MENU_CALLBACK)],
            [InlineKeyboardButton(text="Назад", callback_data=NAV_MAIN_CALLBACK)],
        ]
    )


def build_my_documents_list_callback(scope_token: str) -> str:
    return f"{MY_DOCUMENTS_LIST_PREFIX}{scope_token}"


def build_my_documents_project_scope(project_id: int) -> str:
    return f"project_{project_id}"


def parse_my_documents_list_scope(callback_data: str) -> str:
    return callback_data.removeprefix(MY_DOCUMENTS_LIST_PREFIX)


def parse_my_documents_scoped_document(callback_data: str, prefix: str) -> tuple[str, int]:
    payload = callback_data.removeprefix(prefix)
    if ":" not in payload:
        return MY_DOCUMENTS_SCOPE_MONTH, int(payload)
    scope_token, document_id = payload.rsplit(":", 1)
    return scope_token, int(document_id)


def _document_button_text(document: Any) -> str:
    created_line = document.created_at.strftime('%d.%m.%Y') if getattr(document, 'created_at', None) else '—'
    total_amount = getattr(document, 'total_amount', 0) or 0
    vendor = getattr(document, 'vendor', None) or getattr(document, 'vendor_inn', None) or 'Без поставщика'
    uploader = getattr(document, 'uploaded_by_name', None) or 'не указан'
    return f"{created_line} | {total_amount} | {vendor} | {uploader}"


def _project_button_text(project: Any) -> str:
    document_count = getattr(project, 'document_count', 0) or 0
    return f"{project.name} ({document_count})"
