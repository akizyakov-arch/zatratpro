from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
TMP_DIR = BASE_DIR / 'tmp'
STORAGE_DIR = BASE_DIR / 'storage'


class Settings(BaseSettings):
    telegram_bot_token: str = Field(alias='TELEGRAM_BOT_TOKEN')
    telegram_proxy_enabled: bool = Field(default=False, alias='TELEGRAM_PROXY_ENABLED')
    telegram_proxy_url: str | None = Field(default=None, alias='TELEGRAM_PROXY_URL')
    ocr_space_api_key: str = Field(alias='OCR_SPACE_API_KEY')
    deepseek_api_key: str = Field(alias='DEEPSEEK_API_KEY')
    deepseek_base_url: str = Field(default='https://api.deepseek.com', alias='DEEPSEEK_BASE_URL')
    deepseek_model: str = Field(default='deepseek-chat', alias='DEEPSEEK_MODEL')
    log_level: str = Field(default='INFO', alias='LOG_LEVEL')
    postgres_db: str = Field(default='zatratpro', alias='POSTGRES_DB')
    postgres_user: str = Field(default='zatratpro', alias='POSTGRES_USER')
    postgres_password: str = Field(default='change_me', alias='POSTGRES_PASSWORD')
    postgres_host: str = Field(default='zatratpro-db', alias='POSTGRES_HOST')
    postgres_port: int = Field(default=5432, alias='POSTGRES_PORT')
    bot_owner_telegram_id: int = Field(default=0, alias='BOT_OWNER_TELEGRAM_ID')
    document_storage_root: Path = Field(default=STORAGE_DIR, alias='DOCUMENT_STORAGE_ROOT')
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, alias='MAX_UPLOAD_BYTES')

    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', case_sensitive=False, extra='ignore')

    @property
    def postgres_dsn(self) -> str:
        return f'postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}'


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    settings.document_storage_root.mkdir(parents=True, exist_ok=True)
    return settings
