import asyncio
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender

from app.schemas.document import DocumentSchema
from app.services.companies import CompanyAccessError, CompanyService
from app.services.deepseek import DeepSeekError, DeepSeekService
from app.services.documents import DocumentService, DocumentValidationError
from app.services.json_formatter import chunk_message, format_document_preview
from app.services.ocr_space import OCRSpaceError, OCRSpaceService
from app.services.projects import ProjectService
from app.services.telegram_files import TelegramFileService
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
document_service = DocumentService()
company_service = CompanyService()
OCR_TIMEOUT_SECONDS = 120
EXTRACT_TIMEOUT_SECONDS = 120


async def _main_menu_markup_for_user(user) -> object:
    if user is None:
        return build_main_menu_keyboard(has_company=False)
    await company_service.ensure_platform_user(user)
    context = await company_service.get_user_context(user.id)
    return build_main_menu_keyboard(
        menu_kind=context.menu_kind,
        has_company=context.has_company,
        can_view_reports=context.can_view_reports,
    )


async def _main_menu_markup(message: Message) -> object:
    return await _main_menu_markup_for_user(message.from_user)


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
        clear_document_flow(callback.from_user.id)
        await callback.message.answer('Не удалось восстановить подготовленный документ. Отправь фото заново.', reply_markup=menu_markup)
        return
    try:
        project = await project_service.get_active_project(callback.from_user.id, pending_document.selected_project_id)
    except CompanyAccessError as exc:
        clear_document_flow(callback.from_user.id)
        await callback.message.answer(str(exc), reply_markup=menu_markup)
        return
    if project is None:
        clear_document_flow(callback.from_user.id)
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
        )
    except DocumentValidationError as exc:
        clear_document_flow(callback.from_user.id)
        await callback.message.answer(str(exc), reply_markup=menu_markup)
        return
    except CompanyAccessError as exc:
        clear_document_flow(callback.from_user.id)
        await callback.message.answer(str(exc), reply_markup=menu_markup)
        return
    except Exception as exc:  # noqa: BLE001
        clear_document_flow(callback.from_user.id)
        logger.exception('Document save failed after duplicate confirmation')
        await callback.message.answer(f'Не удалось сохранить документ: {exc}', reply_markup=menu_markup)
        return
    duplicate_check = pending_document.duplicate_check
    clear_document_flow(callback.from_user.id)
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


async def _ensure_company_access(message: Message) -> bool:
    if message.from_user is None:
        await message.answer('Не удалось определить пользователя.', reply_markup=await _main_menu_markup(message))
        return False
    try:
        await company_service.get_active_company_for_user(message.from_user.id)
    except CompanyAccessError:
        await message.answer(
            'Сначала нужно получить доступ к компании. Используй invite-код руководителя и выполни /join КОД.',
            reply_markup=await _main_menu_markup(message),
        )
        return False
    return True


