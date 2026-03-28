from pathlib import Path
import logging
from time import perf_counter

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender

from app.config import get_settings
from app.services.access import AccessService
from app.services.companies import CompanyAccessError
from app.services.document_processing import (
    DocumentPreviewFailure,
    DocumentProcessingService,
    DocumentDuplicateSaveFailure,
    DocumentProjectSelectionDuplicate,
    DocumentProjectSelectionFailure,
    PreparedUpload,
)
from app.services.pdf_files import PDFFileService
from app.services.projects import ProjectService
from app.services.temp_files import safe_unlink
from app.services.telegram_files import DownloadedTelegramPhoto, TelegramFileService
from app.state.pending_actions import set_pending_action
from app.state.pending_documents import (
    clear_document_flow,
    get_pending_document,
    has_active_document_flow,
)
from app.handlers.common import main_menu_markup_for_user
from app.ui.main_menu import build_main_menu_keyboard
from app.ui.projects import (
    DOCUMENT_DUPLICATE_CANCEL_CALLBACK,
    DOCUMENT_DUPLICATE_SAVE_CALLBACK,
    PROJECT_CALLBACK_PREFIX,
    PROJECT_CANCEL_CALLBACK,
    PROJECT_CREATE_CALLBACK,
    build_duplicate_confirmation_keyboard,
    build_projects_keyboard,
)


router = Router()
logger = logging.getLogger(__name__)
project_service = ProjectService()
access_service = AccessService()
document_processing_service = DocumentProcessingService()

MAX_UPLOAD_BYTES = get_settings().max_upload_bytes
SUPPORTED_IMAGE_MIME_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif'}
SUPPORTED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif'}


def _document_extension(message: Message) -> str:
    if message.document is None:
        return ''
    return Path(message.document.file_name or '').suffix.lower()


def _is_pdf_document(message: Message) -> bool:
    if message.document is None:
        return False
    mime_type = (message.document.mime_type or '').lower()
    return mime_type == 'application/pdf' or _document_extension(message) == '.pdf'


def _is_supported_image_document(message: Message) -> bool:
    if message.document is None:
        return False
    mime_type = (message.document.mime_type or '').lower()
    file_ext = _document_extension(message)
    return mime_type in SUPPORTED_IMAGE_MIME_TYPES or file_ext in SUPPORTED_IMAGE_EXTENSIONS


def _format_upload_limit_message() -> str:
    limit_mb = MAX_UPLOAD_BYTES / (1024 * 1024)
    limit_label = f'{limit_mb:.0f}' if float(limit_mb).is_integer() else f'{limit_mb:.1f}'
    return f'Файл слишком большой. Максимальный размер загрузки: {limit_label} МБ.'


def _get_message_photo_size(message: Message) -> int | None:
    if not message.photo:
        return None
    return message.photo[-1].file_size


def _is_message_upload_too_large(message: Message) -> bool:
    file_size = None
    if message.document is not None:
        file_size = message.document.file_size
    elif message.photo:
        file_size = _get_message_photo_size(message)
    return bool(file_size is not None and file_size > MAX_UPLOAD_BYTES)


async def _main_menu_markup(message: Message) -> object:
    return await main_menu_markup_for_user(message.from_user)


def _person_name(user) -> str:
    if user is None:
        return 'коллега'
    return user.first_name or user.full_name or user.username or 'коллега'


def _duplicate_status_label(status: str) -> str:
    return {
        'exact': 'Точный дубль',
        'probable': 'Вероятный дубль',
    }.get(status, status)


def _format_duplicate_warning(duplicate_info, duplicate_status: str) -> str:
    date_line = duplicate_info.document_date.strftime('%d.%m.%Y') if duplicate_info.document_date else 'без даты'
    number = duplicate_info.document_number or 'без номера'
    vendor = duplicate_info.vendor_name or 'контрагент не указан'
    uploader = duplicate_info.uploaded_by_name or 'исполнитель не указан'
    total_amount = duplicate_info.total_amount or 0
    return (
        f"{_duplicate_status_label(duplicate_status)}. В компании эти затраты уже учтены.\n\n"
        f"Проект: {duplicate_info.project_name}\n"
        f"Контрагент: {vendor}\n"
        f"Дата: {date_line}\n"
        f"Номер: {number}\n"
        f"Сумма: {total_amount}\n"
        f"Внес: {uploader}\n\n"
        "Отменить загрузку или все равно добавить документ?"
    )


