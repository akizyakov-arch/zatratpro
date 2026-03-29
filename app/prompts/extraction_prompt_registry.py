from app.document_rules import DEFAULT_EXTRACTION_MODE, GENERIC_FALLBACK_FAMILY
from app.prompts.extraction_prompt_parts import (
    EXTRACTION_PROMPT_BASE,
    EXTRACTION_PROMPT_DOCUMENT_TYPE_ADDONS,
    EXTRACTION_PROMPT_FAMILY_ADDONS,
    EXTRACTION_PROMPT_MODE_ADDONS,
)


def build_extraction_prompt(
    *,
    family: str = GENERIC_FALLBACK_FAMILY,
    extraction_mode: str = DEFAULT_EXTRACTION_MODE,
    document_type: str | None = None,
) -> str:
    family_addon = EXTRACTION_PROMPT_FAMILY_ADDONS.get(
        family,
        EXTRACTION_PROMPT_FAMILY_ADDONS[GENERIC_FALLBACK_FAMILY],
    )
    mode_addon = EXTRACTION_PROMPT_MODE_ADDONS.get(
        extraction_mode,
        EXTRACTION_PROMPT_MODE_ADDONS[DEFAULT_EXTRACTION_MODE],
    )
    document_type_addon = None
    if document_type is not None:
        document_type_addon = EXTRACTION_PROMPT_DOCUMENT_TYPE_ADDONS.get(document_type)
    prompt_parts = [
        EXTRACTION_PROMPT_BASE,
        family_addon,
    ]
    if document_type_addon:
        prompt_parts.append(document_type_addon)
    if mode_addon:
        prompt_parts.append(mode_addon)
    prompt_parts.append('Не добавляй текст вне JSON.')
    return '\n\n'.join(part for part in prompt_parts if part).strip()
