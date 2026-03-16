from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


PROJECT_CALLBACK_PREFIX = "document:project:"
PROJECT_CREATE_CALLBACK = "document:project:create"


def build_projects_keyboard(projects: list[Any], allow_create_project: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=project.name, callback_data=f"{PROJECT_CALLBACK_PREFIX}{project.id}")]
        for project in projects
    ]
    if allow_create_project:
        rows.append([InlineKeyboardButton(text="Создать новый проект", callback_data=PROJECT_CREATE_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
