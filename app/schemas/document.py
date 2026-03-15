import re
from typing import Any

from pydantic import BaseModel, Field, field_validator


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

    @field_validator("quantity", "price", "line_total", mode="before")
    @classmethod
    def normalize_numbers(cls, value: Any) -> Any:
        return _coerce_number(value)


class DocumentSchema(BaseModel):
    document_type: str = "receipt"
    external_document_number: str | None = None
    incoming_number: str | None = None
    vendor: str | None = None
    vendor_inn: str | None = None
    vendor_kpp: str | None = None
    date: str | None = None
    currency: str = "RUB"
    total: float | None = None
    items: list[DocumentItem] = Field(default_factory=lambda: [DocumentItem()])
    raw_text: str | None = None

    @field_validator("total", mode="before")
    @classmethod
    def normalize_total(cls, value: Any) -> Any:
        return _coerce_number(value)


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
