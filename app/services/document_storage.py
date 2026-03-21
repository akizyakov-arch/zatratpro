from dataclasses import dataclass
from pathlib import Path
import shutil

from app.config import get_settings


@dataclass(slots=True)
class StoredDocumentFile:
    storage_key: str
    file_role: str
    page_no: int
    mime_type: str | None
    original_filename: str | None
    file_ext: str
    file_size: int


class DocumentStorageService:
    def __init__(self) -> None:
        self.root = get_settings().document_storage_root

    def save_source(
        self,
        company_id: int,
        document_id: int,
        source_path: str | Path,
        original_filename: str | None = None,
        mime_type: str | None = None,
        file_ext: str | None = None,
    ) -> StoredDocumentFile:
        source = Path(source_path)
        ext = file_ext or source.suffix or '.bin'
        if not ext.startswith('.'):
            ext = f'.{ext}'
        storage_key = f'documents/{company_id}/{document_id}/source{ext.lower()}'
        target_path = self.root / storage_key
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target_path))
        return StoredDocumentFile(
            storage_key=storage_key,
            file_role='source',
            page_no=0,
            mime_type=mime_type,
            original_filename=original_filename,
            file_ext=ext.lower(),
            file_size=target_path.stat().st_size,
        )

    def resolve_path(self, storage_key: str) -> Path:
        return self.root / storage_key

    def delete(self, storage_key: str) -> None:
        path = self.resolve_path(storage_key)
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
