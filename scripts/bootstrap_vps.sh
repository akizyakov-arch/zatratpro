#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  sudo bash scripts/bootstrap_vps.sh \
    --repo-url git@github.com:org/repo.git \
    --project-dir /opt/zatratpro \
    --ref restore-v056 \
    [--env-file /root/zatratpro.env] \
    [--timezone Europe/Moscow] \
    [--backup-schedule "10 3 * * *"] \
    [--rclone-remote yadisk:zatratpro-backups] \
    [--runtime-root /srv/zatratpro]

Required:
  --repo-url         Git repository URL
  --project-dir      Target directory on the VPS
  --ref              Git branch or tag to deploy

Optional:
  --env-file         Path to .env file already present on the VPS
  --timezone         Timezone to set on the VPS, for example Europe/Moscow
  --backup-schedule  Cron schedule for local backups, default: 10 3 * * *
  --rclone-remote    Optional rclone remote for backup upload
  --runtime-root     External runtime root, default: /srv/<project-name>
  --help             Show this message
EOF
}

die() {
  echo "[bootstrap] $*" >&2
  exit 1
}

require_arg() {
  local name="$1"
  local value="$2"
  [[ -n "$value" ]] || die "Missing required argument: $name"
}

if [[ "${EUID}" -ne 0 ]]; then
  die "Run this script as root."
fi

REPO_URL=""
PROJECT_DIR=""
REF=""
ENV_FILE=""
TIMEZONE_NAME=""
BACKUP_SCHEDULE="10 3 * * *"
RCLONE_REMOTE=""
RUNTIME_ROOT=""
HOST_STORAGE_DIR_VALUE=""
HOST_TMP_DIR_VALUE=""
HOST_BACKUPS_DIR_VALUE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-url)
      REPO_URL="${2:-}"
      shift 2
      ;;
    --project-dir)
      PROJECT_DIR="${2:-}"
      shift 2
      ;;
    --ref)
      REF="${2:-}"
      shift 2
      ;;
    --env-file)
      ENV_FILE="${2:-}"
      shift 2
      ;;
    --timezone)
      TIMEZONE_NAME="${2:-}"
      shift 2
      ;;
    --backup-schedule)
      BACKUP_SCHEDULE="${2:-}"
      shift 2
      ;;
    --rclone-remote)
      RCLONE_REMOTE="${2:-}"
      shift 2
      ;;
    --runtime-root)
      RUNTIME_ROOT="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

require_arg "--repo-url" "$REPO_URL"
require_arg "--project-dir" "$PROJECT_DIR"
require_arg "--ref" "$REF"

if [[ -z "$RUNTIME_ROOT" ]]; then
  RUNTIME_ROOT="/srv/$(basename "$PROJECT_DIR")"
fi

if [[ -n "$ENV_FILE" ]]; then
  [[ -f "$ENV_FILE" ]] || die "Env file not found: $ENV_FILE"
fi

log() {
  echo "[bootstrap] $*"
}

read_env_value() {
  local file="$1"
  local key="$2"
  local line value
  [[ -f "$file" ]] || return 0
  line="$(grep -E "^${key}=" "$file" | tail -n 1 || true)"
  [[ -n "$line" ]] || return 0
  value="${line#*=}"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf "%s" "$value"
}

ensure_env_value() {
  local file="$1"
  local key="$2"
  local default_value="$3"
  local current_value
  current_value="$(read_env_value "$file" "$key")"
  if [[ -n "$current_value" ]]; then
    printf "%s" "$current_value"
    return 0
  fi
  if grep -Eq "^${key}=" "$file" 2>/dev/null; then
    sed -i "\|^${key}=|c\${key}=${default_value}" "$file"
  else
    printf "\n%s=%s\n" "$key" "$default_value" >> "$file"
  fi
  printf "%s" "$default_value"
}

ensure_runtime_env() {
  local env_path="${PROJECT_DIR}/.env"
  [[ -f "$env_path" ]] || touch "$env_path"
  HOST_STORAGE_DIR_VALUE="$(ensure_env_value "$env_path" HOST_STORAGE_DIR "${RUNTIME_ROOT}/storage")"
  HOST_TMP_DIR_VALUE="$(ensure_env_value "$env_path" HOST_TMP_DIR "${RUNTIME_ROOT}/tmp")"
  HOST_BACKUPS_DIR_VALUE="$(ensure_env_value "$env_path" HOST_BACKUPS_DIR "${RUNTIME_ROOT}/backups")"
}

