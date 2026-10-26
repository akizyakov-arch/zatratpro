"""python -m app.max_bot --check; --poll-dev starts a development poller."""
import argparse
import asyncio
import logging

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import BASE_DIR
from app.logging_utils import RedactingFormatter
from app.max_bot.client import MaxAPIError, MaxClient
from app.max_bot.runner import poll
from app.services.database import close_db, init_db


class MaxSettings(BaseSettings):
    token: SecretStr = Field(alias='MAX_BOT_TOKEN', min_length=1)
    ca_bundle: str | None = Field(default=None, alias='MAX_CA_BUNDLE')
    model_config = SettingsConfigDict(env_file=BASE_DIR / '.env', extra='ignore')


async def run(settings, development):
    async with MaxClient(settings.token.get_secret_value(), ca_bundle=settings.ca_bundle or None) as client:
        me = await client.me()
        subscriptions = await client.subscriptions()
        print(f"MAX: авторизация проверена, bot_id={me['user_id']}; webhook-подписок: {len(subscriptions)}.", flush=True)
        if not development:
            return
        if subscriptions:
            raise RuntimeError('Для этого MAX-бота настроен Webhook. Polling не запущен; подписки не менялись.')
        print('MAX: тестовый Long Polling. Для production требуется Webhook.', flush=True)
        await init_db()
        try:
            await poll(client, me['user_id'])
        finally:
            await close_db()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true')
    group.add_argument('--poll-dev', action='store_true')
    args = parser.parse_args()
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter('%(levelname)s | %(message)s'))
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
    try:
        settings = MaxSettings()
        asyncio.run(run(settings, args.poll_dev))
    except ValidationError:
        print('MAX_BOT_TOKEN не задан в секретах среды или .env. Значение не выводится.')
        return 2
    except (MaxAPIError, RuntimeError) as exc:
        print(str(exc))
        return 1
    except (OSError, ValueError):
        print('Не удалось запустить MAX: проверьте подключение к БД и доверенный CA bundle.')
        return 1
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        # Do not print raw API events, request headers or connection parameters.
        print(f'Не удалось запустить MAX ({type(exc).__name__}). Проверьте настройки и доступ к сервисам.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
