#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/deploy_remote.sh \
    --host 1.2.3.4 \
    --user root \
    --remote-dir /opt/zatratpro \
    --ref restore-v056 \
    --env-file .env.beta \
    [--port 22] \
    [--key ~/.ssh/id_ed25519] \
    [--repo-url git@github.com:org/repo.git] \
    [--runtime-root /srv/zatratpro]

Required:
  --host        SSH host
  --user        SSH user
  --remote-dir  Remote project directory
  --ref         Git branch or tag to deploy
  --env-file    Local .env file to upload

Optional:
  --port        SSH port, default 22
  --key         SSH private key
  --repo-url    Git remote URL; if omitted, origin from current repo is used
  --runtime-root External runtime root, default: /srv/<remote-dir-name>
  --help        Show this message
EOF
}

die() {
  echo "[deploy] $*" >&2
  exit 1
}

require_arg() {
  local name="$1"
  local value="$2"
  [[ -n "$value" ]] || die "Missing required argument: $name"
}

HOST=""
USER_NAME=""
PORT="22"
SSH_KEY=""
REMOTE_DIR=""
REF=""
ENV_FILE=""
REPO_URL=""
RUNTIME_ROOT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="${2:-}"
      shift 2
      ;;
    --user)
      USER_NAME="${2:-}"
      shift 2
      ;;
    --port)
      PORT="${2:-}"
      shift 2
      ;;
    --key)
      SSH_KEY="${2:-}"
      shift 2
      ;;
    --remote-dir)
      REMOTE_DIR="${2:-}"
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
    --repo-url)
      REPO_URL="${2:-}"
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

require_arg "--host" "$HOST"
require_arg "--user" "$USER_NAME"
require_arg "--remote-dir" "$REMOTE_DIR"
require_arg "--ref" "$REF"
require_arg "--env-file" "$ENV_FILE"

if [[ -z "$RUNTIME_ROOT" ]]; then
  RUNTIME_ROOT="/srv/$(basename "$REMOTE_DIR")"
fi

[[ -f "$ENV_FILE" ]] || die "Env file not found: $ENV_FILE"

if [[ -n "$SSH_KEY" ]]; then
  [[ -f "$SSH_KEY" ]] || die "SSH key not found: $SSH_KEY"
fi

if [[ -z "$REPO_URL" ]]; then
  REPO_URL="$(git remote get-url origin 2>/dev/null || true)"
fi
[[ -n "$REPO_URL" ]] || die "Cannot resolve repo URL. Pass --repo-url explicitly."

SSH_ARGS=(-p "$PORT" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)
if [[ -n "$SSH_KEY" ]]; then
  SSH_ARGS+=(-i "$SSH_KEY")
fi

REMOTE="${USER_NAME}@${HOST}"

echo "[deploy] Checking SSH access to ${REMOTE}"
ssh "${SSH_ARGS[@]}" "$REMOTE" "echo ok" >/dev/null

echo "[deploy] Preparing remote directory ${REMOTE_DIR}"
ssh "${SSH_ARGS[@]}" "$REMOTE" "mkdir -p '$REMOTE_DIR'"

echo "[deploy] Uploading env file to ${REMOTE_DIR}/.env"
scp "${SSH_ARGS[@]}" "$ENV_FILE" "${REMOTE}:${REMOTE_DIR}/.env"

echo "[deploy] Deploying ref ${REF}"
ssh "${SSH_ARGS[@]}" "$REMOTE" "bash -s" -- "$REMOTE_DIR" "$REF" "$REPO_URL" "$RUNTIME_ROOT" <<'REMOTE_SCRIPT'
set -euo pipefail

REMOTE_DIR="$1"
REF="$2"
REPO_URL="$3"
RUNTIME_ROOT="$4"

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

if [[ -e "$REMOTE_DIR" && ! -d "$REMOTE_DIR/.git" ]]; then
  echo "[deploy] Remote path exists but is not a git repo: $REMOTE_DIR" >&2
  exit 1
fi

if [[ ! -d "$REMOTE_DIR/.git" ]]; then
  echo "[deploy] Cloning repository into $REMOTE_DIR"
  git clone "$REPO_URL" "$REMOTE_DIR"
fi

cd "$REMOTE_DIR"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "[deploy] Remote git worktree is dirty. Resolve it manually before deploy." >&2
  exit 1
fi

git remote set-url origin "$REPO_URL"
git fetch origin --tags

if git show-ref --verify --quiet "refs/tags/$REF"; then
  echo "[deploy] Checking out tag $REF"
  git checkout "$REF"
elif git show-ref --verify --quiet "refs/remotes/origin/$REF"; then
  echo "[deploy] Checking out branch $REF"
  if git show-ref --verify --quiet "refs/heads/$REF"; then
    git checkout "$REF"
  else
    git checkout -B "$REF" "origin/$REF"
  fi
  git pull --ff-only origin "$REF"
else
  echo "[deploy] Ref not found on remote origin: $REF" >&2
  exit 1
fi

ENV_PATH="${REMOTE_DIR}/.env"
HOST_STORAGE_DIR_VALUE="$(ensure_env_value "$ENV_PATH" HOST_STORAGE_DIR "${RUNTIME_ROOT}/storage")"
HOST_TMP_DIR_VALUE="$(ensure_env_value "$ENV_PATH" HOST_TMP_DIR "${RUNTIME_ROOT}/tmp")"
HOST_BACKUPS_DIR_VALUE="$(ensure_env_value "$ENV_PATH" HOST_BACKUPS_DIR "${RUNTIME_ROOT}/backups")"

mkdir -p "$HOST_TMP_DIR_VALUE" "$HOST_STORAGE_DIR_VALUE" "$HOST_BACKUPS_DIR_VALUE/db" "$HOST_BACKUPS_DIR_VALUE/storage"
chmod +x scripts/backup_zatratpro.sh scripts/restore_zatratpro.sh || true

echo "[deploy] Runtime dirs: storage=$HOST_STORAGE_DIR_VALUE tmp=$HOST_TMP_DIR_VALUE backups=$HOST_BACKUPS_DIR_VALUE"
echo "[deploy] Running docker compose up -d --build"
docker compose up -d --build

echo "[deploy] docker compose ps"
docker compose ps

echo "[deploy] Last bot logs"
docker compose logs --tail=40 zatratpro-bot || true
REMOTE_SCRIPT

echo "[deploy] Done"
