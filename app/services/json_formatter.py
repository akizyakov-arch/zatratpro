import json
from decimal import Decimal, InvalidOperation
from typing import Iterable

from app.schemas.document import DocumentItem, DocumentSchema


DOCUMENT_TYPE_TITLES = {
    "goods_invoice": "ТОВАРНАЯ НАКЛАДНАЯ",
    "service_act": "АКТ",
    "upd": "УПД",
    "vat_invoice": "СЧЕТ-ФАКТУРА",
    "cash_receipt": "КАССОВЫЙ ЧЕК",
    "bso": "БСО",
    "transport_invoice": "ТРАНСПОРТНАЯ НАКЛАДНАЯ",
    "cash_out_order": "РАСХОДНЫЙ КАССОВЫЙ ОРДЕР",
}

CURRENCY_SYMBOLS = {
    "RUB": "₽",
    "USD": "$",
    "EUR": "€",
}


def format_document_json(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2)


def format_document_preview(document: DocumentSchema) -> str:
    title = DOCUMENT_TYPE_TITLES.get(document.document_type, "ДОКУМЕНТ")
    currency_display = _format_currency(document.currency)
    lines = [title]

    number = document.external_document_number or document.incoming_number
    if number:
        lines.append(f"Номер: {number}")
    if document.date:
        lines.append(f"Дата: {document.date}")
    if document.vendor:
        lines.append("")
        lines.append(f"Поставщик: {document.vendor}")
    if document.vendor_inn:
        lines.append(f"ИНН: {document.vendor_inn}")
    if document.vendor_kpp:
        lines.append(f"КПП: {document.vendor_kpp}")

    items = [item for item in document.items if _item_has_value(item)]
    if items:
        lines.append("")
        lines.append("Состав документа:")
        for item in items:
            lines.append(_format_item(document.document_type, item, currency_display))

    if document.total is not None:
        lines.append("")
        lines.append(f"Итого: {_format_amount(document.total)} {currency_display}")

    vat_lines = _format_vat_lines(document, currency_display)
    if vat_lines:
        lines.append("")
        lines.extend(vat_lines)

    return "\n".join(lines).strip()


def chunk_message(text: str, limit: int = 3900) -> Iterable[str]:
    if len(text) <= limit:
        yield text
        return

    start = 0
    while start < len(text):
        yield text[start : start + limit]
        start += limit


def _item_has_value(item: DocumentItem) -> bool:
    return any(value is not None for value in (item.name, item.quantity, item.price, item.line_total))


def _format_item(document_type: str, item: DocumentItem, currency_display: str) -> str:
    quantity = _format_amount(item.quantity) if item.quantity is not None else None
    price = _format_amount(item.price) if item.price is not None else None
    line_total = _format_amount(item.line_total) if item.line_total is not None else None
    vat_amount = _format_amount(item.vat_amount) if item.vat_amount is not None else None
    vat_label = item.vat_label.strip() if item.vat_label else None

    prefix = f"{item.name} — " if item.name else ""
    has_item_vat = item.vat_amount is not None or vat_label is not None
    is_vat_line = document_type in {'upd', 'vat_invoice'} or has_item_vat

    if is_vat_line:
        details: list[str] = []
        if quantity is not None and price is not None:
            details.append(f"{quantity} шт × {price} {currency_display}")
        elif quantity is not None:
            details.append(f"количество: {quantity} шт")
        elif price is not None:
            details.append(f"цена: {price} {currency_display}")

        if line_total is not None:
            line_label = 'сумма строки'
            if has_item_vat:
                line_label = 'без НДС'
            details.append(f"{line_label}: {line_total} {currency_display}")
        if vat_amount is not None:
            vat_text = f"НДС: {vat_amount} {currency_display}"
            if vat_label:
                vat_text = f"{vat_text} ({vat_label})"
            details.append(vat_text)
        elif vat_label:
            details.append(f"НДС: {vat_label}")

        if item.line_total is not None and item.vat_amount is not None:
            details.append(f"с НДС: {_format_amount(item.line_total + item.vat_amount)} {currency_display}")

        if details:
            return prefix + ', '.join(details)
        return prefix.rstrip(' —')

    if quantity is not None and price is not None and line_total is not None:
        return f"{prefix}{quantity} шт × {price} {currency_display} = {line_total} {currency_display}"
    if quantity is not None and price is not None:
        return f"{prefix}{quantity} шт × {price} {currency_display}"
    if quantity is not None and line_total is not None:
        return f"{prefix}{quantity} шт, сумма строки: {line_total} {currency_display}"
    if price is not None and line_total is not None:
        return f"{prefix}цена: {price} {currency_display}, сумма строки: {line_total} {currency_display}"
    if line_total is not None:
        return f"{prefix}сумма строки: {line_total} {currency_display}"
    if quantity is not None:
        return f"{prefix}количество: {quantity} шт"
    if price is not None:
        return f"{prefix}цена: {price} {currency_display}"
    return prefix.rstrip(' —')


def _format_amount(value: float | int | None) -> str:
    if value is None:
        return "?"

    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return str(value)

    quantized = amount.quantize(Decimal("0.01"))
    return f"{quantized:.2f}"


def _format_vat_lines(document: DocumentSchema, currency_display: str) -> list[str]:
    vat_scope = _vat_scope_label(document.vat_scope)
    vat_amount = document.vat_total_amount

    if vat_amount is None and vat_scope is None:
        return []

    lines: list[str] = []
    if vat_amount is not None:
        lines.append(f"НДС: {_format_amount(vat_amount)} {currency_display}")
    elif document.vat_scope == "no_vat":
        lines.append("НДС: без НДС")

    if vat_scope is not None:
        lines.append(f"Тип НДС: {vat_scope}")
    return lines


def _vat_scope_label(scope: str | None) -> str | None:
    return {
        "document": "весь документ",
        "mixed": "смешанный",
        "no_vat": "без НДС",
    }.get(scope)


def _format_currency(currency_code: str | None) -> str:
    if not currency_code:
        return "RUB"
    return CURRENCY_SYMBOLS.get(currency_code.upper(), currency_code.upper())