def _prepared_upload_from_downloaded(downloaded_photo: DownloadedTelegramPhoto) -> PreparedUpload:
    return PreparedUpload(
        source_temp_path=downloaded_photo.source_path,
        ocr_temp_path=downloaded_photo.ocr_path,
        original_filename=downloaded_photo.original_filename,
        mime_type=downloaded_photo.mime_type,
        file_ext=downloaded_photo.file_ext,
        original_file_size=downloaded_photo.original_file_size,
        normalized_file_size=downloaded_photo.normalized_file_size,
        original_kind=downloaded_photo.original_kind,
    )


async def _notify_ocr_retry(message: Message, menu_markup) -> None:
    await message.answer('OCR занял слишком много времени, пробую еще раз.', reply_markup=menu_markup)


def _preview_failure_message(failure: DocumentPreviewFailure) -> str:
    if failure.stage == 'ocr':
        if failure.reason == 'timeout':
            return 'OCR выполнялся слишком долго. Попробуй отправить документ еще раз.'
        if failure.reason == 'service_error':
            return f'OCR не удался: {failure.details}'
        if failure.reason == 'validation_error' and failure.details == 'empty_text':
            return 'OCR не вернул текст. Попробуй отправить более четкий документ.'
        return f'Не удалось обработать документ: {failure.details or "неизвестная ошибка"}'
    if failure.stage == 'extract':
        if failure.reason == 'timeout':
            return 'Формирование JSON заняло слишком много времени. Попробуй отправить документ еще раз.'
        if failure.reason == 'service_error':
            return f'Не удалось собрать JSON документа: {failure.details}'
        if failure.reason == 'validation_error':
            if failure.details == 'unsupported_guest_bill':
                return 'Гостевой счет не является поддерживаемым затратным документом. Нужен фискальный кассовый чек или другой первичный документ.'
            if failure.details == 'unsupported_payment_invoice':
                return 'Документ распознан, но это счет на оплату, а не поддерживаемый затратный документ. Нужен кассовый чек, БСО, накладная, акт, УПД, транспортная накладная или РКО.'
            return failure.details or 'Не удалось подготовить документ.'
        return f'Не удалось подготовить документ: {failure.details or "неизвестная ошибка"}'
    return f'Не удалось подготовить документ: {failure.details or "неизвестная ошибка"}'


def _project_selection_failure_message(failure: DocumentProjectSelectionFailure) -> str:
    if failure.stage == 'pending' and failure.reason == 'validation_error' and failure.details == 'missing_document':
        return 'Не удалось восстановить подготовленный документ. Отправь фото заново.'
    if failure.reason in {'validation_error', 'access_error'}:
        return failure.details or 'Не удалось сохранить документ.'
    return f'Не удалось сохранить документ: {failure.details or "неизвестная ошибка"}'


def _saved_duplicate_message(duplicate_check) -> str:
    return {
        "exact": f"\n\nНайден точный дубль в этой компании. ID существующей записи: {duplicate_check.duplicate_document_id}. Загрузка не заблокирована.",
        "probable": f"\n\nНайден вероятный дубль в этой компании. ID существующей записи: {duplicate_check.duplicate_document_id}. Проверь запись вручную.",
        "none": "\n\nПроверка на дубли выполнена: совпадений не найдено.",
        "not_checked": "\n\nПроверка на дубли не выполнена: для вероятного дубля нужны дата, сумма и продавец. Для точного дубля дополнительно нужен номер документа.",
    }[duplicate_check.status]


def _duplicate_save_failure_message(failure: DocumentDuplicateSaveFailure) -> str:
    if failure.stage == 'pending' and failure.reason == 'validation_error' and failure.details == 'missing_document':
        return 'Не удалось восстановить подготовленный документ. Отправь фото заново.'
    if failure.stage == 'pending' and failure.reason == 'validation_error' and failure.details == 'missing_duplicate_check':
        return 'Не удалось восстановить подтверждение дубля. Отправь фото заново.'
    if failure.reason in {'validation_error', 'access_error'}:
        return failure.details or 'Не удалось сохранить документ.'
    return f'Не удалось сохранить документ: {failure.details or "неизвестная ошибка"}'


