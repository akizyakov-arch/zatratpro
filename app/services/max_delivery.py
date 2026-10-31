"""MAX polling persistence only; event processing and HTTP stay in the adapter."""
from app.services.database import get_pool


def acquire_lease():
    return get_pool().acquire()


async def check(lease):
    await lease.fetchval('SELECT 1')


async def marker(lease, bot_id):
    return await lease.fetchval('SELECT marker FROM max_poll_offsets WHERE bot_id=$1',bot_id)


async def checkpoint(lease, bot_id, value):
    await lease.execute("""INSERT INTO max_poll_offsets(bot_id,marker) VALUES($1,$2)
        ON CONFLICT(bot_id) DO UPDATE SET marker=EXCLUDED.marker,updated_at=clock_timestamp()""",bot_id,value)


async def lock(lease, key):
    return await lease.fetchval('SELECT pg_try_advisory_lock(hashtextextended($1,0))',key)


async def unlock(lease, key):
    await lease.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))',key)


# Bound outstanding persisted updates, rather than spawning unbounded OCR tasks.
MAX_PENDING_UPDATES = 1000


class InboxFull(RuntimeError):
    pass


async def ingest(lease, bot_id, records, next_marker):
    """Atomically retain a received page and move the transport cursor.

    records contain plain delivery metadata, never SDK objects or trusted actors.
    Sender keys only order events; handlers still resolve identity and access.
    """
    import json
    async with lease.transaction():
        # Keep a bounded deduplication horizon without retaining event contents.
        await lease.execute("""DELETE FROM max_update_inbox WHERE id IN (
            SELECT id FROM max_update_inbox WHERE bot_id=$1 AND status='done'
              AND completed_at<clock_timestamp()-interval '30 days'
            ORDER BY completed_at,id LIMIT 1000)""", bot_id)
        pending = await lease.fetchval("SELECT count(*) FROM max_update_inbox WHERE bot_id=$1 AND status<>'done'", bot_id)
        keys = list({record['key'] for record in records})
        existing = await lease.fetch("SELECT event_key FROM max_update_inbox WHERE bot_id=$1 AND event_key=ANY($2::text[])", bot_id, keys)
        existing_keys = {row['event_key'] for row in existing}
        if pending + len(set(keys) - existing_keys) > MAX_PENDING_UPDATES:
            raise InboxFull('MAX: очередь заполнена; получение новых событий приостановлено.')
        for record in records:
            await lease.execute('''INSERT INTO max_update_inbox(bot_id,event_key,sender_key,lane,payload)
                VALUES($1,$2,$3,$4,$5::jsonb) ON CONFLICT(bot_id,event_key) DO NOTHING''',
                bot_id, record['key'], record['sender'], record['lane'], json.dumps(record['payload'], ensure_ascii=False))
        if next_marker is not None:
            await checkpoint(lease, bot_id, next_marker)


async def recover(bot_id):
    """Called only after obtaining the exclusive bot polling lease."""
    await get_pool().execute("UPDATE max_update_inbox SET status='queued',run_token=NULL,available_at=clock_timestamp() WHERE bot_id=$1 AND status='running'", bot_id)


async def claim(bot_id, lane):
    from uuid import uuid4
    import json
    token = uuid4().hex
    async with get_pool().acquire() as c, c.transaction():
        row = await c.fetchrow('''SELECT q.id,q.payload,q.attempts,q.sender_key,q.prepared_reply,q.handler_started FROM max_update_inbox q
            WHERE q.bot_id=$1 AND q.lane=$2 AND q.status='queued'
              AND q.available_at<=clock_timestamp()
              AND NOT EXISTS(SELECT 1 FROM max_update_inbox p WHERE p.bot_id=q.bot_id
                  AND p.sender_key=q.sender_key AND p.id<q.id AND p.status<>'done')
            ORDER BY q.id FOR UPDATE OF q SKIP LOCKED LIMIT 1''', bot_id, lane)
        if row is None:
            return None
        payload = json.loads(row['payload'])
        retry_document = False
        if row['attempts'] > 0 and row['prepared_reply'] is None and payload.get('update_type') == 'message_created':
            body = payload.get('message', {}).get('body', {})
            event_id = body.get('mid') if isinstance(body, dict) else None
            attachments = body.get('attachments') or [] if isinstance(body, dict) else []
            if isinstance(event_id, str) and any(isinstance(item, dict) and item.get('type') in ('image','photo','file') for item in attachments):
                actor = await c.fetchval("SELECT user_id FROM external_accounts WHERE platform='max' AND external_id=$1", row['sender_key'])
                if actor is not None:
                    import hashlib
                    retry_document = await c.fetchval('''SELECT EXISTS(SELECT 1 FROM document_upload_events e
                        JOIN company_members m ON m.user_id=e.actor_id AND m.company_id=e.company_id AND m.status='active'
                        JOIN companies co ON co.id=m.company_id AND co.status='active'
                        JOIN users u ON u.id=m.user_id AND u.is_active
                        WHERE e.actor_id=$1 AND e.platform='max' AND e.event_hash=$2)''',actor,hashlib.sha256(event_id.encode()).hexdigest())
                    from app.services.document_flow import DocumentFlow
                    await DocumentFlow().recover_interrupted(actor, 'max', event_id, connection=c)
        await c.execute("UPDATE max_update_inbox SET status='running',run_token=$2,attempts=attempts+1 WHERE id=$1", row['id'], token)
    return {'id': row['id'], 'token': token, 'attempts': row['attempts']+1,
            'payload': payload, 'sender': row['sender_key'],
            'reply': json.loads(row['prepared_reply']) if row['prepared_reply'] is not None else None,
            'started': row['handler_started'], 'retry_document': retry_document}


