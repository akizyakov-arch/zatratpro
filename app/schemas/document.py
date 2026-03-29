import re
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.document_rules import ALLOWED_DOCUMENT_TYPES, detect_document_type_from_text


NUMERIC_FIXES = str.maketrans({
    "O": "0",
    "o": "0",
    "О": "0",
    "о": "0",
    "I": "1",
    "l": "1",
    "S": "5",
    "B": "8",
    ",": ".",
})

OCR_TEXT_FIXES = str.maketrans({
    "a": "д",
    "c": "с",
    "e": "е",
    "h": "н",
    "k": "к",
    "m": "м",
    "o": "о",
    "p": "р",
    "t": "т",
    "x": "х",
    "y": "у",
    "3": "з",
    "6": "б",
})

PLACEHOLDER_ITEM_NAMES = {
    "без названия",
    "товар",
    "позиция",
}

TABLE_DOCUMENT_TYPES = {
    "goods_invoice",
    "service_act",
    "upd",
    "vat_invoice",
    "transport_invoice",
}


class DocumentItem(BaseModel):
    name: str | None = None
    quantity: float | None = None
    price: float | None = None
    line_total: float | None = None
    vat_label: str | None = None
    vat_amount: float | None = None

    @field_validator("quantity", "price", "line_total", "vat_amount", mode="before")
    @classmethod
    def normalize_numbers(cls, value: Any) -> Any:
        return _coerce_number(value)


ALLOWED_VAT_SCOPES = {
    "document",
    "mixed",
    "no_vat",
    "unknown",
}


class DocumentSchema(BaseModel):
    document_type: str = "cash_receipt"
    external_document_number: str | None = None
    incoming_number: str | None = None
    vendor: str | None = None
    vendor_inn: str | None = None
    vendor_kpp: str | None = None
    date: str | None = None
    currency: str = "RUB"
    total: float | None = None
    vat_total_amount: float | None = None
    vat_scope: str | None = None
    is_fiscalized: bool | None = None
    items: list[DocumentItem] = Field(default_factory=list)
    raw_text: str | None = None

    @field_validator("total", "vat_total_amount", mode="before")
    @classmethod
    def normalize_total(cls, value: Any) -> Any:
        return _coerce_number(value)

    @field_validator("vat_scope", mode="before")
    @classmethod
    def normalize_vat_scope(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            return "unknown"
        normalized = value.strip().lower()
        if not normalized:
            return None
        return normalized if normalized in ALLOWED_VAT_SCOPES else "unknown"

    @model_validator(mode="after")
    def normalize_document(self) -> "DocumentSchema":
        self.document_type = _detect_document_type(self.document_type, self.raw_text)
        self.items = _sanitize_items(self.items, self.document_type)
        self.vat_scope = _resolve_vat_scope(self)
        return self


def _coerce_number(value: Any) -> Any:
    if value is None or isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return value

    cleaned = value.translate(NUMERIC_FIXES)
    cleaned = re.sub(r"[^0-9.\-]", "", cleaned)
    cleaned = re.sub(r"\.(?=.*\.)", "", cleaned)

    if not cleaned or cleaned in {"-", ".", "-."}:
        return None

    try:
        return float(cleaned)
    except ValueError:
        return value


def _detect_document_type(current_type: str | None, raw_text: str | None) -> str:
    return detect_document_type_from_text(raw_text, current_type)


def _sanitize_items(items: list[DocumentItem], document_type: str) -> list[DocumentItem]:
    prepared: list[DocumentItem] = []
    named_table_rows = 0

    for item in items:
        item.name = _normalize_item_name(item.name)
        item = _normalize_item_math(item, document_type)
        prepared.append(item)
        if item.name is not None and _item_numeric_count(item) >= 2:
            named_table_rows += 1

    drop_nameless_numeric_rows = document_type in TABLE_DOCUMENT_TYPES or named_table_rows >= 2

    sanitized: list[DocumentItem] = []
    for item in prepared:
        if _item_has_meaningful_value(item, document_type, drop_nameless_numeric_rows):
            sanitized.append(item)
    return sanitized


def _normalize_item_name(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = re.sub(r"\s+", " ", value).strip(" -\t\r\n")
    if not cleaned:
        return None

    normalized = cleaned.casefold().replace("ё", "е")
    if normalized in PLACEHOLDER_ITEM_NAMES:
        return None
    return cleaned


def _item_numeric_count(item: DocumentItem) -> int:
    return sum(
        value is not None for value in (item.quantity, item.price, item.line_total)
    )


def _item_has_meaningful_value(
    item: DocumentItem,
    document_type: str,
    drop_nameless_numeric_rows: bool,
) -> bool:
    numeric_count = _item_numeric_count(item)

    if item.name is not None:
        if numeric_count > 0:
            return True
        return document_type not in TABLE_DOCUMENT_TYPES

    if drop_nameless_numeric_rows:
        return False
    return numeric_count >= 2


def _normalize_item_math(item: DocumentItem, document_type: str) -> DocumentItem:
    if document_type not in TABLE_DOCUMENT_TYPES:
        return item
    if item.quantity is None or item.price is None or item.line_total is None:
        return item

    expected_total = item.quantity * item.price
    if _amounts_match(expected_total, item.line_total):
        return item

    item.quantity = None
    item.price = None
    return item


def _amounts_match(left: float, right: float) -> bool:
    tolerance = max(0.05, abs(right) * 0.02)
    return abs(left - right) <= tolerance


def _resolve_vat_scope(document: DocumentSchema) -> str | None:
    labels = {
        normalized
        for normalized in (_normalize_vat_label(item.vat_label) for item in document.items)
        if normalized is not None
    }
    raw_text = (document.raw_text or "").lower()
    vat_total = document.vat_total_amount

    if _should_force_mixed_vat_scope(document.document_type, vat_total, labels, raw_text):
        return "mixed"

    if document.vat_scope in ALLOWED_VAT_SCOPES:
        return document.vat_scope
    if not labels:
        return document.vat_scope
    if labels == {"без ндс"}:
        return "no_vat"
    if len(labels) > 1:
        return "mixed"
    return "document"



def _should_force_mixed_vat_scope(
    document_type: str,
    vat_total: float | None,
    labels: set[str],
    raw_text: str,
) -> bool:
    if document_type not in {"cash_receipt", "bso"}:
        return False

    has_no_vat_signal = _contains_no_vat_signal(raw_text)
    has_positive_vat = vat_total is not None and vat_total > 0

    if "без ндс" in labels and any(label != "без ндс" for label in labels):
        return True
    if has_positive_vat and has_no_vat_signal:
        return True
    return False



def _normalize_vat_label(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().split()).lower()
    return normalized or None


def _contains_no_vat_signal(raw_text: str) -> bool:
    translated = raw_text.lower().translate(OCR_TEXT_FIXES).replace("ё", "е")
    compact = "".join(ch for ch in translated if ch.isalnum())
    if "безндс" in compact or "суммабезндс" in compact:
        return True

    spaced = re.sub(r"[^а-я0-9]+", " ", translated)
    spaced = re.sub(r"\s+", " ", spaced).strip()
    patterns = (
        r"бе[зс3]\s{0,3}н[дaа]?[сc5]",
        r"сумм[аоу]?\s{0,6}бе[зс3]\s{0,3}н[дaа]?[сc5]",
    )
    return any(re.search(pattern, spaced) is not None for pattern in patterns)
