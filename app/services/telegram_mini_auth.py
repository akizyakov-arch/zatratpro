"""Validate Telegram's production Ed25519 signature, without exposing bot tokens."""
import base64
import hashlib
import json
import re
import time
from urllib.parse import parse_qsl
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from app.services.web_auth import WebAuthError

# https://core.telegram.org/bots/webapps#validating-data-for-third-party-use
TELEGRAM_PUBLIC_KEY = bytes.fromhex('e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d')
MAX_AGE = 300


def verify_init_data(raw, bot_id, *, now=None):
    try:
        if not isinstance(raw, str) or not 1 <= len(raw) <= 16384 or type(bot_id) is not int or bot_id <= 0:
            raise ValueError
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=30)
        data = dict(pairs)
        if len(data) != len(pairs) or any(not re.fullmatch(r'[a-z_]+', key) for key in data):
            raise ValueError
        signature = data['signature']
        if not re.fullmatch(r'[A-Za-z0-9_-]{86}={0,2}', signature):
            raise ValueError
        signature_bytes = base64.urlsafe_b64decode(signature + '=' * (-len(signature) % 4))
        check = f'{bot_id}:WebAppData\n' + '\n'.join(f'{key}={value}' for key, value in sorted(data.items()) if key not in ('hash','signature'))
        Ed25519PublicKey.from_public_bytes(TELEGRAM_PUBLIC_KEY).verify(signature_bytes, check.encode())
        if not re.fullmatch(r'[0-9]{1,12}', data['auth_date']):
            raise ValueError
        auth_date = int(data['auth_date'])
        age = (time.time() if now is None else now) - auth_date
        if age < -30 or age > MAX_AGE:
            raise ValueError
        user = json.loads(data['user'])
        if not isinstance(user, dict) or type(user.get('id')) is not int or not 0 < user['id'] < 2**63 or user.get('is_bot') is True:
            raise ValueError
        return {'telegram_id': user['id'], 'auth_date': auth_date,
                'proof_hash': hashlib.sha256(signature_bytes).hexdigest()}
    except (ValueError, KeyError, TypeError, InvalidSignature):
        raise WebAuthError('Не удалось проверить вход Telegram. Закройте мини-приложение и откройте его заново.') from None