async def _get_access_context_or_reply(message: Message):
    if message.from_user is None:
        logger.info('Access context missing: no from_user on message')
        await message.answer('Не удалось определить пользователя.', reply_markup=await _main_menu_markup(message))
        return None
    context = await access_service.get_access_context(message.from_user)
    logger.info(
        'Access context resolved: user_id=%s menu_kind=%s has_company=%s can_manage_company=%s can_view_reports=%s',
        message.from_user.id,
        context.menu_kind,
        context.has_company,
        context.can_manage_company,
        context.can_view_reports,
    )
    if not context.has_company:
        logger.info('Access context rejected for document flow: user_id=%s has_company=%s', message.from_user.id, context.has_company)
        await message.answer(
            'Сначала нужно получить доступ к компании. Используй invite-код руководителя и выполни /join КОД.',
            reply_markup=build_main_menu_keyboard(
                menu_kind=context.menu_kind,
                has_company=context.has_company,
                can_view_reports=context.can_view_reports,
            ),
        )
        return None
    return context


async def _process_uploaded_image(
    message: Message,
    menu_markup,
    context,
    downloaded_photo: DownloadedTelegramPhoto,
    received_label: str,
    prepared_elapsed_ms: float | None = None,
) -> None:
    if message.from_user is None:
        safe_unlink(downloaded_photo.ocr_path)
        safe_unlink(downloaded_photo.source_path)
        return

    bot = message.bot
    prepared_upload = _prepared_upload_from_downloaded(downloaded_photo)

    if prepared_elapsed_ms is not None:
        logger.info(
            'Document preprocessing completed: user_id=%s original_kind=%s prep_ms=%.1f source_size=%s ocr_size=%s',
            message.from_user.id,
            downloaded_photo.original_kind,
            prepared_elapsed_ms,
            downloaded_photo.original_file_size,
            downloaded_photo.normalized_file_size,
        )

    pending_failure = await document_processing_service.begin_pending_preview(message.from_user.id)
    if pending_failure is not None:
        await clear_document_flow(message.from_user.id)
        await message.answer(_preview_failure_message(pending_failure), reply_markup=menu_markup)
        return
    await message.answer(f'{_person_name(message.from_user)}, {received_label}. Начинаю распознавание.', reply_markup=menu_markup)

    async with ChatActionSender.typing(chat_id=message.chat.id, bot=bot):
        ocr_result = await document_processing_service.run_ocr(
            prepared_upload,
            on_retry_needed=lambda: _notify_ocr_retry(message, menu_markup),
        )
    if isinstance(ocr_result, DocumentPreviewFailure):
        await clear_document_flow(message.from_user.id)
        await message.answer(_preview_failure_message(ocr_result), reply_markup=menu_markup)
        return

    logger.info(
        'OCR completed: user_id=%s original_kind=%s ocr_ms=%.1f chars=%s',
        message.from_user.id,
        downloaded_photo.original_kind,
        ocr_result.ocr_elapsed_ms,
        len(ocr_result.ocr_text),
    )

    await message.answer(f'{_person_name(message.from_user)}, OCR завершен. Извлекаю структуру документа.', reply_markup=menu_markup)
    async with ChatActionSender.typing(chat_id=message.chat.id, bot=bot):
        preview_result = await document_processing_service.build_preview_from_ocr(prepared_upload, ocr_result.ocr_text)
    if isinstance(preview_result, DocumentPreviewFailure):
        await clear_document_flow(message.from_user.id)
        await message.answer(_preview_failure_message(preview_result), reply_markup=menu_markup)
        return

    logger.info(
        'Extraction completed: user_id=%s original_kind=%s extract_ms=%.1f items=%s',
        message.from_user.id,
        downloaded_photo.original_kind,
        preview_result.extract_elapsed_ms,
        len(preview_result.document.items),
    )

    stored_preview_result = await document_processing_service.store_pending_preview(message.from_user.id, preview_result)
    if isinstance(stored_preview_result, DocumentPreviewFailure):
        await clear_document_flow(message.from_user.id)
        await message.answer(_preview_failure_message(stored_preview_result), reply_markup=menu_markup)
        return
    preview_result = stored_preview_result
    await message.answer(preview_result.preview_text, reply_markup=menu_markup)

    try:
        projects = await project_service.list_active_projects(message.from_user.id)
    except CompanyAccessError as exc:
        await clear_document_flow(message.from_user.id)
        await message.answer(str(exc), reply_markup=menu_markup)
        return

    if not projects and not context.can_manage_company:
        await clear_document_flow(message.from_user.id)
        await message.answer('В текущей компании нет активных проектов. Обратись к manager.', reply_markup=menu_markup)
        return

    await message.answer(
        f'{_person_name(message.from_user)}, выбери проект для сохранения документа.',
        reply_markup=build_projects_keyboard(projects, allow_create_project=context.can_manage_company),
    )


