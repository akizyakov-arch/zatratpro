import re
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


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


ALLOWED_DOCUMENT_TYPES = {
    "goods_invoice",
    "service_act",
    "upd",
    "vat_invoice",
    "cash_receipt",
    "bso",
    "transport_invoice",
    "cash_out_order",
}

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
    text = (raw_text or "").lower()

    if any(token in text for token in ("универсальный передаточный документ", " упд", "упд ")):
        return "upd"
    if any(token in text for token in ("счет-фактура", "счёт-фактура")):
        return "vat_invoice"
    if any(token in text for token in ("товарная накладная", "торг-12")):
        return "goods_invoice"
    if any(token in text for token in ("транспортная накладная",)):
        return "transport_invoice"
    if any(token in text for token in ("акт выполненных работ", "акт оказанных услуг")):
        return "service_act"
    if any(token in text for token in ("бланк строгой отчетности", "бланк строгой отчётности", " бсо", "бсо ")):
        return "bso"
    if any(token in text for token in ("расходный кассовый ордер", "рко")):
        return "cash_out_order"
    if any(token in text for token in ("кассовый чек", "фискальный чек", "чек ккт", "кассовый документ", "чек")):
        return "cash_receipt"

    if current_type in ALLOWED_DOCUMENT_TYPES:
        return current_type
    return "unknown"


def _sanitize_items(items: list[DocumentItem], document_type: str) -> list[DocumentItem]:
    sanitized: list[DocumentItem] = []
    for item in items:
        item.name = _normalize_item_name(item.name)
        if _item_has_meaningful_value(item, document_type):
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


def _item_has_meaningful_value(item: DocumentItem, document_type: str) -> bool:
    numeric_count = sum(
        value is not None for value in (item.quantity, item.price, item.line_total)
    )

    if item.name is not None:
        if numeric_count > 0:
            return True
        return document_type not in TABLE_DOCUMENT_TYPES

    if document_type in TABLE_DOCUMENT_TYPES:
        return False
    return numeric_count >= 2



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
