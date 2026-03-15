import logging

from aiogram import F, Router
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from app.services.deepseek import DeepSeekError, DeepSeekService
from app.services.json_formatter import chunk_message
from app.services.ocr_space import OCRSpaceError, OCRSpaceService
from app.services.telegram_files import TelegramFileService
from app.ui.main_menu import build_main_menu_keyboard


router = Router()
logger = logging.getLogger(__name__)


@router.message(F.photo)
async def process_photo(message: Message) -> None:
    if not message.photo:
        await message.answer("Фото не найдено в сообщении.", reply_markup=build_main_menu_keyboard())
        return

    bot = message.bot
    file_service = TelegramFileService(bot)
    ocr_service = OCRSpaceService()
    deepseek_service = DeepSeekService()

    await message.answer("Фото получено. Начинаю распознавание.", reply_markup=build_main_menu_keyboard())

    try:
        async with ChatActionSender.typing(chat_id=message.chat.id, bot=bot):
            file_path = await file_service.download_best_photo(message.photo)
            ocr_text = await ocr_service.extract_text(file_path)
    except OCRSpaceError as exc:
        logger.exception("OCR failed")
        await message.answer(f"OCR не удался: {exc}", reply_markup=build_main_menu_keyboard())
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error while processing photo")
        await message.answer(f"Не удалось обработать фото: {exc}", reply_markup=build_main_menu_keyboard())
        return

    if not ocr_text.strip():
        await message.answer("OCR не вернул текст. Попробуй более четкое фото.", reply_markup=build_main_menu_keyboard())
        return

    await message.answer("OCR завершен. Нормализую документ.", reply_markup=build_main_menu_keyboard())

    try:
        async with ChatActionSender.typing(chat_id=message.chat.id, bot=bot):
            normalized_text = await deepseek_service.normalize_document_text(ocr_text)
    except DeepSeekError as exc:
        logger.exception("DeepSeek normalization failed")
        await message.answer(f"Не удалось нормализовать документ: {exc}", reply_markup=build_main_menu_keyboard())
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("Normalization failed")
        await message.answer(f"Не удалось подготовить документ: {exc}", reply_markup=build_main_menu_keyboard())
        return

    for chunk in chunk_message(normalized_text):
        await message.answer(chunk, reply_markup=build_main_menu_keyboard())

    await message.answer(
        "Документ подготовлен. Следующий шаг: выбрать проект, после чего я соберу JSON для сохранения.",
        reply_markup=build_main_menu_keyboard(),
    )


@router.message()
async def unsupported_message(message: Message) -> None:
    await message.answer(
        "Поддерживаются команды /start, /help, кнопки главного меню и фото документов.",
        reply_markup=build_main_menu_keyboard(),
    )
