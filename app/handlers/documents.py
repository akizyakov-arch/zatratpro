import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender

from app.config import get_settings
from app.services.access import AccessContext
from app.services.document_processing import (
    DocumentPreviewFailure,
    DocumentProcessingService,
    DocumentDuplicateSaveFailure,
    DocumentPreviewProjectOptionsFailure,
    DocumentProjectSelectionDuplicate,
    DocumentProjectSelectionFailure,
    DocumentUploadInput,
)
from app.state.pending_actions import set_pending_action
from app.handlers.common import ensure_user_context, main_menu_markup_for_user
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
document_processing_service = DocumentProcessingService()

MAX_UPLOAD_BYTES = get_settings().max_upload_bytes


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


async def _main_menu_markup(
    message: Message,
    access_context: AccessContext | None = None,
) -> object:
    return await main_menu_markup_for_user(message.from_user, access_context)


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


def _build_upload_input(message: Message) -> DocumentUploadInput:
    return DocumentUploadInput(
        bot=message.bot,
        photo_sizes=list(message.photo or []),
        document=message.document,
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
    if failure.stage == 'preprocess':
        if failure.reason == 'validation_error' and failure.details == 'missing_upload':
            return 'Файл не найден в сообщении.'
        if failure.reason == 'validation_error' and failure.details == 'unsupported_upload':
            return 'Поддерживаются PDF и изображения: JPG, JPEG, PNG, WEBP, HEIC, HEIF. Этот файл пока не поддерживается для OCR.'
        return f'Не удалось подготовить файл: {failure.details or "неизвестная ошибка"}'
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
    if failure.stage == 'pending' and failure.reason == 'validation_error' and failure.details == 'active_document_flow':
        return 'У тебя уже есть незавершенный документ. Заверши выбор проекта по текущему документу, прежде чем отправлять новый.'
    return f'Не удалось подготовить документ: {failure.details or "неизвестная ошибка"}'


async def _handle_upload_message(
    message: Message,
    *,
    upload_kind: str,
    missing_payload_message: str,
    access_context: AccessContext | None = None,
) -> None:
    context = await _get_access_context_or_reply(message, access_context)
    if context is None:
        logger.info('Upload stopped before OCR: context unavailable upload_kind=%s', upload_kind)
        return

    menu_markup = build_main_menu_keyboard(
        menu_kind=context.menu_kind,
        has_company=context.has_company,
        can_view_reports=context.can_view_reports,
    )
    upload_input = _build_upload_input(message)
    if message.from_user is None:
        logger.info('Upload rejected: user missing upload_kind=%s', upload_kind)
        await message.answer(missing_payload_message, reply_markup=menu_markup)
        return
    if upload_kind == 'photo' and not upload_input.photo_sizes:
        logger.info('Photo upload rejected: photo payload missing')
        await message.answer(missing_payload_message, reply_markup=menu_markup)
        return
    if upload_kind == 'document' and upload_input.document is None:
        logger.info('Document upload rejected: document payload missing')
        await message.answer(missing_payload_message, reply_markup=menu_markup)
        return
    if _is_message_upload_too_large(message):
        file_size = _get_message_photo_size(message) if upload_kind == 'photo' else upload_input.document.file_size
        logger.info(
            'Upload rejected: user_id=%s upload_kind=%s reason=file_too_large size=%s limit=%s',
            message.from_user.id,
            upload_kind,
            file_size,
            MAX_UPLOAD_BYTES,
        )
        await message.answer(_format_upload_limit_message(), reply_markup=menu_markup)
        return
    logger.info(
        'Upload accepted for OCR handoff: user_id=%s upload_kind=%s file_name=%s mime_type=%s',
        message.from_user.id,
        upload_kind,
        upload_input.document.file_name if upload_input.document is not None else None,
        upload_input.document.mime_type if upload_input.document is not None else None,
    )
    await _process_upload_preview(
        message,
        menu_markup,
        context,
        upload_input,
    )


def _preview_project_options_failure_message(failure: DocumentPreviewProjectOptionsFailure) -> str:
    if failure.reason == 'no_active_projects':
        return 'В текущей компании нет активных проектов. Обратись к manager.'
    if failure.reason == 'access_error':
        return failure.details or 'Не удалось получить список проектов.'
    return f'Не удалось получить список проектов: {failure.details or "неизвестная ошибка"}'


def _project_selection_failure_message(failure: DocumentProjectSelectionFailure) -> str:
    if failure.stage == 'pending' and failure.reason == 'validation_error':
        if failure.details == 'missing_document':
            return 'Не удалось восстановить подготовленный документ. Отправь фото заново.'
        if failure.details == 'missing_pending':
            return 'Нет подготовленного документа. Отправь фото заново.'
    if failure.stage == 'project' and failure.reason == 'validation_error' and failure.details == 'project_unavailable':
        return 'Проект недоступен. Обнови список и попробуй снова.'
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
    if failure.stage == 'pending' and failure.reason == 'validation_error':
        if failure.details == 'missing_pending':
            return 'Нет документа для подтверждения. Отправь фото заново.'
        if failure.details == 'missing_document':
            return 'Не удалось восстановить подготовленный документ. Отправь фото заново.'
        if failure.details == 'missing_duplicate_check':
            return 'Не удалось восстановить подтверждение дубля. Отправь фото заново.'
    if failure.stage == 'project' and failure.reason == 'validation_error' and failure.details == 'project_unavailable':
        return 'Проект больше недоступен. Отправь документ заново.'
    if failure.reason in {'validation_error', 'access_error'}:
        return failure.details or 'Не удалось сохранить документ.'
    return f'Не удалось сохранить документ: {failure.details or "неизвестная ошибка"}'


async def _get_access_context_or_reply(
    message: Message,
    access_context: AccessContext | None = None,
):
    if message.from_user is None:
        logger.info('Access context missing: no from_user on message')
        await message.answer(
            'Не удалось определить пользователя.',
            reply_markup=await _main_menu_markup(message, access_context),
        )
        return None
    context = await ensure_user_context(message.from_user, access_context)
    if context is None:
        logger.info('Access context missing after middleware: user_id=%s', message.from_user.id)
        await message.answer(
            'Не удалось определить пользователя.',
            reply_markup=await _main_menu_markup(message, access_context),
        )
        return None
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


async def _process_upload_preview(
    message: Message,
    menu_markup,
    context,
    upload_input: DocumentUploadInput,
) -> None:
    if message.from_user is None:
        return

    user_name = _person_name(message.from_user)

    async def _on_prepared(preparation_result) -> None:
        prepared_upload = preparation_result.prepared_upload
        logger.info(
            'Document preprocessing completed: user_id=%s original_kind=%s prep_ms=%.1f source_size=%s ocr_size=%s',
            message.from_user.id,
            prepared_upload.original_kind,
            preparation_result.prep_elapsed_ms,
            prepared_upload.original_file_size,
            prepared_upload.normalized_file_size,
        )
        received_label = {
            'photo': 'фото получено',
            'pdf': 'PDF получен',
            'image_file': 'файл получен',
        }[prepared_upload.original_kind]
        await message.answer(f'{user_name}, {received_label}. Начинаю распознавание.', reply_markup=menu_markup)

    async def _on_ocr_completed(prepared_upload, ocr_result) -> None:
        logger.info(
            'OCR completed: user_id=%s original_kind=%s ocr_ms=%.1f chars=%s',
            message.from_user.id,
            prepared_upload.original_kind,
            ocr_result.ocr_elapsed_ms,
            len(ocr_result.ocr_text),
        )
        await message.answer(f'{user_name}, OCR завершен. Извлекаю структуру документа.', reply_markup=menu_markup)

    async with ChatActionSender.typing(chat_id=message.chat.id, bot=message.bot):
        preview_pipeline_result = await document_processing_service.build_pending_preview_from_upload(
            telegram_user_id=message.from_user.id,
            upload_input=upload_input,
            on_prepared=_on_prepared,
            on_retry_needed=lambda: _notify_ocr_retry(message, menu_markup),
            on_ocr_completed=_on_ocr_completed,
        )

    if isinstance(preview_pipeline_result, DocumentPreviewFailure):
        await message.answer(_preview_failure_message(preview_pipeline_result), reply_markup=menu_markup)
        return

    preview_result = preview_pipeline_result.preview
    logger.info(
        'Extraction completed: user_id=%s original_kind=%s extract_ms=%.1f items=%s',
        message.from_user.id,
        preview_pipeline_result.prepared_upload.original_kind,
        preview_result.extract_elapsed_ms,
        len(preview_result.document.items),
    )
    await message.answer(preview_result.preview_text, reply_markup=menu_markup)

    project_options = await document_processing_service.load_preview_project_options(
        telegram_user=message.from_user,
        can_manage_company=context.can_manage_company,
    )
    if isinstance(project_options, DocumentPreviewProjectOptionsFailure):
        await message.answer(_preview_project_options_failure_message(project_options), reply_markup=menu_markup)
        return

    await message.answer(
        f'{user_name}, выбери проект для сохранения документа.',
        reply_markup=build_projects_keyboard(project_options.projects, allow_create_project=context.can_manage_company),
    )


@router.message(F.photo)
async def process_photo(message: Message, access_context: AccessContext | None = None) -> None:
    logger.info(
        'Photo upload received: user_id=%s photo_count=%s caption=%s',
        message.from_user.id if message.from_user is not None else None,
        len(message.photo or []),
        message.caption,
    )
    await _handle_upload_message(
        message,
        upload_kind='photo',
        missing_payload_message='Фото не найдено в сообщении.',
        access_context=access_context,
    )


@router.message(F.document)
async def process_document_file(message: Message, access_context: AccessContext | None = None) -> None:
    logger.info(
        'Document upload received: user_id=%s file_name=%s mime_type=%s',
        message.from_user.id if message.from_user is not None else None,
        message.document.file_name if message.document is not None else None,
        message.document.mime_type if message.document is not None else None,
    )
    await _handle_upload_message(
        message,
        upload_kind='document',
        missing_payload_message='Файл не найден в сообщении.',
        access_context=access_context,
    )


@router.callback_query(F.data == PROJECT_CANCEL_CALLBACK)
async def cancel_project_selection(callback: CallbackQuery, access_context: AccessContext | None = None) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await document_processing_service.cancel_pending_document_flow(callback.from_user.id)
    await callback.answer('Загрузка отменена.')
    await callback.message.answer(
        'Подготовка документа отменена.',
        reply_markup=await main_menu_markup_for_user(callback.from_user, access_context),
    )


@router.callback_query(F.data == PROJECT_CREATE_CALLBACK)
async def create_project_from_document(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await set_pending_action(callback.from_user.id, 'create_project')
    await callback.answer()
    await callback.message.answer(f'{_person_name(callback.from_user)}, отправь название нового проекта.')


@router.callback_query(F.data.startswith(PROJECT_CALLBACK_PREFIX))
async def process_project_selection(callback: CallbackQuery, access_context: AccessContext | None = None) -> None:
    if callback.from_user is None or callback.message is None:
        return
    menu_markup = await main_menu_markup_for_user(callback.from_user, access_context)

    try:
        project_id = int(callback.data.removeprefix(PROJECT_CALLBACK_PREFIX))
    except (TypeError, ValueError):
        await callback.answer('Проект недоступен. Обнови список и попробуй снова.', show_alert=True)
        return

    selection_started = False

    async def _on_ready_to_resolve() -> None:
        nonlocal selection_started
        selection_started = True
        await callback.answer()
        await callback.message.answer(f'{_person_name(callback.from_user)}, проверяю документ...', reply_markup=menu_markup)

    selection_result = await document_processing_service.select_project_for_pending_document(
        telegram_user=callback.from_user,
        project_id=project_id,
        on_ready_to_resolve=_on_ready_to_resolve,
    )
    if isinstance(selection_result, DocumentProjectSelectionFailure):
        if not selection_started:
            await callback.answer(_project_selection_failure_message(selection_result), show_alert=True)
            return
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
async def duplicate_cancel_callback(callback: CallbackQuery, access_context: AccessContext | None = None) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await document_processing_service.cancel_pending_document_flow(callback.from_user.id)
    await callback.answer('Загрузка отменена.')
    await callback.message.answer(
        'Документ не сохранен. Можно отправить новый файл.',
        reply_markup=await main_menu_markup_for_user(callback.from_user, access_context),
    )


@router.callback_query(F.data == DOCUMENT_DUPLICATE_SAVE_CALLBACK)
async def duplicate_save_callback(callback: CallbackQuery, access_context: AccessContext | None = None) -> None:
    if callback.from_user is None or callback.message is None:
        return

    menu_markup = await main_menu_markup_for_user(callback.from_user, access_context)
    save_started = False

    async def _on_ready_to_save() -> None:
        nonlocal save_started
        save_started = True
        await callback.answer()

    save_result = await document_processing_service.confirm_duplicate_save(
        telegram_user=callback.from_user,
        on_ready_to_save=_on_ready_to_save,
    )
    if isinstance(save_result, DocumentDuplicateSaveFailure):
        if not save_started and save_result.stage == 'pending' and save_result.reason == 'validation_error' and save_result.details in {'missing_pending', 'missing_duplicate_check'}:
            await callback.answer(_duplicate_save_failure_message(save_result), show_alert=True)
            return
        if not save_started:
            await callback.answer()
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
async def unsupported_message(message: Message, access_context: AccessContext | None = None) -> None:
    await message.answer(
        'Поддерживаются кнопки главного меню, /start, /help, /join, а также фото, изображения и PDF документов.',
        reply_markup=await _main_menu_markup(message, access_context),
    )
