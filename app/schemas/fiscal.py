"""Evidence in the OCR text, never an online fiscal registration check."""
import re


_NEGATIVE_MARKER = re.compile(
    r'(?:не\s*фискальн\w*(?:\s+(?:чек|документ))?'
    r'|(?:чек|документ)\s+не\s*фискальн\w*'
    r'|(?:(?:этот|данный)\s+)?(?:(?:чек|документ)\s+)?не\s+является\s+фискальн\w*(?:\s+(?:чеком|документом))?'
    r'|(?:(?:чек|документ)\s+)?не\s+фискализирован\w*'
    r'|non[- ]fiscal(?:\s+(?:receipt|document))?)', re.I,
)


def _has_negative_marker(text):
    # Only a standalone status/header counts. Product descriptions containing a
    # quoted phrase such as «Нефискальный документ» are not document evidence.
    for line in text.splitlines():
        line = re.sub(r'\s+', ' ', line).strip(' \t*#«»"\'.,!;:—–-')
        line = re.sub(r'^(?:внимание|статус|примечание)\s*:\s*', '', line, flags=re.I)
        # OCR can join a receipt heading and its status on one line. Only
        # strip that exact heading, not arbitrary text or product descriptions.
        line = re.sub(r'^(?:кассовый\s+чек|чек|документ)\s*[.!;:]\s*', '', line, flags=re.I)
        if _NEGATIVE_MARKER.fullmatch(line):
            return True
    return False


def detect_fiscalization(text: str | None) -> bool | None:
    text = text or ''
    fields = (
        (r'(?<!\w)(?:фн|фискальный\s+накопитель)\s*(?:№|n|:|=)?\s*([0-9]{10,16})(?![0-9])', r'(?:[?&]|\b)fn=([0-9]{10,16})(?![0-9])'),
        (r'(?<!\w)(?:фд|фискальный\s+документ)\s*(?:№|n|:|=)?\s*([0-9]{1,10})(?![0-9])', r'(?:[?&]|\b)i=([0-9]{1,10})(?![0-9])'),
        (r'(?<!\w)(?:фп(?:д)?|фискальный\s+признак(?:\s+документа)?)\s*(?:№|n|:|=)?\s*([0-9]{1,10})(?![0-9])', r'(?:[?&]|\b)fp=([0-9]{1,10})(?![0-9])'),
    )
    positive = all(any(re.search(pattern, text, re.I) for pattern in alternatives) for alternatives in fields)
    negative = _has_negative_marker(text)
    if positive and negative:
        return None
    if negative:
        return False
    return True if positive else None


def fiscalization_label(value: bool | None) -> str:
    return 'Да' if value is True else 'Нет' if value is False else 'Не определено'
