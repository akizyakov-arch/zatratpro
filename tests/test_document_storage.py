import tempfile
import unittest
from pathlib import Path

from app.services.document_storage import DocumentStorageService


class DocumentStorageServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "storage"
        self.root.mkdir(parents=True, exist_ok=True)
        self.source_dir = Path(self.temp_dir.name) / "incoming"
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.service = DocumentStorageService()
        self.service.root = self.root

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_source(self, name: str = "source.jpg", content: bytes = b"payload") -> Path:
        path = self.source_dir / name
        path.write_bytes(content)
        return path

    def test_prepare_and_finalize_source(self) -> None:
        source = self._write_source()

        prepared = self.service.prepare_source(
            company_id=1,
            document_id=99,
            source_path=source,
            original_filename="receipt.jpg",
            mime_type="image/jpeg",
            file_ext=".jpg",
        )

        self.assertFalse(source.exists())
        self.assertTrue(prepared.temp_path.exists())
        self.assertFalse(prepared.final_path.exists())

        stored = self.service.finalize_prepared_source(prepared)
        final_path = self.root / stored.storage_key

        self.assertTrue(final_path.exists())
        self.assertFalse(prepared.temp_path.exists())
        self.assertEqual(final_path.read_bytes(), b"payload")
        self.assertEqual(stored.storage_key, "documents/1/99/source.jpg")

    def test_discard_prepared_source_removes_finalized_file(self) -> None:
        source = self._write_source(content=b"to-delete")

        prepared = self.service.prepare_source(
            company_id=2,
            document_id=7,
            source_path=source,
            original_filename="invoice.jpg",
            mime_type="image/jpeg",
            file_ext=".jpg",
        )
        stored = self.service.finalize_prepared_source(prepared)

        self.service.discard_prepared_source(prepared)

        self.assertFalse((self.root / stored.storage_key).exists())
        self.assertFalse(prepared.temp_path.exists())


if __name__ == "__main__":
    unittest.main()
