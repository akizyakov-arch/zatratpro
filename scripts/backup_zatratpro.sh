#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_ROOT="${ROOT_DIR}/backups"
DB_BACKUP_DIR="${BACKUP_ROOT}/db"
STORAGE_BACKUP_DIR="${BACKUP_ROOT}/storage"
STORAGE_DIR="${ROOT_DIR}/storage"
TIMESTAMP="$(date +%F_%H%M)"
DB_FILE="${DB_BACKUP_DIR}/db_${TIMESTAMP}.dump"
STORAGE_FILE="${STORAGE_BACKUP_DIR}/storage_${TIMESTAMP}.tar.gz"
KEEP_LOCAL_COUNT="${KEEP_LOCAL_COUNT:-2}"
DB_CONTAINER="${DB_CONTAINER:-zatratpro-db}"
RCLONE_REMOTE="${RCLONE_REMOTE:-}"

mkdir -p "${DB_BACKUP_DIR}" "${STORAGE_BACKUP_DIR}" "${STORAGE_DIR}"

echo "[backup] dumping postgres from ${DB_CONTAINER} -> ${DB_FILE}"
docker exec -t "${DB_CONTAINER}" sh -lc 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "${DB_FILE}"

echo "[backup] archiving storage -> ${STORAGE_FILE}"
tar -czf "${STORAGE_FILE}" -C "${ROOT_DIR}" storage

cleanup_old() {
  local pattern=$1
  local keep=$2
  mapfile -t files < <(ls -1t ${pattern} 2>/dev/null || true)
  if (( ${#files[@]} > keep )); then
    printf '%s\n' "${files[@]:keep}" | xargs -r rm -f --
  fi
}

cleanup_old "${DB_BACKUP_DIR}/db_*.dump" "${KEEP_LOCAL_COUNT}"
cleanup_old "${STORAGE_BACKUP_DIR}/storage_*.tar.gz" "${KEEP_LOCAL_COUNT}"

if [[ -n "${RCLONE_REMOTE}" ]] && command -v rclone >/dev/null 2>&1; then
  echo "[backup] uploading to rclone remote ${RCLONE_REMOTE}"
  rclone copyto "${DB_FILE}" "${RCLONE_REMOTE}/db/$(basename "${DB_FILE}")"
  rclone copyto "${STORAGE_FILE}" "${RCLONE_REMOTE}/storage/$(basename "${STORAGE_FILE}")"
fi

echo "[backup] done"
echo "[backup] db: ${DB_FILE}"
echo "[backup] storage: ${STORAGE_FILE}"
