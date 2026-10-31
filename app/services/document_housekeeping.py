"""Bounded expiry cleanup shared by all application bootstraps."""
import asyncio
import logging

from app.services.database import get_pool

logger = logging.getLogger(__name__)
CLEANUP_INTERVAL = 60
CLEANUP_BATCH = 100


async def cleanup_expired_document_drafts(limit=CLEANUP_BATCH):
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('Некорректный размер очистки черновиков.')
    # Lock only an expired batch and skip drafts currently handled by a user.
    # Recheck expiry after locking so a refreshed draft is never removed.
    async with get_pool().acquire() as connection, connection.transaction():
        result = await connection.fetchval('''WITH expired AS (
            SELECT actor_id FROM pending_document_flows
            WHERE expires_at <= clock_timestamp()
            ORDER BY expires_at,actor_id LIMIT $1 FOR UPDATE SKIP LOCKED
        ), removed AS (
            DELETE FROM pending_document_flows d USING expired e
            WHERE d.actor_id=e.actor_id AND d.expires_at <= clock_timestamp()
            RETURNING d.actor_id
        ) SELECT count(*) FROM removed''', limit)
    return result


async def _run():
    while True:
        try:
            await cleanup_expired_document_drafts()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning('document_draft_cleanup_failed error_type=%s', type(exc).__name__)
        await asyncio.sleep(CLEANUP_INTERVAL)


def start_document_housekeeping():
    """Return an owned task; each bootstrap cancels it before closing its DB pool."""
    return asyncio.create_task(_run(), name='document-draft-housekeeping')


async def stop_document_housekeeping(task):
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
