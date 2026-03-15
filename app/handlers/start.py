from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message


router = Router()


@router.message(Command("start"))
async def start_command(message: Message) -> None:
    await message.answer(
        "Отправь фото чека, акта или накладной, и я попробую распознать текст и собрать JSON."
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(
        "Поддерживается фото документа. После загрузки бот скачает файл, выполнит OCR и попробует собрать структурированный JSON."
    )
