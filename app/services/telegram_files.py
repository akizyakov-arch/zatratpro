from pathlib import Path
from uuid import uuid4

from aiogram import Bot
from aiogram.types import PhotoSize

from app.config import TMP_DIR


OCR_MAX_WIDTH = 2000
OCR_JPEG_QUALITY = 88


class TelegramFileService:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def download_best_photo(self, photos: list[PhotoSize]) -> Path:
        photo = photos[-1]
        telegram_file = await self.bot.get_file(photo.file_id)
        original_path = TMP_DIR / f"{uuid4()}-raw.jpg"
        try:
            await self.bot.download_file(telegram_file.file_path, destination=original_path)
            return self._prepare_image_for_ocr(original_path)
        finally:
            original_path.unlink(missing_ok=True)

    def _prepare_image_for_ocr(self, source_path: Path) -> Path:
        from app.services.image_files import prepare_image
        return prepare_image(source_path, TMP_DIR)
