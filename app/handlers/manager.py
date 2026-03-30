from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.services.access import AccessContext

from app.handlers.common import (
    build_main_menu_markup_from_context,
    company_service,
    ensure_context,
    ensure_user_context,
    format_company_card,
    format_member_card,
    format_project_card,
    main_menu_markup,
    main_menu_markup_for_user,
    notify_membership_update,
    project_service,
    view_service,
)
from app.services.companies import CompanyAccessError
from app.services.document_storage import DocumentStorageService
from app.state.pending_actions import set_pending_action
from app.ui.company import (
    MANAGER_EMPLOYEES_ACTIVE_CALLBACK,
    MANAGER_EMPLOYEES_BLOCKED_CALLBACK,
    MANAGER_EMPLOYEES_LIST_CALLBACK,
    MANAGER_EMPLOYEES_MENU_CALLBACK,
    MANAGER_EMPLOYEE_INVITE_CALLBACK,
    MANAGER_EMPLOYEE_REMOVE_CONFIRM_PREFIX,
    MANAGER_EMPLOYEE_REMOVE_PREFIX,
    MANAGER_EMPLOYEE_UNBLOCK_CONFIRM_PREFIX,
    MANAGER_EMPLOYEE_UNBLOCK_PREFIX,
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
from app.ui.reports import REPORT_KIND_PROJECTS, build_report_documents_keyboard
from app.ui.my_documents import (
    MY_DOCUMENTS_FILTER_MENU_CALLBACK,
    MY_DOCUMENTS_ITEMS_PREFIX,
    MY_DOCUMENTS_LIST_CALLBACK,
    MY_DOCUMENTS_LIST_PREFIX,
    MY_DOCUMENTS_OPEN_PREFIX,
    MY_DOCUMENTS_PROJECTS_CALLBACK,
    MY_DOCUMENTS_SCOPE_ALL,
    MY_DOCUMENTS_SCOPE_MONTH,
    MY_DOCUMENTS_VIEW_PREFIX,
    build_my_document_card_keyboard,
    build_my_document_items_keyboard,
    build_my_documents_filter_keyboard,
    build_my_documents_keyboard,
    build_my_documents_projects_keyboard,
    parse_my_documents_list_scope,
    parse_my_documents_scoped_document,
)

router = Router()
NL = chr(10)
document_storage_service = DocumentStorageService()


@router.message(Command('invite'))
async def invite_command(
    message: Message,
    command: CommandObject,
    access_context: AccessContext | None = None,
) -> None:
    if message.from_user is None:
        return
    role = (command.args or 'employee').strip()
    if role != 'employee':
        await message.answer('Использование: /invite employee', reply_markup=await main_menu_markup(message, access_context))
        return
    try:
        code = await company_service.create_invite(message.from_user, 'employee')
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await main_menu_markup(message, access_context))
        return
    await message.answer('Invite-код для сотрудника:', reply_markup=await main_menu_markup(message, access_context))
    await message.answer(code)


@router.message(F.text == MENU_BUTTONS['projects'])
async def projects_menu_entry(message: Message, access_context: AccessContext | None = None) -> None:
    if message.from_user is None:
        return
    context = await ensure_context(message, access_context)
    if context is None or not context.can_manage_company:
        await message.answer(
            'Раздел проектов доступен только manager.',
            reply_markup=build_main_menu_markup_from_context(context) if context is not None else await main_menu_markup(message, access_context),
        )
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
async def project_create_callback(callback: CallbackQuery, access_context: AccessContext | None = None) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await set_pending_action(callback.from_user.id, 'create_project')
    await callback.answer()
    context = await ensure_user_context(callback.from_user, access_context)
    reply_markup = build_main_menu_markup_from_context(context) if context is not None else await main_menu_markup_for_user(callback.from_user, access_context)
    await callback.message.answer('Отправь название нового проекта.', reply_markup=reply_markup)


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
async def project_rename_prompt(callback: CallbackQuery, access_context: AccessContext | None = None) -> None:
    if callback.from_user is None or callback.message is None:
        return
    project_id = int(callback.data.removeprefix(MANAGER_PROJECT_RENAME_PREFIX))
    await set_pending_action(callback.from_user.id, 'rename_project', {'project_id': project_id})
    await callback.answer()
    context = await ensure_user_context(callback.from_user, access_context)
    reply_markup = build_main_menu_markup_from_context(context) if context is not None else await main_menu_markup_for_user(callback.from_user, access_context)
    await callback.message.answer('Отправь новое название проекта.', reply_markup=reply_markup)


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
    await callback.message.answer(
        'Документы проекта:',
        reply_markup=build_report_documents_keyboard(REPORT_KIND_PROJECTS, 'all_time', project_id, documents),
    )


