from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.handlers.common import (
    company_service,
    ensure_context,
    format_company_card,
    format_member_card,
    format_project_card,
    main_menu_markup,
    main_menu_markup_for_user,
    project_service,
    view_service,
)
from app.services.companies import CompanyAccessError
from app.state.pending_actions import set_pending_action
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
    build_confirm_keyboard,
    build_employee_card_keyboard,
    build_employees_keyboard,
    build_employees_menu_keyboard,
    build_project_card_keyboard,
    build_projects_keyboard,
    build_projects_menu_keyboard,
)
from app.ui.main_menu import MENU_BUTTONS

router = Router()
NL = chr(10)


@router.message(Command('invite'))
async def invite_command(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        return
    role = (command.args or 'employee').strip()
    if role != 'employee':
        await message.answer('Использование: /invite employee', reply_markup=await main_menu_markup(message))
        return
    try:
        code = await company_service.create_invite(message.from_user, 'employee')
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await main_menu_markup(message))
        return
    await message.answer(f'Invite-код для сотрудника: {code}', reply_markup=await main_menu_markup(message))


@router.message(F.text == MENU_BUTTONS['projects'])
async def projects_menu_entry(message: Message) -> None:
    if message.from_user is None:
        return
    context = await ensure_context(message)
    if context is None or not context.can_manage_company:
        await message.answer('Раздел проектов доступен только manager.', reply_markup=await main_menu_markup(message))
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
    await set_pending_action(callback.from_user.id, 'create_project')
    await callback.answer()
    await callback.message.answer('Отправь название нового проекта.', reply_markup=await main_menu_markup_for_user(callback.from_user))


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
    await callback.message.answer(format_project_card(project), reply_markup=build_project_card_keyboard(project.id, archived=project.is_archived))


@router.callback_query(F.data.startswith(MANAGER_PROJECT_RENAME_PREFIX))
async def project_rename_prompt(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    project_id = int(callback.data.removeprefix(MANAGER_PROJECT_RENAME_PREFIX))
    await set_pending_action(callback.from_user.id, 'rename_project', {'project_id': project_id})
    await callback.answer()
    await callback.message.answer('Отправь новое название проекта.', reply_markup=await main_menu_markup_for_user(callback.from_user))


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
    context = await ensure_context(message)
    if context is None or not context.can_manage_company:
        await message.answer('Раздел сотрудников доступен только manager.', reply_markup=await main_menu_markup(message))
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
    await callback.message.answer(format_member_card(member), reply_markup=build_employee_card_keyboard(member.user_id))


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


@router.message(F.text == MENU_BUTTONS['my_company'])
async def my_company_entry(message: Message) -> None:
    if message.from_user is None:
        return
    try:
        card = await view_service.get_my_company_card(message.from_user.id)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await main_menu_markup(message))
        return
    await message.answer(format_company_card(card), reply_markup=await main_menu_markup(message))


@router.message(F.text == MENU_BUTTONS['my_documents'])
async def my_documents_entry(message: Message) -> None:
    if message.from_user is None:
        return
    try:
        documents = await view_service.list_my_documents(message.from_user.id)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await main_menu_markup(message))
        return
    if not documents:
        await message.answer('У тебя пока нет документов.', reply_markup=await main_menu_markup(message))
        return
    lines = ['Мои документы:', '']
    for index, document in enumerate(documents, start=1):
        date_line = document.document_date.isoformat() if document.document_date else 'без даты'
        lines.append(f"{index}. {date_line} — {document.vendor or 'Без поставщика'} — {document.total_amount or 0} — {document.project_name}")
    await message.answer(NL.join(lines), reply_markup=await main_menu_markup(message))
