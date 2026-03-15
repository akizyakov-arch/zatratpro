from pathlib import Path
from uuid import uuid4

from aiogram import Bot
from aiogram.types import PhotoSize

from app.config import TMP_DIR


class TelegramFileService:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def download_best_photo(self, photos: list[PhotoSize]) -> Path:
        photo = photos[-1]
        telegram_file = await self.bot.get_file(photo.file_id)
        target_path = TMP_DIR / f"{uuid4()}.jpg"
        await self.bot.download_file(telegram_file.file_path, destination=target_path)
        return target_path