install_base_packages() {
  log "Installing base packages"
  apt-get update -y
  apt-get install -y ca-certificates curl gnupg git cron lsb-release
}

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    log "Docker and docker compose already installed"
    return
  fi

  . /etc/os-release
  case "${ID}" in
    ubuntu|debian) ;;
    *)
      die "Unsupported distro for automatic Docker install: ${ID}"
      ;;
  esac

  log "Installing Docker repository"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/${ID}/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc

  ARCH="$(dpkg --print-architecture)"
  echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${ID} ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list

  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
}

enable_services() {
  log "Enabling docker and cron"
  systemctl enable --now docker
  systemctl enable --now cron
}

configure_timezone() {
  if [[ -z "$TIMEZONE_NAME" ]]; then
    return
  fi
  log "Setting timezone to ${TIMEZONE_NAME}"
  timedatectl set-timezone "$TIMEZONE_NAME"
}

prepare_repo() {
  log "Preparing project directory ${PROJECT_DIR}"
  mkdir -p "$PROJECT_DIR"

  if [[ -e "$PROJECT_DIR" && ! -d "$PROJECT_DIR/.git" && -n "$(find "$PROJECT_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    die "Project directory exists and is not an empty git repo target: ${PROJECT_DIR}"
  fi

  if [[ ! -d "$PROJECT_DIR/.git" ]]; then
    log "Cloning repository"
    git clone "$REPO_URL" "$PROJECT_DIR"
  fi

  cd "$PROJECT_DIR"
  git remote set-url origin "$REPO_URL"
  git fetch origin --tags

  if git show-ref --verify --quiet "refs/tags/$REF"; then
    log "Checking out tag ${REF}"
    git checkout "$REF"
  elif git show-ref --verify --quiet "refs/remotes/origin/$REF"; then
    log "Checking out branch ${REF}"
    if git show-ref --verify --quiet "refs/heads/$REF"; then
      git checkout "$REF"
    else
      git checkout -B "$REF" "origin/$REF"
    fi
    git pull --ff-only origin "$REF"
  else
    die "Ref not found on origin: $REF"
  fi
}

prepare_env() {
  cd "$PROJECT_DIR"
  if [[ -n "$ENV_FILE" ]]; then
    log "Copying env file into project"
    cp "$ENV_FILE" .env
  elif [[ ! -f .env && -f .env.example ]]; then
    log "Creating .env from .env.example"
    cp .env.example .env
    log "Fill .env before using the bot in production"
  fi

  ensure_runtime_env
}

prepare_directories() {
  cd "$PROJECT_DIR"
  log "Creating runtime directories under ${RUNTIME_ROOT}"
  mkdir -p "$HOST_TMP_DIR_VALUE" "$HOST_STORAGE_DIR_VALUE" "$HOST_BACKUPS_DIR_VALUE/db" "$HOST_BACKUPS_DIR_VALUE/storage"
  chmod +x scripts/backup_zatratpro.sh scripts/restore_zatratpro.sh || true
}

install_backup_cron() {
  cd "$PROJECT_DIR"
  local cron_line backup_log
  backup_log="${HOST_BACKUPS_DIR_VALUE}/backup.log"
  mkdir -p "$(dirname "$backup_log")"
  if [[ -n "$RCLONE_REMOTE" ]]; then
    cron_line="${BACKUP_SCHEDULE} cd ${PROJECT_DIR} && RCLONE_REMOTE=\"${RCLONE_REMOTE}\" /bin/bash scripts/backup_zatratpro.sh >> ${backup_log} 2>&1"
  else
    cron_line="${BACKUP_SCHEDULE} cd ${PROJECT_DIR} && /bin/bash scripts/backup_zatratpro.sh >> ${backup_log} 2>&1"
  fi

  log "Installing backup cron job"
  local existing
  existing="$(crontab -l 2>/dev/null | grep -v 'scripts/backup_zatratpro.sh' || true)"
  {
    if [[ -n "$existing" ]]; then
      printf '%s
' "$existing"
    fi
    printf '%s
' "$cron_line"
  } | crontab -
}

run_deploy() {
  cd "$PROJECT_DIR"
  log "Running docker compose up -d --build"
  docker compose up -d --build
  log "docker compose ps"
  docker compose ps
  log "Last bot logs"
  docker compose logs --tail=40 zatratpro-bot || true
}

install_base_packages
install_docker
enable_services
configure_timezone
prepare_repo
prepare_env
prepare_directories
install_backup_cron
run_deploy

log "Done"
