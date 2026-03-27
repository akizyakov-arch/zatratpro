#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_ROOT="${ROOT_DIR}/backups"
DB_BACKUP_DIR="${BACKUP_ROOT}/db"
STORAGE_BACKUP_DIR="${BACKUP_ROOT}/storage"
STORAGE_DIR="${ROOT_DIR}/storage"
TIMESTAMP="$(date +%F_%H%M%S)"
DB_CONTAINER="${DB_CONTAINER:-zatratpro-db}"
DB_SERVICE="${DB_SERVICE:-zatratpro-db}"
BOT_SERVICE="${BOT_SERVICE:-zatratpro-bot}"
DB_FILE="${DB_RESTORE_FILE:-}"
STORAGE_FILE="${STORAGE_RESTORE_FILE:-}"
RESTORE_STORAGE=true
KEEP_OLD_STORAGE=false


usage() {
  cat <<'EOF'
Usage: bash scripts/restore_zatratpro.sh [options]

Options:
  --db-file NAME         Restore a specific DB dump from backups/db
  --storage-file NAME    Restore a specific storage archive from backups/storage
  --db-only              Restore only the database
  --keep-old-storage     Rename the current storage dir instead of replacing it in-place
  --help                 Show this help

Environment overrides:
  DB_CONTAINER
  DB_SERVICE
  BOT_SERVICE
  DB_RESTORE_FILE
  STORAGE_RESTORE_FILE
EOF
}


while [[ $# -gt 0 ]]; do
  case "$1" in
    --db-file)
      DB_FILE="${2:-}"
      shift 2
      ;;
    --storage-file)
      STORAGE_FILE="${2:-}"
      shift 2
      ;;
    --db-only)
      RESTORE_STORAGE=false
      shift
      ;;
    --keep-old-storage)
      KEEP_OLD_STORAGE=true
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "[restore] unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done


pick_latest() {
  local pattern=$1
  local latest
  latest="$(ls -1t ${pattern} 2>/dev/null | head -n 1 || true)"
  if [[ -z "${latest}" ]]; then
    return 1
  fi
  basename "${latest}"
}


wait_for_db() {
  local status=""
  for _ in $(seq 1 60); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "${DB_CONTAINER}" 2>/dev/null || true)"
    if [[ "${status}" == "healthy" ]]; then
      return 0
    fi
    sleep 2
  done
  echo "[restore] database container did not become healthy in time" >&2
  return 1
}


if [[ -z "${DB_FILE}" ]]; then
  DB_FILE="$(pick_latest "${DB_BACKUP_DIR}/db_*.dump")"
fi
if [[ ! -f "${DB_BACKUP_DIR}/${DB_FILE}" ]]; then
  echo "[restore] database dump not found: ${DB_BACKUP_DIR}/${DB_FILE}" >&2
  exit 1
fi

if [[ "${RESTORE_STORAGE}" == "true" && -z "${STORAGE_FILE}" ]]; then
  STORAGE_FILE="$(pick_latest "${STORAGE_BACKUP_DIR}/storage_*.tar.gz" || true)"
fi
if [[ "${RESTORE_STORAGE}" == "true" && -n "${STORAGE_FILE}" && ! -f "${STORAGE_BACKUP_DIR}/${STORAGE_FILE}" ]]; then
  echo "[restore] storage archive not found: ${STORAGE_BACKUP_DIR}/${STORAGE_FILE}" >&2
  exit 1
fi

echo "[restore] using db dump: ${DB_FILE}"
if [[ "${RESTORE_STORAGE}" == "true" ]]; then
  if [[ -n "${STORAGE_FILE}" ]]; then
    echo "[restore] using storage archive: ${STORAGE_FILE}"
  else
    echo "[restore] no storage archive found, database-only restore"
  fi
fi

echo "[restore] ensuring database container is up"
docker compose up -d "${DB_SERVICE}"
wait_for_db

echo "[restore] validating db dump"
docker exec -i "${DB_CONTAINER}" pg_restore -l "/backups/db/${DB_FILE}" >/dev/null

if [[ "${RESTORE_STORAGE}" == "true" && -n "${STORAGE_FILE}" ]]; then
  echo "[restore] validating storage archive"
  tar -tzf "${STORAGE_BACKUP_DIR}/${STORAGE_FILE}" >/dev/null
fi

echo "[restore] stopping bot"
docker compose stop "${BOT_SERVICE}" || true

echo "[restore] recreating database"
docker exec -i "${DB_CONTAINER}" sh -lc 'dropdb -U "$POSTGRES_USER" --if-exists "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'

echo "[restore] restoring database"
docker exec -i "${DB_CONTAINER}" sh -lc "pg_restore -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" --no-owner --no-privileges /backups/db/${DB_FILE}"

if [[ "${RESTORE_STORAGE}" == "true" && -n "${STORAGE_FILE}" ]]; then
  if [[ -d "${STORAGE_DIR}" && "${KEEP_OLD_STORAGE}" == "true" ]]; then
    backup_storage_dir="${ROOT_DIR}/storage_before_restore_${TIMESTAMP}"
    echo "[restore] moving current storage -> ${backup_storage_dir}"
    mv "${STORAGE_DIR}" "${backup_storage_dir}"
  else
    echo "[restore] replacing current storage"
    rm -rf "${STORAGE_DIR}"
  fi
  mkdir -p "${ROOT_DIR}"
  echo "[restore] restoring storage"
  tar -xzf "${STORAGE_BACKUP_DIR}/${STORAGE_FILE}" -C "${ROOT_DIR}"
fi

echo "[restore] starting bot"
docker compose up -d "${BOT_SERVICE}"

echo "[restore] done"
echo "[restore] db: ${DB_BACKUP_DIR}/${DB_FILE}"
if [[ "${RESTORE_STORAGE}" == "true" && -n "${STORAGE_FILE}" ]]; then
  echo "[restore] storage: ${STORAGE_BACKUP_DIR}/${STORAGE_FILE}"
fi
