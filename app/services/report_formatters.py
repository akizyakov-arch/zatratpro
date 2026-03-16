from __future__ import annotations

from collections import defaultdict

from app.ui.reports import REPORT_PERIOD_LABELS

NL = chr(10)


def format_amount(value) -> str:
    return str(value or 0)


def report_period_label(period: str) -> str:
    return REPORT_PERIOD_LABELS.get(period, period)


def format_report_overview(summary, title: str) -> str:
    return NL.join([
        title,
        f'Период: {report_period_label(summary.period)}',
        f'С даты: {summary.start_at:%Y-%m-%d}',
        f'Документов: {summary.documents}',
        f'Сумма: {format_amount(summary.total_amount)}',
        f'Точных дублей: {summary.exact_duplicates}',
        f'Вероятных дублей: {summary.probable_duplicates}',
    ])


def format_project_report(summary, rows) -> str:
    lines = [format_report_overview(summary, 'Отчет по проектам'), '']
    if not rows:
        lines.append('За период документов по проектам нет.')
        return NL.join(lines)
    for index, row in enumerate(rows[:20], start=1):
        lines.append(
            f"{index}. {row.project_name} — {row.document_count} док. — {format_amount(row.total_amount)} "
            f"(exact: {row.exact_duplicate_count}, probable: {row.probable_duplicate_count})"
        )
    return NL.join(lines)


def format_employee_report(summary, rows) -> str:
    lines = [format_report_overview(summary, 'Отчет по сотрудникам'), '']
    if not rows:
        lines.append('За период документов по сотрудникам нет.')
        return NL.join(lines)
    for index, row in enumerate(rows[:20], start=1):
        employee_name = row.employee_name or (f'@{row.username}' if row.username else f'user:{row.user_id}')
        lines.append(
            f"{index}. {employee_name} — {row.document_count} док. — {format_amount(row.total_amount)} "
            f"(exact: {row.exact_duplicate_count}, probable: {row.probable_duplicate_count})"
        )
    return NL.join(lines)


def format_duplicate_report(summary, rows) -> str:
    lines = [format_report_overview(summary, 'Отчет по дублям документов'), '']
    if not rows:
        lines.append('За период дублей не найдено.')
        return NL.join(lines)
    for index, row in enumerate(rows[:20], start=1):
        vendor = row.vendor_inn or row.vendor or 'без продавца'
        number = row.document_number or 'без номера'
        date_line = row.document_date.isoformat() if row.document_date else 'без даты'
        link = f' -> {row.duplicate_of_document_id}' if row.duplicate_of_document_id else ''
        lines.append(
            f"{index}. #{row.id} [{row.duplicate_status}] {row.project_name} | {number} | {date_line} | {vendor} | {format_amount(row.total_amount)}{link}"
        )
    return NL.join(lines)


def format_documents_with_items(title: str, period: str, documents, items) -> str:
    lines = [title, f'Период: {report_period_label(period)}', '']
    if not documents:
        lines.append('Документов за период нет.')
        return NL.join(lines)
    items_by_document = defaultdict(list)
    for item in items:
        items_by_document[item.document_id].append(item)
    for index, document in enumerate(documents[:10], start=1):
        number = document.document_number or 'без номера'
        date_line = document.document_date.isoformat() if document.document_date else 'без даты'
        vendor = document.vendor_inn or document.vendor or 'без продавца'
        lines.append(
            f"{index}. Документ #{document.id} | {document.project_name} | {number} | {date_line} | {vendor} | {format_amount(document.total_amount)} | {document.duplicate_status}"
        )
        for item in items_by_document.get(document.id, [])[:10]:
            item_name = item.name or 'Без наименования'
            qty = item.quantity if item.quantity is not None else '—'
            price = item.price if item.price is not None else '—'
            line_total = item.line_total if item.line_total is not None else '—'
            lines.append(f"  {item.line_no}. {item_name} | {qty} x {price} = {line_total}")
        if len(items_by_document.get(document.id, [])) > 10:
            lines.append('  ... позиции обрезаны')
        lines.append('')
    if len(documents) > 10:
        lines.append('Показаны только первые 10 документов за период.')
    return NL.join(lines).strip()
