from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.ui.company import NAV_MAIN_CALLBACK

MY_DOCUMENTS_LIST_CALLBACK = "my_documents:list"
MY_DOCUMENTS_VIEW_PREFIX = "my_documents:view:"
MY_DOCUMENTS_ITEMS_PREFIX = "my_documents:items:"


def build_my_documents_keyboard(documents: list[Any]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_document_button_text(document), callback_data=f"{MY_DOCUMENTS_VIEW_PREFIX}{document.id}")]
        for document in documents
    ]
    rows.append([InlineKeyboardButton(text="Назад", callback_data=NAV_MAIN_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_my_document_card_keyboard(document_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Состав документа", callback_data=f"{MY_DOCUMENTS_ITEMS_PREFIX}{document_id}")],
            [InlineKeyboardButton(text="Назад к документам", callback_data=MY_DOCUMENTS_LIST_CALLBACK)],
            [InlineKeyboardButton(text="Назад", callback_data=NAV_MAIN_CALLBACK)],
        ]
    )


def build_my_document_items_keyboard(document_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад к карточке", callback_data=f"{MY_DOCUMENTS_VIEW_PREFIX}{document_id}")],
            [InlineKeyboardButton(text="Назад к документам", callback_data=MY_DOCUMENTS_LIST_CALLBACK)],
            [InlineKeyboardButton(text="Назад", callback_data=NAV_MAIN_CALLBACK)],
        ]
    )


def _document_button_text(document: Any) -> str:
    created_line = document.created_at.strftime('%Y-%m-%d') if getattr(document, 'created_at', None) else '—'
    number = getattr(document, 'document_number', None) or 'без №'
    check_date = document.document_date.strftime('%Y-%m-%d') if getattr(document, 'document_date', None) else 'без даты'
    total_amount = getattr(document, 'total_amount', 0) or 0
    return f"{created_line} | {number} | {check_date} | {total_amount}"
