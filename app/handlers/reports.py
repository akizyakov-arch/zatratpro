from datetime import datetime
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile, Message

from app.config import TMP_DIR

from app.handlers.common import build_main_menu_markup_from_context, document_service, ensure_context, format_duplicate_card, main_menu_markup, view_service
from app.services.companies import CompanyAccessError
from app.services.document_exports import build_document_scans_archive
from app.services.document_storage import DocumentStorageService
from app.services.report_exports import build_manager_report_workbook
from app.services.report_formatters import (
    format_duplicate_report,
    format_project_report,
    format_report_document_card,
    format_report_document_items,
    format_report_documents,
    format_items_only,
    report_period_label,
)
from app.ui.main_menu import MENU_BUTTONS
from app.state.pending_actions import PendingAction, set_pending_action
from app.ui.reports import (
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
    MANAGER_REPORTS_DOCUMENTS_CALLBACK,
    MANAGER_REPORTS_SCANS_EXPORT_CALLBACK,
    MANAGER_REPORTS_EMPLOYEES_CALLBACK,
    MANAGER_REPORTS_EMPLOYEE_PERIOD_PREFIX,
    MANAGER_REPORTS_EMPLOYEE_SELECT_PREFIX,
    MANAGER_REPORTS_EXPORT_CALLBACK,
    MANAGER_REPORTS_MENU_CALLBACK,
    MANAGER_REPORTS_PERIOD_CUSTOM_PREFIX,
    MANAGER_REPORTS_PERIOD_PREFIX,
    MANAGER_REPORTS_PROJECTS_CALLBACK,
    MANAGER_REPORTS_PROJECT_DETAIL_PREFIX,
    REPORT_KIND_DOCUMENTS,
    REPORT_KIND_DUPLICATES,
    REPORT_KIND_SCANS_EXPORT,
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
    build_report_document_card_keyboard,
    build_report_document_items_back_keyboard,
    build_report_documents_keyboard,
    build_report_period_keyboard,
    build_reports_menu_keyboard,
    build_custom_report_period_input_keyboard,
)

router = Router()
NL = '\n'
document_storage_service = DocumentStorageService()
logger = logging.getLogger(__name__)

async def _edit_or_answer(message: Message, text: str, reply_markup, parse_mode: str | None = None) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest:
        await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)

async def _send_duplicate_report(message, period: str, summary, rows) -> None:
    await message.answer(
        format_duplicate_report(summary, rows),
        reply_markup=build_duplicate_report_keyboard(period, rows),
        parse_mode='HTML',
    )


async def _send_custom_period_result(message: Message, telegram_user_id: int, report_kind: str, period: str) -> None:
    logger.info('Custom report result start: user_id=%s report_kind=%s period=%s', telegram_user_id, report_kind, period)
    if report_kind == REPORT_KIND_DOCUMENTS:
        rows = await view_service.list_report_documents_for_company(telegram_user_id, period)
        await message.answer(
            format_report_documents('Документы компании', period, rows),
            reply_markup=build_report_documents_keyboard(REPORT_KIND_DOCUMENTS, period, 0, rows),
            parse_mode='HTML',
        )
        return
    if report_kind == REPORT_KIND_SCANS_EXPORT:
        job_dir = None
        try:
            rows = await view_service.list_report_document_sources_for_company(telegram_user_id, period)
            logger.info('Custom report scan export rows loaded: user_id=%s period=%s count=%s', telegram_user_id, period, len(rows))
            if not rows:
                await message.answer('За период нет документов со сканами.', reply_markup=build_reports_menu_keyboard())
                return
            job_dir, archive_name, archive_path = build_document_scans_archive(period, rows, document_storage_service, TMP_DIR)
            await message.answer_document(FSInputFile(archive_path, filename=archive_name), caption=f'Сканы документов за период: {report_period_label(period)}')
        except Exception as exc:
            logger.exception('Custom report scan export failed: user_id=%s period=%s', telegram_user_id, period)
            await message.answer(f'Не удалось собрать выгрузку сканов: {exc}', reply_markup=build_reports_menu_keyboard())
        finally:
            if job_dir is not None:
                import shutil
                shutil.rmtree(job_dir, ignore_errors=True)
        return
    raise CompanyAccessError('Произвольный период поддерживается только для документов и выгрузки сканов.')


def _parse_report_input_date(value: str) -> datetime.date:
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError as exc:
        raise CompanyAccessError('Некорректная дата. Используйте формат YYYY-MM-DD.') from exc


def _build_custom_period_token(date_from, date_to) -> str:
    return f'custom_{date_from.isoformat()}_{date_to.isoformat()}'


