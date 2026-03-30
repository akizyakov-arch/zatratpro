import logging
import re
from dataclasses import dataclass

from app.schemas.document import DocumentSchema


logger = logging.getLogger(__name__)
PASSTHROUGH_SOURCE = 'schema_passthrough'
OCR_TOTALS_BLOCK_SOURCE = 'ocr_totals_block'
ITEM_VAT_SUM_SOURCE = 'item_vat_sum'
ITEM_TOTAL_WITH_VAT_SUM_SOURCE = 'item_sum_with_vat'
NULLIFIED_SOURCE = 'nullified'
ALLOWED_VAT_SCOPES = {'document', 'mixed', 'no_vat', 'unknown'}
OCR_TEXT_FIXES = str.maketrans({
    'a': 'д',
    'c': 'с',
    'e': 'е',
    'h': 'н',
    'k': 'к',
    'm': 'м',
    'o': 'о',
    'p': 'р',
    't': 'т',
    'x': 'х',
    'y': 'у',
    '3': 'з',
    '6': 'б',
})


@dataclass(frozen=True, slots=True)
class FinancialProvenance:
    total_source: str | None = None
    vat_total_amount_source: str | None = None
    sum_without_vat_source: str | None = None
    suppressed_values: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(slots=True)
class DocumentFinancialNormalizationResult:
    document: DocumentSchema
    provenance: FinancialProvenance


class BaseFinancialResolver:
    def normalize(self, document: DocumentSchema) -> DocumentFinancialNormalizationResult:
        return DocumentFinancialNormalizationResult(
            document=document,
            provenance=FinancialProvenance(
                total_source=PASSTHROUGH_SOURCE if document.total is not None else None,
                vat_total_amount_source=PASSTHROUGH_SOURCE if document.vat_total_amount is not None else None,
            ),
        )


class ReceiptFinancialResolver(BaseFinancialResolver):
    def normalize(self, document: DocumentSchema) -> DocumentFinancialNormalizationResult:
        fallback_vat = _extract_receipt_vat_from_text(document.raw_text, total=document.total)
        current_vat = document.vat_total_amount
        vat_source = PASSTHROUGH_SOURCE if current_vat is not None else None
        suppressed_values: tuple[str, ...] = ()
        warnings: list[str] = []

        if current_vat is None:
            current_vat = fallback_vat
            vat_source = OCR_TOTALS_BLOCK_SOURCE if fallback_vat is not None else None
        elif document.total is not None and _looks_like_total_instead_of_vat(current_vat, document.total):
            if fallback_vat is None or _looks_like_total_instead_of_vat(fallback_vat, document.total):
                current_vat = None
                vat_source = NULLIFIED_SOURCE
                suppressed_values = ('vat_total_amount',)
                warnings.append('vat_equal_total_rejected')
            else:
                current_vat = fallback_vat
                vat_source = OCR_TOTALS_BLOCK_SOURCE
                warnings.append('vat_equal_total_replaced_from_ocr')
        elif fallback_vat is not None and current_vat <= 0:
            current_vat = fallback_vat
            vat_source = OCR_TOTALS_BLOCK_SOURCE
            warnings.append('vat_non_positive_replaced_from_ocr')

        document.vat_total_amount = current_vat
        document.vat_scope = _resolve_receipt_vat_scope(document, current_vat)

        return DocumentFinancialNormalizationResult(
            document=document,
            provenance=FinancialProvenance(
                total_source=PASSTHROUGH_SOURCE if document.total is not None else None,
                vat_total_amount_source=vat_source,
                suppressed_values=suppressed_values,
                warnings=tuple(warnings),
            ),
        )


