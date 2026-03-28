# Техническое задание ZATRATPRO v0.5.8.18

## 1. Назначение документа

Документ фиксирует актуальное состояние продукта ZATRATPRO на версии `v0.5.8.18` и предназначен как рабочее ТЗ для дальнейшей разработки.

Документ нужен, чтобы:
- зафиксировать текущий функциональный объем по коду;
- зафиксировать архитектурные границы, которые уже считаются принятыми;
- не ломать рабочие beta-сценарии при дальнейшем развитии продукта.

Главный принцип: развивать текущую архитектуру без переписывания работающих flow с нуля.

## 2. Продукт

ZATRATPRO — Telegram-first система учета затрат по первичным документам внутри компании.

Продукт решает задачи:
- прием фото, image-файлов и PDF документов;
- OCR и извлечение структуры документа;
- привязка документа к проекту;
- хранение нормализованного исходного source-файла;
- просмотр документов в Telegram;
- manager-отчеты и Excel-выгрузки;
- архивные бухгалтерские выгрузки;
- поиск точных и вероятных дублей;
- резервное копирование базы и файлов.

Продукт не является бухгалтерской системой, но поддерживает контур сбора подтверждающих расходных документов для управленческого учета и дальнейшей работы с расходами при УСН `доходы минус расходы`.

## 3. Текущий статус

Версия `v0.5.8.18` — рабочее beta-состояние.

На этой версии стабилизированы:
- photo / image / PDF upload flow;
- OCR + extraction flow;
- duplicate check flow;
- pending preview/save flow;
- source-file storage flow;
- manager reports and Excel export;
- accountant ZIP export с manifest;
- temp-file cleanup;
- backup / restore contour;
- document-processing service boundary.

## 4. Поддерживаемые документы

Допустимые типы документов:
- товарная накладная;
- акт;
- УПД;
- счет-фактура;
- кассовый чек;
- БСО;
- транспортная накладная;
- расходный кассовый ордер.

Поддерживаемые входные форматы:
- фото из Telegram;
- image-файлы: JPG, JPEG, PNG, WEBP, HEIC, HEIF;
- PDF.

Семантически неподдерживаемые документы, которые должны отклоняться:
- гостевой счет;
- счет гостя;
- предчек;
- счет на оплату;
- прочие документы, не являющиеся подтверждающими расходными первичными документами.

## 5. Основные пользовательские сценарии

### 5.1 Сотрудник / manager загружает документ
1. Пользователь отправляет фото, image-файл или PDF в бот.
2. Бот подготавливает временный OCR input.
3. Выполняется OCR.
4. Выполняется extraction структурированного документа.
5. Если документ неподдерживаемый, бот останавливает flow и показывает причину.
6. Если документ поддерживаемый, бот показывает preview.
7. Пользователь выбирает проект.
8. Выполняется duplicate check.
9. Документ либо сохраняется сразу, либо показывается duplicate warning.
10. После подтверждения документ сохраняется.

### 5.2 Manager работает с документами и отчетами
- просматривает документы компании;
- открывает исходный source-файл;
- фильтрует документы;
- получает manager dashboard и registry в Excel;
- получает бухгалтерский ZIP-архив с manifest.

### 5.3 Система обслуживает хранение и резервирование
- source-файлы хранятся в `storage/`;
- temp-файлы живут в `tmp/` и очищаются автоматически;
- база и storage резервируются через host-side scripts.

## 6. Роли

### 6.1 Owner
- системный владелец платформы;
- создает компании;
- назначает первых manager;
- управляет системным контуром.

### 6.2 Manager
- управляет проектами;
- приглашает сотрудников;
- блокирует и разблокирует сотрудников;
- загружает документы;
- просматривает документы компании;
- запускает отчеты и выгрузки;
- контролирует дубли.

### 6.3 Employee
- загружает документы;
- выбирает проект для документа;
- просматривает свои документы;
- открывает свои source-файлы.

## 7. Функциональный объем версии v0.5.8.18

### 7.1 Document intake
- photo upload;
- image-file upload;
- PDF upload;
- лимит размера upload;
- ранний reject неподдерживаемых file formats.

### 7.2 OCR / extraction
- OCR.Space;
- DeepSeek extraction;
- поддержка НДС-полей;
- поддержка признака фискализации;
- консервативное извлечение табличных документов;
- mixed VAT detection для чеков;
- semantic unsupported-document gate.

### 7.3 Save / duplicate / preview
- preview перед сохранением;
- pending state;
- duplicate check: exact / probable / none / not_checked;
- duplicate warning с подтверждением;
- immediate save при отсутствии конфликтующей ветки.

### 7.4 Storage
- нормализованный source-файл документа;
- открытие source-файла из Telegram;
- стабильное хранение по storage path;
- отдельный temp cleanup layer.

### 7.5 Reports / export
- manager dashboard;
- manager registry;
- VAT-поля в preview и отчетах;
- accountant ZIP export;
- manifest со ссылками и полями по документам.

### 7.6 Ops
- backup script;
- restore script;
- bootstrap VPS script;
- cron + rclone backup contour.

## 8. Текущая архитектурная граница

### 8.1 handlers/documents.py
Handler-слой отвечает только за:
- Telegram entry points;
- callback parsing;
- access checks;
- upload type / size checks;
- UI-сообщения;
- клавиатуры.

### 8.2 app/services/document_processing.py
Service-слой orchestrate-ит:
- OCR pipeline;
- extraction pipeline;
- preview preparation;
- pending preview state;
- duplicate-check при выборе проекта;
- immediate save или duplicate-warning;
- duplicate-confirm save;
- semantic reject неподходящих документов.

### 8.3 app/services/temp_files.py
Единый temp cleanup utility:
- `safe_unlink(...)`;
- `temporary_files(...)`.

## 9. Бизнес-ограничения

- один активный company membership на пользователя;
- один активный manager на компанию;
- документы всегда принадлежат компании и проекту;
- employee видит только свои документы;
- manager видит документы своей компании;
- blocked-участник не работает в company-flow, но история и документы сохраняются;
- storage-файлы не должны удаляться temp cleanup utility;
- user flow не должен зависеть от ручной чистки `tmp/`.

## 10. Технологический стек

Backend:
- Python 3.12
- aiogram 3
- asyncpg
- PostgreSQL 16
- httpx
- Pillow
- openpyxl

Инфраструктура:
- Docker Compose
- VPS deployment
- PostgreSQL в отдельном контейнере
- persistent storage на хосте
- cron + backup scripts
- rclone

Внешние интеграции:
- Telegram Bot API
- OCR.Space
- DeepSeek API

## 11. Нефункциональные требования

- не ломать beta user flow;
- temp cleanup должен быть детерминированным;
- source-файлы в `storage/` не должны теряться;
- document handlers не должны снова становиться центром orchestration;
- новые ветки document flow должны добавляться через service layer;
- unsupported-документы должны отрезаться до preview/save.

## 12. Ближайшие приоритеты после v0.5.8.18

1. Routing по типам документов с разными prompt-ветками.
2. Оптимизация OCR / extraction latency.
3. Расширение semantic reject правил.
4. Минимальный regression-smoke набор для document flow.
5. Подготовка transport layer к будущим каналам кроме Telegram.
