import logging
from time import perf_counter
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update


class SlowUpdateMiddleware(BaseMiddleware):
    def __init__(self, threshold_ms: float = 400.0) -> None:
        self.threshold_ms = threshold_ms
        self.logger = logging.getLogger(__name__)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        started = perf_counter()
        try:
            return await handler(event, data)
        finally:
            elapsed_ms = (perf_counter() - started) * 1000
            self._log_non_text_update(event)
            if elapsed_ms < self.threshold_ms:
                return
            self.logger.warning(
                "Slow update: %s",
                self._build_message(event, elapsed_ms),
            )

    def _log_non_text_update(self, event: TelegramObject) -> None:
        message = None
        if isinstance(event, Update):
            message = event.message or event.edited_message
        elif isinstance(event, Message):
            message = event
        if message is None:
            return
        if message.text:
            return
        if not any((message.photo, message.document, message.animation, message.video, message.sticker, message.voice, message.audio)):
            return
        self.logger.info(
            "Inbound non-text update: user_id=%s has_photo=%s has_document=%s has_animation=%s has_video=%s has_sticker=%s has_voice=%s has_audio=%s file_name=%s mime_type=%s caption=%s",
            message.from_user.id if message.from_user else 0,
            bool(message.photo),
            message.document is not None,
            message.animation is not None,
            message.video is not None,
            message.sticker is not None,
            message.voice is not None,
            message.audio is not None,
            message.document.file_name if message.document is not None else None,
            message.document.mime_type if message.document is not None else None,
            message.caption,
        )

    def _build_message(self, event: TelegramObject, elapsed_ms: float) -> str:
        if isinstance(event, Update):
            if event.callback_query is not None:
                return self._build_message(event.callback_query, elapsed_ms)
            if event.message is not None:
                return self._build_message(event.message, elapsed_ms)
            if event.edited_message is not None:
                return self._build_message(event.edited_message, elapsed_ms)
            return f"update_id={event.update_id} type=unknown took={elapsed_ms:.1f}ms"
        if isinstance(event, CallbackQuery):
            return (
                f"callback update_user_id={event.from_user.id if event.from_user else 0} "
                f"data={event.data!r} took={elapsed_ms:.1f}ms"
            )
        if isinstance(event, Message):
            text = event.text or event.caption or ""
            snippet = text.replace("\n", " ")[:80]
            return (
                f"message update_user_id={event.from_user.id if event.from_user else 0} "
                f"text={snippet!r} took={elapsed_ms:.1f}ms"
            )
        return f"event={event.__class__.__name__} took={elapsed_ms:.1f}ms"
