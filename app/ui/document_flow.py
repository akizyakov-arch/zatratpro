"""Telegram rendering of platform-neutral document workflow responses."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def callback_data(action, upload_id):
    if action.name == 'project':
        return f'document:project:{action.value}:{upload_id}'
    names = {'cancel': 'project:cancel', 'create_project': 'project:create',
             'duplicate_save': 'duplicate:save', 'review': 'review', 'resume': 'resume', 'projects': 'projects'}
    suffix = (':' + action.value) if action.value else ''
    return f'document:{names[action.name]}:{upload_id}{suffix}'


def keyboard(view):
    if not view.actions:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=a.label, callback_data=callback_data(a, view.upload_id))] for a in view.actions])
