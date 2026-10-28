"""Bounded PDF rendering in a separate process; no uploaded filenames are used."""
import asyncio
from io import BytesIO
import json
import logging
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from app.config import TMP_DIR

logger = logging.getLogger(__name__)

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 10


class PDFError(ValueError):
    pass


class LimitedDownload(BytesIO):
    def write(self, data):
        if self.tell() + len(data) > MAX_PDF_BYTES:
            raise PDFError('PDF слишком большой. Максимум 10 МБ.')
        return super().write(data)


def page_selection(caption, count):
    value = (caption or '').strip().lower()
    if not value and count == 1:
        return [0]
    if value in ('все', 'all'):
        return list(range(count))
    match = re.fullmatch(r'([0-9]{1,3})(?:\s*-\s*([0-9]{1,3}))?', value)
    if match:
        first = int(match[1]); last = int(match[2] or match[1])
        if 1 <= first <= last <= count:
            return list(range(first - 1, last))
    raise PDFError(f'В PDF {count} стр. Отправь файл с подписью: номер страницы (например, 2), диапазон (1-3) или «все», если это один документ. Разные документы отправляй отдельными диапазонами.')


def render_pdf(source, directory, caption):
    import pypdfium2 as pdfium
    try:
        with pdfium.PdfDocument(source) as pdf:
            count = len(pdf)
            if not 1 <= count <= MAX_PDF_PAGES:
                raise PDFError('Допускается PDF от 1 до 10 страниц. Раздели большой файл на части.')
            pages = page_selection(caption, count)
            for number in pages:
                page = pdf[number]
                try:
                    width, height = page.get_size()
                    if min(width, height) <= 0:
                        raise PDFError('Некорректный размер страницы PDF.')
                    bitmap = page.render(scale=1800 / max(width, height))
                    try:
                        image = bitmap.to_pil().convert('RGB')
                        try:
                            image.save(Path(directory) / f'{number + 1}.jpg', quality=88)
                        finally:
                            image.close()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            return pages
    except PDFError:
        raise
    except Exception:
        raise PDFError('Не удалось открыть PDF. Проверь, что файл не повреждён и не защищён паролем.') from None


def _render_worker(source, directory, caption):
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'app.services.pdf_files', str(source), str(directory), caption or ''],
            capture_output=True, text=True, timeout=60,
        )
        payload = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, ValueError):
        raise PDFError('Не удалось обработать PDF за отведённое время. Попробуй меньший файл.') from None
    if 'error' in payload:
        raise PDFError(payload['error'])
    return payload['pages']


async def extract_pdf_bytes(data, ocr_service, caption='', notify=None):
    if len(data) > MAX_PDF_BYTES:
        raise PDFError('PDF слишком большой. Максимум 10 МБ.')
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pdf-', dir=TMP_DIR) as directory:
        source = Path(directory) / 'source.pdf'
        if not data.startswith(b'%PDF-'):
            raise PDFError('Файл не является PDF. Отправь PDF или фотографию документа.')
        source.write_bytes(data)
        pages = await asyncio.to_thread(_render_worker, source, directory, caption)
        texts = []
        for number in pages:
            if notify:
                await notify(f'Распознаю страницу {number + 1} PDF…')
            logger.info('pdf_page_start page=%s provider=%s', number + 1, type(ocr_service).__name__)
            text = await ocr_service.extract_text(Path(directory) / f'{number + 1}.jpg')
            logger.info('pdf_page_done page=%s chars=%s', number + 1, len(text))
            if not text.strip():
                raise PDFError(f'На странице {number + 1} не удалось прочитать текст. Документ не сохранён. Проверь скан или выбери другой диапазон страниц.')
            texts.append(f'--- Страница {number + 1} ---\n{text}')
        return '\n\n'.join(texts)


if __name__ == '__main__':
    try:
        print(json.dumps({'pages': render_pdf(sys.argv[1], sys.argv[2], sys.argv[3])}))
    except PDFError as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
