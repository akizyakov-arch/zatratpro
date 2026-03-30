import asyncpg
import logging
from asyncpg import Pool

from app.config import get_settings


_pool: Pool | None = None

logger = logging.getLogger(__name__)


async def init_db() -> Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(settings.postgres_dsn, min_size=1, max_size=5)
        await _run_runtime_migrations(_pool)
        await _align_runtime_sequences(_pool)
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
            await connection.execute('ALTER TABLE company_invites ADD COLUMN IF NOT EXISTS start_token TEXT')
            await connection.execute('ALTER TABLE company_invites DROP CONSTRAINT IF EXISTS chk_company_invites_status')
            await connection.execute("ALTER TABLE company_invites ALTER COLUMN status SET DEFAULT 'new'")
            await connection.execute("UPDATE company_invites SET status = 'new' WHERE status = 'active'")
            await connection.execute(
                '''
                ALTER TABLE company_invites
                ADD CONSTRAINT chk_company_invites_status
                CHECK (status IN ('new', 'used', 'expired', 'revoked'))
                '''
            )
            await connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_company_invites_start_token ON company_invites(start_token) WHERE start_token IS NOT NULL')
            await connection.execute('DROP INDEX IF EXISTS uq_company_invites_active_manager_per_company')
            await connection.execute(
                '''
                CREATE UNIQUE INDEX IF NOT EXISTS uq_company_invites_active_manager_per_company
                ON company_invites(company_id)
                WHERE status = 'new' AND role = 'manager'
                '''
            )
            await connection.execute('DROP INDEX IF EXISTS uq_company_invites_active_employee_per_company')
            await connection.execute(
                '''
                CREATE UNIQUE INDEX IF NOT EXISTS uq_company_invites_active_employee_per_company
                ON company_invites(company_id)
                WHERE status = 'new' AND role = 'employee'
                '''
            )
            await connection.execute('ALTER TABLE documents ADD COLUMN IF NOT EXISTS vat_total_amount NUMERIC(14, 2)')
            await connection.execute('ALTER TABLE documents ADD COLUMN IF NOT EXISTS vat_scope TEXT')
            await connection.execute('ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_fiscalized BOOLEAN')
            await connection.execute('ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_number_normalized TEXT')
            await connection.execute('ALTER TABLE documents ADD COLUMN IF NOT EXISTS vendor_key_normalized TEXT')
            await connection.execute(
                '''
                UPDATE documents
                SET document_number_normalized = NULLIF(
                    LOWER(
                        REGEXP_REPLACE(
                            COALESCE(NULLIF(external_document_number, ''), incoming_number, ''),
                            '[^[:alnum:]]+',
                            '',
                            'g'
                        )
                    ),
                    ''
                )
                WHERE document_number_normalized IS NULL
                '''
            )
            await connection.execute(
                '''
                UPDATE documents
                SET vendor_key_normalized = NULLIF(
                    LOWER(
                        REGEXP_REPLACE(
                            COALESCE(NULLIF(vendor_inn, ''), vendor, ''),
                            '[^[:alnum:]]+',
                            '',
                            'g'
                        )
                    ),
                    ''
                )
                WHERE vendor_key_normalized IS NULL
                '''
            )
            await connection.execute(
                '''
                CREATE INDEX IF NOT EXISTS idx_documents_duplicate_exact_lookup
                ON documents(company_id, document_type, document_number_normalized, document_date, total_amount, vendor_key_normalized, id DESC)
                '''
            )
            await connection.execute(
                '''
                CREATE INDEX IF NOT EXISTS idx_documents_duplicate_probable_lookup
                ON documents(company_id, document_type, document_date, total_amount, vendor_key_normalized, id DESC)
                '''
            )
            await connection.execute('ALTER TABLE document_items ADD COLUMN IF NOT EXISTS vat_label TEXT')
            await connection.execute('ALTER TABLE document_items ADD COLUMN IF NOT EXISTS vat_amount NUMERIC(14, 2)')
            await connection.execute('ALTER TABLE documents DROP CONSTRAINT IF EXISTS chk_documents_vat_scope')
            await connection.execute(
                '''
                ALTER TABLE documents
                ADD CONSTRAINT chk_documents_vat_scope
                CHECK (vat_scope IN ('document', 'mixed', 'no_vat', 'unknown'))
                '''
            )
            await connection.execute('ALTER TABLE company_members DROP CONSTRAINT IF EXISTS chk_company_members_status')
            await connection.execute(
                '''
                ALTER TABLE company_members
                ADD CONSTRAINT chk_company_members_status
                CHECK (status IN ('new', 'active', 'blocked', 'removed'))
                '''
            )


async def _align_runtime_sequences(pool: Pool) -> None:
    serial_targets = (
        ('users', 'id'),
        ('companies', 'id'),
        ('company_members', 'id'),
        ('company_invites', 'id'),
        ('projects', 'id'),
        ('documents', 'id'),
        ('document_items', 'id'),
        ('document_files', 'id'),
    )
    async with pool.acquire() as connection:
        for table_name, column_name in serial_targets:
            sequence_name = await connection.fetchval(
                "SELECT pg_get_serial_sequence($1, $2)",
                table_name,
                column_name,
            )
            if not sequence_name:
                continue
            max_id = int(
                await connection.fetchval(
                    f"SELECT COALESCE(MAX({column_name}), 0) FROM {table_name}"
                )
            )
            if max_id <= 0:
                continue
            last_value = int(await connection.fetchval(f"SELECT last_value FROM {sequence_name}"))
            if last_value >= max_id:
                continue
            await connection.execute(
                "SELECT setval($1::regclass, $2, true)",
                sequence_name,
                max_id,
            )
            logger.warning(
                "Aligned serial sequence: table=%s column=%s sequence=%s old_last_value=%s new_last_value=%s",
                table_name,
                column_name,
                sequence_name,
                last_value,
                max_id,
            )

