import logging
from time import perf_counter

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
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
logger = logging.getLogger(__name__)
SLOW_STAGE_MS = 400.0


@router.message(Command('help'))
async def help_command(message: Message) -> None:
    started = perf_counter()
    menu_kind = await help_menu_kind_for_user(message.from_user)
    after_kind = perf_counter()
    await message.answer(f'{person_name(message.from_user)}, выбери тему помощи.', reply_markup=build_help_topics_keyboard(menu_kind))
    finished = perf_counter()
    total_ms = (finished - started) * 1000
    if total_ms >= SLOW_STAGE_MS:
        logger.warning(
            "Help stages: user_id=%s menu_kind=%.1fms send=%.1fms total=%.1fms",
            message.from_user.id if message.from_user else 0,
            (after_kind - started) * 1000,
            (finished - after_kind) * 1000,
            total_ms,
        )


@router.message(F.text == MENU_BUTTONS['help'])
async def help_button(message: Message) -> None:
    await help_command(message)


@router.callback_query(F.data.startswith(HELP_MENU_PREFIX))
async def help_menu_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    started = perf_counter()
    await callback.answer()
    after_answer = perf_counter()
    menu_kind = callback.data.removeprefix(HELP_MENU_PREFIX) or 'employee'
    if menu_kind not in HELP_TOPICS:
        await callback.answer('Раздел помощи недоступен.', show_alert=True)
        return
    before_send = perf_counter()
    try:
        await callback.message.edit_text('Выбери тему помощи.', reply_markup=build_help_topics_keyboard(menu_kind))
    except TelegramBadRequest:
        await callback.message.answer('Выбери тему помощи.', reply_markup=build_help_topics_keyboard(menu_kind))
    finished = perf_counter()
    total_ms = (finished - started) * 1000
    if total_ms >= SLOW_STAGE_MS:
        logger.warning(
            "Help menu stages: user_id=%s answer=%.1fms send=%.1fms total=%.1fms data=%r",
            callback.from_user.id if callback.from_user else 0,
            (after_answer - started) * 1000,
            (finished - before_send) * 1000,
            total_ms,
            callback.data,
        )


@router.callback_query(F.data.startswith(HELP_TOPIC_PREFIX))
async def help_topic_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    started = perf_counter()
    await callback.answer()
    after_answer = perf_counter()
    payload = callback.data.removeprefix(HELP_TOPIC_PREFIX)
    try:
        menu_kind, topic_id = payload.split(':', 1)
    except ValueError:
        await callback.answer('Тема помощи недоступна.', show_alert=True)
        return
    if menu_kind not in HELP_TOPICS:
        await callback.answer('Тема помощи недоступна.', show_alert=True)
        return
    text_value = get_help_topic_text(menu_kind, topic_id)
    if text_value is None:
        await callback.answer('Тема помощи недоступна.', show_alert=True)
        return
    before_send = perf_counter()
    try:
        await callback.message.edit_text(text_value, reply_markup=build_help_topic_keyboard(menu_kind))
    except TelegramBadRequest:
        await callback.message.answer(text_value, reply_markup=build_help_topic_keyboard(menu_kind))
    finished = perf_counter()
    total_ms = (finished - started) * 1000
    if total_ms >= SLOW_STAGE_MS:
        logger.warning(
            "Help topic stages: user_id=%s answer=%.1fms send=%.1fms total=%.1fms data=%r",
            callback.from_user.id if callback.from_user else 0,
            (after_answer - started) * 1000,
            (finished - before_send) * 1000,
            total_ms,
            callback.data,
        )
