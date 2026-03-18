from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.handlers.common import NL, ensure_context, main_menu_markup, main_menu_markup_for_user, person_identity
from app.ui.company import NAV_MAIN_CALLBACK
from app.ui.main_menu import MAIN_MENU_TEXT


router = Router()


@router.message(Command("start"))
async def start_command(message: Message, command: CommandObject | None = None) -> None:
    context = await ensure_context(message)
    if context is not None and context.menu_kind == "platform_owner":
        line = "Owner-режим: управление компаниями и системным состоянием."
    elif context is not None and context.has_company:
        line = f"Текущая компания: {context.company.name}"
    else:
        line = "Сначала нужен invite-код компании."
    await message.answer(
        f"Привет, {person_identity(message.from_user)}." + NL + NL + MAIN_MENU_TEXT + NL + NL + line,
        reply_markup=await main_menu_markup(message),
    )


@router.callback_query(F.data == NAV_MAIN_CALLBACK)
async def nav_main_callback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await callback.message.answer(MAIN_MENU_TEXT, reply_markup=await main_menu_markup_for_user(callback.from_user))


@router.message(F.text)
async def fallback_text(message: Message) -> None:
    if message.from_user is None or not message.text:
        await message.answer(
            "Поддерживаются кнопки главного меню, /start, /help, /join и фото документов.",
            reply_markup=await main_menu_markup(message),
        )
        return
    await message.answer("Используй кнопки главного меню или отправь фото документа.", reply_markup=await main_menu_markup(message))
