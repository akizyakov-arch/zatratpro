# ZATRATPRO

MVP Telegram-бота для распознавания чеков, актов и накладных.

## Что умеет каркас

- запускает Telegram-бота на `aiogram`
- обрабатывает `/start` и `/help`
- принимает фото
- скачивает файл во временную папку `tmp/`
- отправляет фото в OCR.Space
- передает OCR-текст в DeepSeek
- валидирует JSON по контракту документа

## Требования

- WSL2 Ubuntu
- Python 3.11+
- Telegram Bot Token
- OCR.Space API key
- DeepSeek API key

## Быстрый старт

```bash
cd ~/DEVV/ZATRATPRO
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.main
```

## Telegram Proxy

Если есть проблемы с маршрутом до Telegram API или Telegram CDN, бот можно запустить через SOCKS5-прокси только для Telegram-трафика.

Пример `.env`:

```env
TELEGRAM_PROXY_ENABLED=true
TELEGRAM_PROXY_URL=socks5://user:password@1.2.3.4:1080
```

Через этот прокси идет только Telegram-трафик aiogram:
- long polling
- Bot API запросы
- `getFile`
- скачивание файлов через Telegram

OCR.Space, DeepSeek и Postgres через этот proxy не идут.

## Структура

```text
app/
  handlers/
  prompts/
  schemas/
  services/
tmp/
tests/
```
