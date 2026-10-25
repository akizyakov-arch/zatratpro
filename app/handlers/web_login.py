"""Telegram adapter: explicitly approve a browser login, without registration."""
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.web_auth import WebAuthError, WebAuthService

router = Router()
service = WebAuthService()


async def private(message):
    if message.chat.type != 'private':
        await message.answer('Вход в веб-панель подтверждается только в личном чате с ботом.')
        return False
    return True


async def show_request(message, code):
    if not await private(message) or message.from_user is None:
        return
    try:
        result = await service.present(message.from_user.id, code)
        await message.answer(
            'Вход в веб-панель FIINOPS\n\n'
            f"Пользователь: {result['user']['name']}\n"
            f"Браузер: {result['browser']}\n"
            f"Время запроса UTC: {result['created_at']:%d.%m.%Y %H:%M}\n\n"
            'Подтвердите, только если вы начали вход в этом браузере. '
            'Подтверждение откроет доступ к вашему кабинету. Запрос действует 5 минут.',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='Подтвердить вход', callback_data=f"web:approve:{result['id']}")],
                [InlineKeyboardButton(text='Отклонить', callback_data=f"web:deny:{result['id']}")],
            ]),
        )
    except WebAuthError as exc:
        await message.answer(str(exc))


@router.message(Command('web_login'))
async def web_login(message, command: CommandObject):
    await show_request(message, command.args or '')


@router.message(Command('start'), F.text.regexp(r'^/start(?:@\w+)?\s+web_'))
async def web_start(message, command: CommandObject):
    await show_request(message, (command.args or '')[4:])


@router.callback_query(F.data.startswith('web:'))
async def decide_login(callback):
    if callback.message is None or not await private(callback.message):
        return
    try:
        _, action, request_id = callback.data.split(':', 2)
        if action not in ('approve', 'deny'):
            raise WebAuthError('Откройте запрос входа заново.')
        status = await service.decide(callback.from_user.id, request_id, action == 'approve')
        await callback.answer()
        await callback.message.answer('Вход подтверждён. Вернитесь в браузер.' if status == 'approved' else 'Вход отклонён.')
    except (WebAuthError, ValueError) as exc:
        await callback.answer()
        await callback.message.answer(str(exc) if isinstance(exc, WebAuthError) else 'Откройте запрос входа заново.')
