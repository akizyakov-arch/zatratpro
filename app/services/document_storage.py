from dataclasses import dataclass
import logging
from pathlib import Path
import shutil

from app.config import get_settings


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class StoredDocumentFile:
    storage_key: str
    file_role: str
    page_no: int
    mime_type: str | None
    original_filename: str | None
    file_ext: str
    file_size: int
    original_file_size: int | None
    stored_file_size: int
    was_normalized: bool
    original_kind: str | None


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
        original_file_size: int | None = None,
        was_normalized: bool = False,
        original_kind: str | None = None,
    ) -> StoredDocumentFile:
        source = Path(source_path)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f'Prepared document file is missing before storage save: {source}')
        ext = file_ext or source.suffix or '.bin'
        if not ext.startswith('.'):
            ext = f'.{ext}'
        storage_key = f'documents/{company_id}/{document_id}/source{ext.lower()}'
        target_path = self.root / storage_key
        target_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info('Persisting prepared document file: source=%s target=%s', source, target_path)
        shutil.move(str(source), str(target_path))
        if not target_path.exists() or not target_path.is_file():
            raise FileNotFoundError(f'Prepared document file is missing after storage save: {target_path}')
        stored_file_size = target_path.stat().st_size
        return StoredDocumentFile(
            storage_key=storage_key,
            file_role='source',
            page_no=0,
            mime_type=mime_type,
            original_filename=original_filename,
            file_ext=ext.lower(),
            file_size=stored_file_size,
            original_file_size=original_file_size,
            stored_file_size=stored_file_size,
            was_normalized=was_normalized,
            original_kind=original_kind,
        )

    def resolve_path(self, storage_key: str) -> Path:
        return self.root / storage_key

    def delete(self, storage_key: str) -> None:
        path = self.resolve_path(storage_key)
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
