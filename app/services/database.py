import asyncpg
from asyncpg import Pool

from app.config import BASE_DIR, get_settings


_pool: Pool | None = None


async def init_db() -> Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        pool = await asyncpg.create_pool(
            host=settings.postgres_host, port=settings.postgres_port,
            database=settings.postgres_db, user=settings.postgres_user,
            password=settings.postgres_password, min_size=1, max_size=5,
        )
        try:
            await _migrate(pool)
        except BaseException:
            await pool.close()
            raise
        _pool = pool
    return _pool


async def _migrate(pool: Pool) -> None:
    async with pool.acquire() as connection:
        async with connection.transaction():
            # Serialize schema changes when multiple processes start together.
            await connection.execute('SELECT pg_advisory_xact_lock(734291001)')
            await connection.execute('CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)')
            for path in sorted((BASE_DIR / 'db' / 'migrations').glob('*.sql')):
                if not await connection.fetchval('SELECT 1 FROM schema_migrations WHERE name=$1', path.name):
                    await connection.execute(path.read_text())
                    await connection.execute('INSERT INTO schema_migrations VALUES ($1)', path.name)
            # Configuration, rather than a stale cached role, owns this privilege.
            await connection.execute(
                "UPDATE users SET system_role=CASE WHEN telegram_id=$1 AND $1<>0 THEN 'owner' ELSE 'user' END "
                "WHERE system_role IS DISTINCT FROM CASE WHEN telegram_id=$1 AND $1<>0 THEN 'owner' ELSE 'user' END",
                get_settings().bot_owner_telegram_id,
            )
            await connection.execute('DELETE FROM pending_document_flows WHERE expires_at <= NOW()')
            await connection.execute('DELETE FROM pending_actions WHERE expires_at <= NOW()')


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> Pool:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized.")
    return _pool
