import httpx

from app.config import get_settings


_ocr_client: httpx.AsyncClient | None = None
_deepseek_client: httpx.AsyncClient | None = None


async def init_http_clients() -> None:
    global _ocr_client, _deepseek_client
    if _ocr_client is None:
        _ocr_client = httpx.AsyncClient(
            base_url="https://api.ocr.space",
            timeout=httpx.Timeout(90.0, connect=20.0),
        )
    if _deepseek_client is None:
        settings = get_settings()
        _deepseek_client = httpx.AsyncClient(
            base_url=settings.deepseek_base_url,
            timeout=60,
            headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
        )


async def close_http_clients() -> None:
    global _ocr_client, _deepseek_client
    if _ocr_client is not None:
        await _ocr_client.aclose()
        _ocr_client = None
    if _deepseek_client is not None:
        await _deepseek_client.aclose()
        _deepseek_client = None


def get_ocr_client() -> httpx.AsyncClient:
    if _ocr_client is None:
        raise RuntimeError("OCR client is not initialized.")
    return _ocr_client


def get_deepseek_client() -> httpx.AsyncClient:
    if _deepseek_client is None:
        raise RuntimeError("DeepSeek client is not initialized.")
    return _deepseek_client
