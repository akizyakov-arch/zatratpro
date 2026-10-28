"""Durable, canonical-user input state. No external messenger IDs in the contract."""
import json
from dataclasses import dataclass, field
from datetime import timedelta
from secrets import token_urlsafe
from app.services.database import get_pool
from app.services.workspace import workspace_transaction

PENDING_ACTION_TTL = timedelta(minutes=15)


@dataclass(slots=True)
class PendingAction:
    action: str
    payload: dict = field(default_factory=dict)
    revision: str = ''
    company_id: int | None = None


def decode(row):
    return PendingAction(row['action'], json.loads(row['payload']), row['revision'], row['company_id']) if row else None


async def set_input(actor, action, payload=None, *, connection=None, company_id=None):
    async with workspace_transaction(connection) as c:
        await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f'conversation:{actor}')
        if company_id is None:
            company_id=await c.fetchval("SELECT company_id FROM company_members WHERE user_id=$1 AND status='active'",actor)
        await c.execute('''INSERT INTO pending_actions(actor_id,company_id,action,payload,revision,expires_at)
            VALUES($1,$2,$3,$4::jsonb,$5,clock_timestamp()+interval '15 minutes')
            ON CONFLICT(actor_id) DO UPDATE SET company_id=EXCLUDED.company_id,action=EXCLUDED.action,
            payload=EXCLUDED.payload,revision=EXCLUDED.revision,expires_at=EXCLUDED.expires_at''',
            actor,company_id,action,json.dumps(payload or {}),token_urlsafe(16))


async def get_input(actor, *, connection=None):
    return decode(await (connection or get_pool()).fetchrow('SELECT * FROM pending_actions WHERE actor_id=$1 AND expires_at>clock_timestamp()',actor))


async def pop_input(actor, *, expected_revision=None, connection=None):
    row=await (connection or get_pool()).fetchrow('''DELETE FROM pending_actions WHERE actor_id=$1
        AND ($2::text IS NULL OR revision=$2) RETURNING *,expires_at>clock_timestamp() AS valid''',actor,expected_revision)
    return decode(row) if row and row['valid'] else None
