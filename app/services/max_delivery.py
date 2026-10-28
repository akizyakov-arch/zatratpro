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
