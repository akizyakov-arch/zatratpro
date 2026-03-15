from pydantic import BaseModel, Field


class DocumentItem(BaseModel):
    name: str | None = None
    quantity: float | None = None
    price: float | None = None
    line_total: float | None = None


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
