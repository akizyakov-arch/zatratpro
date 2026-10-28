"""Bounded MAX attachment downloads; Bot API credentials never enter CDN requests."""
import asyncio
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit, urljoin

import httpx

from app.max_bot.client import ROOT_CA
from app.services.documents import DocumentValidationError


async def public_url(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError
        addresses = await asyncio.get_running_loop().getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError
    except (ValueError, OSError, TypeError):
        raise DocumentValidationError('Недопустимая ссылка вложения. Отправьте файл заново.') from None


async def download(url, limit):
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=str(ROOT_CA))
    # A distinct client is intentional: no Authorization/header from MaxClient.
    async with httpx.AsyncClient(verify=context, timeout=40, follow_redirects=False) as client:
        for _ in range(4):
            await public_url(url)
            async with client.stream('GET', url) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers.get('Location', ''))
                    continue
                if response.status_code != 200:
                    raise DocumentValidationError('MAX не отдал файл. Отправьте вложение заново.')
                length = response.headers.get('Content-Length', '')
                if length.isdigit() and int(length) > limit:
                    raise DocumentValidationError('Файл слишком большой.')
                result = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(result) + len(chunk) > limit:
                        raise DocumentValidationError('Файл слишком большой.')
                    result.extend(chunk)
                return bytes(result)
    raise DocumentValidationError('Не удалось получить вложение MAX.')
