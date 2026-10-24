"""Shared Telegram financial controls, with no handler-to-handler imports."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=data)] for text, data in rows
    ])


async def send_details(message, text, rows):
    """Keep long histories and action lists inside Telegram message limits."""
    from app.services.json_formatter import chunk_message
    chunks = list(chunk_message(text))
    for chunk in chunks[:-1]:
        await message.answer(chunk)
    batches = [rows[index:index + 40] for index in range(0, len(rows), 40)] or [[]]
    await message.answer(chunks[-1] if chunks else 'Действия', reply_markup=keyboard(batches[0]) if batches[0] else None)
    for batch in batches[1:]:
        await message.answer('Продолжение действий', reply_markup=keyboard(batch))
