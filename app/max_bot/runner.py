"""Development Long Polling only; production MAX delivery requires Webhook."""
import asyncio
import logging

from app.max_bot.client import MaxAPIError
from app.max_bot.handler import MaxHandler
from app.services.database import get_pool

logger = logging.getLogger(__name__)


async def process_batch(client, handler, updates):
    for update in updates:
        reply = await handler.handle(update)
        if reply is not None:
            user_id, text = reply
            await client.send(user_id, text)


async def poll(client, bot_id, *, timeout=30, once=False):
    handler = MaxHandler()
    async with get_pool().acquire() as lease:
        # A session advisory lock elects one poller per bot. No transaction is
        # kept open across HTTP requests. Disconnection releases the lock.
        key = f'fiinops:max-poll:{bot_id}'
        if not await lease.fetchval('SELECT pg_try_advisory_lock(hashtextextended($1,0))', key):
            raise RuntimeError('Для этого бота MAX уже работает другой polling-процесс.')
        try:
            marker = await lease.fetchval('SELECT marker FROM max_poll_offsets WHERE bot_id=$1', bot_id)
            failures = 0
            while True:
                try:
                    updates, next_marker = await client.updates(marker, timeout)
                    await process_batch(client, handler, updates)
                    if next_marker is not None:
                        await lease.execute('''INSERT INTO max_poll_offsets(bot_id,marker) VALUES($1,$2)
                            ON CONFLICT(bot_id) DO UPDATE SET marker=EXCLUDED.marker,updated_at=clock_timestamp()''', bot_id, next_marker)
                        marker = next_marker
                    failures = 0
                    if once:
                        return
                    if not updates:
                        await asyncio.sleep(.5)
                except MaxAPIError as exc:
                    if once or (exc.status is not None and exc.status < 500 and exc.status != 429):
                        raise
                    failures += 1
                    logger.warning('MAX: временная ошибка, повтор %s', failures)
                    await asyncio.sleep(max(exc.retry_after, min(60, 2 ** min(failures, 6))))
                except Exception as exc:
                    if once:
                        raise
                    failures += 1
                    logger.error('MAX: ошибка обработки (%s), marker не изменён.', type(exc).__name__)
                    await asyncio.sleep(min(60, 2 ** min(failures, 6)))
        finally:
            await lease.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))', key)
