"""Legacy Telegram recognition settings names resolve to canonical identities."""
from app.services.recognition import get_provider_for_user, set_provider_for_user
from app.services.account_links import AccountLinkService


async def get_provider_name(external_id):
    actor=await AccountLinkService().resolve('telegram',str(external_id))
    return await get_provider_for_user(actor) if actor is not None else 'deepseek'


async def set_provider(external_id, provider):
    actor=await AccountLinkService().resolve('telegram',str(external_id))
    if actor is None:raise ValueError('Сначала войди в бот через /start.')
    await set_provider_for_user(actor,provider)
