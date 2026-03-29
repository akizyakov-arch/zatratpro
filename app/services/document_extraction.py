import logging
from dataclasses import dataclass

from app.config import get_settings
from app.prompts.extraction_prompt_registry import build_extraction_prompt
from app.services.deepseek import DeepSeekService
from app.services.document_family_router import (
    DocumentFamilyRoutingResult,
    build_generic_fallback_result,
    route_document_family,
)


logger = logging.getLogger(__name__)
VALID_EXTRACTION_STRATEGIES = {'generic', 'family_routing', 'ocr_structured'}


@dataclass(frozen=True, slots=True)
class DocumentExtractionInput:
    ocr_text: str
    source_kind: str = 'ocr_text'
    mime_type: str | None = None
    source_path: str | None = None


@dataclass(slots=True)
class DocumentExtractionResult:
    payload: dict
    strategy: str
    detected_family: str
    candidate_type: str | None
    matched_rules: tuple[str, ...]
    confidence_score: int
    extraction_mode: str
    fallback_reason: str | None = None
    is_noisy: bool = False


class DocumentExtractionService:
    def __init__(
        self,
        *,
        deepseek_service: DeepSeekService | None = None,
    ) -> None:
        self.deepseek_service = deepseek_service or DeepSeekService()

    async def extract_from_source(self, extraction_input: DocumentExtractionInput) -> DocumentExtractionResult:
        configured_strategy = get_settings().document_extraction_strategy.strip().lower()
        strategy, strategy_fallback_reason = self._resolve_strategy(configured_strategy)
        routing_result = self._build_routing_result(
            strategy=strategy,
            ocr_text=extraction_input.ocr_text,
            strategy_fallback_reason=strategy_fallback_reason,
        )
        system_prompt = self._resolve_system_prompt(
            strategy=strategy,
            routing_result=routing_result,
        )
        payload = await self.deepseek_service.extract_document(
            extraction_input.ocr_text,
            system_prompt=system_prompt,
        )
        logger.info(
            'Document extraction selected: strategy=%s source_kind=%s family=%s candidate_type=%s confidence=%s mode=%s fallback_reason=%s matched_rules=%s',
            strategy,
            extraction_input.source_kind,
            routing_result.detected_family,
            routing_result.candidate_type,
            routing_result.confidence_score,
            routing_result.extraction_mode,
            routing_result.fallback_reason,
            ','.join(routing_result.matched_rules) or '-',
        )
        return DocumentExtractionResult(
            payload=payload,
            strategy=strategy,
            detected_family=routing_result.detected_family,
            candidate_type=routing_result.candidate_type,
            matched_rules=routing_result.matched_rules,
            confidence_score=routing_result.confidence_score,
            extraction_mode=routing_result.extraction_mode,
            fallback_reason=routing_result.fallback_reason,
            is_noisy=routing_result.is_noisy,
        )

    def _build_routing_result(
        self,
        *,
        strategy: str,
        ocr_text: str,
        strategy_fallback_reason: str | None,
    ) -> DocumentFamilyRoutingResult:
        if strategy == 'family_routing':
            return route_document_family(ocr_text)

        return build_generic_fallback_result(
            ocr_text,
            fallback_reason=strategy_fallback_reason or 'strategy_generic',
        )

    def _resolve_strategy(self, configured_strategy: str) -> tuple[str, str | None]:
        if configured_strategy not in VALID_EXTRACTION_STRATEGIES:
            logger.warning(
                'Unknown DOCUMENT_EXTRACTION_STRATEGY=%s, fallback to generic',
                configured_strategy,
            )
            return 'generic', f'invalid_strategy:{configured_strategy or "empty"}'
        if configured_strategy == 'ocr_structured':
            logger.info(
                'DOCUMENT_EXTRACTION_STRATEGY=ocr_structured is not implemented yet, fallback to generic',
            )
            return 'generic', 'strategy_not_implemented:ocr_structured'
        return configured_strategy, None

    def _resolve_system_prompt(
        self,
        *,
        strategy: str,
        routing_result: DocumentFamilyRoutingResult,
    ) -> str:
        if strategy != 'family_routing':
            return build_extraction_prompt()

        return build_extraction_prompt(
            family=routing_result.detected_family,
            extraction_mode=routing_result.extraction_mode,
            document_type=routing_result.candidate_type,
        )
