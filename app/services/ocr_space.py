import asyncio
import logging
import time
from secrets import token_hex
from pathlib import Path

import httpx

from app.config import get_recognition_settings as get_settings


logger = logging.getLogger(__name__)


class OCRSpaceError(RuntimeError):
    pass


class OCRSpaceService:
    async def extract_text(self, file_path: Path) -> str:
        settings = get_settings()
        response = None
        last_error: Exception | None = None

        request_id = token_hex(6)
        for attempt in range(1, 4):
            started = time.monotonic()
            logger.warning('ocr_space_start request=%s attempt=%s', request_id, attempt)
            try:
                timeout = httpx.Timeout(120.0, connect=20.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    with file_path.open("rb") as image_file:
                        response = await client.post(
                            "https://api.ocr.space/parse/image",
                            data={
                                "apikey": settings.ocr_space_api_key,
                                "language": "rus",
                                "OCREngine": 2,
                            },
                            files={"file": (file_path.name, image_file, "image/jpeg")},
                        )
                response.raise_for_status()
                logger.warning('ocr_space_response request=%s attempt=%s status=%s elapsed=%.2f', request_id, attempt, response.status_code, time.monotonic()-started)
                break
            except asyncio.CancelledError:
                logger.warning('ocr_space_cancelled request=%s attempt=%s elapsed=%.2f', request_id, attempt, time.monotonic()-started)
                raise
            except httpx.ReadTimeout as exc:
                logger.warning('ocr_space_read_timeout request=%s attempt=%s elapsed=%.2f', request_id, attempt, time.monotonic()-started)
                last_error = exc
                if attempt == 3:
                    raise OCRSpaceError("OCR.Space не ответил вовремя. Попробуй отправить документ еще раз.") from exc
            except httpx.HTTPError as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                logger.warning('ocr_space_failed request=%s attempt=%s error_type=%s status=%s elapsed=%.2f', request_id, attempt, type(exc).__name__, status, time.monotonic()-started)
                raise OCRSpaceError(f'Ошибка подключения к OCR.space. Код проверки: {request_id}.') from None

        if response is None:
            raise OCRSpaceError(f"Ошибка сети OCR.Space: {last_error}")

        payload = response.json()
        parsed_results = payload.get("ParsedResults") or []
        texts = [item.get("ParsedText", "").strip() for item in parsed_results]
        text = "\n".join(filter(None, texts)).strip()

        if payload.get("IsErroredOnProcessing"):
            message = "; ".join(payload.get("ErrorMessage") or ["OCR.Space вернул ошибку"])
            raise OCRSpaceError(message)

        return text
