"""At-least-once Telegram delivery using short database leases, never network locks."""
import asyncio
import logging
from uuid import uuid4

from app.services.database import get_pool
from app.ui.money import keyboard

_task = None
logger = logging.getLogger(__name__)


async def _reserve_notification():
    token = uuid4().hex
    async with get_pool().acquire() as connection, connection.transaction():
        row = await connection.fetchrow(
            '''SELECT r.id,r.target_platform,r.target_external_id,e.external_id
               FROM account_link_requests r JOIN external_accounts e ON e.id=r.source_account_id
               JOIN users u ON u.id=r.user_id
               WHERE r.status='claimed' AND r.notified_at IS NULL AND r.expires_at>clock_timestamp()
                 AND r.notification_retry_at<=clock_timestamp()
                 AND (r.notification_lease_until IS NULL OR r.notification_lease_until<=clock_timestamp())
                 AND e.platform='telegram' AND u.is_active
               ORDER BY r.created_at LIMIT 1 FOR UPDATE OF r SKIP LOCKED'''
        )
        if row is None:
            return None
        await connection.execute(
            '''UPDATE account_link_requests SET notification_token=$2,
               notification_lease_until=clock_timestamp()+interval '30 seconds' WHERE id=$1''',
            row['id'], token,
        )
        return dict(row, token=token)


async def _finish_notification(row, *, delivered):
    async with get_pool().acquire() as connection:
        # An old worker must not acknowledge a newer worker's reclaimed lease.
        await connection.execute(
            '''UPDATE account_link_requests SET
               notified_at=CASE WHEN $3 THEN clock_timestamp() ELSE notified_at END,
               notification_token=NULL,notification_lease_until=NULL,
               notification_retry_at=CASE WHEN $3 THEN notification_retry_at
                   ELSE clock_timestamp()+interval '30 seconds' END
               WHERE id=$1 AND notification_token=$2''',
            row['id'], row['token'], delivered,
        )


async def deliver_once(bot):
    row = await _reserve_notification()
    if row is None:
        return
    # The reservation transaction and its connection are already released here.
    try:
        await asyncio.wait_for(bot.send_message(
            chat_id=int(row['external_id']),
            text=(f"Запрос привязки аккаунта {row['target_platform']}: {row['target_external_id']}.\n"
                  'Подтверждайте только если сами вводили код в этом аккаунте.'),
            reply_markup=keyboard([
                ('Подтвердить', f"profile:confirm:{row['id']}"),
                ('Отклонить', f"profile:cancel:{row['id']}"),
            ]),
        ), timeout=10)
    except BaseException:
        await _finish_notification(row, delivered=False)
        raise
    await _finish_notification(row, delivered=True)


async def _worker(bot):
    while True:
        try:
            await deliver_once(bot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning('Account link notification failed: %s', type(exc).__name__)
        await asyncio.sleep(5)


def start_notifications(bot):
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_worker(bot))


async def stop_notifications():
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