@router.message(F.text == MENU_BUTTONS['employees'])
async def employees_menu_entry(message: Message, access_context: AccessContext | None = None) -> None:
    if message.from_user is None:
        return
    context = await ensure_context(message, access_context)
    if context is None or not context.can_manage_company:
        await message.answer(
            'Раздел сотрудников доступен только manager.',
            reply_markup=build_main_menu_markup_from_context(context) if context is not None else await main_menu_markup(message, access_context),
        )
        return
    await message.answer('Раздел сотрудников:', reply_markup=build_employees_menu_keyboard())


@router.callback_query(F.data == MANAGER_EMPLOYEES_MENU_CALLBACK)
async def employees_menu_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await callback.message.answer('Раздел сотрудников:', reply_markup=build_employees_menu_keyboard())


@router.callback_query(F.data == MANAGER_EMPLOYEES_LIST_CALLBACK)
@router.callback_query(F.data == MANAGER_EMPLOYEES_ACTIVE_CALLBACK)
async def employees_list_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    try:
        employees = await view_service.list_employees_for_manager(callback.from_user.id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()
    active_employees = [member for member in employees if not member.is_blocked]
    if not active_employees:
        await callback.message.answer('Активных сотрудников пока нет.', reply_markup=build_employees_menu_keyboard())
        return
    await callback.message.answer('Активные сотрудники:', reply_markup=build_employees_keyboard(active_employees, MANAGER_EMPLOYEES_MENU_CALLBACK))


@router.callback_query(F.data == MANAGER_EMPLOYEES_BLOCKED_CALLBACK)
async def employees_blocked_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    try:
        employees = await view_service.list_employees_for_manager(callback.from_user.id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    blocked_employees = [member for member in employees if member.is_blocked]
    await callback.answer()
    if not blocked_employees:
        await callback.message.answer('Заблокированных сотрудников пока нет.', reply_markup=build_employees_menu_keyboard())
        return
    await callback.message.answer('Заблокированные сотрудники:', reply_markup=build_employees_keyboard(blocked_employees, MANAGER_EMPLOYEES_MENU_CALLBACK))


@router.callback_query(F.data == MANAGER_EMPLOYEE_INVITE_CALLBACK)
async def employee_invite_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer('Генерирую invite...')
    try:
        code = await company_service.create_invite(callback.from_user, 'employee')
    except CompanyAccessError as exc:
        await callback.message.answer(str(exc), reply_markup=build_employees_menu_keyboard())
        return
    await callback.message.answer('Invite-код для сотрудника:')
    await callback.message.answer(code)


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
    back_callback = MANAGER_EMPLOYEES_BLOCKED_CALLBACK if member.is_blocked else MANAGER_EMPLOYEES_ACTIVE_CALLBACK
    await callback.message.answer(format_member_card(member), reply_markup=build_employee_card_keyboard(member.user_id, member.is_blocked, back_callback))


@router.callback_query(F.data.startswith(MANAGER_EMPLOYEE_REMOVE_PREFIX))
async def employee_remove_prompt(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    member_user_id = int(callback.data.removeprefix(MANAGER_EMPLOYEE_REMOVE_PREFIX))
    await callback.answer()
    await callback.message.answer('Подтвердить блокировку сотрудника?', reply_markup=build_confirm_keyboard(f'{MANAGER_EMPLOYEE_REMOVE_CONFIRM_PREFIX}{member_user_id}', f'{MANAGER_EMPLOYEE_VIEW_PREFIX}{member_user_id}'))


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
    await callback.answer('Сотрудник заблокирован.')
    await callback.message.answer(f'Сотрудник заблокирован: {member.full_name or member.username or member.telegram_user_id}.')
    await notify_membership_update(
        callback.bot,
        member.telegram_user_id,
        'Доступ к компании приостановлен. Обратитесь к руководителю.',
    )


@router.callback_query(F.data.startswith(MANAGER_EMPLOYEE_UNBLOCK_PREFIX))
async def employee_unblock_prompt(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    member_user_id = int(callback.data.removeprefix(MANAGER_EMPLOYEE_UNBLOCK_PREFIX))
    await callback.answer()
    await callback.message.answer('Подтвердить разблокировку сотрудника?', reply_markup=build_confirm_keyboard(f'{MANAGER_EMPLOYEE_UNBLOCK_CONFIRM_PREFIX}{member_user_id}', f'{MANAGER_EMPLOYEE_VIEW_PREFIX}{member_user_id}'))


@router.callback_query(F.data.startswith(MANAGER_EMPLOYEE_UNBLOCK_CONFIRM_PREFIX))
async def employee_unblock_confirm(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    member_user_id = int(callback.data.removeprefix(MANAGER_EMPLOYEE_UNBLOCK_CONFIRM_PREFIX))
    try:
        member = await company_service.restore_employee_access(callback.from_user.id, member_user_id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer('Сотрудник разблокирован.')
    await callback.message.answer(f'Сотрудник разблокирован: {member.full_name or member.username or member.telegram_user_id}.')
    await notify_membership_update(
        callback.bot,
        member.telegram_user_id,
        'Доступ к компании восстановлен.',
    )


@router.message(F.text == MENU_BUTTONS['my_company'])
async def my_company_entry(message: Message, access_context: AccessContext | None = None) -> None:
    if message.from_user is None:
        return
    try:
        card = await view_service.get_my_company_card(message.from_user.id)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await main_menu_markup(message, access_context))
        return
    await message.answer(format_company_card(card), reply_markup=await main_menu_markup(message, access_context))


async def _send_my_documents_filters(message: Message, *, edit: bool = False) -> None:
    if edit:
        await message.edit_text('Как показать документы?', reply_markup=build_my_documents_filter_keyboard())
    else:
        await message.answer('Как показать документы?', reply_markup=build_my_documents_filter_keyboard())


async def _send_my_documents_projects(message: Message, telegram_user_id: int, *, edit: bool = False) -> None:
    projects = await view_service.list_my_document_projects(telegram_user_id)
    if not projects:
        text = 'В активных проектах у тебя пока нет документов.'
        if edit:
            await message.edit_text(text, reply_markup=build_my_documents_filter_keyboard())
        else:
            await message.answer(text, reply_markup=build_my_documents_filter_keyboard())
        return
    if edit:
        await message.edit_text('Выбери активный проект:', reply_markup=build_my_documents_projects_keyboard(projects))
    else:
        await message.answer('Выбери активный проект:', reply_markup=build_my_documents_projects_keyboard(projects))


async def _send_my_documents_menu(
    message: Message,
    telegram_user_id: int,
    scope_token: str,
    *,
    edit: bool = False,
) -> None:
    period, project_id = _resolve_my_documents_scope(scope_token)
    documents = await view_service.list_my_documents(telegram_user_id, period=period, project_id=project_id)
    if not documents:
        text = _empty_my_documents_text(scope_token)
        if edit:
            await message.edit_text(text, reply_markup=build_my_documents_filter_keyboard())
        else:
            await message.answer(text, reply_markup=build_my_documents_filter_keyboard())
        return
    title = _my_documents_title(scope_token, documents[0].project_name if project_id is not None else None)
    if edit:
        await message.edit_text(title, reply_markup=build_my_documents_keyboard(documents, scope_token))
    else:
        await message.answer(title, reply_markup=build_my_documents_keyboard(documents, scope_token))


def _resolve_my_documents_scope(scope_token: str) -> tuple[str, int | None]:
    if scope_token == MY_DOCUMENTS_SCOPE_MONTH:
        return 'month', None
    if scope_token == MY_DOCUMENTS_SCOPE_ALL:
        return 'all_time', None
    if scope_token.startswith('project_'):
        return 'all_time', int(scope_token.removeprefix('project_'))
    raise CompanyAccessError('Неизвестный фильтр документов.')


def _my_documents_title(scope_token: str, project_name: str | None = None) -> str:
    if scope_token == MY_DOCUMENTS_SCOPE_MONTH:
        return 'Мои документы за месяц:'
    if scope_token == MY_DOCUMENTS_SCOPE_ALL:
        return 'Все мои документы:'
    if scope_token.startswith('project_'):
        return f'Мои документы по проекту: {project_name or "Проект"}'
    return 'Мои документы:'


def _empty_my_documents_text(scope_token: str) -> str:
    if scope_token == MY_DOCUMENTS_SCOPE_MONTH:
        return 'За этот месяц у тебя пока нет документов.'
    if scope_token == MY_DOCUMENTS_SCOPE_ALL:
        return 'У тебя пока нет документов.'
    if scope_token.startswith('project_'):
        return 'В этом активном проекте у тебя пока нет документов.'
    return 'У тебя пока нет документов.'


@router.message(F.text == MENU_BUTTONS['my_documents'])
async def my_documents_entry(message: Message, access_context: AccessContext | None = None) -> None:
    if message.from_user is None:
        return
    try:
        await _send_my_documents_filters(message)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=await main_menu_markup(message, access_context))


@router.callback_query(F.data == MY_DOCUMENTS_FILTER_MENU_CALLBACK)
@router.callback_query(F.data == MY_DOCUMENTS_LIST_CALLBACK)
async def my_documents_filters_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await _send_my_documents_filters(callback.message, edit=True)


@router.callback_query(F.data == MY_DOCUMENTS_PROJECTS_CALLBACK)
async def my_documents_projects_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    try:
        await callback.answer()
        await _send_my_documents_projects(callback.message, callback.from_user.id, edit=True)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)


@router.callback_query(F.data.startswith(MY_DOCUMENTS_LIST_PREFIX))
async def my_documents_list_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    try:
        scope_token = parse_my_documents_list_scope(callback.data)
        await callback.answer()
        await _send_my_documents_menu(callback.message, callback.from_user.id, scope_token, edit=True)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)


@router.callback_query(F.data.startswith(MY_DOCUMENTS_VIEW_PREFIX))
async def my_document_view_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    try:
        scope_token, document_id = parse_my_documents_scoped_document(callback.data, MY_DOCUMENTS_VIEW_PREFIX)
        document, items = await view_service.get_my_document_detail(callback.from_user.id, document_id)
    except (ValueError, CompanyAccessError) as exc:
        message = str(exc) if isinstance(exc, CompanyAccessError) else 'Документ не найден.'
        await callback.answer(message, show_alert=True)
        return
    await callback.answer()
    first_item = items[0].name if items else (document.first_item_name or 'Позиции не найдены')
    vendor = document.vendor or document.vendor_inn or 'Контрагент не указан'
    number = document.document_number or 'без номера'
    date_line = document.document_date.strftime('%d.%m.%Y') if document.document_date else 'без даты'
    uploaded_at = document.created_at.strftime('%d.%m.%Y %H:%M') if document.created_at else '—'
    lines = [
        'Документ',
        '',
        f'Проект: {document.project_name}',
        f'Контрагент: {vendor}',
        f'Дата документа: {date_line}',
        f'Номер: {number}',
        f'Сумма: {document.total_amount or 0}',
        f'Дата ввода: {uploaded_at}',
        f'Первая позиция: {first_item}',
    ]
    await callback.message.edit_text(NL.join(lines), reply_markup=build_my_document_card_keyboard(document.id, scope_token))


@router.callback_query(F.data.startswith(MY_DOCUMENTS_OPEN_PREFIX))
async def my_document_open_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    logger.info(
        'My-documents open requested: user_id=%s callback_data=%s',
        callback.from_user.id,
        callback.data,
    )
    try:
        _, document_id = parse_my_documents_scoped_document(callback.data, MY_DOCUMENTS_OPEN_PREFIX)
        source = await view_service.get_my_document_source(callback.from_user.id, document_id)
    except (ValueError, CompanyAccessError) as exc:
        message = str(exc) if isinstance(exc, CompanyAccessError) else 'Документ не найден.'
        logger.warning(
            'My-documents open rejected: user_id=%s callback_data=%s error=%s',
            callback.from_user.id,
            callback.data,
            exc,
        )
        await callback.answer(message, show_alert=True)
        return
    file_path = document_storage_service.resolve_path(source.storage_key)
    if not file_path.exists():
        logger.warning('Stored document file missing in my-documents open: document_id=%s storage_key=%s', document_id, source.storage_key)
        await callback.answer('Файл документа не найден в storage.', show_alert=True)
        return
    await callback.answer()
    caption = 'Исходный файл документа'
    filename = source.original_filename or file_path.name
    file_size = None
    try:
        file_size = file_path.stat().st_size
    except OSError:
        pass

    logger.info(
        'My-documents open resolved: document_id=%s storage_key=%s mime_type=%s file_ext=%s path=%s size=%s',
        document_id,
        source.storage_key,
        source.mime_type,
        source.file_ext,
        file_path,
        file_size,
    )
    try:
        await callback.message.answer_document(FSInputFile(file_path, filename=filename), caption=caption)
    except Exception:  # noqa: BLE001
        logger.exception(
            'My-documents open send failed: document_id=%s storage_key=%s filename=%s path=%s',
            document_id,
            source.storage_key,
            filename,
            file_path,
        )
        raise
    logger.info(
        'My-documents open sent as document: document_id=%s storage_key=%s filename=%s',
        document_id,
        source.storage_key,
        filename,
    )


@router.callback_query(F.data.startswith(MY_DOCUMENTS_ITEMS_PREFIX))
async def my_document_items_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    try:
        scope_token, document_id = parse_my_documents_scoped_document(callback.data, MY_DOCUMENTS_ITEMS_PREFIX)
        document, items = await view_service.get_my_document_detail(callback.from_user.id, document_id)
    except (ValueError, CompanyAccessError) as exc:
        message = str(exc) if isinstance(exc, CompanyAccessError) else 'Документ не найден.'
        await callback.answer(message, show_alert=True)
        return
    await callback.answer()
    from app.services.report_formatters import format_report_document_items
    await callback.message.edit_text(
        format_report_document_items('Состав документа', 'all_time', document, items),
        reply_markup=build_my_document_items_keyboard(document.id, scope_token),
        parse_mode='HTML',
    )
