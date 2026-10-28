"""Render the existing Telegram administration keyboards as native MAX buttons."""
from app.max_bot.menu import MenuButton
from app.ui import company as ui

EXACT = {
    ui.NAV_MAIN_CALLBACK: '/start', ui.OWNER_COMPANIES_CALLBACK: '/companies',
    ui.OWNER_USERS_CALLBACK: '/users', ui.MANAGER_PROJECTS_MENU_CALLBACK: '/projects',
    ui.MANAGER_PROJECTS_ACTIVE_CALLBACK: '/admin_projects',
    ui.MANAGER_PROJECTS_ARCHIVED_CALLBACK: '/archived_projects',
    ui.MANAGER_PROJECT_CREATE_CALLBACK: '/create_project',
    ui.MANAGER_EMPLOYEES_MENU_CALLBACK: '/employees',
    ui.MANAGER_EMPLOYEES_LIST_CALLBACK: '/employee_list',
    ui.MANAGER_EMPLOYEE_INVITE_CALLBACK: '/invite',
}
PREFIXES = {
    ui.OWNER_COMPANY_VIEW_PREFIX: '/company',
    ui.OWNER_COMPANY_ISSUE_INVITE_PREFIX: '/company_invite',
    ui.OWNER_COMPANY_SHOW_INVITE_PREFIX: '/company_show_invite',
    ui.OWNER_COMPANY_RESET_INVITE_PREFIX: '/company_revoke',
    ui.OWNER_COMPANY_MEMBERS_PREFIX: '/company_members',
    ui.OWNER_COMPANY_ARCHIVE_PREFIX: '/company_archive',
    ui.OWNER_COMPANY_ARCHIVE_CONFIRM_PREFIX: '/company_archive_yes',
    ui.OWNER_USER_VIEW_PREFIX: '/user',
    ui.OWNER_USER_ASSIGN_EMPLOYEE_PREFIX: '/assign_employee',
    ui.OWNER_USER_ASSIGN_MANAGER_PREFIX: '/assign_manager',
    ui.OWNER_USER_REMOVE_PREFIX: '/user_remove',
    ui.OWNER_USER_REMOVE_CONFIRM_PREFIX: '/user_remove_yes',
    ui.MANAGER_PROJECT_VIEW_PREFIX: '/project',
    ui.MANAGER_PROJECT_RENAME_PREFIX: '/rename_project',
    ui.MANAGER_PROJECT_ARCHIVE_PREFIX: '/project_archive',
    ui.MANAGER_PROJECT_ARCHIVE_CONFIRM_PREFIX: '/project_archive_yes',
    ui.MANAGER_PROJECT_RESTORE_PREFIX: '/project_restore',
    ui.MANAGER_PROJECT_DOCUMENTS_PREFIX: '/project_documents',
    ui.MANAGER_EMPLOYEE_VIEW_PREFIX: '/employee',
    ui.MANAGER_EMPLOYEE_REMOVE_PREFIX: '/employee_remove',
    ui.MANAGER_EMPLOYEE_REMOVE_CONFIRM_PREFIX: '/employee_remove_yes',
}


def command(data):
    if data in EXACT:
        return EXACT[data]
    if data.startswith(ui.OWNER_USER_ASSIGN_COMPANY_PREFIX):
        return '/assign ' + data.removeprefix(ui.OWNER_USER_ASSIGN_COMPANY_PREFIX).replace(':', ' ')
    for prefix, name in PREFIXES.items():
        if data.startswith(prefix):
            return name + ' ' + data.removeprefix(prefix)
    raise ValueError('Неизвестная кнопка интерфейса.')


def keyboard(markup):
    return [[MenuButton(button.text, command(button.callback_data)) for button in row]
            for row in markup.inline_keyboard]
