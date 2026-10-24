import json
from dataclasses import dataclass, field
from datetime import timedelta
from secrets import token_urlsafe

from app.services.database import get_pool

PENDING_ACTION_TTL = timedelta(minutes=15)


@dataclass(slots=True)
class PendingAction:
    action: str
    payload: dict[str, str | int] = field(default_factory=dict)
    revision: str = ''


def _action(row):
    return PendingAction(row['action'], json.loads(row['payload']), row['revision'])


async def set_pending_action(telegram_user_id: int, action: str, payload: dict[str, str | int] | None = None) -> None:
    async with get_pool().acquire() as connection:
        await connection.execute('DELETE FROM pending_actions WHERE expires_at <= clock_timestamp()')
        await connection.execute(
            """INSERT INTO pending_actions (telegram_user_id, action, payload, expires_at, revision)
               VALUES ($1,$2,$3::jsonb,clock_timestamp()+$4::interval,$5)
               ON CONFLICT (telegram_user_id) DO UPDATE SET action=EXCLUDED.action,
               payload=EXCLUDED.payload, expires_at=EXCLUDED.expires_at, revision=EXCLUDED.revision""",
            telegram_user_id, action, json.dumps(payload or {}), PENDING_ACTION_TTL, token_urlsafe(16),
        )


async def pop_pending_action(telegram_user_id: int, *, expected_revision: str | None = None) -> PendingAction | None:
    async with get_pool().acquire() as connection:
        row = await connection.fetchrow(
            """DELETE FROM pending_actions WHERE telegram_user_id=$1
               AND ($2::text IS NULL OR revision=$2)
               RETURNING action,payload,revision,expires_at > clock_timestamp() AS valid""",
            telegram_user_id, expected_revision,
        )
    return _action(row) if row is not None and row['valid'] else None


async def get_pending_action(telegram_user_id: int) -> PendingAction | None:
    async with get_pool().acquire() as connection:
        row = await connection.fetchrow(
            'SELECT action,payload,revision FROM pending_actions WHERE telegram_user_id=$1 AND expires_at>clock_timestamp()',
            telegram_user_id,
        )
    return _action(row) if row else None
