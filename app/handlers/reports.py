import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.services.access import AccessContext

from app.handlers.common import build_main_menu_markup_from_context, document_service, ensure_context, format_duplicate_card, main_menu_markup, view_service
from app.services.companies import CompanyAccessError
from app.services.document_exports import DocumentExportService
from app.services.document_storage import DocumentStorageService
from app.services.report_exports import ManagerReportExportService
from app.services.temp_files import safe_unlink
from app.state.pending_actions import set_pending_action
from app.services.report_formatters import (
    format_duplicate_report,
    format_project_report,
    format_report_document_card,
    format_report_document_items,
    format_report_documents,
    format_items_only,
)
from app.ui.main_menu import MENU_BUTTONS
from app.ui.reports import (
    MANAGER_REPORTS_ACCOUNTANT_EXPORT_CALLBACK,
    MANAGER_REPORTS_ACCOUNTANT_EXPORT_CONFIRM_CALLBACK,
    MANAGER_REPORTS_ACCOUNTANT_EXPORT_PERIOD_PREFIX,
    MANAGER_REPORTS_ACCOUNTANT_EXPORT_YEAR_CURRENT_CALLBACK,
    MANAGER_REPORTS_ACCOUNTANT_EXPORT_YEAR_CUSTOM_CALLBACK,
    MANAGER_REPORTS_DOCUMENT_DETAIL_PREFIX,
    MANAGER_REPORTS_DOCUMENT_OPEN_PREFIX,
    MANAGER_REPORTS_DOCUMENT_ITEMS_PREFIX,
    MANAGER_REPORTS_DUPLICATE_DELETE_CONFIRM_PREFIX,
    MANAGER_REPORTS_DUPLICATE_DELETE_PREFIX,
    MANAGER_REPORTS_DUPLICATE_DELETE_SOURCE_CONFIRM_PREFIX,
    MANAGER_REPORTS_DUPLICATE_OPEN_PREFIX,
    MANAGER_REPORTS_DUPLICATE_OPEN_SOURCE_PREFIX,
    MANAGER_REPORTS_DUPLICATE_DELETE_SOURCE_PREFIX,
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
    build_accountant_export_keyboard,
    build_accountant_export_year_keyboard,
    build_duplicate_card_keyboard,
    build_duplicate_delete_confirm_keyboard,
    build_duplicate_delete_source_confirm_keyboard,
    build_duplicate_report_keyboard,
    build_employee_report_period_keyboard,
    build_employee_report_selector_keyboard,
    build_project_report_keyboard,
    build_report_document_card_keyboard,
    build_report_document_items_back_keyboard,
    build_report_documents_keyboard,
    build_report_period_keyboard,
    build_reports_menu_keyboard,
)

router = Router()
logger = logging.getLogger(__name__)
NL = '\n'
document_storage_service = DocumentStorageService()
document_export_service = DocumentExportService(document_storage_service)
manager_report_export_service = ManagerReportExportService()


async def _send_duplicate_report(message, period: str, summary, rows) -> None:
    await message.answer(
        format_duplicate_report(summary, rows),
        reply_markup=build_duplicate_report_keyboard(period, rows),
        parse_mode='HTML',
    )


async def _send_accountant_export(message: Message, telegram_user_id: int, *, period: str | None = None, custom_year: int | None = None) -> None:
    archive_path = None
    try:
        archive_path, filename, document_count, period_label = await document_export_service.build_accountant_archive_for_manager(
            telegram_user_id,
            period=period,
            custom_year=custom_year,
        )
        await message.answer_document(
            FSInputFile(archive_path, filename=filename),
            caption=f'Архив чеков готов. Период: {period_label}. Документов: {document_count}.',
        )
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=build_reports_menu_keyboard())
    except Exception as exc:  # noqa: BLE001
        logger.exception('Accountant export build failed')
        await message.answer(f'Не удалось собрать архив чеков: {exc}', reply_markup=build_reports_menu_keyboard())
    finally:
        if archive_path is not None:
            safe_unlink(archive_path)


@router.message(F.text == MENU_BUTTONS['reports'])
async def reports_menu_entry(message: Message, access_context: AccessContext | None = None) -> None:
    if message.from_user is None:
        return
    context = await ensure_context(message, access_context)
    if context is None or not context.can_view_reports:
        await message.answer(
            'Раздел отчетов доступен только manager.',
            reply_markup=build_main_menu_markup_from_context(context) if context is not None else await main_menu_markup(message, access_context),
        )
        return
    await message.answer('Раздел отчетов:', reply_markup=build_reports_menu_keyboard())


