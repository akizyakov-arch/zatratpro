EXTRACTION_PROMPT = """
Ты извлекаешь данные из OCR-текста документа.
Верни только JSON без пояснений.
Соблюдай контракт:
{
  "document_type": "receipt",
  "external_document_number": null,
  "incoming_number": null,
  "vendor": null,
  "vendor_inn": null,
  "vendor_kpp": null,
  "date": null,
  "currency": "RUB",
  "total": null,
  "items": [
    {
      "name": null,
      "quantity": null,
      "price": null,
      "line_total": null
    }
  ],
  "raw_text": null
}

Если значение не найдено, оставь null.
Поле raw_text заполни полным OCR-текстом.
""".strip()
