"""Telegram download boundary for shared PDF recognition."""
from app.services.pdf_files import PDFError, LimitedDownload, MAX_PDF_BYTES, extract_pdf_bytes


async def extract_pdf(message, ocr_service):
    document = message.document
    if document.file_size and document.file_size > MAX_PDF_BYTES:
        raise PDFError('PDF слишком большой. Максимум 10 МБ.')
    with LimitedDownload() as destination:
        await message.bot.download(document, destination=destination)
        data = destination.getvalue()
    return await extract_pdf_bytes(data, ocr_service, message.caption, message.answer)
