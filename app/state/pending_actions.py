import json
from dataclasses import dataclass, field
from datetime import timedelta

from app.services.database import get_pool

PENDING_ACTION_TTL = timedelta(minutes=15)


@dataclass(slots=True)
class PendingAction:
    action: str
    payload: dict[str, str | int] = field(default_factory=dict)


async def set_pending_action(telegram_user_id: int, action: str, payload: dict[str, str | int] | None = None) -> None:
    async with get_pool().acquire() as connection:
        await connection.execute('DELETE FROM pending_actions WHERE expires_at <= NOW()')
        await connection.execute(
            """INSERT INTO pending_actions (telegram_user_id, action, payload, expires_at)
               VALUES ($1,$2,$3::jsonb,NOW()+$4::interval)
               ON CONFLICT (telegram_user_id) DO UPDATE SET action=EXCLUDED.action,
               payload=EXCLUDED.payload, expires_at=EXCLUDED.expires_at""",
            telegram_user_id, action, json.dumps(payload or {}), PENDING_ACTION_TTL,
        )


async def pop_pending_action(telegram_user_id: int) -> PendingAction | None:
    # A single DELETE RETURNING consumes an action exactly once under concurrency.
    async with get_pool().acquire() as connection:
        row = await connection.fetchrow(
            'DELETE FROM pending_actions WHERE telegram_user_id=$1 RETURNING action,payload,expires_at > NOW() AS valid',
            telegram_user_id,
        )
    if row is None or not row['valid']:
        return None
    return PendingAction(action=row['action'], payload=json.loads(row['payload']))


async def get_pending_action(telegram_user_id: int) -> PendingAction | None:
    async with get_pool().acquire() as connection:
        row = await connection.fetchrow('SELECT action,payload FROM pending_actions WHERE telegram_user_id=$1 AND expires_at>NOW()', telegram_user_id)
    return PendingAction(row['action'], json.loads(row['payload'])) if row else None
