from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Message, ReplyKeyboardMarkup

from app.services.companies import CompanyAccessError, CompanyService
from app.services.documents import DocumentService
from app.services.projects import ProjectService
from app.services.report_exports import build_manager_report_workbook
from app.services.report_formatters import (
    format_duplicate_report,
    format_employee_report,
    format_project_report,
    format_report_document_items,
    format_report_documents,
    report_period_label,
)
from app.services.views import ViewService
from app.state.pending_actions import get_pending_action, pop_pending_action, set_pending_action
from app.state.pending_documents import get_pending_document
from app.ui.company import (
    MANAGER_EMPLOYEES_LIST_CALLBACK,
    MANAGER_EMPLOYEES_MENU_CALLBACK,
    MANAGER_EMPLOYEE_INVITE_CALLBACK,
    MANAGER_EMPLOYEE_REMOVE_CONFIRM_PREFIX,
    MANAGER_EMPLOYEE_REMOVE_PREFIX,
    MANAGER_EMPLOYEE_VIEW_PREFIX,
    MANAGER_PROJECTS_ACTIVE_CALLBACK,
    MANAGER_PROJECTS_ARCHIVED_CALLBACK,
    MANAGER_PROJECTS_MENU_CALLBACK,
    MANAGER_PROJECT_ARCHIVE_CONFIRM_PREFIX,
    MANAGER_PROJECT_ARCHIVE_PREFIX,
    MANAGER_PROJECT_CREATE_CALLBACK,
    MANAGER_PROJECT_DOCUMENTS_PREFIX,
    MANAGER_PROJECT_RENAME_PREFIX,
    MANAGER_PROJECT_RESTORE_PREFIX,
    MANAGER_PROJECT_VIEW_PREFIX,
    NAV_MAIN_CALLBACK,
    OWNER_COMPANIES_CALLBACK,
    OWNER_COMPANY_ARCHIVE_CONFIRM_PREFIX,
    OWNER_COMPANY_ARCHIVE_PREFIX,
    OWNER_COMPANY_ISSUE_INVITE_PREFIX,
    OWNER_COMPANY_MEMBERS_PREFIX,
    OWNER_COMPANY_RESET_INVITE_PREFIX,
    OWNER_COMPANY_SHOW_INVITE_PREFIX,
    OWNER_COMPANY_VIEW_PREFIX,
    OWNER_USERS_CALLBACK,
    OWNER_USER_ASSIGN_COMPANY_PREFIX,
    OWNER_USER_ASSIGN_EMPLOYEE_PREFIX,
    OWNER_USER_ASSIGN_MANAGER_PREFIX,
    OWNER_USER_REMOVE_CONFIRM_PREFIX,
    OWNER_USER_REMOVE_PREFIX,
    OWNER_USER_VIEW_PREFIX,
    build_companies_keyboard,
    build_company_actions_keyboard,
    build_company_members_keyboard,
    build_confirm_keyboard,
    build_employee_card_keyboard,
    build_employees_keyboard,
    build_employees_menu_keyboard,
    build_owner_user_card_keyboard,
    build_owner_user_company_select_keyboard,
    build_owner_users_keyboard,
    build_project_card_keyboard,
    build_projects_keyboard,
    build_projects_menu_keyboard,
)
from app.ui.help import (
    HELP_MENU_PREFIX,
    HELP_TOPIC_PREFIX,
    build_help_topic_keyboard,
    build_help_topics_keyboard,
    get_help_topic_text,
)
from app.ui.main_menu import MAIN_MENU_TEXT, MENU_BUTTONS, build_main_menu_keyboard
from app.ui.reports import (
    MANAGER_REPORTS_DOCUMENT_DETAIL_PREFIX,
    MANAGER_REPORTS_DUPLICATE_DELETE_CONFIRM_PREFIX,
    MANAGER_REPORTS_DUPLICATE_DELETE_PREFIX,
    MANAGER_REPORTS_DUPLICATE_DELETE_SOURCE_CONFIRM_PREFIX,
    MANAGER_REPORTS_DUPLICATE_DELETE_SOURCE_PREFIX,
    MANAGER_REPORTS_DUPLICATE_KEEP_PREFIX,
    MANAGER_REPORTS_DUPLICATE_VIEW_PREFIX,
    MANAGER_REPORTS_DUPLICATES_CALLBACK,
    MANAGER_REPORTS_EMPLOYEES_CALLBACK,
    MANAGER_REPORTS_EMPLOYEE_DETAIL_PREFIX,
    MANAGER_REPORTS_EXPORT_CALLBACK,
    MANAGER_REPORTS_MENU_CALLBACK,
    MANAGER_REPORTS_PERIOD_PREFIX,
    MANAGER_REPORTS_PROJECTS_CALLBACK,
    MANAGER_REPORTS_PROJECT_DETAIL_PREFIX,
    REPORT_KIND_DUPLICATES,
    REPORT_KIND_EMPLOYEES,
    REPORT_KIND_EXPORT,
    REPORT_KIND_PROJECTS,
    REPORT_PERIOD_ALL,
    build_duplicate_card_keyboard,
    build_duplicate_delete_confirm_keyboard,
    build_duplicate_delete_source_confirm_keyboard,
    build_duplicate_report_keyboard,
    build_employee_report_keyboard,
    build_project_report_keyboard,
    build_report_document_back_keyboard,
    build_report_documents_keyboard,
    build_report_period_keyboard,
    build_reports_menu_keyboard,
)
from app.ui.projects import build_projects_keyboard as build_document_projects_keyboard


router = Router()
company_service = CompanyService()
project_service = ProjectService()
document_service = DocumentService()
view_service = ViewService()
NL = chr(10)


async def _ensure_context(message: Message):
    if message.from_user is None:
        return None
    await company_service.ensure_platform_user(message.from_user)
    return await company_service.get_user_context(message.from_user.id)


async def _main_menu_markup_for_user(user) -> ReplyKeyboardMarkup:
    if user is None:
        return build_main_menu_keyboard(has_company=False)
    await company_service.ensure_platform_user(user)
    context = await company_service.get_user_context(user.id)
    return build_main_menu_keyboard(
        menu_kind=context.menu_kind,
        has_company=context.has_company,
        can_view_reports=context.can_view_reports,
    )


