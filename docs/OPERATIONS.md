# FIINOPS: запуск и сопровождение

Версия 1.0 · 28.10.2026 · срез `69c2842`. Команды выполняются из корня выбранного
checkout. Ниже имя Compose-проекта `fiinops`; для существующей установки используйте
её прежнее имя. Это инструкция, не отчёт о выполненном развёртывании.

## 1. Состав установки

| Профиль | Сервисы | Примечание |
|---|---|---|
| Только Telegram | zatratpro-db + zatratpro-bot | Основной Compose, запуск явных сервисов |
| Telegram и MAX | База + bot + zatratpro-max | 3 контейнера, с max-dev override |
| С панелью | Дополнительно zatratpro-web | HTTP на 127.0.0.1:8080 по базовому Compose |
| Публичная панель | Дополнительно caddy | HTTPS override, домен и доступные 80/443 |

Отдельного контейнера ядра/OCR-worker нет. Все адаптеры используют одну БД и
совместимую версию схемы. `docker compose up` без списка сервисов основного
файла запускает также веб-панель: это уже не профиль из трёх контейнеров.

Требуются Linux VPS с Docker Engine/Compose v2, доступом к используемым API,
диском для PostgreSQL и резервных копий. Debian 13 подходит как Docker-хост;
Python приложения работает внутри образа `python:3.12-slim`. Windows/Android
могут быть клиентами веба/мессенджеров; Docker-хост не обязан быть тем же устройством.
Аппаратный минимум под конкретную нагрузку не измерен; PDF/OCR, RAM и размер
БД нужно учитывать при подборе VPS. Подтверждённых нормативов CPU/RAM/RPO/RTO нет.

## 2. Переменные окружения

Исходные примеры: [`.env.example`](../.env.example) и
[`.env.production.example`](../.env.production.example). Храните рабочий `.env`
локально с ограниченным доступом. Не копируйте его содержимое в документацию,
коммиты, PR или диагностические сообщения.

| Группа | Переменные | Для чего |
|---|---|---|
| PostgreSQL | POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT | Одно соединение с общей БД; внутри Compose host `zatratpro-db`, port `5432` |
| Telegram | TELEGRAM_BOT_TOKEN | Токен Bot API; облачное имя секрета TOKEN не является именем настройки Python |
| Владелец | BOT_OWNER_TELEGRAM_ID | Положительный Telegram ID действующего owner; не ID бота |
| Telegram proxy | TELEGRAM_PROXY_URL | Пусто либо URL HTTP/SOCKS5; MTProxy не подходит |
| OCR.space proxy | OCR_SPACE_PROXY_URL | Полный HTTP/SOCKS5 URL; отдельно от Telegram, см. OCR_DIAGNOSTICS |
| MAX | MAX_BOT_TOKEN, MAX_CA_BUNDLE | MAX-токен; дополнительный PEM CA необязателен |
| Ссылка на Telegram | TELEGRAM_BOT_USERNAME | Имя без @ для ссылок привязки из MAX |
| OCR/LLM | OCR_SPACE_API_KEY, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, DEEPSEEK_VISION_MODEL | Распознавание и структура/вопросы; выберите актуальные модели |
| Голос | ASSEMBLYAI_API_KEY | Также поддержано имя ASSAMBLY; без ключа голос недоступен |
| HTTP | WEB_HOST, WEB_PORT, WEB_ORIGIN, WEB_ALLOWED_HOSTS, WEB_COOKIE_SECURE, WEB_TRUSTED_PROXIES | Адреса, cookies, доверие reverse proxy |
| Веб-вход | WEB_BOT_USERNAME | Telegram-бот, в котором подтверждается браузерный вход |
| Mini App | WEB_MINI_APP_ENABLED, WEB_TELEGRAM_BOT_ID | Включение и числовой ID Telegram-бота |
| HTTPS Compose | WEB_DOMAIN, FIINOPS_PROXY_SUBNET, FIINOPS_PROXY_IP, FIINOPS_WEB_IP | Домен и Docker-сеть Caddy; см. DEPLOYMENT |
| Логи | LOG_LEVEL | Уровень диагностики |

