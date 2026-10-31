"""Development Long Polling only; production MAX delivery requires Webhook."""
import asyncio
from collections import deque
import logging
import hashlib
import json
import time

import asyncpg

from app.max_bot.client import MaxAPIError
from app.max_bot.handler import MaxHandler, event_message, LINK_HELP
from app.max_bot.menu import command_text, MenuText, MenuButton, LinkButton
from app.services import max_delivery as store

logger = logging.getLogger(__name__)


class PollingLeaseLost(RuntimeError):
    def __init__(self):
        super().__init__('MAX: соединение с блокировкой потеряно. Перезапустите polling-процесс.')


async def process_batch(client, handler, updates, *, check_lease=None, prepare_reply=None, before_handle=None):
    # A deque owned by the poller retains only unfinished events on retry.
    pending = updates if isinstance(updates, deque) else deque(updates)
    while pending:
        if check_lease:
            await check_lease()
        update = pending[0]
        started = time.perf_counter()
        ack_ms = handle_ms = send_ms = 0.0
        stamp = update.get('timestamp')
        # MAX timestamps are epoch milliseconds; local clock skew affects this value.
        age_ms = max(0, time.time() * 1000 - stamp) if type(stamp) in (int, float) and 0 < stamp < 10**15 else None
        if update.get('update_type') == 'message_callback' and event_message(update) is not None:
            try:
                await client.answer(update['callback']['callback_id'])
            except MaxAPIError as exc:
                # Old/already answered callbacks must not block the update queue.
                if exc.status not in (400, 404, 410):
                    raise
            ack_ms = (time.perf_counter() - started) * 1000
            if check_lease:
                await check_lease()
        if before_handle is not None:
            await before_handle()
        handling = time.perf_counter()
        reply = await handler.handle(update)
        handle_ms = (time.perf_counter() - handling) * 1000
        if reply is not None:
            if check_lease:
                await check_lease()
            user_id, text = reply
            if prepare_reply is not None:
                user_id, text = await prepare_reply(user_id, text)
            sending = time.perf_counter()
            try:
                await client.send(user_id, text)
            except MaxAPIError as exc:
                # POST /messages documents 403 as denied access to this dialog.
                # Authentication failures, redirects and unknown 4xx stay fatal.
                if exc.status != 403:
                    raise
                logger.warning('MAX: ответ недоступному получателю пропущен (HTTP 403).')
            send_ms = (time.perf_counter() - sending) * 1000
        # Never log event bodies, names, callbacks, IDs, URLs or query text.
        kind = update.get('update_type')
        kind = kind if kind in ('bot_started', 'message_created', 'message_callback') else 'other'
        logger.info('max_event type=%s age_ms=%s ack_ms=%.0f handle_ms=%.0f send_ms=%.0f total_ms=%.0f pending=%s',
                    kind, round(age_ms) if age_ms is not None else 'unknown', ack_ms,
                    handle_ms, send_ms, (time.perf_counter() - started) * 1000, len(pending) - 1)
        pending.popleft()


def encode_reply(user_id, text, scope):
    buttons = []
    for row in getattr(text, 'buttons', None) or []:
        rendered = []
        for button in row:
            item = {'label': str(button)}
            if isinstance(button, LinkButton): item['url'] = button.url
            elif isinstance(button, MenuButton): item['command'] = button.command
            rendered.append(item)
        buttons.append(rendered)
    return {'user_id': user_id, 'text': str(text), 'buttons': buttons, 'scope': scope}


def decode_reply(response):
    buttons = [[LinkButton(item['label'], item['url']) if 'url' in item else
                MenuButton(item['label'], item['command']) if 'command' in item else item['label']
                for item in row] for row in response['buttons']]
    return response['user_id'], MenuText(response['text'], buttons)


FAST_WORKERS = 2
BACKGROUND_WORKERS = 4


def inbox_record(update, page_marker, index):
    """Transport identity and scheduling only; never derive authorization here."""
    event = event_message(update)
    sender = str(event[0]) if event else 'unrecognized'
    kind = update.get('update_type')
    if kind == 'message_callback' and event:
        identity = ['callback', update['callback']['callback_id']]
    elif kind == 'message_created' and event and isinstance(update.get('message', {}).get('body', {}).get('mid'), str):
        identity = ['message', sender, update['message']['body']['mid']]
    else:
        identity = ['event', page_marker, index, update]
    key = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    # Scheduling is not authorization: callbacks and text commands still resolve
    # the sender in MaxHandler. Reserve fast capacity for both button and typed
    # menus, but never let voice/media/AI callbacks occupy those menu slots.
    body = update.get('message', {}).get('body', {})
    attachments = body.get('attachments') or [] if isinstance(body, dict) else []
    media = any(isinstance(item, dict) and item.get('type') in ('image', 'photo', 'file', 'audio', 'video') for item in attachments)
    text = command_text(event[1]) if event else ''
    command = text.split(maxsplit=1)[0] if text else ''
    ai = command == '/ask' or (command.startswith('/ai_') and command not in ('/ai_reports','/ai_exit','/ai_cancel'))
    fast = kind in ('message_callback','bot_started') or command.startswith('/')
    lane = 'fast' if fast and not media and not ai else 'background'
    return {'key': key, 'sender': sender, 'lane': lane, 'payload': update}


def retry_delay(exc, attempts):
    return max(exc.retry_after, min(60, 2 ** min(attempts, 6)))


