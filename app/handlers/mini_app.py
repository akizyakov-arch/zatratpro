"""Launch via an INLINE web_app button: reply web_app buttons lack initData."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from app.adapters.telegram.companies import CompanyService
from app.web.config import mini_app_url

router = Router()
router.message.filter(F.chat.type == 'private')


@router.message(Command('panel'))
@router.message(F.text == 'Панель руководителя')
async def open_panel(message):
    if message.from_user is None:
        return
    await _show_panel(message.from_user.id, message)


@router.callback_query(F.data == 'manager:reports:panel')
async def panel_from_reports(callback):
    if callback.message is None or callback.message.chat.type != 'private':
        await callback.answer()
        return
    await callback.answer()
    await _show_panel(callback.from_user.id, callback.message)


async def _show_panel(sender, message):
    context = await CompanyService().get_user_context(sender)
    if context.menu_kind != 'manager' or not context.has_company:
        await message.answer('Панель доступна руководителю активной компании.')
        return
    url = mini_app_url()
    if not url:
        await message.answer('Панель ещё не подключена. Администратор настраивает адрес сервера.')
        return
    await message.answer(
        'Откройте панель: проекты, деньги, документы и отчёты вашей компании.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text='Открыть панель', web_app=WebAppInfo(url=url)),
        ]]),
    )
