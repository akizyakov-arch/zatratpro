from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Message, ReplyKeyboardMarkup

from app.adapters.telegram.companies import CompanyAccessError, CompanyService
from app.adapters.telegram.documents import DocumentService
from app.adapters.telegram.projects import ProjectService
from app.services.report_formatters import (
    format_duplicate_report,
    format_project_report,
    format_report_document_items,
    format_report_documents,
    report_period_label,
)
from app.adapters.telegram.views import ViewService
from app.handlers.money_reports import send_money_report
from app.services.advances import AdvanceError
from app.state.pending_actions import pop_pending_action, set_pending_action
from app.ui.company import NAV_MAIN_CALLBACK
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
    MANAGER_REPORTS_EMPLOYEE_PERIOD_PREFIX,
    MANAGER_REPORTS_EMPLOYEE_SELECT_PREFIX,
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
    build_employee_report_period_keyboard,
    build_employee_report_selector_keyboard,
    build_project_report_keyboard,
    build_report_document_back_keyboard,
    build_report_documents_keyboard,
    build_report_period_keyboard,
    build_reports_menu_keyboard,
)


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


async def _main_menu_markup_for_user(user, *, allow_web_app=False) -> ReplyKeyboardMarkup:
    if user is None:
        return build_main_menu_keyboard(has_company=False)
    await company_service.ensure_platform_user(user)
    context = await company_service.get_user_context(user.id)
    return build_main_menu_keyboard(
        menu_kind=context.menu_kind,
        has_company=context.has_company,
        can_view_reports=context.can_view_reports,
        allow_web_app=allow_web_app,
    )


async def _main_menu_markup(message: Message) -> ReplyKeyboardMarkup:
    return await _main_menu_markup_for_user(message.from_user, allow_web_app=getattr(getattr(message, 'chat', None), 'type', None) == 'private')


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
    try:
        context = await _ensure_context(message)
    except (CompanyAccessError, AdvanceError) as exc:
        await message.answer(str(exc))
        return
    from app.handlers.telegram_identity import actor
    from app.services.workspace_flow import WorkspaceFlow
    if message.from_user is not None and getattr(getattr(message, 'chat', None), 'type', 'private') == 'private':
        await WorkspaceFlow().cancel(await actor(message.from_user))
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
    except (CompanyAccessError, AdvanceError) as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return
    await message.answer(f'Доступ к компании "{company.name}" подключен.', reply_markup=await _main_menu_markup(message))


@router.message(F.text == MENU_BUTTONS['join_company'])
async def join_company_button(message: Message) -> None:
    if message.from_user is None:
        return
    await set_pending_action(message.from_user.id, 'join_company')
    await message.answer(f'{_person_name(message.from_user)}, отправь invite-код следующим сообщением.', reply_markup=await _main_menu_markup(message))


@router.message(F.text == MENU_BUTTONS['upload_document'])
async def upload_document_entry(message: Message) -> None:
    if not await _require_company_access(message):
        return
    await message.answer(f'{_person_name(message.from_user)}, отправь фото или PDF документа (до 10 МБ, 10 страниц). Для PDF укажи в подписи страницы одного документа: 1-3 или «все». После распознавания я предложу проекты кнопками.', reply_markup=await _main_menu_markup(message))


@router.message(F.text == MENU_BUTTONS['reports'])
async def reports_menu_entry(message: Message) -> None:
    if message.from_user is None:
        return
    context = await _ensure_context(message)
    if context is None or not context.can_view_reports:
        await message.answer('Раздел отчетов доступен только manager.', reply_markup=await _main_menu_markup(message))
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
        await send_money_report(callback.message, callback.from_user.id, REPORT_PERIOD_ALL)
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
    if report_kind == REPORT_KIND_EMPLOYEES:
        rows = await view_service.list_report_employees(callback.from_user.id, REPORT_PERIOD_ALL)
        await callback.answer()
        if not rows:
            await callback.message.answer('Сотрудников с затратами пока нет.', reply_markup=build_reports_menu_keyboard())
            return
        await callback.message.answer('Выбери сотрудника.', reply_markup=build_employee_report_selector_keyboard(rows))
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
        if report_kind == 'money':
            await callback.answer()
            await send_money_report(callback.message, callback.from_user.id, period)
            return
        if report_kind == REPORT_KIND_PROJECTS:
            summary = await view_service.get_manager_report_summary(callback.from_user.id, period)
            rows = await view_service.list_report_projects(callback.from_user.id, period)
            await callback.answer()
            await callback.message.answer(format_project_report(summary, rows), reply_markup=build_project_report_keyboard(period, rows), parse_mode='HTML')
            await send_money_report(callback.message, callback.from_user.id, period)
            return
        if report_kind == REPORT_KIND_DUPLICATES:
            rows = await view_service.list_duplicate_report_rows(callback.from_user.id, period)
            duplicate_summary = await view_service.get_duplicate_report_summary(callback.from_user.id, period)
            await callback.answer()
            await callback.message.answer(format_duplicate_report(duplicate_summary, rows), reply_markup=build_duplicate_report_keyboard(period, rows), parse_mode='HTML')
            return
        if report_kind == REPORT_KIND_EXPORT:
            from app.services.reporting import ReportService
            from app.handlers.telegram_identity import actor
            from app.services.report_periods import report_period_start
            from datetime import datetime, timezone
            filename, payload_bytes = await ReportService().export(await actor(callback.from_user), report_period_start(period), datetime.now(timezone.utc))
            await callback.answer()
            await callback.message.answer_document(BufferedInputFile(payload_bytes, filename=filename), caption=f'Выгрузка отчетов за период: {report_period_label(period)}')
            return
    except (CompanyAccessError, AdvanceError, ValueError) as exc:
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

    await send_money_report(callback.message, callback.from_user.id, period, project_id=project.id)