async def _poll_locked(client, bot_id, lease, *, timeout, once):
    lease_guard = asyncio.Lock()
    wake = asyncio.Event()
    ingested = asyncio.Event()

    async def check_lease():
        try:
            async with lease_guard:
                await store.check(lease)
        except Exception:
            raise PollingLeaseLost() from None

    async def ingest_pages():
        async with lease_guard:
            marker = await store.marker(lease, bot_id)
        pending_page = None
        failures = 0
        while True:
            try:
                await check_lease()
                if pending_page is None:
                    updates, next_marker = await client.updates(marker, timeout)
                    records = [inbox_record(update, marker, index) for index, update in enumerate(updates)]
                    pending_page = records, next_marker
                async with lease_guard:
                    await store.ingest(lease, bot_id, *pending_page)
                wake.set()
                if next_marker is not None:
                    marker = next_marker
                pending_page = None
                failures = 0
                if once:
                    ingested.set()
                    wake.set()
                    return
                if not updates:
                    await asyncio.sleep(.5)
            except store.InboxFull:
                # Keep this page/cursor until workers free space. No events dropped.
                wake.set()
                await asyncio.sleep(.25)
            except MaxAPIError as exc:
                if once or (exc.status is not None and exc.status < 500 and exc.status != 429):
                    raise
                failures += 1
                logger.warning('MAX: временная ошибка получения, повтор %s', failures)
                await asyncio.sleep(retry_delay(exc, failures))

    handler = MaxHandler(notify=client.send)
    await store.recover(bot_id)

    async def execute(job):
        try:
            if job['reply'] is not None:
                await check_lease()
                scope = await store.reply_scope(job['sender'])
                user_id, text = decode_reply(job['reply']) if scope == job['reply']['scope'] else (job['reply']['user_id'], LINK_HELP)
                try:
                    await client.send(user_id, text)
                except MaxAPIError as exc:
                    if exc.status != 403:
                        raise
                    logger.warning('MAX: ответ недоступному получателю пропущен (HTTP 403).')
            else:
                execution_scope = await store.reply_scope(job['sender'])
                async def prepare(user_id, text):
                    current_scope = await store.reply_scope(job['sender'])
                    if execution_scope is not None and execution_scope != current_scope:
                        text = MenuText('Доступ изменился. Откройте главное меню.', [[MenuButton('Главное меню', '/start')]])
                    response = encode_reply(user_id, text, current_scope)
                    await check_lease()
                    if not await store.prepare_reply(job, response):
                        raise PollingLeaseLost()
                    return user_id, text
                if job['started'] and not job['retry_document']:
                    event = event_message(job['payload'])
                    if event is not None:
                        user_id, text = await prepare(event[0], MenuText(
                            'Обработка прервалась. Проверьте состояние операции перед повтором. Откройте главное меню.',
                            [[MenuButton('Главное меню','/start')]]))
                        await client.send(user_id,text)
                else:
                    async def started():
                        await check_lease()
                        if not await store.mark_started(job):
                            raise PollingLeaseLost()
                    await process_batch(client, handler, [job['payload']], check_lease=check_lease,
                                        prepare_reply=prepare, before_handle=started)
        except MaxAPIError as exc:
            if once or (exc.status is not None and exc.status < 500 and exc.status != 429):
                await store.retry(job, 0)
                raise
            await store.retry(job, retry_delay(exc, job['attempts']))
            logger.warning('MAX: повтор доставки запланирован attempt=%s', job['attempts'])
        else:
            await check_lease()
            if not await store.complete(job):
                raise PollingLeaseLost()
        finally:
            wake.set()

    async def dispatch():
        running = {}
        try:
            while True:
                wake.clear()
                for task in list(running):
                    if task.done():
                        running.pop(task)
                        task.result()  # Propagate errors without an ExceptionGroup.
                for lane, limit in (('fast', FAST_WORKERS), ('background', BACKGROUND_WORKERS)):
                    slots = limit - sum(value == lane for value in running.values())
                    for _ in range(slots):
                        await check_lease()
                        job = await store.claim(bot_id, lane)
                        if job is None:
                            break
                        running[asyncio.create_task(execute(job))] = lane
                if once and ingested.is_set() and not running and not await store.pending_count(bot_id):
                    return
                # Retry deadlines are persisted. No busy-wait/DB query per idle worker.
                open_lanes = [lane for lane, limit in (('fast', FAST_WORKERS), ('background', BACKGROUND_WORKERS))
                              if sum(value == lane for value in running.values()) < limit]
                delay = await store.next_delay(bot_id, open_lanes)
                if wake.is_set():
                    continue
                try:
                    await asyncio.wait_for(wake.wait(), timeout=delay)
                except TimeoutError:
                    pass
        finally:
            for task in running:
                task.cancel()
            if running:
                await asyncio.gather(*running, return_exceptions=True)

    fetching = asyncio.create_task(ingest_pages())
    processing = asyncio.create_task(dispatch())
    try:
        done, _ = await asyncio.wait((fetching, processing), return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        if once:
            if processing in done:
                return
            await processing
        else:
            raise RuntimeError('MAX: обработчик очереди неожиданно завершился.')
    finally:
        fetching.cancel()
        processing.cancel()
        await asyncio.gather(fetching, processing, return_exceptions=True)


async def poll(client, bot_id, *, timeout=30, once=False):
    async with store.acquire_lease() as lease:
        key = f'fiinops:max-poll:{bot_id}'
        if not await store.lock(lease,key):
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
                    await store.unlock(lease,key)
                except Exception:
                    # A failed unlock must not leave a pooled session locked.
                    try:
                        lease.terminate()
                    except asyncpg.InterfaceError:
                        # asyncpg already detached a terminated pooled session.
                        pass
                    logger.warning('MAX: соединение блокировки закрыто при завершении.')
