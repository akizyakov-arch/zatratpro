from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.projects import Project


PROJECT_CALLBACK_PREFIX = "project:"


def build_projects_keyboard(projects: list[Project]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=project.name, callback_data=f"{PROJECT_CALLBACK_PREFIX}{project.id}")]
            for project in projects
        ]
    )
