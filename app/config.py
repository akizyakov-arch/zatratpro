from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit
from typing import Annotated

from pydantic import Field, AliasChoices, SecretStr, field_validator, AfterValidator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
TMP_DIR = BASE_DIR / "tmp"


def _validate_ocr_proxy(value):
    url = value.get_secret_value().strip()
    if not url:
        return SecretStr('')
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in ('http', 'socks5') or not parsed.hostname
                or not parsed.port or parsed.path not in ('', '/') or parsed.query
                or parsed.fragment or any(c.isspace() for c in url)):
            raise ValueError
    except ValueError:
        raise ValueError('OCR_SPACE_PROXY_URL: нужен http://host:port или socks5://host:port.') from None
    return SecretStr(url)


OCRProxy = Annotated[SecretStr, AfterValidator(_validate_ocr_proxy)]


class DatabaseSettings(BaseSettings):
    postgres_db: str = Field(default="zatratpro", alias="POSTGRES_DB")
    postgres_user: str = Field(default="zatratpro", alias="POSTGRES_USER")
    postgres_password: str = Field(default="change_me", alias="POSTGRES_PASSWORD")
    postgres_host: str = Field(default="zatratpro-db", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


class OwnerSettings(BaseSettings):
    """Owner policy can be read without Telegram/OCR provider credentials."""
    bot_owner_telegram_id: int = Field(default=0, alias='BOT_OWNER_TELEGRAM_ID')
    model_config = DatabaseSettings.model_config


def get_owner_telegram_id() -> int:
    # Reuse the active application configuration when it has been initialized.
    # Standalone MAX can read owner policy without initializing API credentials.
    if get_settings.cache_info().currsize:
        return get_settings().bot_owner_telegram_id
    return OwnerSettings().bot_owner_telegram_id


class Settings(DatabaseSettings):
    model_config = SettingsConfigDict(**{**DatabaseSettings.model_config, 'hide_input_in_errors': True})
    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")
    telegram_proxy_url: SecretStr = Field(default='', alias='TELEGRAM_PROXY_URL')

    @field_validator('telegram_proxy_url')
    @classmethod
    def validate_telegram_proxy(cls, value):
        url = value.get_secret_value().strip()
        if not url:
            return SecretStr('')
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in ('http', 'socks5'):
                raise ValueError
            if (not parsed.hostname or not parsed.port or parsed.path not in ('', '/')
                    or parsed.query or parsed.fragment or any(c.isspace() for c in url)):
                raise ValueError
        except ValueError:
            raise ValueError('TELEGRAM_PROXY_URL: нужен http://host:port или socks5://host:port. MTProxy не поддерживает Telegram Bot API.') from None
        return SecretStr(url)

    ocr_space_api_key: str = Field(alias="OCR_SPACE_API_KEY")
    ocr_space_proxy_url: OCRProxy = Field(default='', alias='OCR_SPACE_PROXY_URL')
    deepseek_api_key: str = Field(alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com",
        alias="DEEPSEEK_BASE_URL",
    )
    deepseek_model: str = Field(default="deepseek-chat", alias="DEEPSEEK_MODEL")
    deepseek_vision_model: str = Field(default="deepseek-flash", alias="DEEPSEEK_VISION_MODEL")
    assemblyai_api_key: str = Field(default="", validation_alias=AliasChoices("ASSEMBLYAI_API_KEY", "ASSAMBLY"))
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    bot_owner_telegram_id: int = Field(default=0, alias="BOT_OWNER_TELEGRAM_ID")


def get_database_settings() -> DatabaseSettings:
    # Read once per pool initialization, independently of adapter credentials.
    return DatabaseSettings()


@lru_cache
def get_settings() -> Settings:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()


class RecognitionSettings(BaseSettings):
    """Provider configuration independent of messenger credentials."""
    model_config = SettingsConfigDict(**{**DatabaseSettings.model_config, 'hide_input_in_errors': True})
    ocr_space_api_key: str = Field(default='', alias='OCR_SPACE_API_KEY')
    ocr_space_proxy_url: OCRProxy = Field(default='', alias='OCR_SPACE_PROXY_URL')
    deepseek_api_key: str = Field(default='', alias='DEEPSEEK_API_KEY')
    deepseek_base_url: str = Field(default='https://api.deepseek.com', alias='DEEPSEEK_BASE_URL')
    deepseek_model: str = Field(default='deepseek-chat', alias='DEEPSEEK_MODEL')
    deepseek_vision_model: str = Field(default='deepseek-flash', alias='DEEPSEEK_VISION_MODEL')


def get_recognition_settings():
    return get_settings() if get_settings.cache_info().currsize else RecognitionSettings()


class SpeechSettings(BaseSettings):
    model_config = DatabaseSettings.model_config
    assemblyai_api_key: str = Field(default='', validation_alias=AliasChoices('ASSEMBLYAI_API_KEY', 'ASSAMBLY'))


def get_speech_settings():
    return get_settings() if get_settings.cache_info().currsize else SpeechSettings()
