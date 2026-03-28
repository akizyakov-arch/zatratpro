import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update, User

from app.services.access import AccessService


logger = logging.getLogger(__name__)


def _extract_telegram_user(event: TelegramObject) -> User | None:
    if isinstance(event, Update):
        if event.callback_query is not None:
            return event.callback_query.from_user
        if event.message is not None:
            return event.message.from_user
        if event.edited_message is not None:
            return event.edited_message.from_user
        return None
    if isinstance(event, CallbackQuery):
        return event.from_user
    if isinstance(event, Message):
        return event.from_user
    return getattr(event, "from_user", None)


class AccessContextMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self.access_service = AccessService()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        telegram_user = _extract_telegram_user(event)
        if telegram_user is None:
            data.setdefault("access_context", None)
            return await handler(event, data)

        try:
            data["access_context"] = await self.access_service.get_access_context(telegram_user)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to load access context: telegram_user_id=%s", telegram_user.id)
            data.setdefault("access_context", None)

        return await handler(event, data)