Для MAX-финансов без OCR достаточно его токена и БД; политика owner дополнительно
зависит от BOT_OWNER_TELEGRAM_ID. Для OCR MAX нужны ключи провайдеров, но не
Telegram-токен. Браузерный вход можно подтвердить через Telegram или MAX; см. [MAX_WEB_LOGIN](MAX_WEB_LOGIN.md).
Секреты разных платформ не взаимозаменяемы.

## 3. Новая пустая установка

Подготовьте `.env` с действительными значениями и нужный checkout. Для примера
двух ботов:

```bash
docker compose -p fiinops -f docker-compose.yml -f docker-compose.max-dev.yml build zatratpro-bot zatratpro-max
docker compose -p fiinops -f docker-compose.yml -f docker-compose.max-dev.yml up -d zatratpro-bot zatratpro-max
```

Зависимость запускает БД, применяет исходную схему через docker-entrypoint-initdb.d,
а приложение — миграции. Init SQL выполняется только для нового тома. Указание
нового Compose project name или каталога без прежнего имени может создать другой
пустой том: это не перенос существующих данных.

MAX здесь работает только в тестовом Long Polling. Production Webhook ещё не
реализован; домен/Caddy панели сами по себе не включают Webhook MAX.

## 4. Проверка внешних соединений

Проверка MAX без запуска второго poller:

```bash
docker compose -p fiinops -f docker-compose.yml -f docker-compose.max-dev.yml run --rm --no-deps zatratpro-max python -m app.max_bot --check
```

`--check` проверяет авторизацию и подписки. Если подписки существуют, poll-dev
их не удаляет и отказывается запускаться. Для одного токена не запускайте
одновременно старый и новый polling в разных окружениях.

Если Telegram недоступен, настройте `TELEGRAM_PROXY_URL` и пересоздайте контейнер.
Простой restart не перечитывает `.env`. Если MAX сообщает о TLS, проверьте
официальный `platform-api2.max.ru`, доверенный CA и сетевой доступ; не отключайте
проверку сертификата и не подменяйте API2 старым адресом.

## 5. Обновление существующей базы

Сначала выберите нужную проверенную ветку/коммит. Не подменяйте рабочий `.env`.
Сборка выполняется до остановки ботов. Пример для двух ботов:

```bash
(
set -e
COMPOSE_PROJECT_NAME=fiinops python3 scripts/backup_database.py
docker compose -p fiinops -f docker-compose.yml -f docker-compose.max-dev.yml build zatratpro-bot zatratpro-max
docker compose -p fiinops -f docker-compose.yml -f docker-compose.max-dev.yml stop zatratpro-bot zatratpro-max
docker compose -p fiinops -f docker-compose.yml -f docker-compose.max-dev.yml up -d --no-deps --force-recreate zatratpro-bot zatratpro-max
)
```

Миграция 024 переводит оставшийся ввод возвратов, решений и карт на внутренний
actor_id; старые писатели этой таблицы несовместимы с новой схемой. Требуются
backup и согласованное обновление ботов/панели.
[Архитектурные требования](CORE_BOUNDARY_REQUIREMENTS.md).

Миграция 023 объединяет черновики администрирования и выдачи Telegram/MAX.
Требует согласованного обновления всех адаптеров; подробности —
[APPLICATION_CORE.md](APPLICATION_CORE.md).

Миграция 022 переводит владельца черновика с внешнего Telegram ID на actor_id.
Все процессы, работающие с изменяемой схемой, обновляются согласованно. Если
панель тоже работает, включите её в сборку/остановку/запуск подходящим Compose-
профилем. Автоматическая блокировка миграций не делает старый код совместимым
с новой схемой. Не используйте `down -v` для обычного обновления.

## 6. Веб-панель и HTTPS

Локальный процесс панели добавляется командой:

```bash
docker compose -p fiinops up -d --build zatratpro-web
```

Базовый bind — loopback 127.0.0.1:8080. Для внешней работы используйте
[DEPLOYMENT.md](DEPLOYMENT.md): HTTPS override, Caddy, DNS и корректные WEB_*
значения. Проверка конфигурации:

