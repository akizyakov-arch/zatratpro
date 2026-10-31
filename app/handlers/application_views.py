"""Render application results using Telegram objects only at this boundary."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.application.navigation import callback
from app.services.json_formatter import chunk_message

_LABELS = {
    'Главное меню': '/start', 'Деньги': '/money', 'Сотрудники': '/employees',
    'Проекты': '/projects', 'Настройки': '/settings', 'Помощь': '/help',
    'Моя компания': '/my_company', 'Отчёты': '/reports', 'Отчеты': '/reports', 'Мой профиль': '/profile',
    'Загрузить документ': '/upload_document', 'Мои документы': '/my_documents',
    'Компании': '/companies', 'Пользователи': '/users', 'Создать компанию': '/create_company',
    'Статус системы': '/system_status',
}


def command_for_button(button):
    return getattr(button, 'command', None) or _LABELS[str(button)]


def telegram_callback(command):
    if command.startswith('/section_report '):
        return 'r:' + command.removeprefix('/section_report ').replace(' ', ':')
    if command.startswith('/report_periods '):
        return 'rp:' + command.removeprefix('/report_periods ').replace(' ', ':')
    if command.startswith('/issue_'):
        return 'issue:' + command.removeprefix('/issue_').replace(' ', ':')
    if command.startswith('/advance '):
        return 'cash:card:' + command.split()[1]
    if command == '/money':
        return 'issue:money'
    return callback(command)


async def send_view(message, view):
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=str(button), callback_data=telegram_callback(command_for_button(button)))
        for button in row
    ] for row in view.buttons]) if view.buttons else None
    chunks = list(chunk_message(str(view)))
    for index, chunk in enumerate(chunks):
        await message.answer(chunk, reply_markup=markup if index == len(chunks)-1 else None)