@router.message(F.photo)
async def process_photo(message: Message) -> None:
    logger.info(
        'Photo upload received: user_id=%s photo_count=%s caption=%s',
        message.from_user.id if message.from_user is not None else None,
        len(message.photo or []),
        message.caption,
    )
    context = await _get_access_context_or_reply(message)
    if context is None:
        logger.info('Photo upload stopped before OCR: context unavailable')
        return
    menu_markup = build_main_menu_keyboard(
        menu_kind=context.menu_kind,
        has_company=context.has_company,
        can_view_reports=context.can_view_reports,
    )
    if not message.photo or message.from_user is None:
        logger.info('Photo upload rejected: photo payload missing or user missing')
        await message.answer('Фото не найдено в сообщении.', reply_markup=menu_markup)
        return
    if _is_message_upload_too_large(message):
        logger.info('Photo upload rejected: user_id=%s reason=file_too_large size=%s limit=%s', message.from_user.id, _get_message_photo_size(message), MAX_UPLOAD_BYTES)
        await message.answer(_format_upload_limit_message(), reply_markup=menu_markup)
        return
    logger.info('Photo upload checking active pending flow: user_id=%s', message.from_user.id)
    has_active_flow = await has_active_document_flow(message.from_user.id)
    logger.info('Photo upload active pending flow result: user_id=%s active=%s', message.from_user.id, has_active_flow)
    if has_active_flow:
        logger.info('Photo upload blocked: active pending document flow user_id=%s', message.from_user.id)
        await message.answer(
            f'{_person_name(message.from_user)}, у тебя уже есть незавершенный документ. Заверши выбор проекта по текущему документу, прежде чем отправлять новый.',
            reply_markup=menu_markup,
        )
        return
    logger.info('Photo upload accepted for OCR: user_id=%s', message.from_user.id)
    logger.info('Photo upload starting file download: user_id=%s photo_count=%s', message.from_user.id, len(message.photo))
    download_started = perf_counter()
    file_service = TelegramFileService(message.bot)
    downloaded_photo = await file_service.download_best_photo(message.photo)
    await _process_uploaded_image(
        message,
        menu_markup,
        context,
        downloaded_photo,
        'фото получено',
        prepared_elapsed_ms=(perf_counter() - download_started) * 1000,
    )


