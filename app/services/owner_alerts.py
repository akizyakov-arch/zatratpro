import logging
from typing import Iterable

from app.config import get_settings


logger = logging.getLogger(__name__)
_MAX_ALERT_TEXT_LEN = 3500


async def notify_owner_critical(bot, title: str, lines: Iterable[str]) -> None:
    owner_telegram_id = get_settings().bot_owner_telegram_id
    if owner_telegram_id <= 0:
        return

    parts = [f'CRITICAL: {title}']
    parts.extend(line for line in lines if line)
    text = '\n'.join(parts)
    if len(text) > _MAX_ALERT_TEXT_LEN:
        text = text[: _MAX_ALERT_TEXT_LEN - 3] + '...'

    try:
        await bot.send_message(owner_telegram_id, text)
    except Exception:
        logger.warning(
            'Failed to deliver critical owner alert: owner_telegram_id=%s title=%s',
            owner_telegram_id,
            title,
            exc_info=True,
        )
