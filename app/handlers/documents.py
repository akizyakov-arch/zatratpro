import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender

from app.schemas.document import DocumentSchema
from app.services.companies import CompanyAccessError, CompanyService
from app.services.deepseek import DeepSeekError, DeepSeekService
from app.services.documents import DocumentService
from app.services.json_formatter import chunk_message
from app.services.ocr_space import OCRSpaceError, OCRSpaceService
from app.services.projects import ProjectService
from app.services.telegram_files import TelegramFileService
from app.state.pending_actions import set_pending_action
from app.state.pending_documents import PendingDocument, get_pending_document, pop_pending_document, store_pending_document
from app.ui.main_menu import build_main_menu_keyboard
from app.ui.projects import PROJECT_CALLBACK_PREFIX, PROJECT_CREATE_CALLBACK, build_projects_keyboard


router = Router()
logger = logging.getLogger(__name__)
project_service = ProjectService()
document_service = DocumentService()
company_service = CompanyService()


async def _main_menu_markup(message: Message) -> object:
    if message.from_user is None:
        return build_main_menu_keyboard(has_company=False)
    await company_service.ensure_platform_user(message.from_user)
    context = await company_service.get_user_context(message.from_user.id)
    return build_main_menu_keyboard(menu_kind=context.menu_kind, has_company=context.has_company)


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

    bot = message.bot
    file_service = TelegramFileService(bot)
    ocr_service = OCRSpaceService()
    deepseek_service = DeepSeekService()

    await message.answer('Фото получено. Начинаю распознавание.', reply_markup=menu_markup)
    try:
        async with ChatActionSender.typing(chat_id=message.chat.id, bot=bot):
            file_path = await file_service.download_best_photo(message.photo)
            ocr_text = await ocr_service.extract_text(file_path)
    except OCRSpaceError as exc:
        logger.exception('OCR failed')
        await message.answer(f'OCR не удался: {exc}', reply_markup=menu_markup)
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception('Unexpected error while processing photo')
        await message.answer(f'Не удалось обработать фото: {exc}', reply_markup=menu_markup)
        return

    if not ocr_text.strip():
        await message.answer('OCR не вернул текст. Попробуй более четкое фото.', reply_markup=menu_markup)
        return

    await message.answer('OCR завершен. Нормализую документ.', reply_markup=menu_markup)
    try:
        async with ChatActionSender.typing(chat_id=message.chat.id, bot=bot):
            normalized_text = await deepseek_service.normalize_document_text(ocr_text)
    except DeepSeekError as exc:
        logger.exception('DeepSeek normalization failed')
        await message.answer(f'Не удалось нормализовать документ: {exc}', reply_markup=menu_markup)
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception('Normalization failed')
        await message.answer(f'Не удалось подготовить документ: {exc}', reply_markup=menu_markup)
        return

    store_pending_document(message.from_user.id, PendingDocument(ocr_text=ocr_text, normalized_text=normalized_text))
    for chunk in chunk_message(normalized_text):
        await message.answer(chunk, reply_markup=menu_markup)

    try:
        projects = await project_service.list_active_projects(message.from_user.id)
        context = await company_service.get_user_context(message.from_user.id)
    except CompanyAccessError as exc:
        await message.answer(str(exc), reply_markup=menu_markup)
        return

    if not projects and not context.can_manage_company:
        await message.answer('В текущей компании нет активных проектов. Обратись к manager.', reply_markup=menu_markup)
        return

    await message.answer(
        'Выбери проект для сохранения документа.',
        reply_markup=build_projects_keyboard(projects, allow_create_project=context.can_manage_company),
    )


@router.callback_query(F.data == PROJECT_CREATE_CALLBACK)
async def create_project_from_document(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    set_pending_action(callback.from_user.id, 'create_project')
    await callback.answer()
    await callback.message.answer('Отправь название нового проекта.')


@router.callback_query(F.data.startswith(PROJECT_CALLBACK_PREFIX))
async def process_project_selection(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    menu_markup = await _main_menu_markup(callback.message)
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

    deepseek_service = DeepSeekService()
    await callback.answer()
    await callback.message.answer('Проверяю документ...', reply_markup=menu_markup)
    try:
        async with ChatActionSender.typing(chat_id=callback.message.chat.id, bot=callback.bot):
            extracted_document = await deepseek_service.extract_document(pending_document.ocr_text)
        document = DocumentSchema.model_validate({**extracted_document, 'raw_text': pending_document.ocr_text})
        document_id = await document_service.save_document(
            telegram_user=callback.from_user,
            project=project,
            normalized_text=pending_document.normalized_text,
            document=document,
            source_type='photo',
        )
    except DeepSeekError as exc:
        logger.exception('DeepSeek extraction failed')
        await callback.message.answer(f'Не удалось собрать JSON документа: {exc}', reply_markup=menu_markup)
        return
    except CompanyAccessError as exc:
        await callback.message.answer(str(exc), reply_markup=menu_markup)
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception('Document save failed')
        await callback.message.answer(f'Не удалось сохранить документ: {exc}', reply_markup=menu_markup)
        return

    pop_pending_document(callback.from_user.id)
    await callback.message.answer(f'Документ сохранен в проект "{project.name}". ID записи: {document_id}.', reply_markup=menu_markup)


@router.message()
async def unsupported_message(message: Message) -> None:
    await message.answer(
        'Поддерживаются кнопки главного меню, /start, /help, /join и фото документов.',
        reply_markup=await _main_menu_markup(message),
    )
