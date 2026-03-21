from pathlib import Path
import asyncio
import logging
from time import perf_counter

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender

from app.schemas.document import DocumentSchema
from app.services.access import AccessService
from app.services.companies import CompanyAccessError, CompanyService
from app.services.deepseek import DeepSeekError, DeepSeekService
from app.services.documents import DocumentService, DocumentValidationError
from app.services.json_formatter import chunk_message, format_document_preview
from app.services.ocr_space import OCRSpaceError, OCRSpaceService
from app.services.projects import ProjectService
from app.services.telegram_files import DownloadedTelegramPhoto, TelegramFileService
from app.state.pending_actions import set_pending_action
from app.state.pending_documents import (
    PendingDocument,
    begin_document_flow,
    clear_document_flow,
    get_pending_document,
    has_active_document_flow,
    pop_pending_document,
    store_pending_document,
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
SLOW_DOCUMENT_STAGE_MS = 500.0
project_service = ProjectService()
document_service = DocumentService()
company_service = CompanyService()
access_service = AccessService()
OCR_TIMEOUT_SECONDS = 120
EXTRACT_TIMEOUT_SECONDS = 120
OCR_RETRY_DELAY_SECONDS = 3


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


async def _save_pending_document(callback: CallbackQuery, pending_document: PendingDocument, menu_markup) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if pending_document.extracted_document is None or pending_document.selected_project_id is None:
        await clear_document_flow(callback.from_user.id)
        await callback.message.answer('Не удалось восстановить подготовленный документ. Отправь фото заново.', reply_markup=menu_markup)
        return
    try:
        project = await project_service.get_active_project(callback.from_user.id, pending_document.selected_project_id)
    except CompanyAccessError as exc:
        await clear_document_flow(callback.from_user.id)
        await callback.message.answer(str(exc), reply_markup=menu_markup)
        return
    if project is None:
        await clear_document_flow(callback.from_user.id)
        await callback.message.answer('Проект больше недоступен. Отправь документ заново.', reply_markup=menu_markup)
        return
    try:
        document_id = await document_service.save_document(
            telegram_user=callback.from_user,
            project=project,
            normalized_text=pending_document.normalized_text,
            document=pending_document.extracted_document,
            duplicate_check=pending_document.duplicate_check,
            source_type='photo',
            source_temp_path=pending_document.source_temp_path,
            source_original_name=pending_document.source_original_name,
            source_mime_type=pending_document.source_mime_type,
            source_file_ext=pending_document.source_file_ext,
        )
    except DocumentValidationError as exc:
        await clear_document_flow(callback.from_user.id)
        await callback.message.answer(str(exc), reply_markup=menu_markup)
        return
    except CompanyAccessError as exc:
        await clear_document_flow(callback.from_user.id)
        await callback.message.answer(str(exc), reply_markup=menu_markup)
        return
    except Exception as exc:  # noqa: BLE001
        await clear_document_flow(callback.from_user.id)
        logger.exception('Document save failed after duplicate confirmation')
        await callback.message.answer(f'Не удалось сохранить документ: {exc}', reply_markup=menu_markup)
        return
    duplicate_check = pending_document.duplicate_check
    await clear_document_flow(callback.from_user.id)
    duplicate_message = {
        'exact': f"\n\nДокумент сохранен принудительно. Точный дубль уже был в записи ID {duplicate_check.duplicate_document_id}.",
        'probable': f"\n\nДокумент сохранен принудительно. Возможный дубль уже был в записи ID {duplicate_check.duplicate_document_id}.",
        'none': '',
        'not_checked': '',
    }[duplicate_check.status]
    await callback.message.answer(
        f'Документ сохранен в проект "{project.name}". ID записи: {document_id}.{duplicate_message}',
        reply_markup=menu_markup,
    )


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
) -> None:
    if message.from_user is None:
        TelegramFileService(message.bot).delete_temp_file(downloaded_photo.ocr_path)
        TelegramFileService(message.bot).delete_temp_file(downloaded_photo.source_path)
        return

    bot = message.bot
    file_service = TelegramFileService(bot)
    ocr_service = OCRSpaceService()
    deepseek_service = DeepSeekService()

    await begin_document_flow(message.from_user.id)
    await message.answer(f'{_person_name(message.from_user)}, {received_label}. Начинаю распознавание.', reply_markup=menu_markup)

    try:
        async with ChatActionSender.typing(chat_id=message.chat.id, bot=bot):
            try:
                async with asyncio.timeout(OCR_TIMEOUT_SECONDS):
                    ocr_text = await ocr_service.extract_text(downloaded_photo.ocr_path)
            except TimeoutError:
                await message.answer('OCR занял слишком много времени, пробую еще раз.', reply_markup=menu_markup)
                await asyncio.sleep(OCR_RETRY_DELAY_SECONDS)
                async with asyncio.timeout(OCR_TIMEOUT_SECONDS):
                    ocr_text = await ocr_service.extract_text(downloaded_photo.ocr_path)
            except OCRSpaceError as exc:
                if 'E101' not in str(exc):
                    raise
                await message.answer('OCR занял слишком много времени, пробую еще раз.', reply_markup=menu_markup)
                await asyncio.sleep(OCR_RETRY_DELAY_SECONDS)
                async with asyncio.timeout(OCR_TIMEOUT_SECONDS):
                    ocr_text = await ocr_service.extract_text(downloaded_photo.ocr_path)
    except TimeoutError:
        file_service.delete_temp_file(downloaded_photo.ocr_path)
        file_service.delete_temp_file(downloaded_photo.source_path)
        await clear_document_flow(message.from_user.id)
        logger.exception('OCR timed out')
        await message.answer('OCR выполнялся слишком долго. Попробуй отправить документ еще раз.', reply_markup=menu_markup)
        return
    except OCRSpaceError as exc:
        file_service.delete_temp_file(downloaded_photo.ocr_path)
        file_service.delete_temp_file(downloaded_photo.source_path)
        await clear_document_flow(message.from_user.id)
        logger.exception('OCR failed')
        await message.answer(f'OCR не удался: {exc}', reply_markup=menu_markup)
        return
    except Exception as exc:  # noqa: BLE001
        file_service.delete_temp_file(downloaded_photo.ocr_path)
        file_service.delete_temp_file(downloaded_photo.source_path)
        await clear_document_flow(message.from_user.id)
        logger.exception('Unexpected error while processing uploaded image')
        await message.answer(f'Не удалось обработать документ: {exc}', reply_markup=menu_markup)
        return
    finally:
        file_service.delete_temp_file(downloaded_photo.ocr_path)

    if not ocr_text.strip():
        file_service.delete_temp_file(downloaded_photo.source_path)
        await clear_document_flow(message.from_user.id)
        await message.answer('OCR не вернул текст. Попробуй более четкое фото.', reply_markup=menu_markup)
        return

    await message.answer(f'{_person_name(message.from_user)}, OCR завершен. Извлекаю структуру документа.', reply_markup=menu_markup)
    try:
        async with ChatActionSender.typing(chat_id=message.chat.id, bot=bot):
            async with asyncio.timeout(EXTRACT_TIMEOUT_SECONDS):
                extracted_document = await deepseek_service.extract_document(ocr_text)
        document = DocumentSchema.model_validate({**extracted_document, 'raw_text': ocr_text})
        preview_text = format_document_preview(document)
    except TimeoutError:
        file_service.delete_temp_file(downloaded_photo.source_path)
        await clear_document_flow(message.from_user.id)
        logger.exception('DeepSeek extraction timed out')
        await message.answer('Формирование JSON заняло слишком много времени. Попробуй отправить документ еще раз.', reply_markup=menu_markup)
        return
    except DeepSeekError as exc:
        file_service.delete_temp_file(downloaded_photo.source_path)
        await clear_document_flow(message.from_user.id)
        logger.exception('DeepSeek extraction failed')
        await message.answer(f'Не удалось собрать JSON документа: {exc}', reply_markup=menu_markup)
        return
    except DocumentValidationError as exc:
        file_service.delete_temp_file(downloaded_photo.source_path)
        await clear_document_flow(message.from_user.id)
        await message.answer(str(exc), reply_markup=menu_markup)
        return
    except Exception as exc:  # noqa: BLE001
        file_service.delete_temp_file(downloaded_photo.source_path)
        await clear_document_flow(message.from_user.id)
        logger.exception('Extraction failed')
        await message.answer(f'Не удалось подготовить документ: {exc}', reply_markup=menu_markup)
        return

    await store_pending_document(
        message.from_user.id,
        PendingDocument(
            ocr_text=ocr_text,
            normalized_text=preview_text,
            extracted_document=document,
            source_temp_path=str(downloaded_photo.ocr_path),
            source_original_name=downloaded_photo.original_filename,
            source_mime_type='image/jpeg',
            source_file_ext='.jpg',
        ),
    )
    file_service.delete_temp_file(downloaded_photo.source_path)
    await message.answer(preview_text, reply_markup=menu_markup)

    try:
        projects = await project_service.list_active_projects(message.from_user.id)
    except CompanyAccessError as exc:
        file_service.delete_temp_file(downloaded_photo.source_path)
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
    file_service = TelegramFileService(message.bot)
    downloaded_photo = await file_service.download_best_photo(message.photo)
    await _process_uploaded_image(message, menu_markup, context, downloaded_photo, 'фото получено')


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
    logger.info('Photo upload checking active pending flow: user_id=%s', message.from_user.id)
    has_active_flow = await has_active_document_flow(message.from_user.id)
    logger.info('Photo upload active pending flow result: user_id=%s active=%s', message.from_user.id, has_active_flow)
    if has_active_flow:
        await message.answer(
            f'{_person_name(message.from_user)}, у тебя уже есть незавершенный документ. Заверши выбор проекта по текущему документу, прежде чем отправлять новый.',
            reply_markup=menu_markup,
        )
        return
    if not _is_supported_image_document(message):
        file_name = message.document.file_name or 'файл'
        logger.info(
            'Document upload rejected: user_id=%s file_name=%s mime_type=%s',
            message.from_user.id,
            file_name,
            message.document.mime_type,
        )
        if (message.document.mime_type or '').lower() == 'application/pdf' or file_name.lower().endswith('.pdf'):
            await message.answer('PDF уже принимается как файл, но отдельный PDF OCR-flow еще не включен. Пока отправь документ как фото или изображение-файл.', reply_markup=menu_markup)
            return
        await message.answer('Поддерживаются изображения: JPG, JPEG, PNG, WEBP, HEIC, HEIF. Этот файл пока не поддерживается для OCR.', reply_markup=menu_markup)
        return
    logger.info(
        'Document upload accepted for OCR: user_id=%s file_name=%s mime_type=%s',
        message.from_user.id,
        message.document.file_name,
        message.document.mime_type,
    )
    file_service = TelegramFileService(message.bot)
    downloaded_photo = await file_service.download_image_document(message.document)
    await _process_uploaded_image(message, menu_markup, context, downloaded_photo, 'файл получен')


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
    document = pending_document.extracted_document
    if document is None:
        await clear_document_flow(callback.from_user.id)
        await callback.message.answer('Не удалось восстановить подготовленный документ. Отправь фото заново.', reply_markup=menu_markup)
        return
    try:
        duplicate_check = await document_service.find_company_duplicate_document(
            telegram_user=callback.from_user,
            project=project,
            document=document,
            normalized_text=pending_document.normalized_text,
        )
        pending_document.duplicate_check = duplicate_check
        pending_document.selected_project_id = project.id
        if duplicate_check.status in {'exact', 'probable'}:
            await store_pending_document(callback.from_user.id, pending_document)
            duplicate_info = await document_service.get_duplicate_document_info(
                callback.from_user.id,
                duplicate_check.duplicate_document_id,
            )
            await callback.message.answer(
                _format_duplicate_warning(duplicate_info, duplicate_check.status),
                reply_markup=build_duplicate_confirmation_keyboard(),
            )
            return
        document_id = await document_service.save_document(
            telegram_user=callback.from_user,
            project=project,
            normalized_text=pending_document.normalized_text,
            document=document,
            duplicate_check=duplicate_check,
            source_type='photo',
            source_temp_path=pending_document.source_temp_path,
            source_original_name=pending_document.source_original_name,
            source_mime_type=pending_document.source_mime_type,
            source_file_ext=pending_document.source_file_ext,
        )
    except DocumentValidationError as exc:
        await clear_document_flow(callback.from_user.id)
        await callback.message.answer(str(exc), reply_markup=menu_markup)
        return
    except CompanyAccessError as exc:
        await clear_document_flow(callback.from_user.id)
        await callback.message.answer(str(exc), reply_markup=menu_markup)
        return
    except Exception as exc:  # noqa: BLE001
        await clear_document_flow(callback.from_user.id)
        logger.exception('Document save failed')
        await callback.message.answer(f'Не удалось сохранить документ: {exc}', reply_markup=menu_markup)
        return

    await pop_pending_document(callback.from_user.id)
    duplicate_message = {
        "exact": f"\n\nНайден точный дубль в этой компании. ID существующей записи: {duplicate_check.duplicate_document_id}. Загрузка не заблокирована.",
        "probable": f"\n\nНайден вероятный дубль в этой компании. ID существующей записи: {duplicate_check.duplicate_document_id}. Проверь запись вручную.",
        "none": "\n\nПроверка на дубли выполнена: совпадений не найдено.",
        "not_checked": "\n\nПроверка на дубли не выполнена: для вероятного дубля нужны дата, сумма и продавец. Для точного дубля дополнительно нужен номер документа.",
    }[duplicate_check.status]
    await callback.message.answer(
        f"Документ сохранен в проект \"{project.name}\". ID записи: {document_id}.{duplicate_message}",
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
    await callback.answer()
    await _save_pending_document(callback, pending_document, await main_menu_markup_for_user(callback.from_user))


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
        'Поддерживаются кнопки главного меню, /start, /help, /join и фото документов.',
        reply_markup=await _main_menu_markup(message),
    )
