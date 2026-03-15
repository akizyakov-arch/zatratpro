from pathlib import Path

import httpx

from app.config import get_settings


class OCRSpaceError(RuntimeError):
    pass


class OCRSpaceService:
    async def extract_text(self, file_path: Path) -> str:
        settings = get_settings()

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                with file_path.open("rb") as image_file:
                    response = await client.post(
                        "https://api.ocr.space/parse/image",
                        data={"apikey": settings.ocr_space_api_key, "language": "rus"},
                        files={"file": (file_path.name, image_file, "image/jpeg")},
                    )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OCRSpaceError(f"Ошибка сети OCR.Space: {exc}") from exc

        payload = response.json()
        parsed_results = payload.get("ParsedResults") or []
        texts = [item.get("ParsedText", "").strip() for item in parsed_results]
        text = "\n".join(filter(None, texts)).strip()

        if payload.get("IsErroredOnProcessing"):
            message = "; ".join(payload.get("ErrorMessage") or ["OCR.Space вернул ошибку"])
            raise OCRSpaceError(message)

        return text
