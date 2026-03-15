import json
from decimal import Decimal, InvalidOperation
from typing import Iterable

from app.schemas.document import DocumentItem, DocumentSchema


DOCUMENT_TYPE_TITLES = {
    "receipt": "КАССОВЫЙ ЧЕК",
    "invoice": "НАКЛАДНАЯ",
    "act": "АКТ",
}


def format_document_json(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2)


def format_document_preview(document: DocumentSchema) -> str:
    title = DOCUMENT_TYPE_TITLES.get(document.document_type, "ДОКУМЕНТ")
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
            lines.append(_format_item(item, document.currency))

    if document.total is not None:
        lines.append("")
        lines.append(f"Итого: {_format_amount(document.total)} {document.currency}")

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


def _format_item(item: DocumentItem, currency: str) -> str:
    name = item.name or "Без названия"
    quantity = _format_amount(item.quantity) if item.quantity is not None else "?"
    price = _format_amount(item.price) if item.price is not None else "?"
    line_total = _format_amount(item.line_total) if item.line_total is not None else "?"
    return f"{name} — {quantity} шт × {price} {currency} = {line_total} {currency}"


def _format_amount(value: float | int | None) -> str:
    if value is None:
        return "?"

    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return str(value)

    quantized = amount.quantize(Decimal("0.01"))
    return f"{quantized:.2f}"
