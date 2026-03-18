# ZATRATPRO

Telegram-first SaaS для учета затрат: OCR, DeepSeek, компании, проекты, invite onboarding и сохранение документов в Postgres.

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
- Telegram Bot Username
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

## Onboarding

- manager и employee могут входить по deep link `https://t.me/<bot_username>?start=invite_<token>`
- fallback через ручной `/join КОД` сохранен

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
