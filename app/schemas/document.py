import re
from typing import Any, Literal

from pydantic import BaseModel, Field, StrictBool, field_validator, model_validator
from app.schemas.fiscal import detect_fiscalization


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


class DocumentItem(BaseModel):
    name: str | None = None
    quantity: float | None = None
    price: float | None = None
    line_total: float | None = None

    vat_rate: float | None = None
    vat_amount: float | None = None
    line_total_without_vat: float | None = None
    price_includes_vat: bool | None = None

    @field_validator("quantity", "price", "line_total", "vat_rate", "vat_amount", "line_total_without_vat", mode="before")
    @classmethod
    def normalize_numbers(cls, value: Any, info) -> Any:
        if info.field_name == 'vat_rate' and isinstance(value, str):
            ratio = re.fullmatch(r'\s*(\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)\s*%?\s*', value)
            if ratio:
                rate, denominator = (float(part.replace(',', '.')) for part in ratio.groups())
                if 0 <= rate <= 100 and denominator == 100 + rate:
                    return rate
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


class DocumentSchema(BaseModel):
    document_type: str = "cash_receipt"
    external_document_number: str | None = None
    incoming_number: str | None = None
    vendor: str | None = None
    vendor_inn: str | None = None
    vendor_kpp: str | None = None
    date: str | None = None
    is_fiscalized: StrictBool | None = None
    currency: str = "RUB"
    total: float | None = None
    vat_total_amount: float | None = None
    vat_scope: Literal['document','mixed','no_vat','unknown'] | None = None
    items: list[DocumentItem] = Field(default_factory=lambda: [DocumentItem()])
    raw_text: str | None = None

    @field_validator("total", "vat_total_amount", mode="before")
    @classmethod
    def normalize_total(cls, value: Any) -> Any:
        return _coerce_number(value)

    @model_validator(mode="after")
    def normalize_document_type(self) -> "DocumentSchema":
        self.document_type = _detect_document_type(self.document_type, self.raw_text)
        self.is_fiscalized = detect_fiscalization(self.raw_text)
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
