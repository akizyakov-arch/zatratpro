import unittest

from app.schemas.document import DocumentItem, DocumentSchema
from app.services.json_formatter import format_document_preview


class DocumentPreviewFormattingTests(unittest.TestCase):
    def test_preview_uses_section_breaks_for_readability(self) -> None:
        document = DocumentSchema(
            document_type='cash_receipt',
            external_document_number='CHK-42',
            vendor='ООО Ромашка',
            vendor_inn='7701234567',
            vendor_kpp='770101001',
            date='2026-03-31',
            total=1234.5,
            vat_total_amount=205.75,
            items=[
                DocumentItem(name='Бумага А4', quantity=2, price=100, line_total=200),
                DocumentItem(name='Ручки', quantity=3, price=50, line_total=150),
            ],
        )

        preview = format_document_preview(document)

        self.assertTrue(preview.startswith('КАССОВЫЙ ЧЕК'))
        self.assertIn('\n\n[РЕКВИЗИТЫ]\nНомер: CHK-42\nДата: 2026-03-31', preview)
        self.assertIn('\n\n[КОНТРАГЕНТ]\nПоставщик: ООО Ромашка\nИНН: 7701234567\nКПП: 770101001', preview)
        self.assertIn('\n\n[ПОЗИЦИИ: 2]\n1. Бумага А4', preview)
        self.assertIn('\n\n2. Ручки', preview)
        self.assertIn('\n\n[ИТОГИ]\nИтого: 1234.50 ₽\nНДС: 205.75 ₽', preview)


if __name__ == '__main__':
    unittest.main()