@router.message(F.document)
async def process_document_file(message: Message) -> None:
    logger.info(
        'Document upload received: user_id=%s file_name=%s mime_type=%s',
        message.from_user.id if message.from_user is not None else None,
        message.document.file_name if message.document is not None else None,
        message.document.mime_type if message.document is not None else None,
    )
    context = await _get_access_context_or_reply(message)
    if context is None:
        return
    menu_markup = build_main_menu_keyboard(
        menu_kind=context.menu_kind,
        has_company=context.has_company,
        can_view_reports=context.can_view_reports,
    )
    if message.document is None or message.from_user is None:
        await message.answer('Файл не найден в сообщении.', reply_markup=menu_markup)
        return
    if _is_message_upload_too_large(message):
        logger.info('Document upload rejected: user_id=%s reason=file_too_large size=%s limit=%s', message.from_user.id, message.document.file_size, MAX_UPLOAD_BYTES)
        await message.answer(_format_upload_limit_message(), reply_markup=menu_markup)
        return
    logger.info('Photo upload checking active pending flow: user_id=%s', message.from_user.id)
    has_active_flow = await has_active_document_flow(message.from_user.id)
    logger.info('Photo upload active pending flow result: user_id=%s active=%s', message.from_user.id, has_active_flow)
    if has_active_flow:
        await message.answer(
            f'{_person_name(message.from_user)}, у тебя уже есть незавершенный документ. Заверши выбор проекта по текущему документу, прежде чем отправлять новый.',
            reply_markup=menu_markup,
        )
        return
    is_pdf_document = _is_pdf_document(message)
    if not is_pdf_document and not _is_supported_image_document(message):
        file_name = message.document.file_name or 'файл'
        logger.info(
            'Document upload rejected: user_id=%s file_name=%s mime_type=%s',
            message.from_user.id,
            file_name,
            message.document.mime_type,
        )
        await message.answer('Поддерживаются PDF и изображения: JPG, JPEG, PNG, WEBP, HEIC, HEIF. Этот файл пока не поддерживается для OCR.', reply_markup=menu_markup)
        return
    logger.info(
        'Document upload accepted for OCR: user_id=%s file_name=%s mime_type=%s original_kind=%s',
        message.from_user.id,
        message.document.file_name,
        message.document.mime_type,
        'pdf' if is_pdf_document else 'image_file',
    )
    download_started = perf_counter()
    try:
        if is_pdf_document:
            file_service = PDFFileService(message.bot)
            downloaded_photo = await file_service.download_pdf_document(message.document)
            received_label = 'PDF получен'
        else:
            file_service = TelegramFileService(message.bot)
            downloaded_photo = await file_service.download_image_document(message.document)
            received_label = 'файл получен'
    except Exception as exc:  # noqa: BLE001
        logger.exception('Document upload preprocessing failed')
        await message.answer(f'Не удалось подготовить файл: {exc}', reply_markup=menu_markup)
        return
    await _process_uploaded_image(
        message,
        menu_markup,
        context,
        downloaded_photo,
        received_label,
        prepared_elapsed_ms=(perf_counter() - download_started) * 1000,
    )


