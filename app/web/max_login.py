"""Resolve the MAX bot's public link without reading updates or sending messages."""
import asyncio
import re
import logging
from pydantic import ValidationError
from app.max_bot.__main__ import MaxSettings
from app.max_bot.client import MaxClient, MaxAPIError
from app.web.config import get_web_settings

logger = logging.getLogger(__name__)

async def login_link(code):
    username = get_web_settings().max_bot_username
    if not username:
        try:
            settings = MaxSettings()
            async with asyncio.timeout(5):
                async with MaxClient(settings.token.get_secret_value(), ca_bundle=settings.ca_bundle or None) as client:
                    username = (await client.me()).get('username', '')
        except (ValidationError, MaxAPIError, TimeoutError, OSError, ValueError):
            logger.warning('max_login_link_unavailable')
            return None
    if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,100}', username):
        return None
    return 'https://max.ru/' + username + '?start=web_' + code
