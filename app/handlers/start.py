from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from app.handlers.common import NL, build_main_menu_markup_from_context, ensure_context, ensure_user_context, main_menu_markup, main_menu_markup_for_user, person_identity
from app.handlers.onboarding import join_company
from app.ui.company import NAV_MAIN_CALLBACK
from app.ui.main_menu import MAIN_MENU_TEXT

router = Router()


@router.message(CommandStart())
async def start_command(message: Message, command: CommandObject | None = None) -> None:
    context = await ensure_context(message)
    payload = command.args if command is not None else None
    if payload and payload.startswith('join_'):
        await join_company(message, payload.removeprefix('join_'))
        return
    if context is not None and context.menu_kind == 'platform_owner':
        line = 'Owner-режим: управление компаниями и системным состоянием.'
    elif context is not None and context.has_company:
        line = f'Текущая компания: {context.company.name}'
    else:
        line = 'Сначала нужен invite-код компании.'
    reply_markup = build_main_menu_markup_from_context(context) if context is not None else await main_menu_markup(message)
    await message.answer(
        f'Привет, {person_identity(message.from_user)}.' + NL + NL + MAIN_MENU_TEXT + NL + NL + line,
        reply_markup=reply_markup,
    )


@router.callback_query(F.data == NAV_MAIN_CALLBACK)
async def nav_main_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    context = await ensure_user_context(callback.from_user)
    if context is None:
        await callback.message.answer(MAIN_MENU_TEXT, reply_markup=await main_menu_markup_for_user(callback.from_user))
        return
    await callback.message.answer(MAIN_MENU_TEXT, reply_markup=build_main_menu_markup_from_context(context))
