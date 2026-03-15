import asyncpg
from asyncpg import Pool

from app.config import get_settings


_pool: Pool | None = None


async def init_db() -> Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(settings.postgres_dsn, min_size=1, max_size=5)
    return _pool


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> Pool:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized.")
    return _pool
