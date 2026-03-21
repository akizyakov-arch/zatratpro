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
        raise RuntimeError('Database pool is not initialized.')
    return _pool


async def _run_runtime_migrations(pool: Pool) -> None:
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                '''
                CREATE TABLE IF NOT EXISTS pending_actions (
                    telegram_user_id BIGINT PRIMARY KEY,
                    action TEXT NOT NULL,
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL
                )
                '''
            )
            await connection.execute(
                '''
                CREATE INDEX IF NOT EXISTS idx_pending_actions_expires_at
                ON pending_actions(expires_at)
                '''
            )
            await connection.execute(
                '''
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
                '''
            )
            await connection.execute('ALTER TABLE pending_documents ADD COLUMN IF NOT EXISTS extracted_document JSONB')
            await connection.execute('ALTER TABLE pending_documents ADD COLUMN IF NOT EXISTS duplicate_check JSONB')
            await connection.execute('ALTER TABLE pending_documents ADD COLUMN IF NOT EXISTS selected_project_id BIGINT')
            await connection.execute('ALTER TABLE pending_documents ADD COLUMN IF NOT EXISTS source_temp_path TEXT')
            await connection.execute('ALTER TABLE pending_documents ADD COLUMN IF NOT EXISTS source_original_name TEXT')
            await connection.execute('ALTER TABLE pending_documents ADD COLUMN IF NOT EXISTS source_mime_type TEXT')
            await connection.execute('ALTER TABLE pending_documents ADD COLUMN IF NOT EXISTS source_file_ext TEXT')
            await connection.execute('ALTER TABLE pending_documents ADD COLUMN IF NOT EXISTS source_original_file_size BIGINT')
            await connection.execute('ALTER TABLE pending_documents ADD COLUMN IF NOT EXISTS source_stored_file_size BIGINT')
            await connection.execute('ALTER TABLE pending_documents ADD COLUMN IF NOT EXISTS source_was_normalized BOOLEAN NOT NULL DEFAULT FALSE')
            await connection.execute('ALTER TABLE pending_documents ADD COLUMN IF NOT EXISTS source_original_kind TEXT')
            await connection.execute(
                '''
                CREATE INDEX IF NOT EXISTS idx_pending_documents_expires_at
                ON pending_documents(expires_at)
                '''
            )
            await connection.execute(
                '''
                CREATE TABLE IF NOT EXISTS document_files (
                    id BIGSERIAL PRIMARY KEY,
                    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    file_role TEXT NOT NULL,
                    page_no INTEGER NOT NULL DEFAULT 0,
                    storage_key TEXT NOT NULL UNIQUE,
                    mime_type TEXT,
                    original_filename TEXT,
                    file_ext TEXT NOT NULL,
                    file_size BIGINT NOT NULL,
                    original_file_size BIGINT,
                    stored_file_size BIGINT,
                    was_normalized BOOLEAN NOT NULL DEFAULT FALSE,
                    original_kind TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT chk_document_files_role CHECK (file_role IN ('source', 'preview', 'page', 'ocr_text')),
                    CONSTRAINT uq_document_files_document_role_page UNIQUE (document_id, file_role, page_no)
                )
                '''
            )
            await connection.execute(
                '''
                CREATE INDEX IF NOT EXISTS idx_document_files_document_id
                ON document_files(document_id)
                '''
            )
            await connection.execute('ALTER TABLE document_files ADD COLUMN IF NOT EXISTS original_file_size BIGINT')
            await connection.execute('ALTER TABLE document_files ADD COLUMN IF NOT EXISTS stored_file_size BIGINT')
            await connection.execute('ALTER TABLE document_files ADD COLUMN IF NOT EXISTS was_normalized BOOLEAN NOT NULL DEFAULT FALSE')
            await connection.execute('ALTER TABLE document_files ADD COLUMN IF NOT EXISTS original_kind TEXT')
