# Backup: Cron + rclone + Yandex Disk

## Что бэкапим

- PostgreSQL через `pg_dump`
- папку `storage/`

Не бэкапим:
- `.env`
- `tmp/`
- контейнеры и docker image
- код приложения

## Что уже есть в проекте

- backup script: `scripts/backup_zatratpro.sh`
- локальные папки backup:
  - `backups/db/`
  - `backups/storage/`
- скрипт оставляет локально только `2` последних backup-файла каждого типа

Ручной запуск:

```bash
cd ~/zatratpro
bash scripts/backup_zatratpro.sh
```

## 1. Проверить cron на VPS

```bash
which cron
which crontab
systemctl status cron
```

Если `cron` не установлен:

```bash
apt update
apt install -y cron
systemctl enable --now cron
```

## 2. Установить rclone на VPS

```bash
curl https://rclone.org/install.sh | sudo bash
rclone version
```

## 3. Настроить remote для Яндекс Диска

Запуск мастера:

```bash
rclone config
```

Шаги:
- `n` — создать новый remote
- имя remote, например: `yadisk`
- storage type: `yandex`
- `client_id`: оставить пустым
- `client_secret`: оставить пустым
- дальше пройти OAuth-авторизацию

Проверка списка remote:

```bash
rclone listremotes
```

Проверка доступа к Яндекс Диску:

```bash
rclone lsd yadisk:
```

## 4. Создать каталоги на Яндекс Диске

```bash
rclone mkdir yadisk:zatratpro-backups/db
rclone mkdir yadisk:zatratpro-backups/storage
```

## 5. Протестировать backup вручную с upload

```bash
cd ~/zatratpro
RCLONE_REMOTE="yadisk:zatratpro-backups" bash scripts/backup_zatratpro.sh
```

Проверить, что файлы появились на Яндекс Диске:

```bash
rclone ls yadisk:zatratpro-backups/db
rclone ls yadisk:zatratpro-backups/storage
```

Проверить локальные файлы:

```bash
ls -lt ~/zatratpro/backups/db
ls -lt ~/zatratpro/backups/storage
```

## 6. Добавить cron-задачу

Открыть crontab:

```bash
crontab -e
```

Рабочая строка для ежедневного backup в `03:10` по времени VPS:

```bash
10 3 * * * cd /root/zatratpro && RCLONE_REMOTE="yadisk:zatratpro-backups" /bin/bash scripts/backup_zatratpro.sh >> /root/zatratpro/backups/backup.log 2>&1
```

Важно:
- сначала идут `минуты`, потом `часы`
- пример `34 22` означает `22:34`
- если проект лежит не в `/root/zatratpro`, замени путь на свой
- если remote называется не `yadisk`, замени имя remote

Проверить установленный cron:

```bash
crontab -l
```

## 7. Быстрый тест cron без ожидания до завтра

Если хочешь проверить сразу, поставь время на ближайшие 2-3 минуты.

Пример для `22:34`:

```bash
34 22 * * * cd /root/zatratpro && RCLONE_REMOTE="yadisk:zatratpro-backups" /bin/bash scripts/backup_zatratpro.sh >> /root/zatratpro/backups/backup.log 2>&1
```

Потом смотреть лог:

```bash
tail -f /root/zatratpro/backups/backup.log
```

После проверки вернуть нормальное ночное расписание.

## 8. Проверить время сервера

`cron` работает по времени VPS.

Проверка:

```bash
date
timedatectl
```

## 9. Что делает backup script

`scripts/backup_zatratpro.sh`:
- делает `pg_dump` из контейнера `zatratpro-db`
- архивирует `storage/`
- оставляет локально только `2` последних backup-файла каждого типа
- при наличии `RCLONE_REMOTE` загружает backup-файлы в Яндекс Диск

## 10. Проверка ротации локальных backup

После третьего запуска локально должно остаться только `2` последних файла:

```bash
ls -lt ~/zatratpro/backups/db
ls -lt ~/zatratpro/backups/storage
```

## 11. Минимальное восстановление

1. Поднять проект из кода
2. Распаковать `storage` backup в каталог `storage/`
3. Восстановить БД из dump
4. Поднять `docker compose`

Пример восстановления БД:

```bash
cat /path/to/db_YYYY-MM-DD_HHMM.dump | docker exec -i zatratpro-db pg_restore -U zatratpro -d zatratpro --clean --if-exists
```

Если dump лежит на VPS локально:

```bash
docker exec -i zatratpro-db pg_restore -U zatratpro -d zatratpro --clean --if-exists < ~/zatratpro/backups/db/db_YYYY-MM-DD_HHMM.dump
```
