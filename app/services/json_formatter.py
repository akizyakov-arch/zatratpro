import json
from typing import Iterable


def format_document_json(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2)


def chunk_message(text: str, limit: int = 3900) -> Iterable[str]:
    if len(text) <= limit:
        yield text
        return

    start = 0
    while start < len(text):
        yield text[start : start + limit]
        start += limit
