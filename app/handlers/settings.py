"""Personal recognition settings shared by photos and PDF uploads."""
from aiogram import F, Router
from aiogram.filters import Command
from app.application.workspace import WorkspaceCommands
from app.handlers.application_views import send_view
from app.handlers.telegram_identity import actor
from app.services.advances import AdvanceError

router = Router()
router.message.filter(F.chat.type == 'private')
router.callback_query.filter(F.message.chat.type == 'private')


@router.message(Command('settings'))
@router.message(F.text == 'Настройки')
async def show_settings(message):
    try:
        await send_view(message, await WorkspaceCommands().handle(await actor(message.from_user), '/settings', platform='telegram'))
    except (AdvanceError, ValueError) as exc:
        await message.answer(str(exc))


@router.callback_query(F.data.startswith('recognition:'))
async def choose_recognition(callback):
    try:
        view = await WorkspaceCommands().handle(await actor(callback.from_user), '/recognition ' + callback.data.split(':', 1)[1], platform='telegram')
    except (ValueError, AdvanceError) as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer('Настройка сохранена')
    await send_view(callback.message, view)
