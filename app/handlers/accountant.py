"""Telegram delivery of the shared accountant archive."""
from aiogram.filters import Command
from aiogram import Router
from aiogram.types import BufferedInputFile
from app.application.accountant import AccountantCommands
from app.handlers.application_views import send_view
from app.handlers.telegram_identity import actor
from app.services.accountant_exports import AccountantExportService
from app.services.advances import AdvanceError

router = Router()

async def show(message, sender, text):
    value = text.partition(' ')[2].strip()
    try:
        uid = await actor(sender)
        if not value or value == 'custom':
            await send_view(message, await AccountantCommands().selection(uid, value))
            return
        await AccountantCommands().dates(uid, value)
        await message.answer('Готовлю архив для бухгалтерии…')
        filename, data, missing = await AccountantExportService().build(uid, value)
        await message.answer_document(BufferedInputFile(data, filename=filename),
            caption=f'Для бухгалтерии. Без скана: {missing}. Подробности и позиции — в реестре.')
    except AdvanceError as exc:
        await message.answer(str(exc))

@router.message(Command('accountant'))
async def command(message):
    if message.chat.type == 'private' and message.from_user:
        await show(message, message.from_user, message.text)
