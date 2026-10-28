"""Telegram compatibility adapter over canonical pending input storage."""
from app.services.pending_inputs import PendingAction, PENDING_ACTION_TTL
from app.services.pending_inputs import set_input, get_input, pop_input
from app.adapters.telegram.companies import actor


async def set_pending_action(telegram_user_id, action, payload=None):
    await set_input(await actor(telegram_user_id), action, payload)


async def get_pending_action(telegram_user_id):
    return await get_input(await actor(telegram_user_id))


async def pop_pending_action(telegram_user_id, *, expected_revision=None):
    return await pop_input(await actor(telegram_user_id), expected_revision=expected_revision)
