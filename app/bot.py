import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher

from app.config import get_settings
from app.handlers.documents import router as documents_router
from app.handlers.start import router as start_router
from app.handlers.advances import router as advances_router
from app.handlers.business_cards import router as business_cards_router
from app.handlers.profile import router as profile_router
from app.handlers.link_notifications import start_notifications,stop_notifications
from app.logging_utils import RedactingFormatter
from app.services.database import close_db, init_db


def configure_logging() -> None:
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(RedactingFormatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s'))
    logging.basicConfig(level=settings.log_level.upper(), handlers=[handler], force=True)
    logging.disable(logging.NOTSET)


async def on_startup(bot: Bot) -> None:
    await init_db()
    logging.getLogger(__name__).info("Database pool initialized")
    start_notifications(bot)


async def on_shutdown() -> None:
    await stop_notifications()
    await close_db()
    logging.getLogger(__name__).info("Database pool closed")


async def main() -> None:
    configure_logging()
    settings = get_settings()

    bot = Bot(token=settings.telegram_bot_token)
    dispatcher = Dispatcher()
    dispatcher.startup.register(on_startup)
    dispatcher.shutdown.register(on_shutdown)

    dispatcher.include_router(documents_router)
    dispatcher.include_router(profile_router)
    dispatcher.include_router(business_cards_router)
    dispatcher.include_router(advances_router)
    dispatcher.include_router(start_router)

    logging.getLogger(__name__).info("Starting Telegram bot polling")
    await dispatcher.start_polling(bot)


def run() -> None:
    asyncio.run(main())
