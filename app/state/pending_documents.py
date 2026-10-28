"""Telegram compatibility adapter for canonical document draft storage."""
from app.services.document_drafts import PendingDocument, PENDING_DOCUMENT_TTL
from app.services import document_drafts as core
from app.services.account_links import AccountLinkService
from app.services.companies import CompanyAccessError


async def _actor(telegram_id):
    actor = await AccountLinkService().resolve('telegram', str(telegram_id))
    if actor is None:
        raise CompanyAccessError('Учётная запись недоступна.')
    return actor


async def begin_document_flow(telegram_user_id):
    return await core.begin_document_flow(await _actor(telegram_user_id))


async def has_active_document_flow(telegram_user_id):
    return await core.has_active_document_flow(await _actor(telegram_user_id))


async def store_pending_document(telegram_user_id, pending_document):
    return await core.store_pending_document(await _actor(telegram_user_id), pending_document)


async def get_pending_document(telegram_user_id):
    return await core.get_pending_document(await _actor(telegram_user_id))


async def clear_document_flow(telegram_user_id, upload_id=None):
    return await core.clear_document_flow(await _actor(telegram_user_id), upload_id)