@router.callback_query(F.data.startswith(MANAGER_REPORTS_EMPLOYEE_SELECT_PREFIX))
async def report_employee_select_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    user_id_text = callback.data.removeprefix(MANAGER_REPORTS_EMPLOYEE_SELECT_PREFIX)
    try:
        user_id = int(user_id_text)
        member = await view_service.get_employee_card(callback.from_user.id, user_id)
    except (ValueError, CompanyAccessError) as exc:
        message = str(exc) if isinstance(exc, CompanyAccessError) else 'Некорректные данные сотрудника.'
        await callback.answer(message, show_alert=True)
        return
    employee_name = member.full_name or (f'@{member.username}' if member.username else str(member.telegram_id))
    title_prefix = 'Руководитель' if member.role == 'manager' else 'Сотрудник'
    await callback.answer()
    await callback.message.answer(f'Выбери период для {title_prefix.lower()}: {employee_name}.', reply_markup=build_employee_report_period_keyboard(member.user_id))


@router.callback_query(F.data.startswith(MANAGER_REPORTS_EMPLOYEE_PERIOD_PREFIX))
async def report_employee_period_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    payload = callback.data.removeprefix(MANAGER_REPORTS_EMPLOYEE_PERIOD_PREFIX)
    try:
        user_id_text, period = payload.split(':', 1)
        user_id = int(user_id_text)
        member, documents = await view_service.get_employee_report_detail(callback.from_user.id, period, user_id)
    except (ValueError, CompanyAccessError) as exc:
        message = str(exc) if isinstance(exc, CompanyAccessError) else 'Некорректные данные сотрудника.'
        await callback.answer(message, show_alert=True)
        return
    employee_name = member.full_name or (f'@{member.username}' if member.username else str(member.telegram_id))
    title_prefix = 'Руководитель' if member.role == 'manager' else 'Сотрудник'
    await callback.answer()
    await callback.message.answer(
        format_report_documents(f'{title_prefix}: {employee_name}', period, documents),
        reply_markup=build_report_documents_keyboard(REPORT_KIND_EMPLOYEES, period, member.user_id, documents),
        parse_mode='HTML',
    )

    await send_money_report(callback.message, callback.from_user.id, period, employee_id=member.user_id)


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


@router.message(F.text == MENU_BUTTONS['my_documents'])
async def my_documents_entry(message: Message) -> None:
    if message.from_user is None:
        return
    try:
        documents = await view_service.list_my_documents(message.from_user.id)
    except (CompanyAccessError, AdvanceError) as exc:
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
        await message.answer('Поддерживаются кнопки главного меню, /start, /help, /join и фото/PDF документов.', reply_markup=await _main_menu_markup(message))
        return
    from app.handlers.documents import handle_project_name
    if await handle_project_name(message):
        return
    pending_action = await pop_pending_action(message.from_user.id)
    if pending_action is None:
        await message.answer('Используй кнопки главного меню или отправь фото/PDF документа.', reply_markup=await _main_menu_markup(message))
        return
    text_value = message.text.strip()
    try:
        if pending_action.action == 'join_company':
            await join_company(message, text_value)
            return
    except (CompanyAccessError, AdvanceError) as exc:
        await message.answer(str(exc), reply_markup=await _main_menu_markup(message))
        return
    await message.answer('Неизвестное действие.', reply_markup=await _main_menu_markup(message))
