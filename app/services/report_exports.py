from __future__ import annotations

from io import BytesIO
import re

from openpyxl import Workbook

from app.services.report_periods import REPORT_PERIOD_LABELS
from app.services.money_reports import CASH_FIELDS, cash_and_employee_debt, employee_name


def build_manager_report_workbook(
    period: str,
    summary,
    projects,
    employees,
    duplicates,
    documents,
    items,
    money_report=None,
) -> tuple[str, bytes]:
    workbook = Workbook()

    overview = workbook.active
    overview.title = 'Overview'
    _append_row(overview, ['Период', REPORT_PERIOD_LABELS.get(period, period)])
    _append_row(overview, ['С даты', summary.start_at.isoformat()])
    _append_row(overview, ['Документов', summary.documents])
    _append_row(overview, ['Сумма', float(summary.total_amount or 0)])
    _append_row(overview, ['Точных дублей', summary.exact_duplicates])
    _append_row(overview, ['Вероятных дублей', summary.probable_duplicates])

    projects_sheet = workbook.create_sheet('Projects')
    _append_row(projects_sheet, ['ID проекта', 'Проект', 'Документов', 'Сумма', 'Точных дублей', 'Вероятных дублей'])
    for row in projects:
        _append_row(projects_sheet, [row.project_id, row.project_name, row.document_count, float(row.total_amount or 0), row.exact_duplicate_count, row.probable_duplicate_count])

    employees_sheet = workbook.create_sheet('Employees')
    _append_row(employees_sheet, ['ID пользователя', 'Сотрудник', 'Username', 'Документов', 'Сумма', 'Точных дублей', 'Вероятных дублей'])
    for row in employees:
        _append_row(employees_sheet, [row.user_id, row.employee_name or '', row.username or '', row.document_count, float(row.total_amount or 0), row.exact_duplicate_count, row.probable_duplicate_count])

    duplicates_sheet = workbook.create_sheet('Duplicates')
    _append_row(duplicates_sheet, ['ID документа', 'Статус дубля', 'Дубль записи', 'Проект', 'Номер', 'Дата', 'Продавец', 'ИНН', 'Сумма', 'Кем загружен'])
    for row in duplicates:
        _append_row(duplicates_sheet, [
            row.id,
            row.duplicate_status,
            row.duplicate_of_document_id or '',
            row.project_name,
            row.document_number or '',
            row.document_date.isoformat() if row.document_date else '',
            row.vendor or '',
            row.vendor_inn or '',
            float(row.total_amount or 0),
            row.uploaded_by_name or '',
        ])

    documents_sheet = workbook.create_sheet('Documents')
    _append_row(documents_sheet, ['ID', 'Проект', 'Номер', 'Дата', 'Продавец', 'ИНН', 'Сумма', 'Статус дубля', 'Загружен', 'Кем загружен'])
    for row in documents:
        _append_row(documents_sheet, [
            row.id,
            row.project_name,
            row.document_number or '',
            row.document_date.isoformat() if row.document_date else '',
            row.vendor or '',
            row.vendor_inn or '',
            float(row.total_amount or 0),
            row.duplicate_status,
            row.created_at.isoformat(),
            row.uploaded_by_name or '',
        ])

    items_sheet = workbook.create_sheet('Items')
    _append_row(items_sheet, ['ID документа', 'Строка', 'Наименование', 'Количество', 'Цена', 'Сумма'])
    for row in items:
        _append_row(items_sheet, [row.document_id, row.line_no, row.name or '', float(row.quantity or 0), float(row.price or 0), float(row.line_total or 0)])

    if money_report is not None:
        money = workbook.create_sheet('Money')
        _append_row(money, ['Сотрудник ID','Сотрудник','Проект ID','Проект','На начало RUB','Получено RUB','Принятые расходы RUB','Возвраты RUB','На конец RUB','Ожидает получения RUB','Расходы на проверке RUB','Возвраты на проверке RUB'])
        for row in money_report['rows']:
            name = employee_name(row)
            _append_row(money, [row['employee_id'],name,row['project_id'],row['project_name']]+[float(row[k]) for k in CASH_FIELDS])
        _append_row(money, ['ИТОГО','','','']+[float(money_report['totals'][k]) for k in CASH_FIELDS])
        _append_row(overview, ['Деньги: остаток на начало RUB',float(money_report['totals']['opening'])])
        _append_row(overview, ['Деньги: получено RUB',float(money_report['totals']['received'])])
        _append_row(overview, ['Деньги: принято расходов RUB',float(money_report['totals']['spent'])])
        _append_row(overview, ['Деньги: возвраты RUB',float(money_report['totals']['returned'])])
        _append_row(overview, ['Деньги: остаток на конец RUB',float(money_report['totals']['closing'])])
        _append_row(overview, ['Деньги: ожидает получения RUB',float(money_report['totals']['pending'])])
        _append_row(overview, ['Деньги: расходы на проверке RUB',float(money_report['totals']['pending_expenses'])])
        _append_row(overview, ['Деньги: возвраты на проверке RUB',float(money_report['totals']['pending_returns'])])
        cash, debt = cash_and_employee_debt(money_report)
        _append_row(overview, ['Деньги: на руках у сотрудников RUB',float(cash)])
        _append_row(overview, ['Деньги: компания должна сотрудникам RUB',float(debt)])

    if money_report is not None:
        card_sheet=workbook.create_sheet('BusinessCards')
        _append_row(card_sheet, ['Чек ID','Карта','Последние 4 цифры','Сотрудник','Проект','Сумма RUB','Статус','Принято'])
        for r in money_report.get('card_rows',[]):
            _append_row(card_sheet, [r['document_id'],r['card_name'],r['last4'],employee_name(r),r['project_name'],float(r['amount']),'Принято' if r['accepted'] else 'На проверке',r['approved_at'].isoformat() if r['accepted'] and r['approved_at'] else ''])
        _append_row(overview, ['Бизнес-карты: принято RUB',float(money_report.get('card_spent',0))])
        _append_row(overview, ['Бизнес-карты: на проверке RUB',float(money_report.get('card_pending',0))])

    for sheet in workbook.worksheets:
        # All cells in these exports are literal data; never export formulas from
        # names, OCR results or other externally supplied strings.
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = 's'
        for column_cells in sheet.columns:
            max_length = 0
            column_letter = column_cells[0].column_letter
            for cell in column_cells:
                value = '' if cell.value is None else str(cell.value)
                if len(value) > max_length:
                    max_length = len(value)
            sheet.column_dimensions[column_letter].width = min(max_length + 2, 40)

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return f'reports-{period}.xlsx', buffer.getvalue()


# XML 1.0 cannot represent these control characters, even in literal strings.
_ILLEGAL_XML = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]')


def _append_row(sheet, values) -> None:
    """Preserve untrusted text and large IDs before openpyxl binds a cell value."""
    row = []
    for value in values:
        if isinstance(value, str):
            value = _ILLEGAL_XML.sub('\ufffd', value)
        elif isinstance(value, int) and not isinstance(value, bool) and abs(value) >= 10**15:
            # Excel stores only 15 significant digits. A BIGINT identifier must
            # remain exact, including after opening and re-saving the workbook.
            value = str(value)
        row.append(value)
    sheet.append(row)
