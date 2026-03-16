from pathlib import Path

import httpx

from app.config import get_settings


class OCRSpaceError(RuntimeError):
    pass


class OCRSpaceService:
    async def extract_text(self, file_path: Path) -> str:
        settings = get_settings()
        response = None
        last_error: Exception | None = None

        for attempt in range(1, 4):
            try:
                timeout = httpx.Timeout(90.0, connect=20.0)
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
