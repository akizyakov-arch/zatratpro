"""The Telegram boundary maps authenticated senders to canonical user IDs."""
from app.services.account_links import AccountLinkService
from app.services.advances import AdvanceError


async def actor(user) -> int:
    if user is None:
        raise AdvanceError('Не удалось определить отправителя.')
    uid = await AccountLinkService().resolve('telegram', str(user.id))
    if uid is None:
        raise AdvanceError('Сначала отправь /start и войди в компанию.')
    return uid
