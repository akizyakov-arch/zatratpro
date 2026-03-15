import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher

from app.config import get_settings
from app.handlers.documents import router as documents_router
from app.handlers.start import router as start_router


def configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )


async def main() -> None:
    configure_logging()
    settings = get_settings()

    bot = Bot(token=settings.telegram_bot_token)
    dispatcher = Dispatcher()

    dispatcher.include_router(start_router)
    dispatcher.include_router(documents_router)

    logging.getLogger(__name__).info("Starting Telegram bot polling")
    await dispatcher.start_polling(bot)


def run() -> None:
    asyncio.run(main())
