from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pymupdf
from aiogram import Bot
from aiogram.types import Document
from PIL import Image

from app.config import TMP_DIR
from app.services.telegram_files import DownloadedTelegramPhoto, OCR_JPEG_QUALITY, OCR_MAX_WIDTH


PDF_RENDER_SCALE = 2.0


class PDFFileService:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def download_pdf_document(self, document: Document) -> DownloadedTelegramPhoto:
        telegram_file = await self.bot.get_file(document.file_id)
        source_path = TMP_DIR / f'{uuid4()}-source.pdf'
        await self.bot.download_file(telegram_file.file_path, destination=source_path)
        original_filename = document.file_name or Path(telegram_file.file_path or '').name or 'telegram_document.pdf'
        try:
            ocr_path = self._render_first_page_for_ocr(source_path)
        except Exception:
            source_path.unlink(missing_ok=True)
            raise
        return DownloadedTelegramPhoto(
            source_path=source_path,
            ocr_path=ocr_path,
            original_filename=original_filename,
            mime_type='application/pdf',
            file_ext='.pdf',
            original_file_size=source_path.stat().st_size,
            normalized_file_size=ocr_path.stat().st_size,
            original_kind='pdf',
        )

    def _render_first_page_for_ocr(self, source_path: Path) -> Path:
        prepared_path = TMP_DIR / f'{uuid4()}.jpg'
        with pymupdf.open(source_path) as pdf:
            if pdf.page_count < 1:
                raise ValueError('PDF не содержит страниц.')
            page = pdf.load_page(0)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(PDF_RENDER_SCALE, PDF_RENDER_SCALE), alpha=False)
        with Image.open(BytesIO(pix.tobytes('png'))) as image:
            if image.mode != 'RGB':
                image = image.convert('RGB')
            width, height = image.size
            if width > OCR_MAX_WIDTH:
                resized_height = int(height * (OCR_MAX_WIDTH / width))
                image = image.resize((OCR_MAX_WIDTH, resized_height), Image.Resampling.LANCZOS)
            image.save(prepared_path, format='JPEG', quality=OCR_JPEG_QUALITY, optimize=True)
        return prepared_path
