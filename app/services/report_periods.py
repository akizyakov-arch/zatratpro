"""Shared reporting periods, independent of a messenger or keyboard framework."""
from datetime import date, datetime, timedelta, timezone

REPORT_PERIOD_WEEK = 'week'
REPORT_PERIOD_MONTH = 'month'
REPORT_PERIOD_QUARTER = 'quarter'
REPORT_PERIOD_HALF_YEAR = 'half_year'
REPORT_PERIOD_YEAR = 'year'
REPORT_PERIOD_ALL = 'all_time'
REPORT_PERIOD_LABELS = {
    REPORT_PERIOD_ALL: 'Всё время',
    REPORT_PERIOD_WEEK: 'Неделя',
    REPORT_PERIOD_MONTH: 'Месяц',
    REPORT_PERIOD_QUARTER: 'Квартал',
    REPORT_PERIOD_HALF_YEAR: 'Полугодие',
    REPORT_PERIOD_YEAR: 'Год',
}


def report_period_start(period: str, *, now: datetime | None = None) -> datetime:
    """Preserve the existing UTC accounting boundaries for every interface."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Для периода необходим часовой пояс.')
    now = now.astimezone(timezone.utc)
    if period == REPORT_PERIOD_ALL:
        start = date(2000, 1, 1)
    elif period == REPORT_PERIOD_WEEK:
        start = (now - timedelta(days=now.weekday())).date()
    elif period == REPORT_PERIOD_MONTH:
        start = date(now.year, now.month, 1)
    elif period == REPORT_PERIOD_QUARTER:
        start = date(now.year, ((now.month - 1) // 3) * 3 + 1, 1)
    elif period == REPORT_PERIOD_HALF_YEAR:
        start = date(now.year, 1 if now.month <= 6 else 7, 1)
    elif period == REPORT_PERIOD_YEAR:
        start = date(now.year, 1, 1)
    else:
        raise ValueError('Неизвестный период отчёта.')
    return datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
