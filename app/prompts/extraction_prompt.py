EXTRACTION_PROMPT = """
Извлеки структурированные данные из OCR-текста документа.
Верни только JSON без пояснений и без markdown.

Контракт ответа:
{
  "document_type": "cash_receipt",
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
  ]
}

Допустимые document_type:

- goods_invoice — товарная накладная, ТОРГ-12
- service_act — акт выполненных работ, акт оказанных услуг
- upd — универсальный передаточный документ
- vat_invoice — счет-фактура
- cash_receipt — кассовый чек, чек ККТ, фискальный чек
- bso — бланк строгой отчетности
- transport_invoice — транспортная накладная
- cash_out_order — расходный кассовый ордер
- unknown — любой другой документ

Правило классификации:
если в тексте нет явных признаков допустимого первичного документа — верни "unknown".

Правила извлечения:

- если значение отсутствует или не очевидно — верни null
- не пытайся догадываться
- извлекай все найденные позиции в items
- дата в формате YYYY-MM-DD
- ИНН и КПП — только цифры
- числовые поля (total, quantity, price, line_total) — числа без валюты
- vendor очисти от OCR-мусора и служебных слов
- если явно указан номер документа, заполни external_document_number или incoming_number

Не добавляй текст вне JSON.
""".strip()
