from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.handlers.common import help_menu_kind_for_user, person_name
from app.ui.help import HELP_TOPICS
from app.ui.help import (
    HELP_MENU_PREFIX,
    HELP_TOPIC_PREFIX,
    build_help_topic_keyboard,
    build_help_topics_keyboard,
    get_help_topic_text,
)
from app.ui.main_menu import MENU_BUTTONS

router = Router()


@router.message(Command('help'))
async def help_command(message: Message) -> None:
    menu_kind = await help_menu_kind_for_user(message.from_user)
    await message.answer(f'{person_name(message.from_user)}, выбери тему помощи.', reply_markup=build_help_topics_keyboard(menu_kind))


@router.message(F.text == MENU_BUTTONS['help'])
async def help_button(message: Message) -> None:
    await help_command(message)


@router.callback_query(F.data.startswith(HELP_MENU_PREFIX))
async def help_menu_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    menu_kind = callback.data.removeprefix(HELP_MENU_PREFIX) or 'employee'
    if menu_kind not in HELP_TOPICS:
        await callback.message.answer('Раздел помощи недоступен.')
        return
    await callback.message.answer('Выбери тему помощи.', reply_markup=build_help_topics_keyboard(menu_kind))


@router.callback_query(F.data.startswith(HELP_TOPIC_PREFIX))
async def help_topic_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    payload = callback.data.removeprefix(HELP_TOPIC_PREFIX)
    try:
        menu_kind, topic_id = payload.split(':', 1)
    except ValueError:
        await callback.message.answer('Тема помощи недоступна.')
        return
    if menu_kind not in HELP_TOPICS:
        await callback.message.answer('Тема помощи недоступна.')
        return
    text_value = get_help_topic_text(menu_kind, topic_id)
    if text_value is None:
        await callback.message.answer('Тема помощи недоступна.')
        return
    await callback.message.answer(text_value, reply_markup=build_help_topic_keyboard(menu_kind))
