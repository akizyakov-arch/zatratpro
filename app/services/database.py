import secrets
import string

import asyncpg
from asyncpg import Pool
from asyncpg.exceptions import UniqueViolationError

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
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_pending_documents_expires_at
                ON pending_documents(expires_at)
                """
            )

        invites_table_exists = await connection.fetchval("SELECT to_regclass('public.company_invites') IS NOT NULL")
        if not invites_table_exists:
            return

        async with connection.transaction():
            await connection.execute("ALTER TABLE company_invites ADD COLUMN IF NOT EXISTS start_token TEXT")
            await connection.execute("ALTER TABLE company_invites DROP CONSTRAINT IF EXISTS chk_company_invites_status")
            await connection.execute("UPDATE company_invites SET status = 'new' WHERE status = 'active'")
            await connection.execute("ALTER TABLE company_invites ALTER COLUMN status SET DEFAULT 'new'")

        invite_ids = await connection.fetch(
            """
            SELECT id
            FROM company_invites
            WHERE start_token IS NULL OR start_token = ''
            ORDER BY id
            """
        )
        for row in invite_ids:
            await _assign_missing_start_token(connection, int(row["id"]))

        async with connection.transaction():
            await connection.execute(
                """
                ALTER TABLE company_invites
                ADD CONSTRAINT chk_company_invites_status
                CHECK (status IN ('new', 'used', 'expired', 'revoked'))
                """
            )
            await connection.execute("ALTER TABLE company_invites ALTER COLUMN start_token SET NOT NULL")
            await connection.execute("DROP INDEX IF EXISTS uq_company_invites_active_manager_per_company")
            await connection.execute("DROP INDEX IF EXISTS uq_company_invites_active_employee_per_company")
            await connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_company_invites_active_manager_per_company
                ON company_invites(company_id)
                WHERE status = 'new' AND role = 'manager'
                """
            )
            await connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_company_invites_active_employee_per_company
                ON company_invites(company_id)
                WHERE status = 'new' AND role = 'employee'
                """
            )
            await connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_company_invites_start_token ON company_invites(start_token)"
            )
            await connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_company_invites_start_token ON company_invites(start_token)"
            )


async def _assign_missing_start_token(connection, invite_id: int) -> None:
    for _ in range(10):
        token = _generate_start_token()
        try:
            updated = await connection.execute(
                """
                UPDATE company_invites
                SET start_token = $2
                WHERE id = $1
                  AND (start_token IS NULL OR start_token = '')
                """,
                invite_id,
                token,
            )
            if not updated.endswith("0"):
                return
        except UniqueViolationError:
            continue
    raise RuntimeError(f"Failed to backfill start_token for invite {invite_id}")


def _generate_start_token(length: int = 24) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
