"""Create and verify a private dump of an already running Compose database."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def backup(env_file, destination):
    if not env_file.is_file():
        raise ValueError('Файл настроек не найден.')
    command = ['docker', 'compose', '--project-directory', str(ROOT),
               '--env-file', str(env_file.resolve()), '-f', str(ROOT / 'docker-compose.yml')]
    # exec deliberately fails if the expected DB is absent. It never creates an
    # empty replacement volume or starts a second PostgreSQL instance.
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = destination / ('zatratpro-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.dump')
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, 'wb') as output:
            result = subprocess.run(command + ['exec', '-T', 'zatratpro-db', 'sh', '-ec',
                'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc'], stdout=output, stderr=subprocess.PIPE)
        if result.returncode or path.stat().st_size == 0:
            raise ValueError('Не удалось создать резервную копию существующей БД. Проверьте Compose и доступ к базе.')
        with path.open('rb') as data:
            result = subprocess.run(command + ['exec', '-T', 'zatratpro-db', 'pg_restore', '--list'],
                stdin=data, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if result.returncode:
            raise ValueError('Резервная копия не прошла проверку pg_restore.')
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--directory', type=Path, default=ROOT.parent / 'backups')
    args = parser.parse_args()
    try:
        path = backup(args.env_file, args.directory)
    except (OSError, ValueError):
        print('Создание проверенной резервной копии не завершилось. Рабочие сервисы не изменялись.', file=sys.stderr)
        return 1
    print(f'Резервная копия проверена и сохранена с правами 0600: {path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
