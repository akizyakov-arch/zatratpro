"""Validate deployment inputs without printing credentials or changing services."""
import argparse
import ipaddress
from pathlib import Path
import re
import socket
import sys

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent


def check(values):
    errors = []
    domain = values.get('WEB_DOMAIN', '') or ''
    if (not re.fullmatch(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', domain)
            or domain.endswith(('.example', '.test', '.localhost', '.invalid'))
            or domain in ('panel.your-domain.ru', 'fiinops.example.com')
            or any(domain == reserved or domain.endswith('.' + reserved)
                   for reserved in ('example.com', 'example.net', 'example.org'))):
        errors.append('WEB_DOMAIN: укажите реальное имя панели без https://, пути и порта.')
    for name in ('TELEGRAM_BOT_TOKEN', 'OCR_SPACE_API_KEY', 'DEEPSEEK_API_KEY',
                 'POSTGRES_DB', 'POSTGRES_USER', 'POSTGRES_PASSWORD'):
        value = values.get(name, '') or ''
        if not value or value.startswith(('replace_with_', 'your_')) or value == 'change_me':
            errors.append(f'{name}: значение не настроено. Секреты не нужно отправлять в чат.')
    try:
        if int(values.get('BOT_OWNER_TELEGRAM_ID', '0') or '0') <= 0:
            raise ValueError
    except ValueError:
        errors.append('BOT_OWNER_TELEGRAM_ID: укажите Telegram ID владельца системы.')
    if not re.fullmatch(r'[A-Za-z0-9_]{5,32}', values.get('WEB_BOT_USERNAME', 'prozatrat_bot') or ''):
        errors.append('WEB_BOT_USERNAME: укажите имя бота без @.')
    if values.get('POSTGRES_HOST', 'zatratpro-db') != 'zatratpro-db':
        errors.append('POSTGRES_HOST: для этого Compose должен быть zatratpro-db; внешний PostgreSQL требует отдельной конфигурации.')
    if str(values.get('POSTGRES_PORT', '5432')) != '5432':
        errors.append('POSTGRES_PORT: для PostgreSQL внутри Compose нужен порт 5432.')
    try:
        subnet = ipaddress.ip_network(values.get('FIINOPS_PROXY_SUBNET', '172.29.248.0/24'))
        proxy = ipaddress.ip_address(values.get('FIINOPS_PROXY_IP', '172.29.248.2'))
        web = ipaddress.ip_address(values.get('FIINOPS_WEB_IP', '172.29.248.3'))
        private_ranges = [ipaddress.ip_network(value) for value in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]
        if (subnet.version != 4 or not any(subnet.subnet_of(block) for block in private_ranges) or proxy not in subnet
                or proxy in (subnet.network_address, subnet.broadcast_address)
                or proxy == subnet.network_address + 1
                or web not in subnet or web == proxy
                or web in (subnet.network_address, subnet.broadcast_address)
                or web == subnet.network_address + 1):
            raise ValueError
    except (ValueError, TypeError):
        errors.append('FIINOPS_PROXY_IP/WEB_IP/SUBNET: нужны разные свободные адреса в частной IPv4-подсети, кроме адреса сети, gateway (.1) и broadcast.')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--check-dns', action='store_true')
    parser.add_argument('--server-ip', help='Expected public IPv4 or IPv6 address, if known.')
    args = parser.parse_args()
    if not args.env_file.is_file():
        print('Не найден файл настроек. Скопируйте .env.production.example в .env на сервере.', file=sys.stderr)
        return 1
    try:
        values = dotenv_values(args.env_file, interpolate=False)
    except (OSError, UnicodeError):
        print('Не удалось прочитать файл настроек.', file=sys.stderr)
        return 1
    errors = check(values)
    if args.check_dns and not errors:
        try:
            addresses = {row[4][0] for row in socket.getaddrinfo(values['WEB_DOMAIN'], 443, type=socket.SOCK_STREAM)}
            if args.server_ip and str(ipaddress.ip_address(args.server_ip)) not in addresses:
                errors.append('DNS панели не указывает на указанный адрес сервера.')
        except (OSError, ValueError):
            errors.append('Домен пока не разрешается в адрес сервера. Проверьте DNS A/AAAA.')
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"Конфигурация проверена: https://{values['WEB_DOMAIN']}. Значения секретов скрыты.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
