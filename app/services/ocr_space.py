from pathlib import Path

import httpx

from app.config import get_settings
from app.services.http_clients import get_ocr_client


class OCRSpaceError(RuntimeError):
    pass


class OCRSpaceService:
    async def extract_text(self, file_path: Path) -> str:
        settings = get_settings()
        response = None
        last_error: Exception | None = None
        client = get_ocr_client()

        for attempt in range(1, 4):
            try:
                with file_path.open("rb") as image_file:
                    response = await client.post(
                        "/parse/image",
                        data={
                            "apikey": settings.ocr_space_api_key,
                            "language": "rus",
                            "OCREngine": 2,
                        },
                        files={"file": (file_path.name, image_file, "image/jpeg")},
                    )
                response.raise_for_status()
                break
            except httpx.ReadTimeout as exc:
                last_error = exc
                if attempt == 3:
                    raise OCRSpaceError("OCR.Space не ответил вовремя. Попробуй отправить документ еще раз.") from exc
            except httpx.HTTPError as exc:
                raise OCRSpaceError(f"Ошибка сети OCR.Space: {exc}") from exc

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
