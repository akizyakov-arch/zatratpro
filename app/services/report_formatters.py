from __future__ import annotations
from html import escape
from collections import defaultdict
from decimal import Decimal
from app.schemas.fiscal import fiscalization_label

from app.services.report_periods import REPORT_PERIOD_LABELS

NL = chr(10)


def _text(value) -> str:
    return escape(str(value), quote=False)


def format_amount(value) -> str:
    amount = value or 0
    try:
        return f'{amount:,.2f}'.replace(',', ' ')
    except Exception:
        return str(amount)


def format_date(value) -> str:
    if value is None:
        return 'без даты'
    if hasattr(value, 'strftime'):
        return value.strftime('%d.%m.%Y')
    return str(value)


def report_period_label(period: str) -> str:
    return REPORT_PERIOD_LABELS.get(period, period)


def format_report_overview(summary, title: str) -> str:
    return NL.join([
        f'<b>{_text(title)}</b>',
        f'Период: {report_period_label(summary.period)}',
        f'С даты: {summary.start_at:%Y-%m-%d}',
        f'Документов: {summary.documents}',
        f'Сумма: {format_amount(summary.total_amount)}',
        f'Точных дублей: {summary.exact_duplicates}',
        f'Вероятных дублей: {summary.probable_duplicates}',
    ])


def format_project_report(summary, rows) -> str:
    lines = [
        '<b>Отчет по проектам</b>',
        f'Документов: {summary.documents}',
        f'Сумма: {format_amount(summary.total_amount)}',
        f'Точных дублей: {summary.exact_duplicates}',
        f'Вероятных дублей: {summary.probable_duplicates}',
        '',
    ]
    if not rows:
        lines.append('За период документов по проектам нет.')
        return NL.join(lines)
    for index, row in enumerate(rows[:20], start=1):
        duplicate_parts = []
        if row.exact_duplicate_count:
            duplicate_parts.append(f'точные дубли: {row.exact_duplicate_count}')
        if row.probable_duplicate_count:
            duplicate_parts.append(f'возможные дубли: {row.probable_duplicate_count}')
        duplicate_suffix = f" | {'; '.join(duplicate_parts)}" if duplicate_parts else ''
        lines.append(
            f"{index}. {_text(row.project_name)} — {row.document_count} док. — {format_amount(row.total_amount)}{duplicate_suffix}"
        )
    return NL.join(lines)


def format_employee_report(summary, rows) -> str:
    lines = [format_report_overview(summary, 'Отчет по сотрудникам'), '']
    if not rows:
        lines.append('За период документов по сотрудникам нет.')
        return NL.join(lines)
    for index, row in enumerate(rows[:20], start=1):
        employee_name = row.employee_name or (f'@{row.username}' if row.username else f'user:{row.user_id}')
        employee_name = _text(employee_name)
        if getattr(row, 'role', None) == 'manager':
            employee_name = f'<b>{employee_name}</b> (руководитель)'
        duplicate_parts = []
        if row.exact_duplicate_count:
            duplicate_parts.append(f'точные дубли: {row.exact_duplicate_count}')
        if row.probable_duplicate_count:
            duplicate_parts.append(f'возможные дубли: {row.probable_duplicate_count}')
        duplicate_suffix = f" | {'; '.join(duplicate_parts)}" if duplicate_parts else ''
        lines.append(
            f"{index}. {employee_name} — {row.document_count} док. — {format_amount(row.total_amount)}{duplicate_suffix}"
        )
    return NL.join(lines)


def format_duplicate_report(summary, rows) -> str:
    lines = [
        '<b>Отчет по дублям документов</b>',
        f'С даты: {summary.start_at:%Y-%m-%d}',
        f'Документов: {summary.documents}',
        f'Сумма: {format_amount(summary.total_amount)}',
        f'Точных дублей: {summary.exact_duplicates}',
        f'Вероятных дублей: {summary.probable_duplicates}',
    ]
    if not rows:
        lines.extend(['', 'За период дублей не найдено.'])
    return NL.join(lines).strip()


def format_report_documents(title: str, period: str, documents) -> str:
    totals = defaultdict(Decimal)
    for document in documents:
        totals[getattr(document, 'currency', None) or 'RUB'] += Decimal(str(document.total_amount or 0))
    total_text = '; '.join(f'{format_amount(amount)} {_text(currency)}' for currency, amount in sorted(totals.items())) or '0.00 RUB'
    lines = [
        f'<b>{_text(title)}</b>',
        f'Общая сумма затрат: {total_text}',
        f'Документов: {len(documents)}',
        '',
    ]
    if not documents:
        lines.append('Документов за период нет.')
        return NL.join(lines)
    lines.append('Документы 👇')
    return NL.join(lines).strip()


def format_report_document_items(title: str, period: str, document, items) -> str:
    number = document.document_number or 'без номера'
    date_line = format_date(document.document_date)
    vendor = document.vendor or document.vendor_inn or 'Контрагент не указан'
    executor = document.uploaded_by_name or 'не указан'
    project_name = document.project_name or 'Проект не указан'
    lines = [
        f'<b>{_text(title)}</b>',
        f'Проект: {_text(project_name)}',
        f'Контрагент: {_text(vendor)}',
        f'Дата: {_text(date_line)}',
        f'Номер: {_text(number)}',
        'Фискализация: ' + fiscalization_label(getattr(document, 'is_fiscalized', None)),
        f'Сумма: {format_amount(document.total_amount)}',
        'В том числе НДС: ' + (format_amount(document.vat_total_amount) if getattr(document, 'vat_total_amount', None) is not None else 'не определено'),
        f'Исполнитель: {_text(executor)}',
        '',
        'Позиции:',
    ]
    if not items:
        lines.append('Позиции не найдены.')
        return NL.join(lines)
    for item in items[:50]:
        item_name = item.name or 'Без наименования'
        qty = item.quantity if item.quantity is not None else '—'
        price = item.price if item.price is not None else '—'
        line_total = item.line_total if item.line_total is not None else '—'
        tax = f"; НДС {format_amount(item.vat_amount)}" if getattr(item, 'vat_amount', None) is not None else ''
        lines.append(f"{_text(item.line_no)}. {_text(item_name)} | {_text(qty)} x {_text(price)} = {_text(line_total)}{tax}")
    if len(items) > 50:
        lines.append('Показаны только первые 50 позиций документа.')
    return NL.join(lines)
