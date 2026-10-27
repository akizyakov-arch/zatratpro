"""Telegram receipt notices with durable retries; no network inside DB transactions."""
import asyncio
import logging

from app.services.advance_receipt_notifications import reserve, finish
from app.ui.money import keyboard

logger = logging.getLogger(__name__)
_task = None


async def deliver_once(bot):
    row = await reserve()
    if row is None:
        return
    try:
        await asyncio.wait_for(bot.send_message(
            chat_id=int(row['external_id']),
            text=(
                'Сотрудник подтвердил получение денег.\n\n'
                f"Сотрудник: {row['employee_name']}\n"
                f"Проект: {row['project_name']}\n"
                f"Сумма: {row['amount']:.2f} ₽\n"
                f"Выдача №{row['advance_id']}\n"
                f"Получено: {row['received_at']:%d.%m.%Y %H:%M} UTC"
            ),
            reply_markup=keyboard([('Открыть выдачу', f"cash:card:{row['advance_id']}")]),
        ), timeout=10)
    except BaseException:
        await finish(row, delivered=False)
        raise
    await finish(row, delivered=True)


async def _worker(bot):
    while True:
        try:
            await deliver_once(bot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning('Advance receipt notification failed: %s', type(exc).__name__)
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
