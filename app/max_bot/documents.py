"""MAX attachments, progress and buttons around the shared document workflow."""
import logging
from app.max_bot import files
from app.max_bot.client import MaxAPIError
from app.max_bot.menu import MenuButton, MenuText, HOME
from app.services.document_flow import DocumentFlow, DocumentFlowError
from app.services.document_processing import MAX_IMAGE_BYTES
from app.services.documents import DocumentValidationError
from app.services.pdf_files import MAX_PDF_BYTES, PDFError
from app.services.deepseek import DeepSeekError
from app.services.ocr_space import OCRSpaceError
from app.services.membership import MembershipError
from app.services.companies import CompanyAccessError

logger = logging.getLogger(__name__)


def render(view):
    buttons = [[MenuButton(a.label, f'/document {a.name} {view.upload_id}' + (f' {a.value}' if a.value else ''))] for a in view.actions]
    return MenuText(view.text, buttons or [HOME])


class DocumentMenu:
    def __init__(self, notify=None):
        self.flow = DocumentFlow()
        self.notify = notify

    async def handle(self, actor, sender, text, update):
        try:
            if text.startswith('/document '):
                parts = text.split()
                if len(parts) not in (3, 4):
                    raise DocumentFlowError('Откройте текущую загрузку.')
                return render(await self.flow.action(actor, parts[1], parts[2], parts[3] if len(parts) == 4 else ''))
            body = update.get('message', {}).get('body', {})
            attachments = body.get('attachments') if isinstance(body, dict) else None
            if update.get('update_type') == 'message_created' and attachments:
                if not isinstance(attachments, list) or len(attachments) != 1:
                    raise DocumentValidationError('Отправьте один документ за раз.')
                attachment = attachments[0]
                if not isinstance(attachment, dict) or attachment.get('type') not in ('image', 'file'):
                    return None
                payload = attachment.get('payload')
                if not isinstance(payload, dict) or not isinstance(payload.get('url'), str):
                    raise DocumentValidationError('MAX не передал файл. Отправьте вложение заново.')
                filename = str(attachment.get('filename', '')).lower()
                source = 'photo' if attachment['type'] == 'image' or filename.endswith(('.jpg', '.jpeg', '.png', '.webp')) else 'pdf' if filename.endswith('.pdf') else None
                if source is None:
                    raise DocumentValidationError('Отправьте фото, скан JPEG/PNG или PDF документа.')
                limit = MAX_PDF_BYTES if source == 'pdf' else MAX_IMAGE_BYTES
                size = attachment.get('size')
                if type(size) is int and size > limit:
                    raise DocumentValidationError('Файл слишком большой.')
                async def progress(message):
                    if self.notify:
                        try:
                            await self.notify(sender, message)
                        except MaxAPIError:
                            logger.warning('max_document_progress_unavailable')
                view = await self.flow.receive(actor, 'max', body.get('mid'), source,
                    lambda: files.download(payload['url'], limit), body.get('text') or '', progress)
                return render(view)
            if not text.startswith('/'):
                view = await self.flow.project_name(actor, text)
                return render(view) if view else None
        except Exception as exc:
            if isinstance(exc, (DocumentFlowError, DocumentValidationError, PDFError, DeepSeekError, OCRSpaceError, MembershipError, CompanyAccessError)):
                message = str(exc)
            else:
                logger.error('max_document_failed error_type=%s', type(exc).__name__)
                message = 'Не удалось обработать документ. Повторите загрузку позже.'
            return MenuText(message, [HOME])
        return None
