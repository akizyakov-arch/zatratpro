from pathlib import Path
from uuid import uuid4

from aiogram import Bot
from aiogram.types import PhotoSize
from PIL import Image, ImageOps

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
        await self.bot.download_file(telegram_file.file_path, destination=original_path)
        return self._prepare_image_for_ocr(original_path)

    def _prepare_image_for_ocr(self, source_path: Path) -> Path:
        prepared_path = TMP_DIR / f"{uuid4()}.jpg"
        with Image.open(source_path) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            elif image.mode == "L":
                image = image.convert("RGB")
            width, height = image.size
            if width > OCR_MAX_WIDTH:
                resized_height = int(height * (OCR_MAX_WIDTH / width))
                image = image.resize((OCR_MAX_WIDTH, resized_height), Image.Resampling.LANCZOS)
            image.save(prepared_path, format="JPEG", quality=OCR_JPEG_QUALITY, optimize=True)
        try:
            source_path.unlink(missing_ok=True)
        except Exception:
            pass
        return prepared_path
