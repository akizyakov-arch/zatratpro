"""Web-only settings read consistently from environment or the project .env."""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import BASE_DIR


class WebSettings(BaseSettings):
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