@router.callback_query(F.data == MANAGER_REPORTS_MENU_CALLBACK)
async def reports_menu_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await callback.message.edit_text('Раздел отчетов:', reply_markup=build_reports_menu_keyboard())


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
        await callback.answer()
        summary = await view_service.get_manager_report_summary(callback.from_user.id, REPORT_PERIOD_ALL)
        rows = await view_service.list_report_projects(callback.from_user.id, REPORT_PERIOD_ALL)
        await callback.message.answer(
            format_project_report(summary, rows),
            reply_markup=build_project_report_keyboard(REPORT_PERIOD_ALL, rows),
            parse_mode='HTML',
        )
        return
    if report_kind == REPORT_KIND_DUPLICATES:
        await callback.answer()
        rows = await view_service.list_duplicate_report_rows(callback.from_user.id, REPORT_PERIOD_ALL)
        summary = await view_service.get_duplicate_report_summary(callback.from_user.id, REPORT_PERIOD_ALL)
        await _send_duplicate_report(callback.message, REPORT_PERIOD_ALL, summary, rows)
        return
    if report_kind == REPORT_KIND_EMPLOYEES:
        await callback.answer()
        rows = await view_service.list_report_employees(callback.from_user.id, REPORT_PERIOD_ALL)
        if not rows:
            await callback.message.answer('Сотрудников с затратами пока нет.', reply_markup=build_reports_menu_keyboard())
            return
        await callback.message.answer('Выбери сотрудника.', reply_markup=build_employee_report_selector_keyboard(rows))
        return
    await callback.answer()
    await callback.message.edit_text('Выбери период отчета.', reply_markup=build_report_period_keyboard(report_kind))


@router.callback_query(F.data == MANAGER_REPORTS_ACCOUNTANT_EXPORT_CALLBACK)
async def accountant_export_prompt_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await callback.message.edit_text(
        'Выбери период выгрузки для бухгалтера.',
        reply_markup=build_accountant_export_keyboard(),
    )


@router.callback_query(F.data.startswith(MANAGER_REPORTS_ACCOUNTANT_EXPORT_PERIOD_PREFIX))
async def accountant_export_period_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    period = callback.data.removeprefix(MANAGER_REPORTS_ACCOUNTANT_EXPORT_PERIOD_PREFIX)
    if period == 'year':
        await callback.answer()
        await callback.message.edit_text(
            'Выбери вариант выгрузки за год.',
            reply_markup=build_accountant_export_year_keyboard(datetime.now().year),
        )
        return
    if period not in {'week', 'month', 'quarter'}:
        await callback.answer('Некорректный период.', show_alert=True)
        return
    await callback.answer('Собираю архив...')
    await _send_accountant_export(callback.message, callback.from_user.id, period=period)


@router.callback_query(F.data == MANAGER_REPORTS_ACCOUNTANT_EXPORT_YEAR_CURRENT_CALLBACK)
async def accountant_export_current_year_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer('Собираю архив...')
    await _send_accountant_export(callback.message, callback.from_user.id, period='year')


