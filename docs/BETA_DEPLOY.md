# Beta Deploy

Короткая инструкция для разворачивания beta-сервера ZATRATPRO в любой директории на новом VPS.

## Что важно

- проект не привязан к пути вида `/home/kizz/...` или `D:\...`
- директория проекта может быть любой
- runtime-данные теперь можно и нужно держать вне git-репозитория
- по умолчанию deploy-скрипты используют внешний runtime root:
  - `/srv/<имя_проекта>/storage`
  - `/srv/<имя_проекта>/tmp`
  - `/srv/<имя_проекта>/backups`
- внутри контейнеров пути остаются стабильными:
  - `/app/storage`
  - `/app/tmp`
  - `/backups`

## Предпосылки

- Ubuntu VPS
- Docker
- Docker Compose
- Git
- домен не обязателен, бот работает через long polling

## Рекомендуемая структура

```bash
/opt/zatratpro
```

И внешний runtime root:

```bash
/srv/zatratpro
```

Можно использовать и другую директорию, например:

```bash
~/zatratpro-beta
```

Тогда runtime root по умолчанию будет:

```bash
/srv/zatratpro-beta
```

## Скрипты и их роли

- `scripts/bootstrap_vps.sh`
  - первичный bootstrap нового VPS
  - ставит базовые пакеты, Docker, cron, rclone
  - клонирует repo
  - создает внешние runtime-каталоги
  - дописывает `HOST_*` в `.env`, если их еще нет
  - ставит backup cron
  - запускает `docker compose up -d --build`
- `scripts/deploy_remote.sh`
  - удаленный deploy по SSH с рабочей машины
  - заливает `.env`
  - обновляет ветку или тег на сервере
  - создает внешние runtime-каталоги
  - дописывает `HOST_*` в `.env`, если их еще нет
  - запускает `docker compose up -d --build`
- `scripts/backup_zatratpro.sh`
  - делает `pg_dump`
  - архивирует storage
  - использует `HOST_STORAGE_DIR` и `HOST_BACKUPS_DIR` из `.env`
  - хранит локально только последние `2` backup-файла каждого типа
  - умеет upload через `RCLONE_REMOTE`
- `scripts/restore_zatratpro.sh`
  - восстанавливает БД и storage из backup
  - использует внешние пути из `.env`
  - теперь требует явный выбор:
    - `--keep-old-storage`
    - `--replace-storage`

## Первичное развертывание

Есть 2 варианта.

### Вариант 1. Полуавтоматический bootstrap на самом VPS

В репозитории есть bootstrap-скрипт:

```bash
scripts/bootstrap_vps.sh
```

Он выполняется прямо на VPS и делает:

- установку `git`, `cron`, `curl`, `gnupg`
- установку Docker и `docker compose plugin`
- включение `docker` и `cron`
- клонирование репозитория
- переключение на нужную ветку или тег
- создание внешних runtime-каталогов
- добавление `HOST_STORAGE_DIR`, `HOST_TMP_DIR`, `HOST_BACKUPS_DIR` в `.env`, если их еще нет
- установку локального backup по cron
- `docker compose up -d --build`

Пример запуска:

```bash
sudo bash scripts/bootstrap_vps.sh \
  --repo-url git@github.com:org/repo.git \
  --project-dir /opt/zatratpro \
  --ref v0.5.8.9 \
  --env-file /root/zatratpro.env \
  --timezone Europe/Moscow \
  --runtime-root /srv/zatratpro
```

Если нужен upload backup через `rclone`, можно добавить:

```bash
--rclone-remote yadisk:zatratpro-backups
```

Важно:

- `.env` должен уже лежать на VPS, например `/root/zatratpro.env`
- bootstrap-скрипт ставит бинарь `rclone`, но сам `remote` не настраивает
- `rclone` remote все равно нужно подготовить отдельно через `rclone config`

### Вариант 2. Ручная подготовка

```bash
git clone <repo_url> /opt/zatratpro
cd /opt/zatratpro
cp .env.example .env
mkdir -p /srv/zatratpro/tmp /srv/zatratpro/storage /srv/zatratpro/backups/db /srv/zatratpro/backups/storage
```

Заполни `.env`:

