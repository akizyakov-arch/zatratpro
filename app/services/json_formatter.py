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
            lines.append(_format_item(item, currency_display))

    if document.total is not None:
        lines.append("")
        lines.append(f"Итого: {_format_amount(document.total)} {currency_display}")

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


def _format_item(item: DocumentItem, currency_display: str) -> str:
    name = item.name or "Без названия"
    quantity = _format_amount(item.quantity) if item.quantity is not None else "?"
    price = _format_amount(item.price) if item.price is not None else "?"
    line_total = _format_amount(item.line_total) if item.line_total is not None else "?"
    return f"{name} — {quantity} шт × {price} {currency_display} = {line_total} {currency_display}"


def _format_amount(value: float | int | None) -> str:
    if value is None:
        return "?"

    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return str(value)

    quantized = amount.quantize(Decimal("0.01"))
    return f"{quantized:.2f}"


def _format_currency(currency_code: str | None) -> str:
    if not currency_code:
        return "RUB"
    return CURRENCY_SYMBOLS.get(currency_code.upper(), currency_code.upper())
