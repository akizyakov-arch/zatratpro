"""Personal recognition settings shared by photos and PDF uploads."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.services.recognition import PROVIDERS, get_provider_name, set_provider

router = Router()
router.message.filter(F.chat.type == 'private')
router.callback_query.filter(F.message.chat.type == 'private')


async def settings_view(telegram_id):
    selected = await get_provider_name(telegram_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=('✓ ' if name == selected else '') + title,
                             callback_data='recognition:' + name)
    ] for name, title in PROVIDERS.items()])
    return ('Настройки → Распознавание\nСейчас: ' + PROVIDERS[selected] +
            '\nВыбор действует для твоих следующих фото и PDF. Уже распознанные документы не меняются.', keyboard)


@router.message(Command('settings'))
@router.message(F.text == 'Настройки')
async def show_settings(message):
    text, keyboard = await settings_view(message.from_user.id)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith('recognition:'))
async def choose_recognition(callback):
    try:
        await set_provider(callback.from_user.id, callback.data.split(':', 1)[1])
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer('Настройка сохранена')
    text, keyboard = await settings_view(callback.from_user.id)
    # A new reply also handles repeated clicks without Telegram's "not modified" error.
    await callback.message.answer(text, reply_markup=keyboard)