async def complete(job):
    return await get_pool().fetchval('''UPDATE max_update_inbox SET status='done',run_token=NULL,
        payload='{}'::jsonb,prepared_reply=NULL,completed_at=clock_timestamp()
        WHERE id=$1 AND status='running' AND run_token=$2 RETURNING id''', job['id'], job['token']) is not None


async def retry(job, delay):
    return await get_pool().fetchval('''UPDATE max_update_inbox SET status='queued',run_token=NULL,
        available_at=clock_timestamp()+$3::double precision*interval '1 second'
        WHERE id=$1 AND status='running' AND run_token=$2 RETURNING id''',
        job['id'], job['token'], max(0, delay)) is not None


async def pending_count(bot_id):
    return await get_pool().fetchval("SELECT count(*) FROM max_update_inbox WHERE bot_id=$1 AND status<>'done'", bot_id)


async def next_delay(bot_id, lanes=None):
    """Wake for a ready head event; blocked followers wake on predecessor completion."""
    lanes = ['fast','background'] if lanes is None else list(lanes)
    if not lanes:
        return 30
    seconds = await get_pool().fetchval('''SELECT extract(epoch FROM min(q.available_at)-clock_timestamp())
        FROM max_update_inbox q WHERE q.bot_id=$1 AND q.status='queued' AND q.lane=ANY($2::text[])
          AND NOT EXISTS(SELECT 1 FROM max_update_inbox p WHERE p.bot_id=q.bot_id
              AND p.sender_key=q.sender_key AND p.id<q.id AND p.status<>'done')''', bot_id, lanes)
    return 30 if seconds is None else min(30, max(.01, float(seconds)))


async def reply_scope(sender):
    """Current identity and authority for re-delivering a prepared private reply."""
    from app.config import get_owner_telegram_id
    row = await get_pool().fetchrow("""SELECT u.id,u.is_active,u.system_role,
        cm.company_id,cm.role,cm.status AS membership_status,co.status AS company_status
        FROM external_accounts a JOIN users u ON u.id=a.user_id
        LEFT JOIN company_members cm ON cm.user_id=u.id AND cm.status='active'
        LEFT JOIN companies co ON co.id=cm.company_id
        WHERE a.platform='max' AND a.external_id=$1""", sender)
    if row is None or not row['is_active']:
        return None
    result = dict(row)
    if row['system_role'] == 'owner':
        result['owner_configuration'] = get_owner_telegram_id()
    return result


async def prepare_reply(job, response):
    """Persist a presentation DTO before sending; retries never resubmit input."""
    import json
    return await get_pool().fetchval("""UPDATE max_update_inbox SET prepared_reply=$3::jsonb
        WHERE id=$1 AND status='running' AND run_token=$2 RETURNING id""",
        job['id'], job['token'], json.dumps(response, ensure_ascii=False)) is not None


async def mark_started(job):
    """Fence the uncertain crash window before executing a state-changing handler."""
    return await get_pool().fetchval("""UPDATE max_update_inbox SET handler_started=TRUE
        WHERE id=$1 AND status='running' AND run_token=$2 RETURNING id""",
        job['id'], job['token']) is not None
