from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


NAV_MAIN_CALLBACK = "nav:main"

OWNER_COMPANIES_CALLBACK = "owner:companies"
OWNER_COMPANY_VIEW_PREFIX = "owner:company:view:"
OWNER_COMPANY_ISSUE_INVITE_PREFIX = "owner:company:issue_invite:"
OWNER_COMPANY_SHOW_INVITE_PREFIX = "owner:company:show_invite:"
OWNER_COMPANY_RESET_INVITE_PREFIX = "owner:company:reset_invite:"
OWNER_COMPANY_MEMBERS_PREFIX = "owner:company:members:"
OWNER_COMPANY_ARCHIVE_PREFIX = "owner:company:archive:"
OWNER_COMPANY_ARCHIVE_CONFIRM_PREFIX = "owner:company:archive_confirm:"

MANAGER_PROJECTS_MENU_CALLBACK = "manager:projects:menu"
MANAGER_PROJECTS_ACTIVE_CALLBACK = "manager:projects:active"
MANAGER_PROJECTS_ARCHIVED_CALLBACK = "manager:projects:archived"
MANAGER_PROJECT_CREATE_CALLBACK = "manager:projects:create"
MANAGER_PROJECT_VIEW_PREFIX = "manager:project:view:"
MANAGER_PROJECT_RENAME_PREFIX = "manager:project:rename:"
MANAGER_PROJECT_ARCHIVE_PREFIX = "manager:project:archive:"
MANAGER_PROJECT_ARCHIVE_CONFIRM_PREFIX = "manager:project:archive_confirm:"
MANAGER_PROJECT_RESTORE_PREFIX = "manager:project:restore:"
MANAGER_PROJECT_DOCUMENTS_PREFIX = "manager:project:documents:"

MANAGER_EMPLOYEES_MENU_CALLBACK = "manager:employees:menu"
MANAGER_EMPLOYEES_LIST_CALLBACK = "manager:employees:list"
MANAGER_EMPLOYEE_INVITE_CALLBACK = "manager:employees:invite"
MANAGER_EMPLOYEE_VIEW_PREFIX = "manager:employee:view:"
MANAGER_EMPLOYEE_REMOVE_PREFIX = "manager:employee:remove:"
MANAGER_EMPLOYEE_REMOVE_CONFIRM_PREFIX = "manager:employee:remove_confirm:"


def build_companies_keyboard(companies: list[Any]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=company.name, callback_data=f"{OWNER_COMPANY_VIEW_PREFIX}{company.id}")]
        for company in companies
    ]
    rows.append([InlineKeyboardButton(text="Назад", callback_data=NAV_MAIN_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_company_actions_keyboard(company_id: int, can_issue_invite: bool, has_active_invite: bool, is_archived: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_issue_invite and not is_archived:
        rows.append([InlineKeyboardButton(text="Выдать invite manager", callback_data=f"{OWNER_COMPANY_ISSUE_INVITE_PREFIX}{company_id}")])
    if has_active_invite and not is_archived:
        rows.append([InlineKeyboardButton(text="Показать invite", callback_data=f"{OWNER_COMPANY_SHOW_INVITE_PREFIX}{company_id}")])
        rows.append([InlineKeyboardButton(text="Сбросить invite", callback_data=f"{OWNER_COMPANY_RESET_INVITE_PREFIX}{company_id}")])
    rows.append([InlineKeyboardButton(text="Участники", callback_data=f"{OWNER_COMPANY_MEMBERS_PREFIX}{company_id}")])
    if not is_archived:
        rows.append([InlineKeyboardButton(text="Архивировать компанию", callback_data=f"{OWNER_COMPANY_ARCHIVE_PREFIX}{company_id}")])
    rows.append([InlineKeyboardButton(text="Назад к компаниям", callback_data=OWNER_COMPANIES_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_projects_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Активные проекты", callback_data=MANAGER_PROJECTS_ACTIVE_CALLBACK)],
            [InlineKeyboardButton(text="Архивные проекты", callback_data=MANAGER_PROJECTS_ARCHIVED_CALLBACK)],
            [InlineKeyboardButton(text="Создать проект", callback_data=MANAGER_PROJECT_CREATE_CALLBACK)],
            [InlineKeyboardButton(text="Назад", callback_data=NAV_MAIN_CALLBACK)],
        ]
    )


def build_projects_keyboard(projects: list[Any], archived: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=project.name, callback_data=f"{MANAGER_PROJECT_VIEW_PREFIX}{project.id}")]
        for project in projects
    ]
    back_callback = MANAGER_PROJECTS_ARCHIVED_CALLBACK if archived else MANAGER_PROJECTS_ACTIVE_CALLBACK
    rows.append([InlineKeyboardButton(text="Назад", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_project_card_keyboard(project_id: int, archived: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if archived:
        rows.append([InlineKeyboardButton(text="Деархивировать", callback_data=f"{MANAGER_PROJECT_RESTORE_PREFIX}{project_id}")])
        back_callback = MANAGER_PROJECTS_ARCHIVED_CALLBACK
    else:
        rows.append([InlineKeyboardButton(text="Переименовать", callback_data=f"{MANAGER_PROJECT_RENAME_PREFIX}{project_id}")])
        rows.append([InlineKeyboardButton(text="Архивировать", callback_data=f"{MANAGER_PROJECT_ARCHIVE_PREFIX}{project_id}")])
        rows.append([InlineKeyboardButton(text="Документы проекта", callback_data=f"{MANAGER_PROJECT_DOCUMENTS_PREFIX}{project_id}")])
        back_callback = MANAGER_PROJECTS_ACTIVE_CALLBACK
    rows.append([InlineKeyboardButton(text="Назад", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_employees_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Список сотрудников", callback_data=MANAGER_EMPLOYEES_LIST_CALLBACK)],
            [InlineKeyboardButton(text="Пригласить сотрудника", callback_data=MANAGER_EMPLOYEE_INVITE_CALLBACK)],
            [InlineKeyboardButton(text="Назад", callback_data=NAV_MAIN_CALLBACK)],
        ]
    )


def build_employees_keyboard(employees: list[Any]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_member_button_text(member), callback_data=f"{MANAGER_EMPLOYEE_VIEW_PREFIX}{member.user_id}")]
        for member in employees
    ]
    rows.append([InlineKeyboardButton(text="Назад", callback_data=MANAGER_EMPLOYEES_MENU_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_employee_card_keyboard(member_user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Исключить сотрудника", callback_data=f"{MANAGER_EMPLOYEE_REMOVE_PREFIX}{member_user_id}")],
            [InlineKeyboardButton(text="Назад", callback_data=MANAGER_EMPLOYEES_LIST_CALLBACK)],
        ]
    )


def build_company_members_keyboard(company_id: int, members: list[Any]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_member_button_text(member), callback_data=f"{OWNER_COMPANY_VIEW_PREFIX}{company_id}")]
        for member in members
    ]
    rows.append([InlineKeyboardButton(text="Назад к карточке компании", callback_data=f"{OWNER_COMPANY_VIEW_PREFIX}{company_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_confirm_keyboard(confirm_callback: str, cancel_callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подтвердить", callback_data=confirm_callback)],
            [InlineKeyboardButton(text="Отмена", callback_data=cancel_callback)],
        ]
    )


def _member_button_text(member: Any) -> str:
    full_name = getattr(member, 'full_name', None)
    username = getattr(member, 'username', None)
    telegram_id = getattr(member, 'telegram_id', None)
    if full_name:
        return full_name
    if username:
        return f"@{username}"
    return str(telegram_id)
