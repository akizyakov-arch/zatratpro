from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from aiogram import Bot
from aiogram.types import Document, PhotoSize
from PIL import Image, ImageOps

from app.config import TMP_DIR


OCR_MAX_WIDTH = 2000
OCR_JPEG_QUALITY = 88


@dataclass(slots=True)
class DownloadedTelegramPhoto:
    source_path: Path
    ocr_path: Path
    original_filename: str
    mime_type: str
    file_ext: str


class TelegramFileService:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def download_best_photo(self, photos: list[PhotoSize]) -> DownloadedTelegramPhoto:
        photo = photos[-1]
        telegram_file = await self.bot.get_file(photo.file_id)
        source_path = TMP_DIR / f'{uuid4()}-source.jpg'
        await self.bot.download_file(telegram_file.file_path, destination=source_path)
        file_ext = source_path.suffix or '.jpg'
        original_filename = Path(telegram_file.file_path or '').name or f'telegram_photo{file_ext}'
        return DownloadedTelegramPhoto(
            source_path=source_path,
            ocr_path=self._prepare_image_for_ocr(source_path),
            original_filename=original_filename,
            mime_type='image/jpeg',
            file_ext=file_ext,
        )


    async def download_image_document(self, document: Document) -> DownloadedTelegramPhoto:
        telegram_file = await self.bot.get_file(document.file_id)
        file_ext = Path(document.file_name or '').suffix.lower() or '.jpg'
        source_path = TMP_DIR / f'{uuid4()}-source{file_ext}'
        await self.bot.download_file(telegram_file.file_path, destination=source_path)
        original_filename = document.file_name or Path(telegram_file.file_path or '').name or f'telegram_document{file_ext}'
        mime_type = document.mime_type or 'application/octet-stream'
        return DownloadedTelegramPhoto(
            source_path=source_path,
            ocr_path=self._prepare_image_for_ocr(source_path),
            original_filename=original_filename,
            mime_type=mime_type,
            file_ext=file_ext,
        )

    def delete_temp_file(self, path: Path | None) -> None:
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass

    def _prepare_image_for_ocr(self, source_path: Path) -> Path:
        prepared_path = TMP_DIR / f'{uuid4()}.jpg'
        with Image.open(source_path) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode not in ('RGB', 'L'):
                image = image.convert('RGB')
            elif image.mode == 'L':
                image = image.convert('RGB')
            width, height = image.size
            if width > OCR_MAX_WIDTH:
                resized_height = int(height * (OCR_MAX_WIDTH / width))
                image = image.resize((OCR_MAX_WIDTH, resized_height), Image.Resampling.LANCZOS)
            image.save(prepared_path, format='JPEG', quality=OCR_JPEG_QUALITY, optimize=True)
        return prepared_path
