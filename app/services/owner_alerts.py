import logging
from time import monotonic
from typing import Iterable

from app.config import get_settings


logger = logging.getLogger(__name__)
_MAX_ALERT_TEXT_LEN = 3500
_ALERT_RATE_LIMIT_SECONDS = 90.0
_recent_alerts: dict[str, float] = {}


def format_owner_company_line(company) -> str:
    if company is None:
        return 'Компания: id=-'
    company_id = getattr(company, 'id', None)
    company_name = getattr(company, 'name', None)
    if company_name:
        return f'Компания: {company_name} (id={company_id})'
    if company_id is not None:
        return f'Компания: id={company_id}'
    return 'Компания: id=-'


def _normalize_alert_lines(lines: Iterable[str]) -> tuple[str, ...]:
    return tuple(str(line) for line in lines if line)


async def notify_owner_critical(bot, title: str, lines: Iterable[str], *, alert_key: str | None = None) -> None:
    owner_telegram_id = get_settings().bot_owner_telegram_id
    if owner_telegram_id <= 0:
        return

    normalized_lines = _normalize_alert_lines(lines)
    dedupe_key = alert_key or '\n'.join((title, *normalized_lines))
    now = monotonic()
    last_sent_at = _recent_alerts.get(dedupe_key)
    if last_sent_at is not None and now - last_sent_at < _ALERT_RATE_LIMIT_SECONDS:
        return
    _recent_alerts[dedupe_key] = now

    parts = [title]
    if normalized_lines:
        parts.append('')
        parts.extend(normalized_lines)
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


async def notify_owner_security_warning(
    bot,
    *,
    company,
    telegram_user_id: int,
    operation: str,
    document_id: int | None = None,
    details: str | None = None,
) -> None:
    lines = [
        'Возможная утечка данных',
        format_owner_company_line(company),
        f'Пользователь: {telegram_user_id}',
        f'Операция: {operation}',
    ]
    if document_id is not None:
        lines.append(f'Document ID: {document_id}')
    if details:
        lines.append(f'Детали: {details}')
    await notify_owner_critical(
        bot,
        title='🚨 SECURITY WARNING',
        lines=lines,
        alert_key=f'security-warning:{getattr(company, "id", "-")}:{telegram_user_id}:{operation}:{document_id}:{details or "-"}',
    )