```bash
python3 scripts/check_deployment.py --env-file .env
```

Скрипт ориентирован на полный HTTPS-профиль и проверяет также его обязательные
секреты/параметры. Он не является универсальной проверкой минимального MAX-only
запуска. Адрес WEB_ORIGIN должен совпадать с внешним HTTPS origin панели.

`GET /healthz` возвращает статус HTTP-приложения. Он не выполняет отдельный SQL
запрос и не подтверждает доступность OCR/мессенджеров. Показатели БД проверяйте
её healthcheck, логами подключения и безопасными прикладными запросами.

## 7. Резервное копирование и восстановление

`backup_database.py` делает `pg_dump -Fc` работающей существующей Compose-БД,
создаёт закрытый dump и проверяет его через `pg_restore --list`. Он не запускает
новую БД вместо отсутствующей. При использовании иного project name обязательно
задайте COMPOSE_PROJECT_NAME, иначе скрипт может не найти сервис.

Проверка списка архива не заменяет тестовое восстановление. Для приёмки backup
нужно на отдельном стенде восстановить БД, проверить миграции/роли, контрольные
суммы отчётов и согласованную версию приложения. Регулярное расписание, вынос
копий с VPS и срок хранения настраиваются оператором; в коде нет подтверждения,
что они настроены у конкретной установки.

Восстановление рабочей БД — отдельная операция с остановкой писателей и
проверенным dump. Откат к старому коду после миграции может требовать восстановления
согласованной копии БД; обратных SQL-миграций для произвольного downgrade нет.

## 8. Диагностика

```bash
docker compose -p fiinops -f docker-compose.yml -f docker-compose.max-dev.yml ps
docker compose -p fiinops -f docker-compose.yml -f docker-compose.max-dev.yml logs --tail=80 zatratpro-bot zatratpro-max
```

| Симптом | Что проверить |
|---|---|
| Telegram не отвечает | Нужный бот/токен, доступ API/proxy, второй poller, логи запуска |
| MAX не отвечает | MAX_CA_BUNDLE/CA, API2, подписки, единственный poller, режим запуска |
| Код не подходит | Приглашение или привязка; срок; повторный выпуск; та же БД и тот же профиль |
| Компания недоступна | Активность компании/членства, текущая роль, подтверждение привязки |
| PDF отклонён | Размер/число страниц, подпись диапазона, пароль/повреждение PDF |
| OCR завис/прервался | Тайм-ауты и провайдер, готов ли черновик; после сбоя посреди OCR нужен новый исходник |
| Расход есть, остаток не изменился | Документ включён в затраты, но ещё не привязан к полученным деньгам/источнику |
| Отчёт не совпал | Период UTC, дата загрузки/документа, статусы денег, валюта, архивные проекты, дубли |
| После обновления старые кнопки | Открыть главное меню заново; уже отправленные сообщения не переписываются |

Логи не должны содержать токены, signed URL, документы или аудио. Перед передачей
журнала проверьте его на секреты; не публикуйте `.env` и полный ответ внешнего API.

## 9. Проверки кода

В контейнерном релизе тесты не копируются в Docker-образ. Запускайте их в checkout
с установленными зависимостями и отдельно доступной тестовой PostgreSQL:

```bash
python -m unittest discover -s tests -p 'test_unit.py' -v
RUN_DATABASE_TESTS=1 python -m unittest discover -s tests -v
```

POSTGRES_* тестового окружения должны быть заданы явно. Пользователю БД нужно
CREATEDB: fixture создаёт отдельные базы. Не выдавайте рабочему приложению CREATEDB
только ради тестов. Без RUN_DATABASE_TESTS=1 интеграционные тесты пропускаются;
код выхода 0 с пропусками не доказывает проверку денежных сценариев.

После рефакторинга общих команд полный прогон содержал 393 успешных теста. Промышленная приёмка
дополнительно включает реальный скан/PDF, живой Telegram/MAX, получение/возврат,
сверку отчёта и XLSX, восстановление backup и проверку доступа с чужого аккаунта.
