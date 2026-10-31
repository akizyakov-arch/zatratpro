"""Photo/PDF recognition pipeline. No messenger types, IDs, or transport calls."""
import asyncio
import logging
import time
import tempfile
from pathlib import Path

from app.config import TMP_DIR
from app.schemas.document import DocumentSchema
from app.services.deepseek import DeepSeekService
from app.services.documents import DocumentService, DocumentValidationError
from app.services.image_files import prepare_image
from app.services.recognition_runtime import extract_page
from app.services.pdf_files import extract_pdf_bytes, MAX_PDF_BYTES, PDFError
from app.services.recognition import create_recognizer
from app.services.recognition_clients import recognition_session
from app.services.async_work import run_blocking

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 20 * 1024 * 1024


async def recognize_document(data, source_type, provider, caption='', notify=None):
    async with recognition_session():
        return await _recognize_document(data, source_type, provider, caption, notify)


async def _recognize_document(data, source_type, provider, caption='', notify=None):
    if source_type not in ('photo', 'pdf'):
        raise DocumentValidationError('Отправьте фотографию или PDF документа.')
    limit = MAX_PDF_BYTES if source_type == 'pdf' else MAX_IMAGE_BYTES
    if not data or len(data) > limit:
        raise DocumentValidationError(f'Файл пустой или слишком большой. Максимум {limit//1024//1024} МБ.')
    ocr = create_recognizer(provider)
    if source_type == 'pdf':
        async with asyncio.timeout(600):
            text = await extract_pdf_bytes(data, ocr, caption, notify)
    else:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='image-', dir=TMP_DIR) as directory:
            path = Path(directory) / 'source'
            path.write_bytes(data)
            try:
                prepared = await run_blocking(prepare_image, path, Path(directory))
            except Exception:
                raise DocumentValidationError('Не удалось открыть изображение. Отправьте фото или скан JPEG/PNG.') from None
            try:
                text = await extract_page(ocr, prepared, notify, provider=provider)
            finally:
                prepared.unlink(missing_ok=True)
    if not text.strip():
        raise DocumentValidationError('OCR не вернул текст. Попробуйте более чёткое фото.')
    if notify:
        await notify('Распознавание завершено. Извлекаю структуру документа.')
    started = time.monotonic()
    logger.warning('document_parse_start provider=%s source=%s', provider, source_type)
    try:
        async with asyncio.timeout(120):
            values = await DeepSeekService().extract_document(text)
    except Exception as exc:
        logger.warning('document_parse_failed provider=%s error_type=%s elapsed=%.2f', provider, type(exc).__name__, time.monotonic()-started)
        raise
    logger.warning('document_parse_done provider=%s elapsed=%.2f', provider, time.monotonic()-started)
    document = DocumentSchema.model_validate({**values, 'raw_text': text})
    DocumentService()._ensure_expense_document(document)
    return text, document
