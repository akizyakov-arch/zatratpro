"""Evidence in the OCR text, never an online fiscal registration check."""
import re


def detect_fiscalization(text: str | None) -> bool | None:
    text = text or ''
    if re.search(r'(?<!\w)(?:не\s*фискальн\w*\s+(?:чек|документ)\b|не\s+фискализирован\w*\b|не\s+является\s+фискальн\w*\b|non[- ]fiscal\s+(?:receipt|document)\b)|^\s*не\s*фискальн\w*\s*$', text, re.I | re.M):
        return False
    fields = (
        (r'(?<!\w)(?:фн|фискальный\s+накопитель)\s*(?:№|n|:|=)?\s*([0-9]{10,16})(?![0-9])', r'(?:[?&]|\b)fn=([0-9]{10,16})(?![0-9])'),
        (r'(?<!\w)(?:фд|фискальный\s+документ)\s*(?:№|n|:|=)?\s*([0-9]{1,10})(?![0-9])', r'(?:[?&]|\b)i=([0-9]{1,10})(?![0-9])'),
        (r'(?<!\w)(?:фп(?:д)?|фискальный\s+признак(?:\s+документа)?)\s*(?:№|n|:|=)?\s*([0-9]{1,10})(?![0-9])', r'(?:[?&]|\b)fp=([0-9]{1,10})(?![0-9])'),
    )
    if all(any(re.search(pattern, text, re.I) for pattern in alternatives) for alternatives in fields):
        return True
    return None


def fiscalization_label(value: bool | None) -> str:
    return 'Да' if value is True else 'Нет' if value is False else 'Не определено'