async def handle_custom_report_period_input(message: Message, pending_action: PendingAction, text_value: str) -> None:
    report_kind = str(pending_action.payload.get('report_kind', '') or '')
    logger.info('Custom report period input: user_id=%s action=%s report_kind=%s text=%s', message.from_user.id if message.from_user else None, pending_action.action, report_kind, text_value)
    if pending_action.action == 'report_custom_period_from':
        date_from = _parse_report_input_date(text_value)
        await set_pending_action(message.from_user.id, 'report_custom_period_to', {'report_kind': report_kind, 'date_from': date_from.isoformat()})
        await message.answer('Введите дату окончания в формате YYYY-MM-DD.', reply_markup=build_custom_report_period_input_keyboard(report_kind))
        return
    if pending_action.action == 'report_custom_period_to':
        date_from_text = str(pending_action.payload.get('date_from', '') or '')
        date_from = _parse_report_input_date(date_from_text)
        date_to = _parse_report_input_date(text_value)
        if date_from > date_to:
            await set_pending_action(message.from_user.id, 'report_custom_period_to', {'report_kind': report_kind, 'date_from': date_from.isoformat()})
            raise CompanyAccessError('Дата окончания не может быть раньше даты начала.')
        period = _build_custom_period_token(date_from, date_to)
        try:
            await _send_custom_period_result(message, message.from_user.id, report_kind, period)
        except CompanyAccessError as exc:
            logger.warning('Custom report result failed: user_id=%s report_kind=%s period=%s error=%s', message.from_user.id if message.from_user else None, report_kind, period, exc)
            await message.answer(str(exc), reply_markup=build_custom_report_period_input_keyboard(report_kind))
        return
    raise CompanyAccessError('Неизвестное действие произвольного периода.')


@router.message(F.text == MENU_BUTTONS['reports'])
async def reports_menu_entry(message: Message) -> None:
    if message.from_user is None:
        return
    context = await ensure_context(message)
    if context is None or not context.can_view_reports:
        await message.answer(
            'Раздел отчетов доступен только manager.',
            reply_markup=build_main_menu_markup_from_context(context) if context is not None else await main_menu_markup(message),
        )
        return
    await message.answer('Раздел отчетов:', reply_markup=build_reports_menu_keyboard())


@router.callback_query(F.data == MANAGER_REPORTS_MENU_CALLBACK)
async def reports_menu_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await callback.message.answer('Раздел отчетов:', reply_markup=build_reports_menu_keyboard())


@router.callback_query(F.data.in_({MANAGER_REPORTS_PROJECTS_CALLBACK, MANAGER_REPORTS_EMPLOYEES_CALLBACK, MANAGER_REPORTS_DOCUMENTS_CALLBACK, MANAGER_REPORTS_SCANS_EXPORT_CALLBACK, MANAGER_REPORTS_DUPLICATES_CALLBACK, MANAGER_REPORTS_EXPORT_CALLBACK}))
async def report_kind_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    report_kind = {
        MANAGER_REPORTS_PROJECTS_CALLBACK: REPORT_KIND_PROJECTS,
        MANAGER_REPORTS_EMPLOYEES_CALLBACK: REPORT_KIND_EMPLOYEES,
        MANAGER_REPORTS_DOCUMENTS_CALLBACK: REPORT_KIND_DOCUMENTS,
        MANAGER_REPORTS_SCANS_EXPORT_CALLBACK: REPORT_KIND_SCANS_EXPORT,
        MANAGER_REPORTS_DUPLICATES_CALLBACK: REPORT_KIND_DUPLICATES,
        MANAGER_REPORTS_EXPORT_CALLBACK: REPORT_KIND_EXPORT,
    }[callback.data]
    logger.info('Report kind callback: user_id=%s report_kind=%s data=%s', callback.from_user.id if callback.from_user else None, report_kind, callback.data)
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
    await _edit_or_answer(callback.message, 'Выбери период отчета.', build_report_period_keyboard(report_kind))


