from functools import lru_cache
import os
import logging
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
TMP_DIR = BASE_DIR / 'tmp'
STORAGE_DIR = BASE_DIR / 'storage'

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    telegram_bot_token: str = Field(alias='TELEGRAM_BOT_TOKEN')
    telegram_proxy_enabled: bool = Field(default=False, alias='TELEGRAM_PROXY_ENABLED')
    telegram_proxy_url: str | None = Field(default=None, alias='TELEGRAM_PROXY_URL')
    ocr_space_api_key: str = Field(alias='OCR_SPACE_API_KEY')
    deepseek_api_key: str = Field(alias='DEEPSEEK_API_KEY')
    deepseek_base_url: str = Field(default='https://api.deepseek.com', alias='DEEPSEEK_BASE_URL')
    deepseek_model: str = Field(default='deepseek-chat', alias='DEEPSEEK_MODEL')
    deepseek_proxy_url: str | None = Field(default=None, alias='DEEPSEEK_PROXY_URL')
    deepseek_connect_timeout: float = Field(default=15.0, alias='DEEPSEEK_CONNECT_TIMEOUT')
    deepseek_read_timeout: float = Field(default=60.0, alias='DEEPSEEK_READ_TIMEOUT')
    deepseek_max_retries: int = Field(default=1, alias='DEEPSEEK_MAX_RETRIES')
    log_level: str = Field(default='INFO', alias='LOG_LEVEL')
    postgres_db: str = Field(default='zatratpro', alias='POSTGRES_DB')
    postgres_user: str = Field(default='zatratpro', alias='POSTGRES_USER')
    postgres_password: str = Field(default='change_me', alias='POSTGRES_PASSWORD')
    postgres_host: str = Field(default='zatratpro-db', alias='POSTGRES_HOST')
    postgres_port: int = Field(default=5432, alias='POSTGRES_PORT')
    bot_owner_telegram_id: int = Field(default=0, alias='BOT_OWNER_TELEGRAM_ID')
    document_storage_root: Path = Field(default=STORAGE_DIR, alias='DOCUMENT_STORAGE_ROOT')
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, alias='MAX_UPLOAD_BYTES')
    document_extraction_strategy: str = Field(default='generic', alias='DOCUMENT_EXTRACTION_STRATEGY')

    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', case_sensitive=False, extra='ignore')

    @property
    def postgres_dsn(self) -> str:
        return f'postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}'

    @property
    def effective_deepseek_proxy_url(self) -> str | None:
        if self.deepseek_proxy_url:
            return self.deepseek_proxy_url
        if self.telegram_proxy_enabled and self.telegram_proxy_url:
            return self.telegram_proxy_url
        return None


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    settings.document_storage_root.mkdir(parents=True, exist_ok=True)

    host_tmp_dir = os.getenv('HOST_TMP_DIR', '').strip()
    host_storage_dir = os.getenv('HOST_STORAGE_DIR', '').strip()

    if not host_tmp_dir and TMP_DIR.resolve() == (BASE_DIR / 'tmp').resolve():
        logger.warning(
            'TMP_DIR is using repo-local fallback path: %s. Configure HOST_TMP_DIR mount for safer runtime storage.',
            TMP_DIR,
        )
    if not host_storage_dir and settings.document_storage_root.resolve() == STORAGE_DIR.resolve():
        logger.warning(
            'DOCUMENT_STORAGE_ROOT is using repo-local fallback path: %s. Configure DOCUMENT_STORAGE_ROOT or HOST_STORAGE_DIR for safer persistent storage.',
            settings.document_storage_root,
        )

    return settings
