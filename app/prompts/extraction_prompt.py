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

Правила для document_type:
- "receipt" только если это кассовый чек, чек ККТ, фискальный чек, кассовый документ
- "invoice" если в тексте есть слова "накладная", "товарная накладная", "ТОРГ-12", "УПД"
- "act" если в тексте есть слова "акт", "акт выполненных работ", "акт оказанных услуг"
- не ставь "receipt" по умолчанию, если текст похож на накладную или акт

Если значение не найдено, оставь null.
Поле raw_text заполни полным OCR-текстом.
Числовые поля total, quantity, price, line_total возвращай только числами без валюты, пробелов и лишних символов.
Исправляй типовые OCR-ошибки в цифрах: O->0, o->0, l->1, I->1, S->5, B->8, запятая -> точка.
Не добавляй комментарии, markdown или текст вне JSON.
""".strip()
