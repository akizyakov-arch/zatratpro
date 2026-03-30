import logging
from dataclasses import dataclass

from app.schemas.document import DocumentSchema


logger = logging.getLogger(__name__)
PASSTHROUGH_SOURCE = 'schema_passthrough'


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
    """Phase 1 placeholder for cash_receipt/bso normalization."""


class GenericFinancialResolver(BaseFinancialResolver):
    """Fallback resolver for document types without dedicated normalization yet."""


class DocumentFinancialNormalizationService:
    def __init__(
        self,
        *,
        receipt_resolver: ReceiptFinancialResolver | None = None,
        generic_resolver: GenericFinancialResolver | None = None,
    ) -> None:
        self.receipt_resolver = receipt_resolver or ReceiptFinancialResolver()
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
        return self.generic_resolver