- `TELEGRAM_BOT_TOKEN`
- `OCR_SPACE_API_KEY`
- `DEEPSEEK_API_KEY`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `BOT_OWNER_TELEGRAM_ID`
- `HOST_STORAGE_DIR=/srv/zatratpro/storage`
- `HOST_TMP_DIR=/srv/zatratpro/tmp`
- `HOST_BACKUPS_DIR=/srv/zatratpro/backups`

Если нужен proxy:

- `TELEGRAM_PROXY_ENABLED`
- `TELEGRAM_PROXY_URL`
- `DEEPSEEK_PROXY_URL` при необходимости отдельного маршрута

## Запуск

```bash
cd /opt/zatratpro
docker compose up -d --build
```

## Проверка

```bash
docker compose ps
docker compose logs --tail=100 zatratpro-bot
docker compose logs --tail=100 zatratpro-db
```

Проверь:

- бот стартовал без traceback
- база поднялась
- созданы внешние runtime-каталоги
- в `.env` есть `HOST_STORAGE_DIR`, `HOST_TMP_DIR`, `HOST_BACKUPS_DIR`

## Обновление beta-сервера

```bash
cd /opt/zatratpro
git fetch origin
git checkout restore-v056
git pull origin restore-v056
docker compose up -d --build
```

Если нужен конкретный релиз:

```bash
cd /opt/zatratpro
git fetch origin --tags
git checkout v0.5.8.9
docker compose up -d --build
```

## Автодеплой по SSH

В репозитории есть helper-скрипт:

```bash
scripts/deploy_remote.sh
```

Он умеет:

- проверить SSH-доступ
- загрузить локальный `.env` на сервер
- клонировать репозиторий, если его еще нет
- переключить сервер на нужную ветку или тег
- создать внешние runtime-каталоги
- дописать `HOST_*` в `.env`, если их еще нет
- выполнить `docker compose up -d --build`
- показать `docker compose ps` и хвост логов

Пример деплоя ветки:

```bash
bash scripts/deploy_remote.sh \
  --host 1.2.3.4 \
  --user root \
  --key ~/.ssh/id_ed25519 \
  --remote-dir /opt/zatratpro \
  --ref restore-v056 \
  --env-file .env.beta \
  --runtime-root /srv/zatratpro
```

Пример деплоя конкретного релиза:

```bash
bash scripts/deploy_remote.sh \
  --host 1.2.3.4 \
  --user root \
  --key ~/.ssh/id_ed25519 \
  --remote-dir /opt/zatratpro \
  --ref v0.5.8.9 \
  --env-file .env.beta \
  --runtime-root /srv/zatratpro
```

Если локальный `origin` не настроен как надо, можно явно передать:

```bash
--repo-url git@github.com:org/repo.git
```

Скрипт не делает `reset --hard` и не деплоит в грязный remote worktree.

## Backup

Для backup используются:

- Postgres через `pg_dump`
- storage по пути `HOST_STORAGE_DIR` из `.env`

Ручной запуск:

```bash
cd /opt/zatratpro
bash scripts/backup_zatratpro.sh
```

### Backup по расписанию

Рекомендуемый вариант для beta:

- запуск 1 раз в сутки ночью
- например в `03:10`
- время берется по timezone самого сервера

Проверь timezone сервера:

```bash
date
timedatectl
```

Добавить задачу в `cron`:

```bash
crontab -e
```

Пример строки:

```bash
10 3 * * * cd /opt/zatratpro && /bin/bash scripts/backup_zatratpro.sh >> /srv/zatratpro/backups/backup.log 2>&1
```

Если настроен `rclone`, можно запускать сразу с upload:

```bash
10 3 * * * cd /opt/zatratpro && RCLONE_REMOTE="yadisk:zatratpro-backups" /bin/bash scripts/backup_zatratpro.sh >> /srv/zatratpro/backups/backup.log 2>&1
```

Проверка:

```bash
crontab -l
tail -n 100 /srv/zatratpro/backups/backup.log
```

## Что переносимо без изменений пути

- runtime-код приложения
- `app/config.py`
- `docker-compose.yml`
- storage внутри контейнера
- backup/restore scripts

## Что не относится к deploy

Локальные helper-скрипты из рабочей машины разработчика, например `*_wsl.py`, `*_unc.py`, `patch_*.py`, не входят в git-репозиторий продукта и на beta-сервер не нужны.
