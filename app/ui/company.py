from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.companies import CompanyMember
from app.services.projects import Project


ARCHIVE_PROJECT_CALLBACK_PREFIX = "company:archive_project:"
RESTORE_PROJECT_CALLBACK_PREFIX = "company:restore_project:"
REMOVE_EMPLOYEE_CALLBACK_PREFIX = "company:remove_employee:"


def build_project_action_keyboard(
    projects: list[Project],
    callback_prefix: str,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=project.name, callback_data=f"{callback_prefix}{project.id}")]
            for project in projects
        ]
    )


def build_employee_removal_keyboard(members: list[CompanyMember]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_member_display_name(member),
                    callback_data=f"{REMOVE_EMPLOYEE_CALLBACK_PREFIX}{member.user_id}",
                )
            ]
            for member in members
        ]
    )


def _member_display_name(member: CompanyMember) -> str:
    return member.full_name or member.username or str(member.telegram_user_id)