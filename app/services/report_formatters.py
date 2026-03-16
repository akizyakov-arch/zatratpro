from __future__ import annotations

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


def format_report_documents(title: str, period: str, documents) -> str:
    lines = [title, f'Период: {report_period_label(period)}', '']
    if not documents:
        lines.append('Документов за период нет.')
        return NL.join(lines)
    for index, document in enumerate(documents[:20], start=1):
        number = document.document_number or 'без номера'
        date_line = document.document_date.isoformat() if document.document_date else 'без даты'
        vendor = document.vendor_inn or document.vendor or 'без продавца'
        executor = document.uploaded_by_name or 'исполнитель не определен'
        lines.append(
            f"{index}. #{document.id} | {number} | {date_line} | {vendor} | {format_amount(document.total_amount)} | исполнитель: {executor} | {document.duplicate_status}"
        )
    if len(documents) > 20:
        lines.append('Показаны только первые 20 документов за период.')
    return NL.join(lines).strip()


def format_report_document_items(title: str, period: str, document, items) -> str:
    number = document.document_number or 'без номера'
    date_line = document.document_date.isoformat() if document.document_date else 'без даты'
    vendor = document.vendor_inn or document.vendor or 'без продавца'
    executor = document.uploaded_by_name or 'исполнитель не определен'
    lines = [
        title,
        f'Период: {report_period_label(period)}',
        f'Документ: #{document.id}',
        f'Номер: {number}',
        f'Дата: {date_line}',
        f'Продавец: {vendor}',
        f'Сумма: {format_amount(document.total_amount)}',
        f'Исполнитель: {executor}',
        f'Статус дубля: {document.duplicate_status}',
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
        lines.append(f"{item.line_no}. {item_name} | {qty} x {price} = {line_total}")
    if len(items) > 50:
        lines.append('Показаны только первые 50 позиций документа.')
    return NL.join(lines)