@router.callback_query(F.data == PROJECT_CANCEL_CALLBACK)
async def cancel_project_selection(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await clear_document_flow(callback.from_user.id)
    await callback.answer('Загрузка отменена.')
    await callback.message.answer('Подготовка документа отменена.', reply_markup=await main_menu_markup_for_user(callback.from_user))


@router.callback_query(F.data == PROJECT_CREATE_CALLBACK)
async def create_project_from_document(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await set_pending_action(callback.from_user.id, 'create_project')
    await callback.answer()
    await callback.message.answer(f'{_person_name(callback.from_user)}, отправь название нового проекта.')


@router.callback_query(F.data.startswith(PROJECT_CALLBACK_PREFIX))
async def process_project_selection(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    menu_markup = await main_menu_markup_for_user(callback.from_user)
    pending_document = await get_pending_document(callback.from_user.id)
    if pending_document is None:
        await callback.answer('Нет подготовленного документа. Отправь фото заново.', show_alert=True)
        return

    try:
        project_id = int(callback.data.removeprefix(PROJECT_CALLBACK_PREFIX))
        project = await project_service.get_active_project(callback.from_user.id, project_id)
    except (TypeError, ValueError):
        await callback.answer('Проект недоступен. Обнови список и попробуй снова.', show_alert=True)
        return
    except CompanyAccessError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    if project is None:
        await callback.answer('Проект недоступен. Обнови список и попробуй снова.', show_alert=True)
        return

    await callback.answer()
    await callback.message.answer(f'{_person_name(callback.from_user)}, проверяю документ...', reply_markup=menu_markup)
    selection_result = await document_processing_service.resolve_project_selection(
        telegram_user=callback.from_user,
        project=project,
        pending_document=pending_document,
    )
    if isinstance(selection_result, DocumentProjectSelectionFailure):
        await clear_document_flow(callback.from_user.id)
        await callback.message.answer(_project_selection_failure_message(selection_result), reply_markup=menu_markup)
        return
    if isinstance(selection_result, DocumentProjectSelectionDuplicate):
        await callback.message.answer(
            _format_duplicate_warning(selection_result.duplicate_info, selection_result.duplicate_check.status),
            reply_markup=build_duplicate_confirmation_keyboard(),
        )
        return
    await callback.message.answer(
        f"Документ сохранен в проект \"{selection_result.project_name}\". ID записи: {selection_result.document_id}.{_saved_duplicate_message(selection_result.duplicate_check)}",
        reply_markup=menu_markup,
    )


@router.callback_query(F.data == DOCUMENT_DUPLICATE_CANCEL_CALLBACK)
async def duplicate_cancel_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await clear_document_flow(callback.from_user.id)
    await callback.answer('Загрузка отменена.')
    await callback.message.answer('Документ не сохранен. Можно отправить новый файл.', reply_markup=await main_menu_markup_for_user(callback.from_user))


@router.callback_query(F.data == DOCUMENT_DUPLICATE_SAVE_CALLBACK)
async def duplicate_save_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return

    pending_document = await get_pending_document(callback.from_user.id)
    if pending_document is None or pending_document.duplicate_check is None:
        await callback.answer('Нет документа для подтверждения. Отправь фото заново.', show_alert=True)
        return

    menu_markup = await main_menu_markup_for_user(callback.from_user)
    if pending_document.selected_project_id is None:
        await clear_document_flow(callback.from_user.id)
        await callback.answer()
        await callback.message.answer('Не удалось восстановить подготовленный документ. Отправь фото заново.', reply_markup=menu_markup)
        return

    try:
        project = await project_service.get_active_project(callback.from_user.id, pending_document.selected_project_id)
    except CompanyAccessError as exc:
        await clear_document_flow(callback.from_user.id)
        await callback.answer()
        await callback.message.answer(str(exc), reply_markup=menu_markup)
        return

    if project is None:
        await clear_document_flow(callback.from_user.id)
        await callback.answer()
        await callback.message.answer('Проект больше недоступен. Отправь документ заново.', reply_markup=menu_markup)
        return

    await callback.answer()
    save_result = await document_processing_service.save_duplicate_confirmed(
        telegram_user=callback.from_user,
        project=project,
        pending_document=pending_document,
    )
    if isinstance(save_result, DocumentDuplicateSaveFailure):
        await clear_document_flow(callback.from_user.id)
        await callback.message.answer(_duplicate_save_failure_message(save_result), reply_markup=menu_markup)
        return

    duplicate_message = {
        'exact': f"\n\nДокумент сохранен принудительно. Точный дубль уже был в записи ID {save_result.duplicate_check.duplicate_document_id}.",
        'probable': f"\n\nДокумент сохранен принудительно. Возможный дубль уже был в записи ID {save_result.duplicate_check.duplicate_document_id}.",
        'none': '',
        'not_checked': '',
    }[save_result.duplicate_check.status]
    await callback.message.answer(
        f'Документ сохранен в проект "{save_result.project_name}". ID записи: {save_result.document_id}.{duplicate_message}',
        reply_markup=menu_markup,
    )


@router.message(~F.text)
async def log_non_text_message(message: Message) -> None:
    logger.info(
        'Non-text message received: user_id=%s has_photo=%s has_document=%s has_animation=%s has_video=%s has_sticker=%s has_voice=%s has_audio=%s file_name=%s mime_type=%s caption=%s',
        message.from_user.id if message.from_user is not None else None,
        bool(message.photo),
        message.document is not None,
        message.animation is not None,
        message.video is not None,
        message.sticker is not None,
        message.voice is not None,
        message.audio is not None,
        message.document.file_name if message.document is not None else None,
        message.document.mime_type if message.document is not None else None,
        message.caption,
    )


@router.message(~F.text)
async def unsupported_message(message: Message) -> None:
    await message.answer(
        'Поддерживаются кнопки главного меню, /start, /help, /join, а также фото, изображения и PDF документов.',
        reply_markup=await _main_menu_markup(message),
    )
