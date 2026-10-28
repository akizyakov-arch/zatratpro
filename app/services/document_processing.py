"""Photo/PDF recognition pipeline. No messenger types, IDs, or transport calls."""
import asyncio
import tempfile
from pathlib import Path

from app.config import TMP_DIR
from app.schemas.document import DocumentSchema
from app.services.deepseek import DeepSeekService
from app.services.documents import DocumentService, DocumentValidationError
from app.services.image_files import prepare_image
from app.services.ocr_space import OCRSpaceError
from app.services.pdf_files import extract_pdf_bytes, MAX_PDF_BYTES, PDFError
from app.services.recognition import create_recognizer

MAX_IMAGE_BYTES = 20 * 1024 * 1024


async def recognize_document(data, source_type, provider, caption='', notify=None):
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
                prepared = await asyncio.to_thread(prepare_image, path)
            except Exception:
                raise DocumentValidationError('Не удалось открыть изображение. Отправьте фото или скан JPEG/PNG.') from None
            try:
                for attempt in range(2):
                    try:
                        async with asyncio.timeout(120):
                            text = await ocr.extract_text(prepared)
                        break
                    except (TimeoutError, OCRSpaceError) as exc:
                        if attempt or (isinstance(exc, OCRSpaceError) and 'E101' not in str(exc)):
                            raise
                        if notify:
                            await notify('OCR занял слишком много времени, пробую ещё раз.')
                        await asyncio.sleep(3)
            finally:
                prepared.unlink(missing_ok=True)
    if not text.strip():
        raise DocumentValidationError('OCR не вернул текст. Попробуйте более чёткое фото.')
    if notify:
        await notify('Распознавание завершено. Извлекаю структуру документа.')
    async with asyncio.timeout(120):
        values = await DeepSeekService().extract_document(text)
    document = DocumentSchema.model_validate({**values, 'raw_text': text})
    DocumentService()._ensure_expense_document(document)
    return text, document
