"""Single page OCR deadline/retry policy shared by photos and rendered PDF pages."""
import asyncio
import logging
import time
from PIL import Image
from app.services.recognition_errors import RecognitionError

logger = logging.getLogger(__name__)
PAGE_TIMEOUT = 120
PAGE_ATTEMPTS = 2
RETRY_DELAY = 3

async def extract_page(recognizer, path, notify=None, *, provider=None):
    provider = provider or getattr(recognizer, 'provider_name', None)
    provider = provider if provider in ('ocr_space', 'deepseek') else 'unknown'
    try:
        with Image.open(path) as image:
            width, height = image.size
    except (OSError, ValueError):
        width = height = None
    size = path.stat().st_size
    for attempt in range(1, PAGE_ATTEMPTS + 1):
        started = time.monotonic()
        logger.warning('document_ocr_start provider=%s attempt=%s bytes=%s width=%s height=%s', provider, attempt, size, width, height)
        try:
            async with asyncio.timeout(PAGE_TIMEOUT):
                text = await recognizer.extract_text(path)
            logger.warning('document_ocr_done provider=%s attempt=%s elapsed=%.2f chars=%s', provider, attempt, time.monotonic()-started, len(text))
            return text
        except TimeoutError:
            error = RecognitionError('Распознавание не завершилось за 120 секунд.', code='timeout', retryable=True)
        except RecognitionError as exc:
            error = exc
        logger.warning('document_ocr_failed provider=%s attempt=%s code=%s elapsed=%.2f', provider, attempt, error.code or 'provider_error', time.monotonic()-started)
        # E101 text compatibility is retained for legacy/custom recognizers.
        retryable = error.retryable or 'E101' in str(error)
        if not retryable or attempt == PAGE_ATTEMPTS:
            if error.code == 'timeout':
                raise RecognitionError('Распознавание не завершилось за две попытки по 120 секунд. Повторите позже или выберите другой сервис в настройках.', code='timeout') from None
            raise error from None
        if notify:
            await notify('OCR не завершился. Пробую ещё раз (попытка 2 из 2).')
        await asyncio.sleep(RETRY_DELAY)
