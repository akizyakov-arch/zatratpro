"""At-least-once Telegram delivery using short database leases, never network locks."""
import asyncio
import logging

from app.services.account_link_notifications import _reserve_notification, _finish_notification
from app.ui.money import keyboard

_task = None
logger = logging.getLogger(__name__)


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
