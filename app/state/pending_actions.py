import json
from dataclasses import dataclass, field

from app.services.database import get_pool


PENDING_ACTION_TTL_MINUTES = 30


@dataclass(slots=True)
class PendingAction:
    action: str
    payload: dict[str, str | int] = field(default_factory=dict)


async def set_pending_action(
    telegram_user_id: int,
    action: str,
    payload: dict[str, str | int] | None = None,
) -> None:
    pool = get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            """
            INSERT INTO pending_actions (telegram_user_id, action, payload, expires_at)
            VALUES ($1, $2, $3::jsonb, NOW() + $4::interval)
            ON CONFLICT (telegram_user_id)
            DO UPDATE SET
                action = EXCLUDED.action,
                payload = EXCLUDED.payload,
                created_at = NOW(),
                expires_at = EXCLUDED.expires_at
            """,
            telegram_user_id,
            action,
            json.dumps(payload or {}),
            f"{PENDING_ACTION_TTL_MINUTES} minutes",
        )


async def get_pending_action(telegram_user_id: int) -> PendingAction | None:
    pool = get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            "DELETE FROM pending_actions WHERE telegram_user_id = $1 AND expires_at <= NOW()",
            telegram_user_id,
        )
        row = await connection.fetchrow(
            """
            SELECT action, payload
            FROM pending_actions
            WHERE telegram_user_id = $1
            """,
            telegram_user_id,
        )
    if row is None:
        return None
    return PendingAction(action=row["action"], payload=dict(row["payload"] or {}))


async def pop_pending_action(telegram_user_id: int) -> PendingAction | None:
    pending_action = await get_pending_action(telegram_user_id)
    if pending_action is None:
        return None
    pool = get_pool()
    async with pool.acquire() as connection:
        await connection.execute("DELETE FROM pending_actions WHERE telegram_user_id = $1", telegram_user_id)
    return pending_action


async def cleanup_expired_pending_actions() -> None:
    pool = get_pool()
    async with pool.acquire() as connection:
        await connection.execute("DELETE FROM pending_actions WHERE expires_at <= NOW()")