class GoodsInvoiceFinancialResolver(BaseFinancialResolver):
    def normalize(self, document: DocumentSchema) -> DocumentFinancialNormalizationResult:
        item_vat_total = _sum_item_vat_amount(document)
        item_total_with_vat = _sum_item_total_with_vat(document)

        total_source = PASSTHROUGH_SOURCE if document.total is not None else None
        vat_source = PASSTHROUGH_SOURCE if document.vat_total_amount is not None else None
        suppressed_values: tuple[str, ...] = ()
        warnings: list[str] = []

        if document.total is None and item_total_with_vat is not None:
            document.total = item_total_with_vat
            total_source = ITEM_TOTAL_WITH_VAT_SUM_SOURCE

        current_vat = document.vat_total_amount
        if item_vat_total is None:
            if current_vat is not None and document.total is not None and _looks_like_total_instead_of_vat(current_vat, document.total):
                current_vat = None
                vat_source = NULLIFIED_SOURCE
                suppressed_values = ('vat_total_amount',)
                warnings.append('vat_equal_total_rejected')
        else:
            if current_vat is None:
                current_vat = item_vat_total
                vat_source = ITEM_VAT_SUM_SOURCE
            elif current_vat <= 0:
                current_vat = item_vat_total
                vat_source = ITEM_VAT_SUM_SOURCE
                warnings.append('vat_non_positive_replaced_from_items')
            elif document.total is not None and _looks_like_total_instead_of_vat(current_vat, document.total):
                current_vat = item_vat_total
                vat_source = ITEM_VAT_SUM_SOURCE
                warnings.append('vat_equal_total_replaced_from_items')
            elif document.total is not None and current_vat > document.total and item_vat_total < document.total:
                current_vat = item_vat_total
                vat_source = ITEM_VAT_SUM_SOURCE
                warnings.append('vat_exceeds_total_replaced_from_items')

        document.vat_total_amount = current_vat
        document.vat_scope = _resolve_goods_vat_scope(document, current_vat)

        return DocumentFinancialNormalizationResult(
            document=document,
            provenance=FinancialProvenance(
                total_source=total_source,
                vat_total_amount_source=vat_source,
                suppressed_values=suppressed_values,
                warnings=tuple(warnings),
            ),
        )


class GenericFinancialResolver(BaseFinancialResolver):
    """Fallback resolver for document types without dedicated normalization yet."""


class DocumentFinancialNormalizationService:
    def __init__(
        self,
        *,
        receipt_resolver: ReceiptFinancialResolver | None = None,
        goods_invoice_resolver: GoodsInvoiceFinancialResolver | None = None,
        generic_resolver: GenericFinancialResolver | None = None,
    ) -> None:
        self.receipt_resolver = receipt_resolver or ReceiptFinancialResolver()
        self.goods_invoice_resolver = goods_invoice_resolver or GoodsInvoiceFinancialResolver()
        self.generic_resolver = generic_resolver or GenericFinancialResolver()

    def normalize_document(self, document: DocumentSchema) -> DocumentFinancialNormalizationResult:
        resolver = self._resolve_resolver(document.document_type)
        result = resolver.normalize(document)
        logger.info(
            'Document financial normalization selected: document_type=%s resolver=%s total_source=%s vat_total_amount_source=%s warnings=%s suppressed_values=%s',
            document.document_type,
            resolver.__class__.__name__,
            result.provenance.total_source,
            result.provenance.vat_total_amount_source,
            ','.join(result.provenance.warnings) or '-',
            ','.join(result.provenance.suppressed_values) or '-',
        )
        return result

    def _resolve_resolver(self, document_type: str) -> BaseFinancialResolver:
        if document_type in {'cash_receipt', 'bso'}:
            return self.receipt_resolver
        if document_type == 'goods_invoice':
            return self.goods_invoice_resolver
        return self.generic_resolver


def _sum_item_vat_amount(document: DocumentSchema) -> float | None:
    values = [float(item.vat_amount) for item in document.items if item.vat_amount is not None and item.vat_amount > 0]
    if not values:
        return None
    return round(sum(values), 2)



def _sum_item_total_with_vat(document: DocumentSchema) -> float | None:
    relevant_items = [item for item in document.items if item.line_total is not None or item.vat_amount is not None or item.vat_label]
    if not relevant_items:
        return None

    total = 0.0
    counted = 0
    for item in relevant_items:
        if item.line_total is None:
            return None

        vat_amount = item.vat_amount
        normalized_label = _normalize_vat_label(item.vat_label)
        if vat_amount is None:
            if normalized_label == 'без ндс':
                vat_amount = 0.0
            else:
                return None

        total += float(item.line_total) + float(vat_amount)
        counted += 1

    if counted == 0:
        return None
    return round(total, 2)



def _resolve_goods_vat_scope(
    document: DocumentSchema,
    vat_total_amount: float | None,
) -> str | None:
    labels = {
        normalized
        for normalized in (_normalize_vat_label(item.vat_label) for item in document.items)
        if normalized is not None
    }

    if 'без ндс' in labels and any(label != 'без ндс' for label in labels):
        return 'mixed'

    if document.vat_scope in ALLOWED_VAT_SCOPES and document.vat_scope != 'unknown':
        return document.vat_scope

    if vat_total_amount is not None and vat_total_amount > 0:
        return 'document'
    if labels == {'без ндс'}:
        return 'no_vat'
    if labels:
        return 'document'
    return document.vat_scope



