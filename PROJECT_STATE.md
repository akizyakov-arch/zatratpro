# PROJECT_STATE

## Project
ZATRATPRO

MVP Telegram-бот для распознавания чеков, актов и накладных с дальнейшей привязкой к проектам и последующим сохранением структурированных затрат.

## Current State
Текущая рабочая версия развернута на VPS в Docker.

Что уже работает:
- Telegram-бот принимает фото документа
- бот скачивает файл из Telegram
- изображение отправляется в OCR.Space
- OCR.Space возвращает текст
- текст отправляется в DeepSeek на нормализацию
- пользователю показывается короткая нормализованная выжимка документа
- после нормализации бот показывает проекты кнопками
- пользователь выбирает проект
- только после выбора проекта бот собирает JSON
- документ сохраняется в Postgres

Что сознательно отключено на текущем этапе:
- ручной ввод затрат
- роли и доступы
- админка

## Current User Flow
1. Пользователь отправляет фото документа.
2. Бот делает OCR.
3. Бот нормализует документ через DeepSeek.
4. Бот показывает пользователю краткую выжимку документа.
5. Бот показывает список проектов.
6. Пользователь выбирает проект.
7. Только после выбора проекта бот собирает JSON.
8. Бот сохраняет документ в БД.

## Output Format
Сейчас пользователю показывается не сырой OCR и не полный технический текст, а короткое представление документа в виде:
- тип документа
- номер
- дата
- поставщик
- ИНН/КПП
- состав документа
- итог

Пример формата:

```text
КАССОВЫЙ ЧЕК
Номер: 2894
Дата: 2025-07-17 14:02

Поставщик: ИП КИЗЯКОВ А.А
ИНН: 614006162237

Состав документа:
Сертификат — 1.00 шт × 2600.00 ₽ = 2600.00 ₽

Итого: 2600.00 ₽
```

## OCR
OCR провайдер: OCR.Space

Текущие параметры OCR:
- language: `rus`
- OCREngine: `2`

## DeepSeek
DeepSeek сейчас используется только для нормализации OCR-текста в читаемую выжимку документа.

JSON-экстракция не удалена из кода полностью, но в текущем рабочем сценарии вызывается только после выбора проекта.

## Currency Display
Красивое отображение валют уже поддержано в preview:
- RUB -> ₽
- USD -> $
- EUR -> €

Единица измерения в preview пока фиксирована как `шт`.

## Document Types
Сейчас в логике предусмотрены типы:
- `receipt`
- `invoice`
- `act`
- `manual_expense` — зарезервирован под ручной ввод

Распознавание типа усилено правилами:
- чек -> `receipt`
- накладная / товарная накладная / ТОРГ-12 / УПД -> `invoice`
- акт / акт выполненных работ / акт оказанных услуг -> `act`

## Source Types
Отдельно от `document_type` должен храниться `source_type` — способ попадания документа в систему:
- `photo`
- `pdf`
- `excel`
- `word`
- `manual`

Принцип:
- `document_type` отвечает за бизнес-сущность документа
- `source_type` отвечает за канал загрузки или ввода

## Deployment
Рабочий сервер:
- VPS
- Ubuntu
- Docker Compose
- каталог проекта: `/root/zatratpro`

Обновление сервера идет через:
1. `git push origin main`
2. `git pull origin main`
3. `docker compose up -d --build`

## Git State
Важные точки:
- `v0.1.0` — первая рабочая серверная версия
- `v0.2.0` — ускоренный flow
- `v0.2.1` — flow, где сначала идет нормализация текста, а JSON откладывается до выбора проекта
- `v0.2.2` — меню добавлено локально, но не попало в релиз
- `v0.2.3` — релиз с главным меню
- `v0.3.0` — выбор проекта, Postgres и сохранение документов

