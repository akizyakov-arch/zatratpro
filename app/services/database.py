import asyncpg
from asyncpg import Pool

from app.config import get_settings


_pool: Pool | None = None


async def init_db() -> Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(settings.postgres_dsn, min_size=1, max_size=5)
        await _run_runtime_migrations(_pool)
        from app.state.pending_actions import cleanup_expired_pending_actions
        from app.state.pending_documents import cleanup_expired_pending_documents

        await cleanup_expired_pending_actions()
        await cleanup_expired_pending_documents()
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


async def _run_runtime_migrations(pool: Pool) -> None:
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_actions (
                    telegram_user_id BIGINT PRIMARY KEY,
                    action TEXT NOT NULL,
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_pending_actions_expires_at
                ON pending_actions(expires_at)
                """
            )
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_documents (
                    telegram_user_id BIGINT PRIMARY KEY,
                    ocr_text TEXT,
                    normalized_text TEXT,
                    extracted_document JSONB,
                    duplicate_check JSONB,
                    selected_project_id BIGINT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await connection.execute("ALTER TABLE pending_documents ADD COLUMN IF NOT EXISTS extracted_document JSONB")
            await connection.execute("ALTER TABLE pending_documents ADD COLUMN IF NOT EXISTS duplicate_check JSONB")
            await connection.execute("ALTER TABLE pending_documents ADD COLUMN IF NOT EXISTS selected_project_id BIGINT")
            await connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_pending_documents_expires_at
                ON pending_documents(expires_at)
                """
            )