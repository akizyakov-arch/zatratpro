"""Notify the original Telegram account; platform adapters own delivery, not core."""
import asyncio
import logging

from app.services.database import get_pool
from app.handlers.advances import keyboard

_task=None
logger=logging.getLogger(__name__)


async def deliver_once(bot):
    async with get_pool().acquire() as c,c.transaction():
        row=await c.fetchrow('''SELECT r.id,r.target_platform,r.target_external_id,e.external_id
            FROM account_link_requests r JOIN external_accounts e ON e.id=r.source_account_id
            JOIN users u ON u.id=r.user_id
            WHERE r.status='claimed' AND r.notified_at IS NULL AND r.expires_at>NOW()
              AND e.platform='telegram' AND u.is_active
            ORDER BY r.created_at LIMIT 1 FOR UPDATE OF r SKIP LOCKED''')
        if row is None: return
        await asyncio.wait_for(bot.send_message(
            chat_id=int(row['external_id']),
            text=f"Запрос привязки аккаунта {row['target_platform']}: {row['target_external_id']}.\nПодтверждайте только если сами вводили код в этом аккаунте.",
            reply_markup=keyboard([('Подтвердить',f"profile:confirm:{row['id']}"),('Отклонить',f"profile:cancel:{row['id']}")]),
        ),timeout=10)
        await c.execute('UPDATE account_link_requests SET notified_at=NOW() WHERE id=$1',row['id'])


async def _worker(bot):
    while True:
        try: await deliver_once(bot)
        except asyncio.CancelledError: raise
        except Exception as exc: logger.warning('Account link notification failed: %s',type(exc).__name__)
        await asyncio.sleep(5)


def start_notifications(bot):
    global _task
    _task=asyncio.create_task(_worker(bot))


async def stop_notifications():
    global _task
    if _task is not None:
        _task.cancel()
        try: await _task
        except asyncio.CancelledError: pass
        _task=None