async def _main_menu_markup(message: Message) -> ReplyKeyboardMarkup:
    return await _main_menu_markup_for_user(message.from_user)


async def _help_menu_kind_for_user(user) -> str:
    if user is None:
        return 'employee'
    await company_service.ensure_platform_user(user)
    context = await company_service.get_user_context(user.id)
    return context.menu_kind


async def _require_company_access(message: Message) -> bool:
    context = await _ensure_context(message)
    if context is None or not context.has_company:
        await message.answer(
            'Сначала нужен invite-код компании. Нажми "Ввести invite-код" или выполни /join КОД.',
            reply_markup=await _main_menu_markup(message),
        )
        return False
    return True


def _format_company_card(card) -> str:
    invite_state = 'есть активный invite' if card.invite is not None else 'invite отсутствует'
    manager_state = card.manager_name if card.manager_name else 'не назначен'
    status = 'active' if getattr(card, 'is_active', True) else 'archived'
    return NL.join([
        f'Компания: {card.name}',
        f'Статус: {status}',
        f'Manager: {manager_state}',
        f'Сотрудников: {card.employee_count}',
        f'Активных проектов: {card.active_project_count}',
        f'Архивных проектов: {card.archived_project_count}',
        f'Документов: {card.document_count}',
        f'Создана: {card.created_at:%Y-%m-%d %H:%M}',
        f'Invite manager: {invite_state}',
    ])


def _format_project_card(project) -> str:
    status = 'archived' if project.is_archived else 'active'
    total_amount = project.total_amount if project.total_amount is not None else 0
    created_line = f'{project.created_at:%Y-%m-%d %H:%M}' if project.created_at else '—'
    creator = project.created_by_name or '—'
    return NL.join([
        f'Проект: {project.name}',
        f'Статус: {status}',
        f'Создан: {created_line}',
        f'Кем создан: {creator}',
        f'Документов: {project.document_count}',
        f'Сумма затрат: {total_amount}',
    ])


def _format_member_card(member) -> str:
    joined = member.joined_at.strftime('%Y-%m-%d %H:%M') if member.joined_at else '—'
    username = f'@{member.username}' if member.username else '—'
    return NL.join([
        f'Сотрудник: {member.full_name or username}',
        f'Username: {username}',
        f'Дата вступления: {joined}',
        f'Загружено документов: {member.document_count}',
    ])


def _format_user_card(user) -> str:
    username = f'@{user.username}' if user.username else '—'
    full_name = user.full_name or '—'
    company_name = user.company_name or 'не привязан'
    company_role = user.company_role or '—'
    company_status = user.company_status or '—'
    joined_at = user.joined_at.strftime('%Y-%m-%d %H:%M') if getattr(user, 'joined_at', None) else '—'
    return NL.join([
        f'Пользователь: {full_name}',
        f'Username: {username}',
        f'Telegram ID: {user.telegram_id}',
        f'System role: {user.system_role}',
        f'Компания: {company_name}',
        f'Роль в компании: {company_role}',
        f'Статус компании: {company_status}',
        f'Дата привязки: {joined_at}',
    ])


def _person_name(user) -> str:
    if user is None:
        return 'коллега'
    return user.first_name or user.full_name or user.username or 'коллега'



def _person_identity(user) -> str:
    if user is None:
        return 'коллега'
    username = f'@{user.username}' if user.username else None
    name = _person_name(user)
    if username:
        return f'{name} ({username})'
    return name


def _format_duplicate_card(row) -> str:
    date_line = row.document_date.strftime('%d.%m.%Y') if row.document_date else 'без даты'
    base_date_line = row.base_document_date.strftime('%d.%m.%Y') if row.base_document_date else 'без даты'
    number = row.document_number or 'без номера'
    base_number = row.base_document_number or 'без номера'
    vendor = row.vendor or row.vendor_inn or 'контрагент не указан'
    base_vendor = row.base_vendor or row.base_vendor_inn or 'контрагент не указан'
    uploader = row.uploaded_by_name or 'не указан'
    base_uploader = row.base_uploaded_by_name or 'не указан'
    duplicate_label = 'Точный дубль' if row.duplicate_status == 'exact' else 'Вероятный дубль'
    return NL.join([
        duplicate_label,
        '',
        'Текущая запись:',
        f'Проект: {row.project_name}',
        f'Контрагент: {vendor}',
        f'Дата: {date_line}',
        f'Номер: {number}',
        f'Сумма: {row.total_amount or 0}',
        f'Внес: {uploader}',
        '',
        'Исходная запись:',
        f'Проект: {row.base_project_name or "не найден"}',
        f'Контрагент: {base_vendor}',
        f'Дата: {base_date_line}',
        f'Номер: {base_number}',
        f'Сумма: {row.base_total_amount or 0}',
        f'Внес: {base_uploader}',
    ])



@router.message(CommandStart())
async def start_command(message: Message, command: CommandObject | None = None) -> None:
    context = await _ensure_context(message)
    payload = command.args if command is not None else None
    if payload and payload.startswith('join_'):
        await join_company(message, payload.removeprefix('join_'))
        return
    if context is not None and context.menu_kind == 'platform_owner':
        line = 'Owner-режим: управление компаниями и системным состоянием.'
    elif context is not None and context.has_company:
        line = f'Текущая компания: {context.company.name}'
    else:
        line = 'Сначала нужен invite-код компании.'
    await message.answer(f'Привет, {_person_identity(message.from_user)}.' + NL + NL + MAIN_MENU_TEXT + NL + NL + line, reply_markup=await _main_menu_markup(message))


@router.message(Command('help'))
async def help_command(message: Message) -> None:
    menu_kind = await _help_menu_kind_for_user(message.from_user)
    await message.answer(f'{_person_name(message.from_user)}, выбери тему помощи.', reply_markup=build_help_topics_keyboard(menu_kind))


