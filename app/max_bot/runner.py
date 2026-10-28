"""Development Long Polling only; production MAX delivery requires Webhook."""
import asyncio
from collections import deque
import logging

import asyncpg

from app.max_bot.client import MaxAPIError
from app.max_bot.handler import MaxHandler, event_message
from app.services.database import get_pool

logger = logging.getLogger(__name__)


class PollingLeaseLost(RuntimeError):
    def __init__(self):
        super().__init__('MAX: соединение с блокировкой потеряно. Перезапустите polling-процесс.')


async def process_batch(client, handler, updates, *, check_lease=None):
    # A deque owned by the poller retains only unfinished events on retry.
    pending = updates if isinstance(updates, deque) else deque(updates)
    while pending:
        if check_lease:
            await check_lease()
        update = pending[0]
        if update.get('update_type') == 'message_callback' and event_message(update) is not None:
            try:
                await client.answer(update['callback']['callback_id'])
            except MaxAPIError as exc:
                # Old/already answered callbacks must not block the update queue.
                if exc.status not in (400, 404, 410):
                    raise
            if check_lease:
                await check_lease()
        reply = await handler.handle(update)
        if reply is not None:
            if check_lease:
                await check_lease()
            user_id, text = reply
            try:
                await client.send(user_id, text)
            except MaxAPIError as exc:
                # POST /messages documents 403 as denied access to this dialog.
                # Authentication failures, redirects and unknown 4xx stay fatal.
                if exc.status != 403:
                    raise
                logger.warning('MAX: ответ недоступному получателю пропущен (HTTP 403).')
        pending.popleft()


async def _poll_locked(client, bot_id, lease, *, timeout, once):
    async def check_lease():
        try:
            await lease.fetchval('SELECT 1')
        except Exception:
            raise PollingLeaseLost() from None

    handler = MaxHandler()
    marker = await lease.fetchval('SELECT marker FROM max_poll_offsets WHERE bot_id=$1', bot_id)
    pending = None
    failures = 0
    while True:
        try:
            await check_lease()
            if pending is None:
                updates, next_marker = await client.updates(marker, timeout)
                pending = deque(updates)
            # Keep the page in memory across transient failures, including when
            # marker is initially None. Recheck authorization on each retry.
            await process_batch(client, handler, pending, check_lease=check_lease)
            if next_marker is not None:
                await lease.execute('''INSERT INTO max_poll_offsets(bot_id,marker) VALUES($1,$2)
                    ON CONFLICT(bot_id) DO UPDATE SET marker=EXCLUDED.marker,updated_at=clock_timestamp()''', bot_id, next_marker)
                marker = next_marker
            pending = None
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
        # Database and programming errors escape: retrying after losing the
        # session lock could run alongside a new poller. No implicit reconnect.


async def poll(client, bot_id, *, timeout=30, once=False):
    async with get_pool().acquire() as lease:
        key = f'fiinops:max-poll:{bot_id}'
        if not await lease.fetchval('SELECT pg_try_advisory_lock(hashtextextended($1,0))', key):
            raise RuntimeError('Для этого бота MAX уже работает другой polling-процесс.')
        lost = asyncio.Event()
        worker = None

        def disconnected(_connection):
            lost.set()
            if worker is not None:
                worker.cancel()

        lease.add_termination_listener(disconnected)
        try:
            worker = asyncio.create_task(_poll_locked(client, bot_id, lease, timeout=timeout, once=once))
            try:
                await worker
            except asyncio.CancelledError:
                if lost.is_set():
                    raise PollingLeaseLost() from None
                raise
            if lost.is_set():
                raise PollingLeaseLost()
        finally:
            if worker is not None and not worker.done():
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
            if not lost.is_set():
                try:
                    lease.remove_termination_listener(disconnected)
                    await lease.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))', key)
                except Exception:
                    # A failed unlock must not leave a pooled session locked.
                    try:
                        lease.terminate()
                    except asyncpg.InterfaceError:
                        # asyncpg already detached a terminated pooled session.
                        pass
                    logger.warning('MAX: соединение блокировки закрыто при завершении.')
