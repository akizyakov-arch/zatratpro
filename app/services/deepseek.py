import json
import logging
import re
from time import perf_counter

import httpx

from app.config import get_settings
from app.prompts.cleanup_prompt import CLEANUP_PROMPT
from app.prompts.extraction_prompt import EXTRACTION_PROMPT


class DeepSeekError(RuntimeError):
    pass


logger = logging.getLogger(__name__)
SLOW_DEEPSEEK_STAGE_MS = 500.0


CURRENCY_SYMBOLS = {
    "RUB": "₽",
    "USD": "$",
    "EUR": "€",
}


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

        try:
            async with httpx.AsyncClient(
                base_url=settings.deepseek_base_url,
                timeout=60,
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            ) as client:
                response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DeepSeekError(f"Ошибка сети DeepSeek: {exc}") from exc

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

    async def extract_document(self, ocr_text: str) -> dict:
        started = perf_counter()
        settings = get_settings()
        payload = {
            "model": settings.deepseek_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": ocr_text},
            ],
        }
        after_payload = perf_counter()

        try:
            async with httpx.AsyncClient(
                base_url=settings.deepseek_base_url,
                timeout=60,
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            ) as client:
                response = await client.post("/chat/completions", json=payload)
            after_post = perf_counter()
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DeepSeekError(f"Ошибка сети DeepSeek: {exc}") from exc

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


def _apply_currency_symbols(text: str) -> str:
    for code, symbol in CURRENCY_SYMBOLS.items():
        text = re.sub(rf"\b{code}\b", symbol, text, flags=re.IGNORECASE)
    return text
