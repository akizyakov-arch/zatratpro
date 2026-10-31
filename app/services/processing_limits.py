"""Bound external recognition work before document bytes are downloaded."""
import asyncio
from contextlib import asynccontextmanager
from app.config import get_recognition_settings

_loop = None
_limit = None


@asynccontextmanager
async def document_processing_slot():
    global _loop, _limit
    loop = asyncio.get_running_loop()
    if _loop is not loop:
        settings = get_recognition_settings()
        capacity = getattr(settings, 'document_processing_concurrency', 4)
        _limit = asyncio.Semaphore(capacity)
        _loop = loop
    async with _limit:
        yield
