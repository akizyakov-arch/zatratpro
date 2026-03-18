import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher

from app.config import get_settings
from app.handlers.documents import router as documents_router
from app.handlers.help import router as help_router
from app.handlers.manager import router as manager_router
from app.handlers.owner import router as owner_router
from app.handlers.reports import router as reports_router
from app.handlers.start import router as start_router
from app.services.database import close_db, init_db


def configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )


async def on_startup() -> None:
    await init_db()
    logging.getLogger(__name__).info("Database pool initialized")


async def on_shutdown() -> None:
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
    dispatcher.include_router(help_router)
    dispatcher.include_router(owner_router)
    dispatcher.include_router(manager_router)
    dispatcher.include_router(reports_router)
    dispatcher.include_router(start_router)

    logging.getLogger(__name__).info("Starting Telegram bot polling")
    await dispatcher.start_polling(bot)


def run() -> None:
    asyncio.run(main())