@router.callback_query(F.data == MANAGER_REPORTS_ACCOUNTANT_EXPORT_YEAR_CUSTOM_CALLBACK)
async def accountant_export_custom_year_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await set_pending_action(callback.from_user.id, 'accountant_export_custom_year')
    await callback.answer()
    await callback.message.answer('Введи год вручную, например 2024.')


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
        await callback.message.edit_text('Выбери период отчета.', reply_markup=build_report_period_keyboard(report_kind))
        return
    try:
        if report_kind == REPORT_KIND_PROJECTS:
            await callback.answer()
            summary = await view_service.get_manager_report_summary(callback.from_user.id, period)
            rows = await view_service.list_report_projects(callback.from_user.id, period)
            await callback.message.answer(format_project_report(summary, rows), reply_markup=build_project_report_keyboard(period, rows), parse_mode='HTML')
            return
        if report_kind == REPORT_KIND_DUPLICATES:
            await callback.answer()
            rows = await view_service.list_duplicate_report_rows(callback.from_user.id, period)
            duplicate_summary = await view_service.get_duplicate_report_summary(callback.from_user.id, period)
            await _send_duplicate_report(callback.message, period, duplicate_summary, rows)
            return
        if report_kind == REPORT_KIND_EXPORT:
            export_path = None
            logger.info('Manager Excel export started: user_id=%s period=%s', callback.from_user.id, period)
            await callback.answer('Собираю Excel...')
            await callback.message.edit_text('Собираю Excel-отчет. Это может занять до минуты.', reply_markup=build_reports_menu_keyboard())
            try:
                export_result = await manager_report_export_service.build_for_manager(callback.from_user.id, period=period)
                export_path = export_result.file_path
                logger.info('Manager Excel export ready: user_id=%s period=%s path=%s', callback.from_user.id, period, export_path.name)
                await callback.message.answer_document(
                    FSInputFile(export_path, filename=export_result.filename),
                    caption=export_result.caption,
                )
                await callback.message.edit_text('Excel-отчет сформирован.', reply_markup=build_reports_menu_keyboard())
            except CompanyAccessError as exc:
                logger.warning('Manager Excel export access error: user_id=%s period=%s error=%s', callback.from_user.id, period, exc)
                await callback.message.edit_text(str(exc), reply_markup=build_reports_menu_keyboard())
            except Exception as exc:  # noqa: BLE001
                logger.exception('Manager Excel export build failed')
                await callback.message.edit_text(f'Не удалось собрать Excel-отчет: {exc}', reply_markup=build_reports_menu_keyboard())
            finally:
                if export_path is not None:
                    safe_unlink(export_path)
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
    await callback.message.edit_text(
        format_report_documents(f'Проект: {project.name}', period, documents),
        reply_markup=build_report_documents_keyboard(REPORT_KIND_PROJECTS, period, project.id, documents),
        parse_mode='HTML',
    )


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
    await callback.answer()
    employee_name = member.full_name or (f'@{member.username}' if member.username else str(member.telegram_id))
    title_prefix = 'Руководитель' if member.role == 'manager' else 'Сотрудник'
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
    await callback.answer()
    employee_name = member.full_name or (f'@{member.username}' if member.username else str(member.telegram_id))
    title_prefix = 'Руководитель' if member.role == 'manager' else 'Сотрудник'
    await callback.message.edit_text(
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
        duplicate_document, duplicate_items = await view_service.get_report_document_items(callback.from_user.id, period, duplicate_id)
        source_document = None
        source_items = []
        if row.duplicate_of_document_id is not None:
            source_document, source_items = await view_service.get_report_document_items(callback.from_user.id, period, row.duplicate_of_document_id)
    except (ValueError, CompanyAccessError) as exc:
        message = str(exc) if isinstance(exc, CompanyAccessError) else 'Некорректные данные дубля.'
        await callback.answer(message, show_alert=True)
        return
    await callback.answer()
    lines = [_format_duplicate_document_card('Документ-дубликат', duplicate_document, duplicate_items)]
    if source_document is not None:
        lines.extend(['', _format_duplicate_document_card('Исходный документ', source_document, source_items)])
    await callback.message.answer(
        NL.join(lines),
        reply_markup=build_duplicate_card_keyboard(period, duplicate_id, row.duplicate_of_document_id),
        parse_mode='HTML',
    )


async def _send_report_document_source(callback: CallbackQuery, document_id: int) -> None:
    if callback.from_user is None or callback.message is None:
        return
    try:
        source = await view_service.get_manager_document_source(callback.from_user.id, document_id)
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    file_path = document_storage_service.resolve_path(source.storage_key)
    if not file_path.exists():
        await callback.answer('Файл документа не найден в storage.', show_alert=True)
        return
    await callback.answer()
    input_file = FSInputFile(file_path, filename=source.original_filename or file_path.name)
    caption = 'Исходный файл документа'
    if (source.mime_type or '').startswith('image/'):
        await callback.message.answer_photo(input_file, caption=caption)
    else:
        await callback.message.answer_document(input_file, caption=caption)


@router.callback_query(F.data.startswith(MANAGER_REPORTS_DUPLICATE_OPEN_PREFIX))
async def duplicate_open_callback(callback: CallbackQuery) -> None:
    payload = callback.data.removeprefix(MANAGER_REPORTS_DUPLICATE_OPEN_PREFIX)
    try:
        _period, document_id_text = payload.split(':', 1)
        document_id = int(document_id_text)
    except ValueError:
        await callback.answer('Некорректные данные документа.', show_alert=True)
        return
    await _send_report_document_source(callback, document_id)


@router.callback_query(F.data.startswith(MANAGER_REPORTS_DUPLICATE_OPEN_SOURCE_PREFIX))
async def duplicate_open_source_callback(callback: CallbackQuery) -> None:
    payload = callback.data.removeprefix(MANAGER_REPORTS_DUPLICATE_OPEN_SOURCE_PREFIX)
    try:
        _period, document_id_text = payload.split(':', 1)
        document_id = int(document_id_text)
    except ValueError:
        await callback.answer('Некорректные данные документа.', show_alert=True)
        return
    await _send_report_document_source(callback, document_id)


def _format_duplicate_document_card(title: str, document, items) -> str:
    vendor = document.vendor or document.vendor_inn or 'Контрагент не указан'
    number = document.document_number or 'без номера'
    date_line = document.document_date.strftime('%d.%m.%Y') if document.document_date else 'без даты'
    uploaded_at = document.created_at.strftime('%d.%m.%Y %H:%M') if document.created_at else '—'
    lines = [
        title,
        '',
        f'Проект: {document.project_name}',
        f'Контрагент: {vendor}',
        f'Дата документа: {date_line}',
        f'Номер: {number}',
        f'Сумма: {document.total_amount or 0}',
        f'Дата ввода: {uploaded_at}',
        '',
        format_items_only('Состав документа', items),
    ]
    return NL.join(lines)


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
    await _send_duplicate_report(callback.message, period, summary, rows)


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
    summary = await view_service.get_duplicate_report_summary(callback.from_user.id, period)
    await _send_duplicate_report(callback.message, period, summary, rows)


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
            document, items = await view_service.get_report_document_items(callback.from_user.id, period, document_id, project_id=target_id)
        elif report_kind == REPORT_KIND_EMPLOYEES:
            document, items = await view_service.get_report_document_items(callback.from_user.id, period, document_id, uploaded_by_user_id=target_id)
        else:
            await callback.answer('Некорректный источник отчета.', show_alert=True)
            return
    except (ValueError, CompanyAccessError) as exc:
        message = str(exc) if isinstance(exc, CompanyAccessError) else 'Некорректные данные документа.'
        await callback.answer(message, show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        format_report_document_card('Документ', document, items),
        reply_markup=build_report_document_card_keyboard(report_kind, period, target_id, document_id),
        parse_mode='HTML',
    )


@router.callback_query(F.data.startswith(MANAGER_REPORTS_DOCUMENT_OPEN_PREFIX))
async def report_document_open_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    payload = callback.data.removeprefix(MANAGER_REPORTS_DOCUMENT_OPEN_PREFIX)
    try:
        report_kind, _period, _target_id_text, document_id_text = payload.split(':', 3)
        if report_kind not in {REPORT_KIND_PROJECTS, REPORT_KIND_EMPLOYEES}:
            await callback.answer('Некорректный источник отчета.', show_alert=True)
            return
        document_id = int(document_id_text)
    except ValueError:
        await callback.answer('Некорректные данные документа.', show_alert=True)
        return
    await _send_report_document_source(callback, document_id)


@router.callback_query(F.data.startswith(MANAGER_REPORTS_DOCUMENT_ITEMS_PREFIX))
async def report_document_items_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    payload = callback.data.removeprefix(MANAGER_REPORTS_DOCUMENT_ITEMS_PREFIX)
    try:
        report_kind, period, target_id_text, document_id_text = payload.split(':', 3)
        target_id = int(target_id_text)
        document_id = int(document_id_text)
        if report_kind == REPORT_KIND_PROJECTS:
            document, items = await view_service.get_report_document_items(callback.from_user.id, period, document_id, project_id=target_id)
        elif report_kind == REPORT_KIND_EMPLOYEES:
            document, items = await view_service.get_report_document_items(callback.from_user.id, period, document_id, uploaded_by_user_id=target_id)
        else:
            await callback.answer('Некорректный источник отчета.', show_alert=True)
            return
    except (ValueError, CompanyAccessError) as exc:
        message = str(exc) if isinstance(exc, CompanyAccessError) else 'Некорректные данные документа.'
        await callback.answer(message, show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        format_items_only('Состав документа', items),
        reply_markup=build_report_document_items_back_keyboard(report_kind, period, target_id, document_id),
        parse_mode='HTML',
    )
