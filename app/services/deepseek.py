import asyncio
import json
import logging
import re
from time import perf_counter

import httpx

from app.config import get_settings
from app.prompts.cleanup_prompt import CLEANUP_PROMPT
from app.prompts.extraction_prompt import EXTRACTION_PROMPT
from app.services.http_clients import get_deepseek_client


class DeepSeekError(RuntimeError):
    pass


logger = logging.getLogger(__name__)
SLOW_DEEPSEEK_STAGE_MS = 500.0


CURRENCY_SYMBOLS = {
    "RUB": "₽",
    "USD": "$",
    "EUR": "€",
}


RETRYABLE_HTTP_EXCEPTIONS = (
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.ConnectError,
    httpx.ProxyError,
    httpx.RemoteProtocolError,
)


class DeepSeekService:
    async def normalize_document_text(self, ocr_text: str) -> str:
        settings = get_settings()
        payload = {
            "model": settings.deepseek_model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": CLEANUP_PROMPT},
                {"role": "user", "content": ocr_text},
            ],
        }

        response = await _post_chat_completion(payload, settings)
        content = (
            response.json()
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if not content:
            raise DeepSeekError("DeepSeek вернул пустой нормализованный текст.")
        return _apply_currency_symbols(content)

    async def extract_document(self, ocr_text: str, *, system_prompt: str | None = None) -> dict:
        started = perf_counter()
        settings = get_settings()
        payload = {
            "model": settings.deepseek_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt or EXTRACTION_PROMPT},
                {"role": "user", "content": ocr_text},
            ],
        }
        after_payload = perf_counter()

        response = await _post_chat_completion(payload, settings)
        after_post = perf_counter()
        response_data = response.json()
        after_json = perf_counter()
        content = (
            response_data
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        after_content = perf_counter()
        if not content:
            raise DeepSeekError("DeepSeek вернул пустой ответ.")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise DeepSeekError("DeepSeek вернул невалидный JSON.") from exc
        after_parse = perf_counter()
        parsed["raw_text"] = ocr_text

        total_ms = (after_parse - started) * 1000
        if total_ms >= SLOW_DEEPSEEK_STAGE_MS:
            logger.warning(
                "DeepSeek extract stages: payload=%.1fms post=%.1fms response_json=%.1fms content=%.1fms parse=%.1fms total=%.1fms ocr_chars=%s content_chars=%s",
                (after_payload - started) * 1000,
                (after_post - after_payload) * 1000,
                (after_json - after_post) * 1000,
                (after_content - after_json) * 1000,
                (after_parse - after_content) * 1000,
                total_ms,
                len(ocr_text),
                len(content),
            )
        return parsed


async def _post_chat_completion(payload: dict, settings) -> httpx.Response:
    proxy_url = settings.effective_deepseek_proxy_url

    attempts = max(settings.deepseek_max_retries + 1, 1)
    last_exc = None
    client = await get_deepseek_client()
    for attempt in range(1, attempts + 1):
        try:
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
            return response
        except RETRYABLE_HTTP_EXCEPTIONS as exc:
            last_exc = exc
            if attempt >= attempts:
                break
            logger.warning(
                "DeepSeek request retrying: attempt=%s/%s proxy=%s reason=%s",
                attempt + 1,
                attempts,
                "on" if proxy_url else "off",
                exc.__class__.__name__,
            )
            await asyncio.sleep(min(attempt, 3))
        except httpx.HTTPError as exc:
            raise DeepSeekError(f"Ошибка сети DeepSeek: {exc}") from exc

    raise DeepSeekError(f"Ошибка сети DeepSeek: {last_exc}") from last_exc


def _apply_currency_symbols(text: str) -> str:
    for code, symbol in CURRENCY_SYMBOLS.items():
        text = re.sub(rf"\b{code}\b", symbol, text, flags=re.IGNORECASE)
    return text
