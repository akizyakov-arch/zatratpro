import json

import httpx

from app.config import get_settings
from app.prompts.cleanup_prompt import CLEANUP_PROMPT
from app.prompts.extraction_prompt import EXTRACTION_PROMPT


class DeepSeekError(RuntimeError):
    pass


class DeepSeekService:
    async def clean_ocr_text(self, ocr_text: str) -> str:
        content = await self._request_completion(
            system_prompt=CLEANUP_PROMPT,
            user_content=ocr_text,
        )
        if not content:
            raise DeepSeekError("DeepSeek вернул пустой очищенный текст.")
        return content

    async def extract_document(self, cleaned_text: str) -> dict:
        content = await self._request_completion(
            system_prompt=EXTRACTION_PROMPT,
            user_content=cleaned_text,
            json_mode=True,
        )
        if not content:
            raise DeepSeekError("DeepSeek вернул пустой ответ.")

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise DeepSeekError("DeepSeek вернул невалидный JSON.") from exc

    async def _request_completion(
        self,
        system_prompt: str,
        user_content: str,
        json_mode: bool = False,
    ) -> str:
        settings = get_settings()
        payload = {
            "model": settings.deepseek_model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

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
        return content
