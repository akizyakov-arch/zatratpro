from dataclasses import dataclass


ALLOWED_DOCUMENT_TYPES = {
    'goods_invoice',
    'service_act',
    'upd',
    'vat_invoice',
    'cash_receipt',
    'bso',
    'transport_invoice',
    'cash_out_order',
}

GENERIC_FALLBACK_FAMILY = 'generic_fallback'
DEFAULT_EXTRACTION_MODE = 'default'
STRICT_EXTRACTION_MODE = 'strict'


@dataclass(frozen=True, slots=True)
class DocumentTypeRule:
    document_type: str
    markers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DocumentFamilyRule:
    family: str
    positive_markers: tuple[str, ...]
    negative_markers: tuple[str, ...] = ()


DOCUMENT_TYPE_RULES = (
    DocumentTypeRule('upd', ('универсальный передаточный документ', ' упд', 'упд ')),
    DocumentTypeRule('vat_invoice', ('счет-фактура', 'счёт-фактура')),
    DocumentTypeRule('goods_invoice', ('товарная накладная', 'торг-12')),
    DocumentTypeRule('transport_invoice', ('транспортная накладная',)),
    DocumentTypeRule('service_act', ('акт выполненных работ', 'акт оказанных услуг')),
    DocumentTypeRule('bso', ('бланк строгой отчетности', 'бланк строгой отчётности', ' бсо', 'бсо ')),
    DocumentTypeRule('cash_out_order', ('расходный кассовый ордер', 'рко')),
    DocumentTypeRule('cash_receipt', ('кассовый чек', 'фискальный чек', 'чек ккт', 'кассовый документ', 'чек')),
)

DOCUMENT_FAMILY_BY_TYPE = {
    'cash_receipt': 'fiscal_documents',
    'bso': 'fiscal_documents',
    'goods_invoice': 'primary_table_documents',
    'service_act': 'primary_table_documents',
    'upd': 'primary_table_documents',
    'transport_invoice': 'primary_table_documents',
    'vat_invoice': 'vat_documents',
    'cash_out_order': 'cash_order_documents',
}

DOCUMENT_FAMILY_RULES = (
    DocumentFamilyRule(
        family='fiscal_documents',
        positive_markers=(
            'кассовый чек',
            'фискальный чек',
            'чек ккт',
            'кассовый документ',
            'бланк строгой отчетности',
            'бланк строгой отчётности',
            ' бсо',
            'бсо ',
            'смена',
            'рн ккт',
            'фн ',
            'фд ',
        ),
        negative_markers=(
            'счет-фактура',
            'счёт-фактура',
            'товарная накладная',
            'торг-12',
            'расходный кассовый ордер',
            'транспортная накладная',
        ),
    ),
    DocumentFamilyRule(
        family='primary_table_documents',
        positive_markers=(
            'товарная накладная',
            'торг-12',
            'универсальный передаточный документ',
            ' упд',
            'упд ',
            'акт выполненных работ',
            'акт оказанных услуг',
            'транспортная накладная',
            'грузоотправитель',
            'грузополучатель',
            'кол-во',
            'ед. изм',
        ),
        negative_markers=(
            'кассовый чек',
            'фискальный чек',
            'бланк строгой отчетности',
            'бланк строгой отчётности',
            'расходный кассовый ордер',
            'счет-фактура',
            'счёт-фактура',
        ),
    ),
    DocumentFamilyRule(
        family='vat_documents',
        positive_markers=(
            'счет-фактура',
            'счёт-фактура',
            'продавец',
            'покупатель',
            'ставка налога',
            'в том числе сумма налога',
        ),
        negative_markers=(
            'кассовый чек',
            'фискальный чек',
            'бланк строгой отчетности',
            'бланк строгой отчётности',
            'расходный кассовый ордер',
        ),
    ),
    DocumentFamilyRule(
        family='cash_order_documents',
        positive_markers=(
            'расходный кассовый ордер',
            'рко',
            'основание',
            'выдать',
            'руб. коп',
        ),
        negative_markers=(
            'кассовый чек',
            'фискальный чек',
            'счет-фактура',
            'счёт-фактура',
            'товарная накладная',
            'торг-12',
        ),
    ),
)


def detect_document_type_from_text(raw_text: str | None, current_type: str | None = None) -> str:
    text = (raw_text or '').lower()
    for rule in DOCUMENT_TYPE_RULES:
        if any(marker in text for marker in rule.markers):
            return rule.document_type
    if current_type in ALLOWED_DOCUMENT_TYPES:
        return current_type
    return 'unknown'


def document_family_for_type(document_type: str | None) -> str | None:
    if document_type is None:
        return None
    return DOCUMENT_FAMILY_BY_TYPE.get(document_type)