@router.message(F.photo)
async def process_photo(message: Message) -> None:
    menu_markup = await _main_menu_markup(message)
    if not await _ensure_company_access(message):
        return
    if not message.photo or message.from_user is None:
        await message.answer('Фото не найдено в сообщении.', reply_markup=menu_markup)
        return
    if has_active_document_flow(message.from_user.id):
        await message.answer(
            f'{_person_name(message.from_user)}, у тебя уже есть незавершенный документ. Заверши выбор проекта по текущему документу, прежде чем отправлять новый.',
            reply_markup=menu_markup,
        )
        return

    bot = message.bot
    file_service = TelegramFileService(bot)
    ocr_service = OCRSpaceService()
    deepseek_service = DeepSeekService()
    begin_document_flow(message.from_user.id)

    await message.answer(f'{_person_name(message.from_user)}, фото получено. Начинаю распознавание.', reply_markup=menu_markup)
    try:
        async with ChatActionSender.typing(chat_id=message.chat.id, bot=bot):
            file_path = await file_service.download_best_photo(message.photo)
            async with asyncio.timeout(OCR_TIMEOUT_SECONDS):
                ocr_text = await ocr_service.extract_text(file_path)
    except TimeoutError:
        clear_document_flow(message.from_user.id)
        logger.exception('OCR timed out')
        await message.answer('OCR выполнялся слишком долго. Попробуй отправить документ еще раз.', reply_markup=menu_markup)
        return
    except OCRSpaceError as exc:
        clear_document_flow(message.from_user.id)
        logger.exception('OCR failed')
        await message.answer(f'OCR не удался: {exc}', reply_markup=menu_markup)
        return
    except Exception as exc:  # noqa: BLE001
        clear_document_flow(message.from_user.id)
        logger.exception('Unexpected error while processing photo')
        await message.answer(f'Не удалось обработать фото: {exc}', reply_markup=menu_markup)
        return

    if not ocr_text.strip():
        clear_document_flow(message.from_user.id)
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
        clear_document_flow(message.from_user.id)
        logger.exception('DeepSeek extraction timed out')
        await message.answer('Формирование JSON заняло слишком много времени. Попробуй отправить документ еще раз.', reply_markup=menu_markup)
        return
    except DeepSeekError as exc:
        clear_document_flow(message.from_user.id)
        logger.exception('DeepSeek extraction failed')
        await message.answer(f'Не удалось собрать JSON документа: {exc}', reply_markup=menu_markup)
        return
    except DocumentValidationError as exc:
        clear_document_flow(message.from_user.id)
        await message.answer(str(exc), reply_markup=menu_markup)
        return
    except Exception as exc:  # noqa: BLE001
        clear_document_flow(message.from_user.id)
        logger.exception('Extraction failed')
        await message.answer(f'Не удалось подготовить документ: {exc}', reply_markup=menu_markup)
        return

    store_pending_document(
        message.from_user.id,
        PendingDocument(
            ocr_text=ocr_text,
            normalized_text=preview_text,
            extracted_document=document,
        ),
    )
    for chunk in chunk_message(preview_text):
        await message.answer(chunk, reply_markup=menu_markup)

    try:
        projects = await project_service.list_active_projects(message.from_user.id)
        context = await company_service.get_user_context(message.from_user.id)
    except CompanyAccessError as exc:
        clear_document_flow(message.from_user.id)
        await message.answer(str(exc), reply_markup=menu_markup)
        return

    if not projects and not context.can_manage_company:
        clear_document_flow(message.from_user.id)
        await message.answer('В текущей компании нет активных проектов. Обратись к manager.', reply_markup=menu_markup)
        return

    await message.answer(
        f'{_person_name(message.from_user)}, выбери проект для сохранения документа.',
        reply_markup=build_projects_keyboard(projects, allow_create_project=context.can_manage_company),
    )


@router.callback_query(F.data == PROJECT_CANCEL_CALLBACK)
async def cancel_project_selection(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    clear_document_flow(callback.from_user.id)
    await callback.answer('Загрузка отменена.')
    await callback.message.answer('Подготовка документа отменена.', reply_markup=await _main_menu_markup_for_user(callback.from_user))


@router.callback_query(F.data == PROJECT_CREATE_CALLBACK)
async def create_project_from_document(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    set_pending_action(callback.from_user.id, 'create_project')
    await callback.answer()
    await callback.message.answer(f'{_person_name(callback.from_user)}, отправь название нового проекта.')


@router.callback_query(F.data.startswith(PROJECT_CALLBACK_PREFIX))
async def process_project_selection(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    menu_markup = await _main_menu_markup_for_user(callback.from_user)
    pending_document = get_pending_document(callback.from_user.id)
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
        clear_document_flow(callback.from_user.id)
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
        )
    except DocumentValidationError as exc:
        clear_document_flow(callback.from_user.id)
        await callback.message.answer(str(exc), reply_markup=menu_markup)
        return
    except CompanyAccessError as exc:
        clear_document_flow(callback.from_user.id)
        await callback.message.answer(str(exc), reply_markup=menu_markup)
        return
    except Exception as exc:  # noqa: BLE001
        clear_document_flow(callback.from_user.id)
        logger.exception('Document save failed')
        await callback.message.answer(f'Не удалось сохранить документ: {exc}', reply_markup=menu_markup)
        return

    pop_pending_document(callback.from_user.id)
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
    clear_document_flow(callback.from_user.id)
    await callback.answer('Загрузка отменена.')
    await callback.message.answer('Документ не сохранен. Можно отправить новый файл.', reply_markup=await _main_menu_markup_for_user(callback.from_user))


@router.callback_query(F.data == DOCUMENT_DUPLICATE_SAVE_CALLBACK)
async def duplicate_save_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    pending_document = get_pending_document(callback.from_user.id)
    if pending_document is None or pending_document.duplicate_check is None:
        await callback.answer('Нет документа для подтверждения. Отправь фото заново.', show_alert=True)
        return
    await callback.answer()
    await _save_pending_document(callback, pending_document, await _main_menu_markup_for_user(callback.from_user))


@router.message(~F.text)
async def unsupported_message(message: Message) -> None:
    await message.answer(
        'Поддерживаются кнопки главного меню, /start, /help, /join и фото документов.',
        reply_markup=await _main_menu_markup(message),
    )
