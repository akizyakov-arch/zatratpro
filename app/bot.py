import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from app.config import get_settings
from app.handlers.ai_reports import router as ai_reports_router
from app.handlers.settings import router as settings_router
from app.handlers.documents import router as documents_router
from app.handlers.start import router as start_router
from app.handlers.workspace import router as workspace_router
from app.handlers.issue import router as issue_router
from app.handlers.advances import router as advances_router
from app.handlers.business_cards import router as business_cards_router
from app.handlers.profile import router as profile_router
from app.handlers.web_login import router as web_login_router
from app.handlers.mini_app import router as mini_app_router
from app.handlers.link_notifications import start_notifications,stop_notifications
from app.handlers.advance_notifications import (
    start_notifications as start_advance_notifications,
    stop_notifications as stop_advance_notifications,
)
from app.logging_utils import RedactingFormatter
from app.services.database import close_db, init_db
from app.services.platform_owner import synchronize_owner
from app.services.document_housekeeping import start_document_housekeeping, stop_document_housekeeping

_housekeeping_task = None


def configure_logging() -> None:
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(RedactingFormatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s'))
    logging.basicConfig(level=settings.log_level.upper(), handlers=[handler], force=True)
    logging.disable(logging.NOTSET)


async def on_startup(bot: Bot) -> None:
    global _housekeeping_task
    await init_db()
    try:
        await synchronize_owner(get_settings().bot_owner_telegram_id)
    except BaseException:
        await close_db()
        raise
    logging.getLogger(__name__).info("Database pool initialized")
    _housekeeping_task = start_document_housekeeping()
    start_notifications(bot)
    start_advance_notifications(bot)


async def on_shutdown() -> None:
    global _housekeeping_task
    await stop_document_housekeeping(_housekeeping_task)
    _housekeeping_task = None
    await stop_advance_notifications()
    await stop_notifications()
    await close_db()
    logging.getLogger(__name__).info("Database pool closed")


def create_bot(settings):
    proxy = settings.telegram_proxy_url.get_secret_value()
    session = AiohttpSession(proxy=proxy) if proxy else None
    return Bot(token=settings.telegram_bot_token, session=session)


async def main() -> None:
    configure_logging()
    settings = get_settings()

    bot = create_bot(settings)
    dispatcher = Dispatcher()
    dispatcher.startup.register(on_startup)
    dispatcher.shutdown.register(on_shutdown)

    from app.handlers.accountant import router as accountant_router
    dispatcher.include_router(accountant_router)
    dispatcher.include_router(workspace_router)
    dispatcher.include_router(issue_router)
    dispatcher.include_router(ai_reports_router)
    dispatcher.include_router(settings_router)
    dispatcher.include_router(mini_app_router)
    dispatcher.include_router(web_login_router)
    dispatcher.include_router(documents_router)
    dispatcher.include_router(profile_router)
    dispatcher.include_router(business_cards_router)
    dispatcher.include_router(advances_router)
    dispatcher.include_router(start_router)

    logging.getLogger(__name__).info("Starting Telegram bot polling")
    await dispatcher.start_polling(bot)


def run() -> None:
    asyncio.run(main())
