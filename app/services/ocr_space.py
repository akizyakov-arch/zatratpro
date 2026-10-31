"""One OCR.space HTTP request; retry and page budgets belong to recognition_runtime."""
import asyncio
import logging
import re
import time
from secrets import token_hex
from pathlib import Path
import httpx
from app.config import get_recognition_settings as get_settings
from app.services.recognition_errors import RecognitionError
from app.services.recognition_clients import provider_client

# Compatibility for existing handlers and third-party provider adapters.
OCRSpaceError = RecognitionError
logger = logging.getLogger(__name__)
API_URL = 'https://api.ocr.space/parse/image'


def _provider_code(payload):
    if not isinstance(payload, dict):
        return None
    for field in ('error', 'ErrorMessage'):
        values = payload.get(field, [])
        for value in values if isinstance(values, list) else [values]:
            if isinstance(value, str):
                match = re.search(r'\bE[0-9]{3}\b', value)
                if match:
                    return match.group()
    return None


def _parse_response(response):
    try:
        payload = response.json()
    except ValueError:
        if response.status_code != 200:
            raise RecognitionError(f'OCR.space отказал в обработке: HTTP {response.status_code}.', code='http_error') from None
        raise RecognitionError('OCR.space вернул некорректный ответ.', code='invalid_response') from None
    code = _provider_code(payload)
    if code == 'E550' or response.status_code == 401:
        raise RecognitionError('OCR.space отклонил ключ API. Проверьте OCR_SPACE_API_KEY.', code=code or 'authentication')
    if response.status_code != 200:
        raise RecognitionError(f'OCR.space отказал в обработке: HTTP {response.status_code}.', code=code or 'http_error')
    if not isinstance(payload, dict):
        raise RecognitionError('OCR.space вернул некорректный ответ.', code='invalid_response')
    if payload.get('IsErroredOnProcessing'):
        message = 'OCR.space временно не смог обработать файл (E101).' if code == 'E101' else 'OCR.space сообщил об ошибке обработки файла.'
        raise RecognitionError(message, code=code or 'processing_error', retryable=code == 'E101')
    results = payload.get('ParsedResults') or []
    if not isinstance(results, list) or any(not isinstance(row, dict) or not isinstance(row.get('ParsedText', ''), str) for row in results):
        raise RecognitionError('OCR.space вернул некорректный текст.', code='invalid_response')
    return '\n'.join(row.get('ParsedText', '').strip() for row in results if row.get('ParsedText', '').strip())


class OCRSpaceService:
    provider_name = 'ocr_space'

    async def extract_text(self, file_path: Path) -> str:
        settings = get_settings()
        key = settings.ocr_space_api_key
        configured_proxy = getattr(settings, 'ocr_space_proxy_url', None)
        proxy = configured_proxy.get_secret_value() if configured_proxy is not None else ''
        if not key:
            raise RecognitionError('Не задан ключ OCR_SPACE_API_KEY.', code='authentication')
        request_id = token_hex(6)
        started = time.monotonic()
        logger.warning('ocr_space_start request=%s bytes=%s route=%s', request_id, file_path.stat().st_size, 'explicit_proxy' if proxy else 'environment')

        async def trace(event, info):
            # Whitelist event names only; info can contain private headers/body.
            if event in ('connection.connect_tcp.complete', 'connection.start_tls.complete',
                         'http11.send_request_body.complete', 'http11.receive_response_headers.complete',
                         'http2.send_request_body.complete', 'http2.receive_response_headers.complete'):
                logger.warning('ocr_space_transport request=%s stage=%s elapsed=%.2f', request_id, event, time.monotonic()-started)
        try:
            proxy_options = {'proxy': proxy} if proxy else {}
            async with provider_client(timeout=httpx.Timeout(120, connect=20), **proxy_options) as client:
                with file_path.open('rb') as image_file:
                    response = await client.post(API_URL,
                        data={'apikey': key, 'language': 'rus', 'OCREngine': 2},
                        files={'file': (file_path.name, image_file, 'image/jpeg')},
                        extensions={'trace': trace})
            logger.warning('ocr_space_response request=%s status=%s elapsed=%.2f', request_id, response.status_code, time.monotonic()-started)
            text = _parse_response(response)
            return text
        except asyncio.CancelledError:
            logger.warning('ocr_space_cancelled request=%s elapsed=%.2f', request_id, time.monotonic()-started)
            raise
        except httpx.TimeoutException:
            logger.warning('ocr_space_failed request=%s code=timeout elapsed=%.2f', request_id, time.monotonic()-started)
            raise RecognitionError('OCR.space не ответил вовремя.', code='timeout', retryable=True) from None
        except httpx.HTTPError:
            logger.warning('ocr_space_failed request=%s code=network elapsed=%.2f', request_id, time.monotonic()-started)
            raise RecognitionError(f'Ошибка подключения к OCR.space. Код проверки: {request_id}.', code='network') from None
        except RecognitionError as exc:
            logger.warning('ocr_space_failed request=%s code=%s elapsed=%.2f', request_id, exc.code, time.monotonic()-started)
            raise
