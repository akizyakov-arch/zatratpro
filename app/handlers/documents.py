"""Telegram file/event adapter; the document workflow lives in services."""
import logging
from io import BytesIO

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender

from app.services.account_links import AccountLinkService
from app.services.companies import CompanyAccessError
from app.services.document_flow import DocumentFlow, DocumentFlowError
from app.services.document_processing import MAX_IMAGE_BYTES
from app.services.documents import DocumentValidationError
from app.services.deepseek import DeepSeekError
from app.services.ocr_space import OCRSpaceError
from app.services.pdf_files import PDFError, MAX_PDF_BYTES
from app.services.membership import MembershipError
from app.services.json_formatter import chunk_message
from app.ui.document_flow import keyboard

router = Router()
router.message.filter(F.chat.type == 'private')
router.callback_query.filter(F.message.chat.type == 'private')
logger = logging.getLogger(__name__)
flow = DocumentFlow()
document_service = flow.documents  # Backward-compatible service export.


async def actor_for_user(user):
    actor = await AccountLinkService().resolve('telegram', str(user.id))
    if actor is None:
        raise CompanyAccessError('Сначала войдите через /start.')
    return actor


class BoundedDownload(BytesIO):
    def __init__(self, limit):
        super().__init__()
        self.limit = limit

    def write(self, data):
        if self.tell() + len(data) > self.limit:
            raise DocumentValidationError('Файл слишком большой.')
        return super().write(data)


async def show(message, view):
    chunks = list(chunk_message(view.text))
    for part in chunks[:-1]:
        await message.answer(part)
    await message.answer(chunks[-1], reply_markup=keyboard(view))


async def error(message, exc):
    if isinstance(exc, (CompanyAccessError, MembershipError, DocumentFlowError, DocumentValidationError, PDFError, OCRSpaceError, DeepSeekError)):
        text = str(exc)
    elif isinstance(exc, TimeoutError):
        text = 'Распознавание выполнялось слишком долго. Отправьте документ заново.'
    else:
        logger.error('document_adapter_failed error_type=%s', type(exc).__name__)
        text = 'Не удалось обработать документ. Попробуйте ещё раз позже.'
    await message.answer(text)


@router.message(F.document)
async def process_pdf(message: Message):
    document = message.document
    if document.mime_type != 'application/pdf' and not (document.file_name or '').lower().endswith('.pdf'):
        await message.answer('Отправьте PDF или фото документа. PDF: до 10 МБ и 10 страниц; страницы одного документа укажите в подписи: 1-3 или «все».')
        return
    await process_photo(message)


@router.message(F.photo)
async def process_photo(message: Message):
    if message.from_user is None:
        return
    document = getattr(message, 'document', None)
    source = 'pdf' if document else 'photo'
    file = document or (message.photo[-1] if message.photo else None)
    if file is None:
        return
    limit = MAX_PDF_BYTES if source == 'pdf' else MAX_IMAGE_BYTES

    async def download():
        if getattr(file, 'file_size', None) and file.file_size > limit:
            raise DocumentValidationError('Файл слишком большой.')
        with BoundedDownload(limit) as output:
            await message.bot.download(file, destination=output)
            return output.getvalue()

    try:
        actor = await actor_for_user(message.from_user)
        async with ChatActionSender.typing(chat_id=message.chat.id, bot=message.bot):
            view = await flow.receive(actor, 'telegram', str(message.message_id), source, download,
                                      getattr(message, 'caption', None) or '', message.answer)
        await show(message, view)
    except Exception as exc:
        await error(message, exc)


async def dispatch_action(callback, name, upload_id, value=''):
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer()
    try:
        view = await flow.action(await actor_for_user(callback.from_user), name, upload_id, value)
        await show(callback.message, view)
    except Exception as exc:
        await error(callback.message, exc)


@router.callback_query(F.data.startswith('document:project:cancel:'))
async def cancel_project_selection(callback: CallbackQuery):
    await dispatch_action(callback, 'cancel', callback.data.rsplit(':', 1)[-1])


@router.callback_query(F.data.startswith('document:project:create:'))
async def create_project_from_document(callback: CallbackQuery):
    await dispatch_action(callback, 'create_project', callback.data.rsplit(':', 1)[-1])


@router.callback_query(F.data.startswith('document:project:'))
async def process_project_selection(callback: CallbackQuery):
    try:
        project, upload_id = callback.data.removeprefix('document:project:').split(':', 1)
    except ValueError:
        await callback.answer('Откройте актуальный список проектов.')
        return
    await dispatch_action(callback, 'project', upload_id, project)


@router.callback_query(F.data.startswith('document:duplicate:cancel:'))
async def duplicate_cancel_callback(callback: CallbackQuery):
    await dispatch_action(callback, 'cancel', callback.data.rsplit(':', 1)[-1])


@router.callback_query(F.data.startswith('document:duplicate:save:'))
async def duplicate_save_callback(callback: CallbackQuery):
    await dispatch_action(callback, 'duplicate_save', callback.data.rsplit(':', 1)[-1])


@router.callback_query(F.data.startswith('document:review:'))
async def review_document_callback(callback: CallbackQuery):
    await dispatch_action(callback, 'review', callback.data.rsplit(':', 1)[-1])


@router.callback_query(F.data.startswith('document:resume:'))
@router.callback_query(F.data.startswith('document:projects:'))
async def resume_document_callback(callback: CallbackQuery):
    parts = callback.data.split(':')
    await dispatch_action(callback, parts[1], parts[2], parts[3] if len(parts) > 3 else '')


async def handle_project_name(message):
    if message.from_user is None or not message.text:
        return False
    try:
        view = await flow.project_name(await actor_for_user(message.from_user), message.text)
        if view is None:
            return False
        await show(message, view)
    except Exception as exc:
        await error(message, exc)
    return True


@router.message(~F.text)
async def unsupported_message(message: Message):
    await message.answer('Отправьте фото или PDF документа.')
