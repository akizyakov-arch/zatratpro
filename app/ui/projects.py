from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


PROJECT_CALLBACK_PREFIX = "document:project:"
PROJECT_CREATE_CALLBACK = "document:project:create"
PROJECT_CANCEL_CALLBACK = "document:project:cancel"
DOCUMENT_DUPLICATE_CANCEL_CALLBACK = "document:duplicate:cancel"
DOCUMENT_DUPLICATE_SAVE_CALLBACK = "document:duplicate:save"


def build_projects_keyboard(projects: list[Any], allow_create_project: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=project.name, callback_data=f"{PROJECT_CALLBACK_PREFIX}{project.id}")]
        for project in projects
    ]
    if allow_create_project:
        rows.append([InlineKeyboardButton(text="Создать новый проект", callback_data=PROJECT_CREATE_CALLBACK)])
    rows.append([InlineKeyboardButton(text="🛑 Отменить", callback_data=PROJECT_CANCEL_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_duplicate_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отменить", callback_data=DOCUMENT_DUPLICATE_CANCEL_CALLBACK)],
            [InlineKeyboardButton(text="Все равно добавить", callback_data=DOCUMENT_DUPLICATE_SAVE_CALLBACK)],
        ]
    )
