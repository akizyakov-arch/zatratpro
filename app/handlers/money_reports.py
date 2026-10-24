"""Telegram reporting adapter; the report service accepts internal user IDs."""
from types import SimpleNamespace

from app.handlers.telegram_identity import actor
from app.services.advances import AdvanceError
from app.services.json_formatter import chunk_message
from app.services.money_reports import format_money_report, get_money_report_for_user
from app.services.report_periods import report_period_start


async def get_money_report(telegram_id: int, period: str, **scope):
    uid = await actor(SimpleNamespace(id=telegram_id))
    try:
        start = report_period_start(period)
    except ValueError as exc:
        raise AdvanceError(str(exc)) from exc
    return await get_money_report_for_user(uid, start, **scope)


async def send_money_report(message, telegram_id: int, period: str, **scope):
    report = await get_money_report(telegram_id, period, **scope)
    for chunk in chunk_message(format_money_report(report)):
        await message.answer(chunk)
