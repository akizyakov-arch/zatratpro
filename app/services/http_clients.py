import asyncio
import logging

import httpx

from app.config import get_settings


logger = logging.getLogger(__name__)

_ocr_client: httpx.AsyncClient | None = None
_deepseek_client: httpx.AsyncClient | None = None
_ocr_client_lock = asyncio.Lock()
_deepseek_client_lock = asyncio.Lock()


def _build_ocr_client() -> httpx.AsyncClient:
    timeout = httpx.Timeout(120.0, connect=20.0)
    limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
    return httpx.AsyncClient(timeout=timeout, limits=limits)


def _build_deepseek_client() -> httpx.AsyncClient:
    settings = get_settings()
    timeout = httpx.Timeout(settings.deepseek_read_timeout, connect=settings.deepseek_connect_timeout)
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    client_kwargs = {
        "base_url": settings.deepseek_base_url,
        "timeout": timeout,
        "limits": limits,
        "headers": {"Authorization": f"Bearer {settings.deepseek_api_key}"},
    }
    proxy_url = settings.effective_deepseek_proxy_url
    if proxy_url:
        client_kwargs["proxy"] = proxy_url
    return httpx.AsyncClient(**client_kwargs)


async def get_ocr_client() -> httpx.AsyncClient:
    global _ocr_client
    if _ocr_client is None:
        async with _ocr_client_lock:
            if _ocr_client is None:
                _ocr_client = _build_ocr_client()
                logger.info("OCR.Space shared HTTP client initialized")
    return _ocr_client


async def get_deepseek_client() -> httpx.AsyncClient:
    global _deepseek_client
    if _deepseek_client is None:
        async with _deepseek_client_lock:
            if _deepseek_client is None:
                _deepseek_client = _build_deepseek_client()
                logger.info("DeepSeek shared HTTP client initialized")
    return _deepseek_client


async def close_http_clients() -> None:
    global _ocr_client, _deepseek_client

    if _ocr_client is not None:
        await _ocr_client.aclose()
        _ocr_client = None
        logger.info("OCR.Space shared HTTP client closed")

    if _deepseek_client is not None:
        await _deepseek_client.aclose()
        _deepseek_client = None
        logger.info("DeepSeek shared HTTP client closed")
