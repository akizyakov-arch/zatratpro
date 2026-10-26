"""Web-only settings read consistently from environment or the project .env."""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import BASE_DIR


class WebSettings(BaseSettings):
    mini_app_enabled: bool = False
    telegram_bot_id: int = Field(default=0, ge=0)
    host: str = '127.0.0.1'
    port: int = Field(default=8080, ge=1, le=65535)
    origin: str = ''
    allowed_hosts: str = ''
    cookie_secure: bool = True
    bot_username: str = 'prozatrat_bot'
    trusted_proxies: str = '127.0.0.1'

    model_config = SettingsConfigDict(
        env_prefix='WEB_', env_file=BASE_DIR / '.env',
        env_file_encoding='utf-8', extra='ignore', case_sensitive=False,
    )


def get_web_settings():
    return WebSettings()


def mini_app_url():
    from urllib.parse import urlsplit
    settings = get_web_settings()
    origin = settings.origin.rstrip('/')
    parsed = urlsplit(origin)
    if (not settings.mini_app_enabled or not settings.telegram_bot_id or parsed.scheme != 'https'
            or not parsed.hostname or parsed.username or parsed.password or parsed.query
            or parsed.fragment or parsed.path or parsed.hostname in ('localhost','127.0.0.1')):
        return None
    return origin + '/mini'
