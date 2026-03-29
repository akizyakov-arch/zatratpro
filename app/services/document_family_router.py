import re
from dataclasses import dataclass

from app.document_rules import (
    DEFAULT_EXTRACTION_MODE,
    DOCUMENT_FAMILY_RULES,
    GENERIC_FALLBACK_FAMILY,
    STRICT_EXTRACTION_MODE,
    detect_document_type_from_text,
    document_family_for_type,
)


SHORT_ALPHA_LINE_RE = re.compile(r'[A-Za-zА-Яа-я]')
SUSPICIOUS_CHAR_RE = re.compile(r'[?~_|]{2,}|�')


@dataclass(frozen=True, slots=True)
class DocumentFamilyRoutingResult:
    detected_family: str
    candidate_type: str | None
    matched_rules: tuple[str, ...] = ()
    confidence_score: int = 0
    extraction_mode: str = DEFAULT_EXTRACTION_MODE
    fallback_reason: str | None = None
    is_noisy: bool = False


def route_document_family(raw_text: str) -> DocumentFamilyRoutingResult:
    candidate_type = detect_document_type_from_text(raw_text)
    direct_family = document_family_for_type(candidate_type)
    if candidate_type != 'unknown' and direct_family is not None:
        return build_generic_fallback_result(
            raw_text,
            candidate_type=candidate_type,
            detected_family=direct_family,
            matched_rules=(f'type:{candidate_type}',),
            confidence_score=100,
        )

    text = (raw_text or '').lower()
    scored_matches: list[tuple[int, int, str, tuple[str, ...]]] = []
    for family_rule in DOCUMENT_FAMILY_RULES:
        positive_hits = tuple(token for token in family_rule.positive_markers if token in text)
        negative_hits = tuple(token for token in family_rule.negative_markers if token in text)
        if not positive_hits and not negative_hits:
            continue

        score = len(positive_hits) * 2 - len(negative_hits) * 3
        matched_rules = tuple(
            [f'+:{token}' for token in positive_hits]
            + [f'-:{token}' for token in negative_hits]
        )
        scored_matches.append((score, len(positive_hits), family_rule.family, matched_rules))

    if not scored_matches:
        return build_generic_fallback_result(raw_text, fallback_reason='no_family_markers')

    scored_matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best_score, _best_positive_hits, best_family, best_rules = scored_matches[0]
    second_score = scored_matches[1][0] if len(scored_matches) > 1 else None

    if best_score < 2:
        return build_generic_fallback_result(
            raw_text,
            fallback_reason='low_confidence_family',
            matched_rules=best_rules,
        )
    if second_score is not None and best_score == second_score:
        return build_generic_fallback_result(
            raw_text,
            fallback_reason='ambiguous_family',
            matched_rules=best_rules,
        )

    return build_generic_fallback_result(
        raw_text,
        detected_family=best_family,
        matched_rules=best_rules,
        confidence_score=best_score,
    )


def build_generic_fallback_result(
    raw_text: str,
    *,
    candidate_type: str | None = None,
    detected_family: str | None = None,
    matched_rules: tuple[str, ...] = (),
    confidence_score: int = 0,
    fallback_reason: str | None = None,
) -> DocumentFamilyRoutingResult:
    resolved_candidate_type = candidate_type or detect_document_type_from_text(raw_text)
    resolved_family = detected_family
    if resolved_family is None:
        resolved_family = document_family_for_type(resolved_candidate_type) or GENERIC_FALLBACK_FAMILY

    is_noisy = _looks_like_noisy_ocr(raw_text)
    extraction_mode = STRICT_EXTRACTION_MODE if is_noisy else DEFAULT_EXTRACTION_MODE

    if resolved_candidate_type == 'unknown':
        resolved_candidate_type = None

    return DocumentFamilyRoutingResult(
        detected_family=resolved_family,
        candidate_type=resolved_candidate_type,
        matched_rules=matched_rules,
        confidence_score=confidence_score,
        extraction_mode=extraction_mode,
        fallback_reason=fallback_reason,
        is_noisy=is_noisy,
    )


def _looks_like_noisy_ocr(raw_text: str) -> bool:
    text = raw_text or ''
    if not text:
        return False

    suspicious_blocks = len(SUSPICIOUS_CHAR_RE.findall(text))
    compact_lines = [re.sub(r'\s+', '', line) for line in text.splitlines() if line.strip()]
    if not compact_lines:
        return False

    short_alpha_lines = sum(
        1
        for line in compact_lines
        if SHORT_ALPHA_LINE_RE.search(line) and len(line) <= 3
    )
    return suspicious_blocks >= 3 or short_alpha_lines >= max(4, len(compact_lines) // 2)
