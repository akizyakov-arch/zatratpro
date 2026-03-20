from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.handlers.common import (
    company_service,
    ensure_context,
    ensure_user_context,
    main_menu_markup_for_user,
    build_main_menu_markup_from_context,
    format_company_card,
    format_user_card,
    main_menu_markup,
    notify_membership_update,
    person_name,
    view_service,
)
from app.services.companies import CompanyAccessError
from app.state.pending_actions import set_pending_action
from app.ui.company import (
    OWNER_COMPANIES_ACTIVE_CALLBACK,
    OWNER_COMPANIES_ARCHIVED_CALLBACK,
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
    build_owner_companies_menu_keyboard,
    build_company_members_keyboard,
    build_confirm_keyboard,
    build_owner_user_card_keyboard,
    build_owner_user_company_select_keyboard,
    build_owner_users_keyboard,
)
from app.ui.main_menu import MENU_BUTTONS

router = Router()
NL = chr(10)


@router.message(Command('create_company'))
async def create_company_command(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        return
    name = (command.args or '').strip()
    if not name:
        await message.answer('Использование: /create_company Название компании', reply_markup=await main_menu_markup(message))
        return
    try:
        company = await company_service.create_company(message.from_user, name)
        invite_code = await company_service.create_initial_manager_invite(message.from_user, company.id)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await main_menu_markup(message))
        return
    await message.answer(f'Компания создана: {company.name}.', reply_markup=await main_menu_markup(message))
    await message.answer('Invite-код для первого manager:')
    await message.answer(invite_code)


@router.message(F.text == MENU_BUTTONS['companies'])
async def companies_entry(message: Message) -> None:
    if message.from_user is None:
        return
    context = await ensure_context(message)
    if context is None or context.platform_role != 'owner':
        await message.answer('Раздел доступен только owner.', reply_markup=await main_menu_markup(message))
        return
    await message.answer('Компании:', reply_markup=build_owner_companies_menu_keyboard())


@router.message(F.text == MENU_BUTTONS['users'])
async def users_entry(message: Message) -> None:
    if message.from_user is None:
        return
    try:
        users = await view_service.list_users(message.from_user.id)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await main_menu_markup(message))
        return
    if not users:
        await message.answer('Пользователей пока нет.', reply_markup=await main_menu_markup(message))
        return
    await message.answer('Пользователи:', reply_markup=build_owner_users_keyboard(users))


@router.message(F.text == MENU_BUTTONS['system_status'])
async def system_status_entry(message: Message) -> None:
    if message.from_user is None:
        return
    try:
        stats = await view_service.get_system_stats(message.from_user.id)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await main_menu_markup(message))
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
    await message.answer(text, reply_markup=await main_menu_markup(message))


@router.message(F.text == MENU_BUTTONS['create_company'])
async def create_company_button(message: Message) -> None:
    if message.from_user is None:
        return
    context = await ensure_context(message)
    if context is None or context.platform_role != 'owner':
        await message.answer('Создавать компании может только owner.', reply_markup=await main_menu_markup(message))
        return
    await set_pending_action(message.from_user.id, 'create_company')
    await message.answer(
        f'{person_name(message.from_user)}, отправь название новой компании.',
        reply_markup=build_main_menu_markup_from_context(context),
    )


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
    await callback.message.answer(format_user_card(user), reply_markup=build_owner_user_card_keyboard(user.user_id, user.has_company))


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
    await callback.message.answer(f'Пользователь привязан к компании как {member.role}.', reply_markup=build_owner_user_card_keyboard(user.user_id, user.has_company))
    await callback.message.answer(format_user_card(user), reply_markup=build_owner_user_card_keyboard(user.user_id, user.has_company))
    role_label = 'руководитель' if member.role == 'manager' else 'сотрудник'
    company_name = user.company_name or 'компания'
    await notify_membership_update(
        callback.bot,
        member.telegram_user_id,
        f'Тебя подключили к компании "{company_name}". Роль: {role_label}.',
    )


@router.callback_query(F.data.startswith(OWNER_USER_REMOVE_PREFIX))
async def user_remove_prompt(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    user_id = int(callback.data.removeprefix(OWNER_USER_REMOVE_PREFIX))
    await callback.answer()
    await callback.message.answer('Подтвердить исключение пользователя из компании?', reply_markup=build_confirm_keyboard(f'{OWNER_USER_REMOVE_CONFIRM_PREFIX}{user_id}', f'{OWNER_USER_VIEW_PREFIX}{user_id}'))


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
    await callback.message.answer(format_user_card(user), reply_markup=build_owner_user_card_keyboard(user.user_id, user.has_company))
    await notify_membership_update(
        callback.bot,
        member.telegram_user_id,
        'Тебя исключили из компании. Доступ к рабочим разделам отключен.',
    )


@router.callback_query(F.data == OWNER_COMPANIES_CALLBACK)
async def companies_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await callback.message.answer('Компании:', reply_markup=build_owner_companies_menu_keyboard())


@router.callback_query(F.data == OWNER_COMPANIES_ACTIVE_CALLBACK)
async def active_companies_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    try:
        companies = [company for company in await view_service.list_companies(callback.from_user.id) if company.is_active]
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    if not companies:
        await callback.message.answer('Активных компаний пока нет.', reply_markup=build_owner_companies_menu_keyboard())
        return
    await callback.message.answer(
        'Активные компании:',
        reply_markup=build_companies_keyboard(companies, back_callback=OWNER_COMPANIES_CALLBACK),
    )


@router.callback_query(F.data == OWNER_COMPANIES_ARCHIVED_CALLBACK)
async def archived_companies_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    try:
        companies = [company for company in await view_service.list_companies(callback.from_user.id) if not company.is_active]
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    if not companies:
        await callback.message.answer('Архивированных компаний пока нет.', reply_markup=build_owner_companies_menu_keyboard())
        return
    await callback.message.answer(
        'Архивированные компании:',
        reply_markup=build_companies_keyboard(companies, back_callback=OWNER_COMPANIES_CALLBACK),
    )


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
    await callback.message.answer(format_company_card(card), reply_markup=build_company_actions_keyboard(card.id, not card.manager_assigned, card.invite is not None, not card.is_active))


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
    context = await ensure_user_context(callback.from_user)
    reply_markup = build_main_menu_markup_from_context(context) if context is not None else await main_menu_markup_for_user(callback.from_user)
    await callback.message.answer('Invite для manager:', reply_markup=reply_markup)
    await callback.message.answer(code)


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
    await callback.message.answer(f'Текущий invite. Действует до: {expires}')
    await callback.message.answer(card.invite.code)


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