def _resolve_receipt_vat_scope(
    document: DocumentSchema,
    vat_total_amount: float | None,
) -> str | None:
    labels = {
        normalized
        for normalized in (_normalize_vat_label(item.vat_label) for item in document.items)
        if normalized is not None
    }
    raw_text = (document.raw_text or '').lower()

    if _should_force_mixed_vat_scope(vat_total_amount, labels, raw_text):
        return 'mixed'

    if vat_total_amount is not None and vat_total_amount > 0:
        if _contains_no_vat_signal(raw_text):
            return 'mixed'
        return 'document'

    if document.vat_scope in ALLOWED_VAT_SCOPES:
        return document.vat_scope
    if not labels:
        return document.vat_scope
    if labels == {'без ндс'}:
        return 'no_vat'
    if len(labels) > 1:
        return 'mixed'
    return 'document'


def _should_force_mixed_vat_scope(
    vat_total: float | None,
    labels: set[str],
    raw_text: str,
) -> bool:
    has_no_vat_signal = _contains_no_vat_signal(raw_text)
    has_positive_vat = vat_total is not None and vat_total > 0

    if 'без ндс' in labels and any(label != 'без ндс' for label in labels):
        return True
    if has_positive_vat and has_no_vat_signal:
        return True
    return False


def _looks_like_total_instead_of_vat(vat_amount: float, total: float) -> bool:
    tolerance = max(0.05, abs(total) * 0.01)
    return abs(vat_amount - total) <= tolerance


def _extract_receipt_vat_from_text(
    raw_text: str | None,
    *,
    total: float | None = None,
) -> float | None:
    if not raw_text:
        return None

    translated = raw_text.lower().replace('ё', 'е')
    compact = re.sub(r'[^а-яa-z0-9%хx.,:\-\s]', ' ', translated)
    compact = re.sub(r'\s+', ' ', compact).strip()
    if not compact:
        return None

    money_value = r'(?:[0-9]{3,}(?:[\s.][0-9]{3})*(?:[.,][0-9]{1,2})?|[0-9]{1,2}[.,][0-9]{2})'
    vat_label = r'[нnh][дdаa][сc5]'
    patterns = (
        rf'(?:сумм[аоу]?\s+)?(?:в\s*т\.?\s*ч\.?\s*)?{vat_label}(?:\s*[аб])?(?:\s*[-:=])?(?:\s*\d{{1,2}}\s*[%хx])?(?:\s*[-:=])?\s*({money_value})',
        rf'({money_value})\s*(?:руб(?:\.|лей)?\s*)?(?:в\s*т\.?\s*ч\.?\s*)?{vat_label}(?:\s*[аб])?(?:\s*\d{{1,2}}\s*[%хx])?',
    )

    candidates: list[float] = []
    for pattern in patterns:
        for match in re.finditer(pattern, compact):
            value = _coerce_number(match.group(1))
            if isinstance(value, (int, float)) and value > 0:
                candidates.append(float(value))

    if not candidates:
        return None

    unique_candidates: list[float] = []
    for value in candidates:
        if not any(abs(value - existing) <= 0.01 for existing in unique_candidates):
            unique_candidates.append(value)

    if total is not None:
        non_total_candidates = [
            value for value in unique_candidates
            if not _looks_like_total_instead_of_vat(value, total)
        ]
        if non_total_candidates:
            below_total = [value for value in non_total_candidates if value < total]
            if below_total:
                if len(below_total) == 1:
                    return below_total[0]
                summed = round(sum(below_total), 2)
                if summed < total:
                    return summed
                return max(below_total)
            return max(non_total_candidates)
        return None

    if len(unique_candidates) == 1:
        return unique_candidates[0]
    return max(unique_candidates)


def _normalize_vat_label(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = ' '.join(value.strip().split()).lower()
    return normalized or None


def _contains_no_vat_signal(raw_text: str) -> bool:
    translated = raw_text.lower().translate(OCR_TEXT_FIXES).replace('ё', 'е')
    compact = ''.join(ch for ch in translated if ch.isalnum())
    if 'безндс' in compact or 'суммабезндс' in compact:
        return True

    spaced = re.sub(r'[^а-я0-9]+', ' ', translated)
    spaced = re.sub(r'\s+', ' ', spaced).strip()
    patterns = (
        r'бе[зс3]\s{0,3}н[дaа]?[сc5]',
        r'сумм[аоу]?\s{0,6}бе[зс3]\s{0,3}н[дaа]?[сc5]',
    )
    return any(re.search(pattern, spaced) is not None for pattern in patterns)


def _coerce_number(value: str) -> float | None:
    cleaned = value.translate(str.maketrans({',': '.', 'O': '0', 'o': '0', 'О': '0', 'о': '0', 'I': '1', 'l': '1', 'S': '5', 'B': '8'}))
    cleaned = re.sub(r'[^0-9.\-]', '', cleaned)
    cleaned = re.sub(r'\.(?=.*\.)', '', cleaned)
    if not cleaned or cleaned in {'-', '.', '-.'}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None
