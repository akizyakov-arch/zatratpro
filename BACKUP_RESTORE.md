# Backup And Restore

## Где лежат backup-файлы

Проект хранит backup-файлы в папке `backups` внутри директории проекта:

- `backups/db` — дампы PostgreSQL
- `backups/storage` — архивы файлов из `storage`

Эти файлы не живут в Postgres volume. Команда удаления volume базы их не трогает.

## Ручной backup

Выполнить из директории проекта:

```bash
cd ~/zatratpro
bash scripts/backup_zatratpro.sh
```

После этого появятся:

- `backups/db/db_YYYY-MM-DD_HHMM.dump`
- `backups/storage/storage_YYYY-MM-DD_HHMM.tar.gz`

Быстрая проверка:

```bash
cd ~/zatratpro
ls -lah backups/db
ls -lah backups/storage
```

## Проверка backup перед restore

Последние файлы:

```bash
cd ~/zatratpro
LATEST_DUMP="$(basename "$(ls -1t backups/db/db_*.dump | head -n 1)")"
LATEST_STORAGE="$(basename "$(ls -1t backups/storage/storage_*.tar.gz | head -n 1)")"
echo "$LATEST_DUMP"
echo "$LATEST_STORAGE"
```

Проверка дампа БД:

```bash
docker exec -i zatratpro-db sh -lc "pg_restore -l /backups/db/$LATEST_DUMP | head"
```

Проверка storage-архива:

```bash
tar -tzf "backups/storage/$LATEST_STORAGE" | head
```

## Полное восстановление через restore-скрипт

Восстановление последних backup-файлов:

```bash
cd ~/zatratpro
bash scripts/restore_zatratpro.sh
```

Только БД:

```bash
cd ~/zatratpro
bash scripts/restore_zatratpro.sh --db-only
```

Восстановление из конкретных файлов:

```bash
cd ~/zatratpro
bash scripts/restore_zatratpro.sh --db-file db_2026-03-27_1304.dump --storage-file storage_2026-03-27_1304.tar.gz
```

С сохранением текущего `storage`:

```bash
cd ~/zatratpro
bash scripts/restore_zatratpro.sh --keep-old-storage
```

Что делает скрипт:

1. Поднимает БД, если контейнер еще не запущен.
2. Проверяет валидность дампа и storage-архива.
3. Останавливает бота.
4. Пересоздает боевую БД.
5. Восстанавливает dump.
6. Восстанавливает `storage`, если архив есть и restore storage не отключен.
7. Поднимает бота обратно.

## Полный reset и restore вручную

Полный reset контейнеров и Postgres volume:

```bash
cd ~/zatratpro
docker compose down
docker volume rm zatratpro_zatratpro_postgres_data
docker compose up -d --build
```

Важно:

- это удаляет контейнеры compose-проекта;
- это удаляет volume Postgres;
- это не удаляет `backups/`, `storage/`, `tmp/`.

После reset можно восстановиться:

```bash
cd ~/zatratpro
bash scripts/restore_zatratpro.sh
```

## Проверка после restore

Проверка таблиц:

```bash
docker exec -it zatratpro-db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"'
```

Проверка количества записей:

```bash
docker exec -it zatratpro-db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT COUNT(*) FROM users; SELECT COUNT(*) FROM companies; SELECT COUNT(*) FROM projects; SELECT COUNT(*) FROM documents;"'
```

Проверка логов бота:

```bash
cd ~/zatratpro
docker compose logs --tail=200 zatratpro-bot
```
