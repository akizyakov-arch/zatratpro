import httpx

from app.config import get_settings
from app.prompts.cleanup_prompt import CLEANUP_PROMPT
from app.prompts.extraction_prompt import EXTRACTION_PROMPT


class DeepSeekError(RuntimeError):
    pass


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
        return content

    async def extract_document(self, ocr_text: str) -> dict:
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
            raise DeepSeekError("DeepSeek вернул пустой ответ.")

        import json

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise DeepSeekError("DeepSeek вернул невалидный JSON.") from exc
