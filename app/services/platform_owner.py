"""Explicit owner bootstrap, called only by the Telegram runtime."""
from app.services.database import get_pool


async def synchronize_owner(telegram_id: int) -> None:
    # Missing configuration must never clear ownership in a shared database.
    if type(telegram_id) is not int or telegram_id <= 0:
        raise ValueError('BOT_OWNER_TELEGRAM_ID должен быть положительным ID владельца.')
    async with get_pool().acquire() as connection, connection.transaction():
        await connection.execute('SELECT pg_advisory_xact_lock(734291002)')
        await connection.execute(
            "UPDATE users SET system_role=CASE WHEN telegram_id=$1 THEN 'owner' ELSE 'user' END "
            "WHERE system_role IS DISTINCT FROM CASE WHEN telegram_id=$1 THEN 'owner' ELSE 'user' END",
            telegram_id,
        )