@router.message(Command('create_company'))
async def create_company_command(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        return
    name = (command.args or '').strip()
    if not name:
        await message.answer('Использование: /create_company Название компании', reply_markup=await _main_menu_markup(message))
        return
    try:
        company = await company_service.create_company(message.from_user, name)
        invite_code = await company_service.create_initial_manager_invite(message.from_user, company.id)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return
    await message.answer(f'Компания создана: {company.name}. Invite для первого manager: {invite_code}', reply_markup=await _main_menu_markup(message))


@router.message(Command('invite'))
async def invite_command(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        return
    role = (command.args or 'employee').strip()
    if role != 'employee':
        await message.answer('Использование: /invite employee', reply_markup=await _main_menu_markup(message))
        return
    try:
        code = await company_service.create_invite(message.from_user, 'employee')
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return
    await message.answer(f'Invite-код для сотрудника: {code}', reply_markup=await _main_menu_markup(message))


@router.message(Command('join'))
async def join_command(message: Message, command: CommandObject) -> None:
    await join_company(message, (command.args or '').strip())


async def join_company(message: Message, invite_code: str) -> None:
    if message.from_user is None:
        return
    if not invite_code:
        await message.answer('Использование: /join КОД', reply_markup=await _main_menu_markup(message))
        return
    try:
        company = await company_service.join_company(message.from_user, invite_code)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return
    await message.answer(f'Доступ к компании "{company.name}" подключен.', reply_markup=await _main_menu_markup(message))


@router.message(F.text == MENU_BUTTONS['join_company'])
async def join_company_button(message: Message) -> None:
    if message.from_user is None:
        return
    set_pending_action(message.from_user.id, 'join_company')
    await message.answer(f'{_person_name(message.from_user)}, отправь invite-код следующим сообщением.', reply_markup=await _main_menu_markup(message))


@router.message(F.text == MENU_BUTTONS['upload_document'])
async def upload_document_entry(message: Message) -> None:
    if not await _require_company_access(message):
        return
    await message.answer(f'{_person_name(message.from_user)}, отправь фото документа. После preview я предложу проекты кнопками.', reply_markup=await _main_menu_markup(message))


@router.message(F.text == MENU_BUTTONS['companies'])
async def companies_entry(message: Message) -> None:
    if message.from_user is None:
        return
    try:
        companies = await view_service.list_companies(message.from_user.id)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return
    if not companies:
        await message.answer('Компаний пока нет.', reply_markup=await _main_menu_markup(message))
        return
    await message.answer('Компании:', reply_markup=build_companies_keyboard(companies))


@router.message(F.text == MENU_BUTTONS['users'])
async def users_entry(message: Message) -> None:
    if message.from_user is None:
        return
    try:
        users = await view_service.list_users(message.from_user.id)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return
    if not users:
        await message.answer('Пользователей пока нет.', reply_markup=await _main_menu_markup(message))
        return
    await message.answer('Пользователи:', reply_markup=build_owner_users_keyboard(users))


@router.callback_query(F.data == OWNER_USERS_CALLBACK)
async def users_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    try:
        users = await view_service.list_users(callback.from_user.id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    await callback.message.answer('Пользователи:', reply_markup=build_owner_users_keyboard(users))


@router.callback_query(F.data.startswith(OWNER_USER_VIEW_PREFIX))
async def user_view_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    user_id = int(callback.data.removeprefix(OWNER_USER_VIEW_PREFIX))
    try:
        user = await view_service.get_user_card(callback.from_user.id, user_id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(_format_user_card(user), reply_markup=build_owner_user_card_keyboard(user.user_id, user.has_company))


@router.callback_query(F.data.startswith(OWNER_USER_ASSIGN_EMPLOYEE_PREFIX))
async def user_assign_employee_prompt(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    user_id = int(callback.data.removeprefix(OWNER_USER_ASSIGN_EMPLOYEE_PREFIX))
    try:
        companies = [company for company in await view_service.list_companies(callback.from_user.id) if company.is_active]
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    if not companies:
        await callback.answer('Нет активных компаний для привязки.', show_alert=True)
        return
    await callback.answer()
    await callback.message.answer('Выбери компанию для роли employee.', reply_markup=build_owner_user_company_select_keyboard(companies, user_id, 'employee'))


@router.callback_query(F.data.startswith(OWNER_USER_ASSIGN_MANAGER_PREFIX))
async def user_assign_manager_prompt(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    user_id = int(callback.data.removeprefix(OWNER_USER_ASSIGN_MANAGER_PREFIX))
    try:
        companies = [company for company in await view_service.list_companies(callback.from_user.id) if company.is_active]
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    if not companies:
        await callback.answer('Нет активных компаний для привязки.', show_alert=True)
        return
    await callback.answer()
    await callback.message.answer('Выбери компанию для роли manager.', reply_markup=build_owner_user_company_select_keyboard(companies, user_id, 'manager'))


@router.callback_query(F.data.startswith(OWNER_USER_ASSIGN_COMPANY_PREFIX))
async def user_assign_company_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    payload = callback.data.removeprefix(OWNER_USER_ASSIGN_COMPANY_PREFIX)
    try:
        user_id_text, role, company_id_text = payload.split(':', 2)
        user_id = int(user_id_text)
        company_id = int(company_id_text)
        member = await company_service.assign_user_to_company_by_owner(callback.from_user.id, user_id, company_id, role)
        user = await view_service.get_user_card(callback.from_user.id, user_id)
    except (TypeError, ValueError):
        await callback.answer('Некорректные данные привязки.', show_alert=True)
        return
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer('Пользователь привязан.')
    await callback.message.answer(
        f'Пользователь привязан к компании как {member.role}.',
        reply_markup=build_owner_user_card_keyboard(user.user_id, user.has_company),
    )
    await callback.message.answer(_format_user_card(user), reply_markup=build_owner_user_card_keyboard(user.user_id, user.has_company))


@router.callback_query(F.data.startswith(OWNER_USER_REMOVE_PREFIX))
async def user_remove_prompt(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    user_id = int(callback.data.removeprefix(OWNER_USER_REMOVE_PREFIX))
    await callback.answer()
    await callback.message.answer(
        'Подтвердить исключение пользователя из компании?',
        reply_markup=build_confirm_keyboard(f'{OWNER_USER_REMOVE_CONFIRM_PREFIX}{user_id}', f'{OWNER_USER_VIEW_PREFIX}{user_id}'),
    )


@router.callback_query(F.data.startswith(OWNER_USER_REMOVE_CONFIRM_PREFIX))
async def user_remove_confirm(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    user_id = int(callback.data.removeprefix(OWNER_USER_REMOVE_CONFIRM_PREFIX))
    try:
        member = await company_service.remove_user_from_company_by_owner(callback.from_user.id, user_id)
        user = await view_service.get_user_card(callback.from_user.id, user_id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer('Пользователь исключен.')
    await callback.message.answer(
        f'Пользователь исключен из компании: {member.full_name or member.username or member.telegram_user_id}.',
        reply_markup=build_owner_user_card_keyboard(user.user_id, user.has_company),
    )
    await callback.message.answer(_format_user_card(user), reply_markup=build_owner_user_card_keyboard(user.user_id, user.has_company))


@router.callback_query(F.data == OWNER_COMPANIES_CALLBACK)
async def companies_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    try:
        companies = await view_service.list_companies(callback.from_user.id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    await callback.message.answer('Компании:', reply_markup=build_companies_keyboard(companies))


@router.callback_query(F.data.startswith(OWNER_COMPANY_VIEW_PREFIX))
async def company_card_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    company_id = int(callback.data.removeprefix(OWNER_COMPANY_VIEW_PREFIX))
    try:
        card = await view_service.get_company_card(callback.from_user.id, company_id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(_format_company_card(card), reply_markup=build_company_actions_keyboard(card.id, not card.manager_assigned, card.invite is not None, not card.is_active))


@router.callback_query(F.data.startswith(OWNER_COMPANY_ISSUE_INVITE_PREFIX))
async def company_issue_invite_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    company_id = int(callback.data.removeprefix(OWNER_COMPANY_ISSUE_INVITE_PREFIX))
    try:
        await view_service.revoke_manager_invite(callback.from_user.id, company_id)
        code = await company_service.create_initial_manager_invite(callback.from_user, company_id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer('Invite выдан.')
    await callback.message.answer(f'Invite для manager: {code}', reply_markup=await _main_menu_markup_for_user(callback.from_user))


@router.callback_query(F.data.startswith(OWNER_COMPANY_SHOW_INVITE_PREFIX))
async def company_show_invite_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    company_id = int(callback.data.removeprefix(OWNER_COMPANY_SHOW_INVITE_PREFIX))
    try:
        card = await view_service.get_company_card(callback.from_user.id, company_id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    if card.invite is None:
        await callback.answer('Активного invite нет.', show_alert=True)
        return
    await callback.answer()
    expires = card.invite.expires_at.strftime('%Y-%m-%d %H:%M') if card.invite.expires_at else 'без срока'
    await callback.message.answer(f'Текущий invite: {card.invite.code}. Действует до: {expires}')


@router.callback_query(F.data.startswith(OWNER_COMPANY_RESET_INVITE_PREFIX))
async def company_reset_invite_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    company_id = int(callback.data.removeprefix(OWNER_COMPANY_RESET_INVITE_PREFIX))
    try:
        changed = await view_service.revoke_manager_invite(callback.from_user.id, company_id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer('Invite сброшен.' if changed else 'Активного invite не было.')


@router.callback_query(F.data.startswith(OWNER_COMPANY_MEMBERS_PREFIX))
async def company_members_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    company_id = int(callback.data.removeprefix(OWNER_COMPANY_MEMBERS_PREFIX))
    try:
        members = await view_service.list_company_members_for_owner(callback.from_user.id, company_id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    if not members:
        await callback.answer('Участников нет.', show_alert=True)
        return
    await callback.answer()
    lines = ['Участники компании:', '']
    for index, member in enumerate(members, start=1):
        lines.append(f"{index}. {member.full_name or member.username or member.telegram_id} — {member.role}")
    await callback.message.answer(NL.join(lines), reply_markup=build_company_members_keyboard(company_id, members))


@router.callback_query(F.data.startswith(OWNER_COMPANY_ARCHIVE_PREFIX))
async def company_archive_prompt(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    company_id = int(callback.data.removeprefix(OWNER_COMPANY_ARCHIVE_PREFIX))
    await callback.answer()
    await callback.message.answer('Подтвердить архивацию компании?', reply_markup=build_confirm_keyboard(f'{OWNER_COMPANY_ARCHIVE_CONFIRM_PREFIX}{company_id}', f'{OWNER_COMPANY_VIEW_PREFIX}{company_id}'))


@router.callback_query(F.data.startswith(OWNER_COMPANY_ARCHIVE_CONFIRM_PREFIX))
async def company_archive_confirm(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return
    company_id = int(callback.data.removeprefix(OWNER_COMPANY_ARCHIVE_CONFIRM_PREFIX))
    try:
        await view_service.archive_company(callback.from_user.id, company_id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer('Компания архивирована.')


@router.message(F.text == MENU_BUTTONS['system_status'])
async def system_status_entry(message: Message) -> None:
    if message.from_user is None:
        return
    try:
        stats = await view_service.get_system_stats(message.from_user.id)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return
    text = NL.join([
        f'Пользователей: {stats.users}',
        f'Компаний: {stats.companies}',
        f'Активных компаний: {stats.active_companies}',
        f'Managers: {stats.managers}',
        f'Employees: {stats.employees}',
        f'Проектов: {stats.projects}',
        f'Документов: {stats.documents}',
    ])
    await message.answer(text, reply_markup=await _main_menu_markup(message))


@router.message(F.text == MENU_BUTTONS['create_company'])
async def create_company_button(message: Message) -> None:
    if message.from_user is None:
        return
    context = await _ensure_context(message)
    if context is None or context.platform_role != 'owner':
        await message.answer('Создавать компании может только owner.', reply_markup=await _main_menu_markup(message))
        return
    set_pending_action(message.from_user.id, 'create_company')
    await message.answer(f'{_person_name(message.from_user)}, отправь название новой компании.', reply_markup=await _main_menu_markup(message))


@router.message(F.text == MENU_BUTTONS['projects'])
async def projects_menu_entry(message: Message) -> None:
    if message.from_user is None:
        return
    context = await _ensure_context(message)
    if context is None or not context.can_manage_company:
        await message.answer('Раздел проектов доступен только manager.', reply_markup=await _main_menu_markup(message))
        return
    await message.answer('Раздел проектов:', reply_markup=build_projects_menu_keyboard())


@router.callback_query(F.data == MANAGER_PROJECTS_MENU_CALLBACK)
async def projects_menu_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await callback.message.answer('Раздел проектов:', reply_markup=build_projects_menu_keyboard())


@router.callback_query(F.data == MANAGER_PROJECTS_ACTIVE_CALLBACK)
async def projects_active_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    try:
        projects = await view_service.list_projects_for_manager(callback.from_user.id, archived=False)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    if not projects:
        await callback.message.answer('Активных проектов пока нет.', reply_markup=build_projects_menu_keyboard())
        return
    await callback.message.answer('Активные проекты:', reply_markup=build_projects_keyboard(projects, archived=False))


@router.callback_query(F.data == MANAGER_PROJECTS_ARCHIVED_CALLBACK)
async def projects_archived_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    try:
        projects = await view_service.list_projects_for_manager(callback.from_user.id, archived=True)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    if not projects:
        await callback.message.answer('Архивных проектов пока нет.', reply_markup=build_projects_menu_keyboard())
        return
    await callback.message.answer('Архивные проекты:', reply_markup=build_projects_keyboard(projects, archived=True))


@router.callback_query(F.data == MANAGER_PROJECT_CREATE_CALLBACK)
async def project_create_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    set_pending_action(callback.from_user.id, 'create_project')
    await callback.answer()
    await callback.message.answer('Отправь название нового проекта.', reply_markup=await _main_menu_markup_for_user(callback.from_user))


@router.callback_query(F.data.startswith(MANAGER_PROJECT_VIEW_PREFIX))
async def project_view_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    project_id = int(callback.data.removeprefix(MANAGER_PROJECT_VIEW_PREFIX))
    try:
        project = await view_service.get_project_card(callback.from_user.id, project_id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(_format_project_card(project), reply_markup=build_project_card_keyboard(project.id, archived=project.is_archived))


@router.callback_query(F.data.startswith(MANAGER_PROJECT_RENAME_PREFIX))
async def project_rename_prompt(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    project_id = int(callback.data.removeprefix(MANAGER_PROJECT_RENAME_PREFIX))
    set_pending_action(callback.from_user.id, 'rename_project', {'project_id': project_id})
    await callback.answer()
    await callback.message.answer('Отправь новое название проекта.', reply_markup=await _main_menu_markup_for_user(callback.from_user))


@router.callback_query(F.data.startswith(MANAGER_PROJECT_ARCHIVE_PREFIX))
async def project_archive_prompt(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    project_id = int(callback.data.removeprefix(MANAGER_PROJECT_ARCHIVE_PREFIX))
    await callback.answer()
    await callback.message.answer('Подтвердить архивацию проекта?', reply_markup=build_confirm_keyboard(f'{MANAGER_PROJECT_ARCHIVE_CONFIRM_PREFIX}{project_id}', f'{MANAGER_PROJECT_VIEW_PREFIX}{project_id}'))


@router.callback_query(F.data.startswith(MANAGER_PROJECT_ARCHIVE_CONFIRM_PREFIX))
async def project_archive_confirm(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    project_id = int(callback.data.removeprefix(MANAGER_PROJECT_ARCHIVE_CONFIRM_PREFIX))
    try:
        project = await project_service.archive_project(callback.from_user.id, project_id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer('Проект архивирован.')
    await callback.message.answer(f'Проект архивирован: {project.name}.')


@router.callback_query(F.data.startswith(MANAGER_PROJECT_RESTORE_PREFIX))
async def project_restore_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    project_id = int(callback.data.removeprefix(MANAGER_PROJECT_RESTORE_PREFIX))
    try:
        project = await project_service.restore_project(callback.from_user.id, project_id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer('Проект деархивирован.')
    await callback.message.answer(f'Проект возвращен: {project.name}.')


@router.callback_query(F.data.startswith(MANAGER_PROJECT_DOCUMENTS_PREFIX))
async def project_documents_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    project_id = int(callback.data.removeprefix(MANAGER_PROJECT_DOCUMENTS_PREFIX))
    try:
        documents = await view_service.list_project_documents(callback.from_user.id, project_id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    if not documents:
        await callback.message.answer('В проекте пока нет документов.')
        return
    lines = ['Документы проекта:', '']
    for index, document in enumerate(documents, start=1):
        lines.append(f"{index}. {document.vendor or 'Без поставщика'} — {document.total_amount or 0} — {document.project_name}")
    await callback.message.answer(NL.join(lines))


@router.message(F.text == MENU_BUTTONS['employees'])
async def employees_menu_entry(message: Message) -> None:
    if message.from_user is None:
        return
    context = await _ensure_context(message)
    if context is None or not context.can_manage_company:
        await message.answer('Раздел сотрудников доступен только manager.', reply_markup=await _main_menu_markup(message))
        return
    await message.answer('Раздел сотрудников:', reply_markup=build_employees_menu_keyboard())


@router.callback_query(F.data == MANAGER_EMPLOYEES_MENU_CALLBACK)
async def employees_menu_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await callback.message.answer('Раздел сотрудников:', reply_markup=build_employees_menu_keyboard())


@router.callback_query(F.data == MANAGER_EMPLOYEES_LIST_CALLBACK)
async def employees_list_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    try:
        employees = await view_service.list_employees_for_manager(callback.from_user.id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    if not employees:
        await callback.message.answer('Сотрудников пока нет.', reply_markup=build_employees_menu_keyboard())
        return
    await callback.message.answer('Сотрудники:', reply_markup=build_employees_keyboard(employees))


@router.callback_query(F.data == MANAGER_EMPLOYEE_INVITE_CALLBACK)
async def employee_invite_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    try:
        code = await company_service.create_invite(callback.from_user, 'employee')
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(f'Invite-код для сотрудника: {code}')


@router.callback_query(F.data.startswith(MANAGER_EMPLOYEE_VIEW_PREFIX))
async def employee_view_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    member_user_id = int(callback.data.removeprefix(MANAGER_EMPLOYEE_VIEW_PREFIX))
    try:
        member = await view_service.get_employee_card(callback.from_user.id, member_user_id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(_format_member_card(member), reply_markup=build_employee_card_keyboard(member.user_id))


@router.callback_query(F.data.startswith(MANAGER_EMPLOYEE_REMOVE_PREFIX))
async def employee_remove_prompt(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    member_user_id = int(callback.data.removeprefix(MANAGER_EMPLOYEE_REMOVE_PREFIX))
    await callback.answer()
    await callback.message.answer('Подтвердить исключение сотрудника?', reply_markup=build_confirm_keyboard(f'{MANAGER_EMPLOYEE_REMOVE_CONFIRM_PREFIX}{member_user_id}', f'{MANAGER_EMPLOYEE_VIEW_PREFIX}{member_user_id}'))


@router.callback_query(F.data.startswith(MANAGER_EMPLOYEE_REMOVE_CONFIRM_PREFIX))
async def employee_remove_confirm(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    member_user_id = int(callback.data.removeprefix(MANAGER_EMPLOYEE_REMOVE_CONFIRM_PREFIX))
    try:
        member = await company_service.remove_employee(callback.from_user.id, member_user_id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer('Сотрудник исключен.')
    await callback.message.answer(f'Сотрудник исключен: {member.full_name or member.username or member.telegram_user_id}.')


@router.message(F.text == MENU_BUTTONS['reports'])
async def reports_menu_entry(message: Message) -> None:
    if message.from_user is None:
        return
    context = await _ensure_context(message)
    if context is None or not context.can_view_reports:
        await message.answer('Раздел отчетов доступен только manager и master.', reply_markup=await _main_menu_markup(message))
        return
    await message.answer('Раздел отчетов:', reply_markup=build_reports_menu_keyboard())


@router.callback_query(F.data == MANAGER_REPORTS_MENU_CALLBACK)
async def reports_menu_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await callback.message.answer('Раздел отчетов:', reply_markup=build_reports_menu_keyboard())


@router.callback_query(F.data.in_({MANAGER_REPORTS_PROJECTS_CALLBACK, MANAGER_REPORTS_EMPLOYEES_CALLBACK, MANAGER_REPORTS_DUPLICATES_CALLBACK, MANAGER_REPORTS_EXPORT_CALLBACK}))
async def report_kind_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    report_kind = {
        MANAGER_REPORTS_PROJECTS_CALLBACK: REPORT_KIND_PROJECTS,
        MANAGER_REPORTS_EMPLOYEES_CALLBACK: REPORT_KIND_EMPLOYEES,
        MANAGER_REPORTS_DUPLICATES_CALLBACK: REPORT_KIND_DUPLICATES,
        MANAGER_REPORTS_EXPORT_CALLBACK: REPORT_KIND_EXPORT,
    }[callback.data]
    if report_kind == REPORT_KIND_PROJECTS:
        summary = await view_service.get_manager_report_summary(callback.from_user.id, REPORT_PERIOD_ALL)
        rows = await view_service.list_report_projects(callback.from_user.id, REPORT_PERIOD_ALL)
        await callback.answer()
        await callback.message.answer(
            format_project_report(summary, rows),
            reply_markup=build_project_report_keyboard(REPORT_PERIOD_ALL, rows),
            parse_mode='HTML',
        )
        return
    if report_kind == REPORT_KIND_DUPLICATES:
        rows = await view_service.list_duplicate_report_rows(callback.from_user.id, REPORT_PERIOD_ALL)
        summary = await view_service.get_duplicate_report_summary(callback.from_user.id, REPORT_PERIOD_ALL)
        await callback.answer()
        await callback.message.answer(
            format_duplicate_report(summary, rows),
            reply_markup=build_duplicate_report_keyboard(REPORT_PERIOD_ALL, rows),
            parse_mode='HTML',
        )
        return
    await callback.answer()
    await callback.message.answer('Выбери период отчета.', reply_markup=build_report_period_keyboard(report_kind))


@router.callback_query(F.data.startswith(MANAGER_REPORTS_PERIOD_PREFIX))
async def report_period_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    payload = callback.data.removeprefix(MANAGER_REPORTS_PERIOD_PREFIX)
    try:
        report_kind, period = payload.split(':', 1)
    except ValueError:
        await callback.answer('Некорректный период отчета.', show_alert=True)
        return
    if period == '_back':
        await callback.answer()
        await callback.message.answer('Выбери период отчета.', reply_markup=build_report_period_keyboard(report_kind))
        return
    try:
        if report_kind == REPORT_KIND_PROJECTS:
            summary = await view_service.get_manager_report_summary(callback.from_user.id, period)
            rows = await view_service.list_report_projects(callback.from_user.id, period)
            await callback.answer()
            await callback.message.answer(format_project_report(summary, rows), reply_markup=build_project_report_keyboard(period, rows), parse_mode='HTML')
            return
        if report_kind == REPORT_KIND_EMPLOYEES:
            summary = await view_service.get_manager_report_summary(callback.from_user.id, period)
            rows = await view_service.list_report_employees(callback.from_user.id, period)
            await callback.answer()
            await callback.message.answer(format_employee_report(summary, rows), reply_markup=build_employee_report_keyboard(period, rows), parse_mode='HTML')
            return
        if report_kind == REPORT_KIND_DUPLICATES:
            rows = await view_service.list_duplicate_report_rows(callback.from_user.id, period)
            duplicate_summary = await view_service.get_duplicate_report_summary(callback.from_user.id, period)
            await callback.answer()
            await callback.message.answer(format_duplicate_report(duplicate_summary, rows), reply_markup=build_duplicate_report_keyboard(period, rows), parse_mode='HTML')
            return
        if report_kind == REPORT_KIND_EXPORT:
            summary = await view_service.get_manager_report_summary(callback.from_user.id, period)
            projects = await view_service.list_report_projects(callback.from_user.id, period)
            employees = await view_service.list_report_employees(callback.from_user.id, period)
            duplicates = await view_service.list_duplicate_report_rows(callback.from_user.id, period)
            documents = await view_service.list_report_documents_for_company(callback.from_user.id, period)
            items = await view_service.list_report_items_for_company(callback.from_user.id, period)
            filename, payload_bytes = build_manager_report_workbook(period, summary, projects, employees, duplicates, documents, items)
            await callback.answer()
            await callback.message.answer_document(BufferedInputFile(payload_bytes, filename=filename), caption=f'Выгрузка отчетов за период: {report_period_label(period)}')
            return
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return


@router.callback_query(F.data.startswith(MANAGER_REPORTS_PROJECT_DETAIL_PREFIX))
async def report_project_detail_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    payload = callback.data.removeprefix(MANAGER_REPORTS_PROJECT_DETAIL_PREFIX)
    try:
        period, project_id_text = payload.split(':', 1)
        project_id = int(project_id_text)
        project, documents = await view_service.get_project_report_detail(callback.from_user.id, period, project_id)
    except (ValueError, CompanyAccessError) as exc:
        message = str(exc) if isinstance(exc, CompanyAccessError) else 'Некорректные данные проекта.'
        await callback.answer(message, show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(
        format_report_documents(f'Проект: {project.name}', period, documents),
        reply_markup=build_report_documents_keyboard(REPORT_KIND_PROJECTS, period, project.id, documents),
        parse_mode='HTML',
    )


@router.callback_query(F.data.startswith(MANAGER_REPORTS_EMPLOYEE_DETAIL_PREFIX))
async def report_employee_detail_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    payload = callback.data.removeprefix(MANAGER_REPORTS_EMPLOYEE_DETAIL_PREFIX)
    try:
        period, user_id_text = payload.split(':', 1)
        user_id = int(user_id_text)
        member, documents = await view_service.get_employee_report_detail(callback.from_user.id, period, user_id)
    except (ValueError, CompanyAccessError) as exc:
        message = str(exc) if isinstance(exc, CompanyAccessError) else 'Некорректные данные сотрудника.'
        await callback.answer(message, show_alert=True)
        return
    employee_name = member.full_name or (f'@{member.username}' if member.username else str(member.telegram_id))
    title_prefix = 'Мастер' if member.role == 'master' else 'Сотрудник'
    await callback.answer()
    await callback.message.answer(
        format_report_documents(f'{title_prefix}: {employee_name}', period, documents),
        reply_markup=build_report_documents_keyboard(REPORT_KIND_EMPLOYEES, period, member.user_id, documents),
        parse_mode='HTML',
    )


@router.callback_query(F.data.startswith(MANAGER_REPORTS_DUPLICATE_VIEW_PREFIX))
async def duplicate_view_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    payload = callback.data.removeprefix(MANAGER_REPORTS_DUPLICATE_VIEW_PREFIX)
    try:
        period, duplicate_id_text = payload.split(':', 1)
        duplicate_id = int(duplicate_id_text)
        row = await view_service.get_duplicate_report_row(callback.from_user.id, period, duplicate_id)
    except (ValueError, CompanyAccessError) as exc:
        message = str(exc) if isinstance(exc, CompanyAccessError) else 'Некорректные данные дубля.'
        await callback.answer(message, show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(_format_duplicate_card(row), reply_markup=build_duplicate_card_keyboard(period, duplicate_id, row.duplicate_of_document_id is not None))


@router.callback_query(F.data.startswith(MANAGER_REPORTS_DUPLICATE_KEEP_PREFIX))
async def duplicate_keep_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    payload = callback.data.removeprefix(MANAGER_REPORTS_DUPLICATE_KEEP_PREFIX)
    try:
        period, duplicate_id_text = payload.split(':', 1)
        duplicate_id = int(duplicate_id_text)
        await document_service.resolve_duplicate_keep_separate(callback.from_user.id, duplicate_id)
    except (ValueError, CompanyAccessError) as exc:
        message = str(exc) if isinstance(exc, CompanyAccessError) else 'Некорректные данные дубля.'
        await callback.answer(message, show_alert=True)
        return
    await callback.answer('Статус дубля снят.')
    rows = await view_service.list_duplicate_report_rows(callback.from_user.id, period)
    summary = await view_service.get_duplicate_report_summary(callback.from_user.id, period)
    await callback.message.answer(format_duplicate_report(summary, rows), reply_markup=build_duplicate_report_keyboard(period, rows))


@router.callback_query(F.data.startswith(MANAGER_REPORTS_DUPLICATE_DELETE_PREFIX))
async def duplicate_delete_prompt_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    payload = callback.data.removeprefix(MANAGER_REPORTS_DUPLICATE_DELETE_PREFIX)
    try:
        period, duplicate_id_text = payload.split(':', 1)
        duplicate_id = int(duplicate_id_text)
    except ValueError:
        await callback.answer('Некорректные данные дубля.', show_alert=True)
        return
    await callback.answer()
    await callback.message.answer('Подтвердить удаление дубликата?', reply_markup=build_duplicate_delete_confirm_keyboard(period, duplicate_id))


@router.callback_query(F.data.startswith(MANAGER_REPORTS_DUPLICATE_DELETE_CONFIRM_PREFIX))
async def duplicate_delete_confirm_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    payload = callback.data.removeprefix(MANAGER_REPORTS_DUPLICATE_DELETE_CONFIRM_PREFIX)
    try:
        period, duplicate_id_text = payload.split(':', 1)
        duplicate_id = int(duplicate_id_text)
        await document_service.delete_duplicate_document(callback.from_user.id, duplicate_id)
    except (ValueError, CompanyAccessError) as exc:
        message = str(exc) if isinstance(exc, CompanyAccessError) else 'Некорректные данные дубля.'
        await callback.answer(message, show_alert=True)
        return
    await callback.answer('Дубликат удален.')
    rows = await view_service.list_duplicate_report_rows(callback.from_user.id, period)
    summary = await view_service.get_duplicate_report_summary(callback.from_user.id, period)
    await callback.message.answer(format_duplicate_report(summary, rows), reply_markup=build_duplicate_report_keyboard(period, rows))



@router.callback_query(F.data.startswith(MANAGER_REPORTS_DUPLICATE_DELETE_SOURCE_PREFIX))
async def duplicate_delete_source_prompt_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    payload = callback.data.removeprefix(MANAGER_REPORTS_DUPLICATE_DELETE_SOURCE_PREFIX)
    try:
        period, duplicate_id_text = payload.split(':', 1)
        duplicate_id = int(duplicate_id_text)
    except ValueError:
        await callback.answer('Некорректные данные дубля.', show_alert=True)
        return
    await callback.answer()
    await callback.message.answer('Подтвердить удаление исходной записи?', reply_markup=build_duplicate_delete_source_confirm_keyboard(period, duplicate_id))


@router.callback_query(F.data.startswith(MANAGER_REPORTS_DUPLICATE_DELETE_SOURCE_CONFIRM_PREFIX))
async def duplicate_delete_source_confirm_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    payload = callback.data.removeprefix(MANAGER_REPORTS_DUPLICATE_DELETE_SOURCE_CONFIRM_PREFIX)
    try:
        period, duplicate_id_text = payload.split(':', 1)
        duplicate_id = int(duplicate_id_text)
        await document_service.delete_source_duplicate_document(callback.from_user.id, duplicate_id)
    except (ValueError, CompanyAccessError) as exc:
        message = str(exc) if isinstance(exc, CompanyAccessError) else 'Некорректные данные дубля.'
        await callback.answer(message, show_alert=True)
        return
    await callback.answer('Исходная запись удалена.')
    rows = await view_service.list_duplicate_report_rows(callback.from_user.id, period)
    summary = await view_service.get_manager_report_summary(callback.from_user.id, period)
    await callback.message.answer(format_duplicate_report(summary, rows), reply_markup=build_duplicate_report_keyboard(period, rows))


@router.callback_query(F.data.startswith(MANAGER_REPORTS_DOCUMENT_DETAIL_PREFIX))
async def report_document_detail_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    payload = callback.data.removeprefix(MANAGER_REPORTS_DOCUMENT_DETAIL_PREFIX)
    try:
        report_kind, period, target_id_text, document_id_text = payload.split(':', 3)
        target_id = int(target_id_text)
        document_id = int(document_id_text)
        if report_kind == REPORT_KIND_PROJECTS:
            document, items = await view_service.get_report_document_items(
                callback.from_user.id,
                period,
                document_id,
                project_id=target_id,
            )
        elif report_kind == REPORT_KIND_EMPLOYEES:
            document, items = await view_service.get_report_document_items(
                callback.from_user.id,
                period,
                document_id,
                uploaded_by_user_id=target_id,
            )
        else:
            await callback.answer('Некорректный источник отчета.', show_alert=True)
            return
    except (ValueError, CompanyAccessError) as exc:
        message = str(exc) if isinstance(exc, CompanyAccessError) else 'Некорректные данные документа.'
        await callback.answer(message, show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(
        format_report_document_items('Позиции документа', period, document, items),
        reply_markup=build_report_document_back_keyboard(report_kind, period, target_id),
        parse_mode='HTML',
    )


@router.message(F.text == MENU_BUTTONS['my_company'])
async def my_company_entry(message: Message) -> None:
    if message.from_user is None:
        return
    try:
        card = await view_service.get_my_company_card(message.from_user.id)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return
    await message.answer(_format_company_card(card), reply_markup=await _main_menu_markup(message))


@router.message(F.text == MENU_BUTTONS['my_documents'])
async def my_documents_entry(message: Message) -> None:
    if message.from_user is None:
        return
    try:
        documents = await view_service.list_my_documents(message.from_user.id)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return
    if not documents:
        await message.answer('У тебя пока нет документов.', reply_markup=await _main_menu_markup(message))
        return
    lines = ['Мои документы:', '']
    for index, document in enumerate(documents, start=1):
        date_line = document.document_date.isoformat() if document.document_date else 'без даты'
        lines.append(f"{index}. {date_line} — {document.vendor or 'Без поставщика'} — {document.total_amount or 0} — {document.project_name}")
    await message.answer(NL.join(lines), reply_markup=await _main_menu_markup(message))


@router.callback_query(F.data == NAV_MAIN_CALLBACK)
async def nav_main_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await callback.message.answer(MAIN_MENU_TEXT, reply_markup=await _main_menu_markup_for_user(callback.from_user))


@router.message(F.text == MENU_BUTTONS['help'])
async def help_button(message: Message) -> None:
    await help_command(message)


@router.callback_query(F.data.startswith(HELP_MENU_PREFIX))
async def help_menu_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    actual_menu_kind = await _help_menu_kind_for_user(callback.from_user)
    requested_menu_kind = callback.data.removeprefix(HELP_MENU_PREFIX) or actual_menu_kind
    if requested_menu_kind != actual_menu_kind:
        await callback.answer('Раздел помощи недоступен.', show_alert=True)
        return
    await callback.answer()
    await callback.message.answer('Выбери тему помощи.', reply_markup=build_help_topics_keyboard(actual_menu_kind))


@router.callback_query(F.data.startswith(HELP_TOPIC_PREFIX))
async def help_topic_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    payload = callback.data.removeprefix(HELP_TOPIC_PREFIX)
    try:
        menu_kind, topic_id = payload.split(':', 1)
    except ValueError:
        await callback.answer('Тема помощи недоступна.', show_alert=True)
        return
    actual_menu_kind = await _help_menu_kind_for_user(callback.from_user)
    if menu_kind != actual_menu_kind:
        await callback.answer('Тема помощи недоступна.', show_alert=True)
        return
    text_value = get_help_topic_text(menu_kind, topic_id)
    if text_value is None:
        await callback.answer('Тема помощи недоступна.', show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(text_value, reply_markup=build_help_topic_keyboard(menu_kind))


@router.message(F.text)
async def handle_pending_text(message: Message) -> None:
    if message.from_user is None or not message.text:
        await message.answer('Поддерживаются кнопки главного меню, /start, /help, /join и фото документов.', reply_markup=await _main_menu_markup(message))
        return
    pending_action = get_pending_action(message.from_user.id)
    if pending_action is None:
        await message.answer('Используй кнопки главного меню или отправь фото документа.', reply_markup=await _main_menu_markup(message))
        return
    pop_pending_action(message.from_user.id)
    text_value = message.text.strip()
    try:
        if pending_action.action == 'join_company':
            await join_company(message, text_value)
            return
        if pending_action.action == 'create_company':
            company = await company_service.create_company(message.from_user, text_value)
            invite_code = await company_service.create_initial_manager_invite(message.from_user, company.id)
            await message.answer(f'Компания создана: {company.name}. Invite для первого manager: {invite_code}', reply_markup=await _main_menu_markup(message))
            return
        if pending_action.action == 'create_project':
            project = await project_service.create_project(message.from_user.id, text_value)
            await message.answer(f'Проект создан: {project.name}.', reply_markup=await _main_menu_markup(message))
            if get_pending_document(message.from_user.id) is not None:
                projects = await project_service.list_active_projects(message.from_user.id)
                await message.answer('Выбери проект для сохранения документа.', reply_markup=build_document_projects_keyboard(projects, allow_create_project=True))
            return
        if pending_action.action == 'rename_project':
            project_id = int(pending_action.payload['project_id'])
            await view_service.rename_project(message.from_user.id, project_id, text_value)
            await message.answer('Проект переименован.', reply_markup=await _main_menu_markup(message))
            return
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return
    await message.answer('Неизвестное действие.', reply_markup=await _main_menu_markup(message))
