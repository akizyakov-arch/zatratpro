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