## Key Files
Основные файлы, которые стоит подгружать в новый чат:
- `TZ.txt`
- `PROJECT_STATE.md`
- `README.md`
- `app/handlers/documents.py`
- `app/services/ocr_space.py`
- `app/services/deepseek.py`
- `app/services/json_formatter.py`
- `app/services/documents.py`
- `app/services/projects.py`
- `app/schemas/document.py`
- `app/prompts/cleanup_prompt.py`
- `app/prompts/extraction_prompt.py`
- `docker-compose.yml`
- `Dockerfile`
- `db/init/001_init.sql`

## Next Product Steps
Ближайшая продуктовая декомпозиция:
- полноценная prod-структура БД
- компании и участники компаний
- приглашения пользователей в компанию
- хранение позиций документов
- ручной ввод затрат
- учетная логика руководителя
- допуск к боту
- создание и архивирование проектов
- отчеты по затратам
- выдача наличных
- переводы

## Recommended Implementation Order
1. Полноценная prod-структура БД
2. Компании
3. Участники компаний и роли
4. Приглашения в компанию
5. Позиции документов
6. Ручной ввод

## Target Prod Database
Целевая структура БД должна сразу быть рассчитана на несколько независимых бизнесов в одном боте.

### Core Tables
- `users`
- `companies`
- `company_members`
- `company_invites`
- `projects`
- `documents`
- `document_items`

### users
Глобальные пользователи Telegram-бота.

Минимальные поля:
- `id`
- `telegram_user_id`
- `username`
- `full_name`
- `platform_role`
- `is_active`
- `created_at`

`platform_role`:
- `owner`
- `support`
- `user`

### companies
Независимые бизнесы внутри одного бота.

Минимальные поля:
- `id`
- `name`
- `slug`
- `is_active`
- `created_at`

### company_members
Связь пользователя с компанией.

Минимальные поля:
- `id`
- `company_id`
- `user_id`
- `role`
- `is_active`
- `invited_by_user_id`
- `joined_at`
- `created_at`

Ограничение:
- `unique(company_id, user_id)`

`role`:
- `manager`\r\n- `employee`

### company_invites
Приглашения пользователей в компанию.

Минимальные поля:
- `id`
- `company_id`
- `code`
- `role`
- `created_by_user_id`
- `used_by_user_id`
- `expires_at`
- `used_at`
- `is_active`
- `created_at`

### projects
Проекты компании.

Минимальные поля:
- `id`
- `company_id`
- `name`
- `is_archived`
- `created_by_user_id`
- `created_at`

### documents
Шапка документа.

Минимальные поля:
- `id`
- `company_id`
- `project_id`
- `user_id`
- `document_type`
- `source_type`
- `external_document_number`
- `incoming_number`
- `vendor`
- `vendor_inn`
- `vendor_kpp`
- `document_date`
- `currency`
- `total`
- `raw_text`
- `normalized_text`
- `structured_json`
- `created_at`

### document_items
Позиции документа.

Минимальные поля:
- `id`
- `document_id`
- `name`
- `quantity`
- `price`
- `line_total`
- `created_at`

### Key Relations
- `users -> company_members` = один ко многим
- `companies -> company_members` = один ко многим
- `companies -> projects` = один ко многим
- `companies -> documents` = один ко многим
- `projects -> documents` = один ко многим
- `users -> documents` = один ко многим
- `documents -> document_items` = один ко многим

### Access Model
- владелец бота — это глобальная роль `platform_role = owner`
- админ компании приглашает пользователей в свою компанию
- пользователь видит только те компании, где он состоит
- все проекты и документы фильтруются по `company_id`

## Architectural Direction
Правильное следующее направление:
- распознавание документа отделено от бизнес-контекста проекта
- сначала бот понимает документ
- затем определяется `document_type`
- отдельно хранится `source_type`
- потом пользователь выбирает проект
- затем строится JSON под запись в БД
- проверка на дубли в БД
- затем добавляются бизнес-сущности: компании, участники компаний, роли, приглашения, проекты, отчеты, движения денег

## Important Note For Next Chat
Для продолжения не нужно поднимать старые технические обсуждения про локальные сетевые проблемы, WSL-прокси и временные обходы. Актуальная рабочая точка — VPS версия в Docker, текущий продуктовый pipeline и целевая prod-структура БД, описанные в этом файле.