@router.callback_query(F.data.startswith(MANAGER_REPORTS_PERIOD_CUSTOM_PREFIX))
async def report_custom_period_prompt(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    report_kind = callback.data.removeprefix(MANAGER_REPORTS_PERIOD_CUSTOM_PREFIX)
    logger.info('Report custom period prompt: user_id=%s report_kind=%s data=%s', callback.from_user.id if callback.from_user else None, report_kind, callback.data)
    await set_pending_action(callback.from_user.id, 'report_custom_period_from', {'report_kind': report_kind})
    await callback.answer()
    await _edit_or_answer(callback.message, 'Введите дату начала в формате YYYY-MM-DD.', build_custom_report_period_input_keyboard(report_kind))


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
    logger.info('Report period callback: user_id=%s report_kind=%s period=%s data=%s', callback.from_user.id if callback.from_user else None, report_kind, period, callback.data)
    if period == '_back':
        await callback.answer()
        await _edit_or_answer(callback.message, 'Выбери период отчета.', build_report_period_keyboard(report_kind))
        return
    try:
        if report_kind == REPORT_KIND_PROJECTS:
            await callback.answer()
            summary = await view_service.get_manager_report_summary(callback.from_user.id, period)
            rows = await view_service.list_report_projects(callback.from_user.id, period)
            await _edit_or_answer(callback.message, format_project_report(summary, rows), build_project_report_keyboard(period, rows), parse_mode='HTML')
            return
        if report_kind == REPORT_KIND_DUPLICATES:
            await callback.answer()
            rows = await view_service.list_duplicate_report_rows(callback.from_user.id, period)
            duplicate_summary = await view_service.get_duplicate_report_summary(callback.from_user.id, period)
            await _send_duplicate_report(callback.message, period, duplicate_summary, rows)
            return
        if report_kind == REPORT_KIND_DOCUMENTS:
            await callback.answer()
            await _edit_or_answer(callback.message, f'Ищу документы за период: {report_period_label(period)}...', build_reports_menu_keyboard())
            rows = await view_service.list_report_documents_for_company(callback.from_user.id, period)
            logger.info('Report documents loaded: user_id=%s period=%s count=%s', callback.from_user.id, period, len(rows))
            await _edit_or_answer(
                callback.message,
                format_report_documents('Документы компании', period, rows),
                build_report_documents_keyboard(REPORT_KIND_DOCUMENTS, period, 0, rows),
                parse_mode='HTML',
            )
            return
        if report_kind == REPORT_KIND_SCANS_EXPORT:
            job_dir = None
            try:
                await callback.answer()
                await _edit_or_answer(callback.message, f'Собираю сканы за период: {report_period_label(period)}...', build_reports_menu_keyboard())
                rows = await view_service.list_report_document_sources_for_company(callback.from_user.id, period)
                logger.info('Report scan export rows loaded: user_id=%s period=%s count=%s', callback.from_user.id, period, len(rows))
                if not rows:
                    await _edit_or_answer(callback.message, 'За период нет документов со сканами.', build_reports_menu_keyboard())
                    return
                job_dir, archive_name, archive_path = build_document_scans_archive(period, rows, document_storage_service, TMP_DIR)
                await callback.message.answer_document(FSInputFile(archive_path, filename=archive_name), caption=f'Сканы документов за период: {report_period_label(period)}')
            except CompanyAccessError as exc:
                await callback.answer(str(exc), show_alert=True)
                return
            except Exception as exc:
                logger.exception('Report scan export failed: user_id=%s period=%s', callback.from_user.id, period)
                await _edit_or_answer(callback.message, f'Не удалось собрать выгрузку сканов: {exc}', build_reports_menu_keyboard())
                return
            finally:
                if job_dir is not None:
                    import shutil
                    shutil.rmtree(job_dir, ignore_errors=True)
            return
        if report_kind == REPORT_KIND_EXPORT:
            await callback.answer()
            summary = await view_service.get_manager_report_summary(callback.from_user.id, period)
            projects = await view_service.list_report_projects(callback.from_user.id, period)
            employees = await view_service.list_report_employees(callback.from_user.id, period)
            duplicates = await view_service.list_duplicate_report_rows(callback.from_user.id, period)
            documents = await view_service.list_report_documents_for_company(callback.from_user.id, period)
            items = await view_service.list_report_items_for_company(callback.from_user.id, period)
            filename, payload_bytes = build_manager_report_workbook(period, summary, projects, employees, duplicates, documents, items)
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
    duplicate_label = 'Точный дубль' if row.duplicate_status == 'exact' else 'Возможный дубль' if row.duplicate_status == 'probable' else 'Дубль'
    lines = [f'<b>Тип:</b> {duplicate_label}', '', _format_duplicate_document_card('Документ-дубликат', duplicate_document, duplicate_items)]
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
        elif report_kind == REPORT_KIND_DOCUMENTS:
            document, items = await view_service.get_report_document_items(callback.from_user.id, period, document_id)
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
        if report_kind not in {REPORT_KIND_PROJECTS, REPORT_KIND_EMPLOYEES, REPORT_KIND_DOCUMENTS}:
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
        elif report_kind == REPORT_KIND_DOCUMENTS:
            document, items = await view_service.get_report_document_items(callback.from_user.id, period, document_id)
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
