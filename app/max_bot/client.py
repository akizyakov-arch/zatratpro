"""Small MAX HTTP transport. Tokens are sent only to the official API host."""
import ssl
from pathlib import Path

import httpx
from app.max_bot.menu import CALLBACK_PREFIX, MenuButton, LinkButton

API_URL = 'https://platform-api2.max.ru'
ROOT_CA = Path(__file__).with_name('certs') / 'russian_trusted_root_ca.pem'
UPDATE_TYPES = 'bot_started,message_created,message_callback'


class MaxAPIError(RuntimeError):
    def __init__(self, message, *, status=None, retry_after=3):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class MaxClient:
    def __init__(self, token, *, ca_bundle=None, transport=None):
        if not isinstance(token, str) or not token.strip():
            raise ValueError('MAX_BOT_TOKEN не настроен.')
        context = ssl.create_default_context()
        # The official API uses Russian Trusted Root CA. Add it only to MAX's
        # context, preserving the system roots and normal hostname verification.
        context.load_verify_locations(cafile=str(ROOT_CA))
        if ca_bundle:
            context.load_verify_locations(cafile=ca_bundle)
        self.http = httpx.AsyncClient(base_url=API_URL, headers={'Authorization': token},
            verify=context, timeout=httpx.Timeout(45, connect=15), transport=transport,
            follow_redirects=False)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.http.aclose()

    async def _request(self, method, path, **kwargs):
        try:
            response = await self.http.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise MaxAPIError('MAX: превышено время ожидания ответа API.') from None
        except httpx.HTTPError as exc:
            if 'CERTIFICATE_VERIFY_FAILED' in str(exc).upper():
                raise MaxAPIError('MAX: сертификат API не прошёл проверку. Проверьте доверенный корневой CA и MAX_CA_BUNDLE.') from None
            raise MaxAPIError('MAX: не удалось соединиться с API. Проверьте DNS и доступ к platform-api2.max.ru:443.') from None
        if response.status_code != 200:
            retry = response.headers.get('Retry-After', '')
            retry = min(60, max(1, int(retry))) if retry.isdigit() and len(retry) < 6 else 3
            raise MaxAPIError(f'MAX API: HTTP {response.status_code}.', status=response.status_code, retry_after=retry)
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
        except ValueError:
            raise MaxAPIError('MAX вернул некорректный ответ.') from None
        return data

    async def me(self):
        data = await self._request('GET', '/me')
        if type(data.get('user_id')) is not int or data['user_id'] <= 0 or data.get('is_bot') is not True:
            raise MaxAPIError('MAX не подтвердил учётную запись бота.')
        return data

    async def subscriptions(self):
        data = await self._request('GET', '/subscriptions')
        if not isinstance(data.get('subscriptions'), list):
            raise MaxAPIError('MAX вернул некорректный список подписок.')
        return data['subscriptions']

    async def updates(self, marker=None, timeout=30):
        params = {'limit': 100, 'timeout': timeout, 'types': UPDATE_TYPES}
        if marker is not None:
            params['marker'] = marker
        data = await self._request('GET', '/updates', params=params)
        updates = data.get('updates')
        marker = data.get('marker')
        if (not isinstance(updates, list) or len(updates) > 1000
                or any(not isinstance(update, dict) for update in updates)
                or (marker is not None and (type(marker) is not int or not -(2**63) <= marker < 2**63))):
            raise MaxAPIError('MAX вернул некорректную страницу событий.')
        return updates, marker

    async def answer(self, callback_id):
        await self._request('POST', '/answers', params={'callback_id': callback_id}, json={})

    async def send(self, user_id, text):
        if type(user_id) is not int or user_id <= 0 or not isinstance(text, str) or not text:
            raise ValueError('Некорректный получатель или текст MAX.')
        buttons = getattr(text, 'buttons', None)
        for start in range(0, len(text), 3500):
            body = {'text': str(text[start:start + 3500])}
            if buttons and start + 3500 >= len(text):
                body['attachments'] = [{'type': 'inline_keyboard', 'payload': {'buttons': [
                    [({'type': 'link', 'text': str(label)[:128], 'url': label.url} if isinstance(label, LinkButton) else
                     {'type': 'callback', 'text': str(label)[:128], 'payload': CALLBACK_PREFIX + label.command}
                      if isinstance(label, MenuButton) else {'type': 'message', 'text': str(label)[:128]}) for label in row] for row in buttons
                ]}}]
            await self._request('POST', '/messages', params={'user_id': user_id, 'disable_link_preview': 'true'},
                json=body)
