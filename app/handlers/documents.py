import json
import logging

from aiogram import F, Router
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from app.schemas.document import DocumentSchema
from app.services.deepseek import DeepSeekError, DeepSeekService
from app.services.json_formatter import chunk_message, format_document_json, format_document_preview
from app.services.ocr_space import OCRSpaceError, OCRSpaceService
from app.services.telegram_files import TelegramFileService


router = Router()
logger = logging.getLogger(__name__)


@router.message(F.photo)
async def process_photo(message: Message) -> None:
    if not message.photo:
        await message.answer("Фото не найдено в сообщении.")
        return

    bot = message.bot
    file_service = TelegramFileService(bot)
    ocr_service = OCRSpaceService()
    deepseek_service = DeepSeekService()

    await message.answer("Фото получено. Начинаю распознавание.")

    try:
        async with ChatActionSender.typing(chat_id=message.chat.id, bot=bot):
            file_path = await file_service.download_best_photo(message.photo)
            ocr_text = await ocr_service.extract_text(file_path)
    except OCRSpaceError as exc:
        logger.exception("OCR failed")
        await message.answer(f"OCR не удался: {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error while processing photo")
        await message.answer(f"Не удалось обработать фото: {exc}")
        return

    if not ocr_text.strip():
        await message.answer("OCR не вернул текст. Попробуй более четкое фото.")
        return

    await message.answer("OCR завершен. Подготавливаю структуру документа.")

    try:
        async with ChatActionSender.typing(chat_id=message.chat.id, bot=bot):
            cleaned_text = await deepseek_service.clean_ocr_text(ocr_text)
            document = await deepseek_service.extract_document(cleaned_text)
            validated = DocumentSchema.model_validate(document)
    except DeepSeekError as exc:
        logger.exception("DeepSeek failed")
        await message.answer(f"Не удалось собрать JSON: {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("JSON validation failed")
        await message.answer(f"JSON не прошел проверку: {exc}")
        return

    preview = format_document_preview(validated)
    for chunk in chunk_message(preview):
        await message.answer(chunk)

    formatted = format_document_json(json.loads(validated.model_dump_json()))
    for chunk in chunk_message(f"Структурированный JSON:\n```json\n{formatted}\n```"):
        await message.answer(chunk, parse_mode="Markdown")


@router.message()
async def unsupported_message(message: Message) -> None:
    await message.answer("Поддерживаются команды /start, /help и фото документов.")
