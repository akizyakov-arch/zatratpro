import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pypdfium2 as pdfium
from app.services.pdf_files import PDFError, LimitedDownload, page_selection, _render_worker, extract_pdf


def make_pdf(path, pages=2):
    with pdfium.PdfDocument.new() as pdf:
        for _ in range(pages):
            page = pdf.new_page(400, 600)
            page.close()
        pdf.save(path)


class PDFTests(unittest.TestCase):
    def test_explicit_document_page_selection(self):
        self.assertEqual(page_selection('', 1), [0])
        self.assertEqual(page_selection('2-3', 3), [1, 2])
        self.assertEqual(page_selection('все', 3), [0, 1, 2])
        for value in ('', '0', '4', '3-1', 'receipt', '1,2'):
            with self.assertRaises(PDFError):
                page_selection(value, 3)

    def test_real_pdf_subprocess_render_and_invalid_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'input.pdf'
            make_pdf(path)
            self.assertEqual(_render_worker(path, folder, '2'), [1])
            self.assertTrue((Path(folder) / '2.jpg').exists())
            self.assertFalse((Path(folder) / '1.jpg').exists())
            with self.assertRaises(PDFError):
                _render_worker(path, folder, '')
            make_pdf(path, 11)
            with self.assertRaises(PDFError):
                _render_worker(path, folder, 'все')
            path.write_bytes(b'%PDF-broken')
            with self.assertRaises(PDFError):
                _render_worker(path, folder, '')

    def test_download_limit_enforced_on_bytes(self):
        with patch('app.services.pdf_files.MAX_PDF_BYTES', 4), LimitedDownload() as output:
            output.write(b'1234')
            with self.assertRaises(PDFError):
                output.write(b'5')


class PDFAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_ocr_page_order_failure_and_temporary_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'input.pdf'
            make_pdf(path)
            data = path.read_bytes()
            async def download(document, destination):
                destination.write(data)
            message = SimpleNamespace(document=SimpleNamespace(file_size=len(data)),
                bot=SimpleNamespace(download=download), caption='все', answer=AsyncMock())
            for responses in (['first', 'second'], ['first', ''], RuntimeError('provider unavailable')):
                ocr = SimpleNamespace(extract_text=AsyncMock(side_effect=responses))
                with patch('app.services.pdf_files.TMP_DIR', Path(folder)):
                    if responses == ['first', 'second']:
                        result = await extract_pdf(message, ocr)
                        self.assertLess(result.index('first'), result.index('second'))
                    else:
                        with self.assertRaises((PDFError, RuntimeError)):
                            await extract_pdf(message, ocr)
                self.assertEqual(list(Path(folder).iterdir()), [path])
