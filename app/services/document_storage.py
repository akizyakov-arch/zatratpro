from dataclasses import dataclass
import logging
from pathlib import Path
import shutil
from uuid import uuid4

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


@dataclass(slots=True)
class PreparedDocumentFile:
    temp_storage_key: str
    temp_path: Path
    final_path: Path
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

    def prepare_source(
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
    ) -> PreparedDocumentFile:
        source = Path(source_path)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f'Prepared document file is missing before storage save: {source}')

        ext = file_ext or source.suffix or '.bin'
        if not ext.startswith('.'):
            ext = f'.{ext}'
        ext = ext.lower()

        storage_key = f'documents/{company_id}/{document_id}/source{ext}'
        temp_storage_key = f'documents/{company_id}/{document_id}/.source-{uuid4().hex}{ext}'
        temp_path = self.root / temp_storage_key
        final_path = self.root / storage_key
        temp_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(
            'Staging prepared document file: source=%s temp_target=%s final_target=%s',
            source,
            temp_path,
            final_path,
        )
        shutil.move(str(source), str(temp_path))
        if not temp_path.exists() or not temp_path.is_file():
            raise FileNotFoundError(f'Prepared document file is missing after staging: {temp_path}')

        stored_file_size = temp_path.stat().st_size
        return PreparedDocumentFile(
            temp_storage_key=temp_storage_key,
            temp_path=temp_path,
            final_path=final_path,
            storage_key=storage_key,
            file_role='source',
            page_no=0,
            mime_type=mime_type,
            original_filename=original_filename,
            file_ext=ext,
            file_size=stored_file_size,
            original_file_size=original_file_size,
            stored_file_size=stored_file_size,
            was_normalized=was_normalized,
            original_kind=original_kind,
        )

    def finalize_prepared_source(self, prepared: PreparedDocumentFile) -> StoredDocumentFile:
        if not prepared.temp_path.exists() or not prepared.temp_path.is_file():
            raise FileNotFoundError(f'Prepared document staging file is missing before finalize: {prepared.temp_path}')
        if prepared.final_path.exists():
            raise FileExistsError(f'Target document storage path already exists: {prepared.final_path}')

        logger.info(
            'Finalizing prepared document file: temp=%s target=%s',
            prepared.temp_path,
            prepared.final_path,
        )
        prepared.temp_path.replace(prepared.final_path)
        if not prepared.final_path.exists() or not prepared.final_path.is_file():
            raise FileNotFoundError(f'Prepared document file is missing after finalize: {prepared.final_path}')

        stored_file_size = prepared.final_path.stat().st_size
        return StoredDocumentFile(
            storage_key=prepared.storage_key,
            file_role=prepared.file_role,
            page_no=prepared.page_no,
            mime_type=prepared.mime_type,
            original_filename=prepared.original_filename,
            file_ext=prepared.file_ext,
            file_size=stored_file_size,
            original_file_size=prepared.original_file_size,
            stored_file_size=stored_file_size,
            was_normalized=prepared.was_normalized,
            original_kind=prepared.original_kind,
        )

    def discard_prepared_source(self, prepared: PreparedDocumentFile) -> None:
        for target in (prepared.temp_path, prepared.final_path):
            try:
                if target.exists():
                    logger.warning('Discarding prepared document file: path=%s storage_key=%s', target, prepared.storage_key)
                    target.unlink()
            except FileNotFoundError:
                continue
            except Exception:
                logger.warning('Failed to cleanup prepared document file: path=%s storage_key=%s', target, prepared.storage_key, exc_info=True)
        self._cleanup_empty_parent_dirs(prepared.final_path.parent)

    def resolve_path(self, storage_key: str) -> Path:
        return self.root / storage_key

    def delete(self, storage_key: str, *, context: str | None = None) -> None:
        path = self.resolve_path(storage_key)
        try:
            existed = path.exists()
            path.unlink(missing_ok=True)
            if existed:
                logger.warning('Deleted stored document file: storage_key=%s context=%s', storage_key, context or '-')
                self._cleanup_empty_parent_dirs(path.parent)
        except Exception:
            logger.warning('Failed to delete stored document file: storage_key=%s context=%s', storage_key, context or '-', exc_info=True)

    def _cleanup_empty_parent_dirs(self, directory: Path) -> None:
        current = directory
        while current != self.root and current.exists():
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
