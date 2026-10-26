"""Deployment checks must fail safely and never retain a broken backup."""
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


checks = module('check_deployment')
backups = module('backup_database')


class DeploymentTests(unittest.TestCase):
    def settings(self):
        return dict(WEB_DOMAIN='panel.company.ru', TELEGRAM_BOT_TOKEN='private-test-token',
                    OCR_SPACE_API_KEY='private-ocr', DEEPSEEK_API_KEY='private-llm',
                    POSTGRES_DB='finance', POSTGRES_USER='finance', POSTGRES_PASSWORD='private-db',
                    BOT_OWNER_TELEGRAM_ID='1001')

    def test_templates_and_unsafe_proxy_targets_fail_without_revealing_secrets(self):
        for changes in ({'WEB_DOMAIN': 'panel.example.org'}, {'WEB_DOMAIN': 'https://panel.company.ru'},
                        {'FIINOPS_PROXY_SUBNET': '127.0.0.0/24', 'FIINOPS_PROXY_IP': '127.0.0.2'},
                        {'FIINOPS_PROXY_IP': '172.29.248.1'}, {'POSTGRES_PASSWORD': 'change_me'},
                        {'FIINOPS_WEB_IP': '172.29.248.2'},
                        {'POSTGRES_HOST': 'different-db'}):
            values = self.settings() | changes
            errors = checks.check(values)
            self.assertTrue(errors, changes)
            self.assertNotIn('private-', ' '.join(errors))
        self.assertEqual(checks.check(self.settings()), [])

    def test_mini_app_requires_numeric_bot_id_only_when_enabled(self):
        for bot_id in ('0', '-1', 'bot_name', '', '9223372036854775808'):
            self.assertTrue(checks.check(self.settings() | {
                'WEB_MINI_APP_ENABLED': 'true', 'WEB_TELEGRAM_BOT_ID': bot_id,
            }), bot_id)
        self.assertTrue(checks.check(self.settings() | {'WEB_MINI_APP_ENABLED': 'invalid'}))
        self.assertEqual(checks.check(self.settings() | {
            'WEB_MINI_APP_ENABLED': 'true', 'WEB_TELEGRAM_BOT_ID': '1234567890',
        }), [])
        self.assertEqual(checks.check(self.settings() | {'WEB_MINI_APP_ENABLED': 'false'}), [])

    def run_backup(self, return_codes):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            env_file = root / '.env'
            env_file.write_text('POSTGRES_PASSWORD=do-not-print-me\n')
            archive = b'PGDMP-test-archive'
            commands = []

            def run(command, **kwargs):
                commands.append(command)
                if 'stdout' in kwargs and hasattr(kwargs['stdout'], 'write'):
                    kwargs['stdout'].write(archive)
                if 'stdin' in kwargs:
                    self.assertEqual(kwargs['stdin'].read(), archive)
                return SimpleNamespace(returncode=return_codes[len(commands) - 1])

            with patch.object(backups.subprocess, 'run', side_effect=run):
                if any(return_codes):
                    with self.assertRaises(ValueError):
                        backups.backup(env_file, root / 'backups')
                    self.assertEqual(list((root / 'backups').iterdir()), [])
                else:
                    path = backups.backup(env_file, root / 'backups')
                    self.assertEqual(path.read_bytes(), archive)
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('do-not-print-me', str(commands))
            self.assertFalse(any('up' in command for command in commands))
            return commands

    def test_successful_backup_is_private_and_verified(self):
        commands = self.run_backup([0, 0])
        self.assertIn('pg_restore', commands[1])
        self.assertIn('--list', commands[1])

    def test_failed_dump_removes_partial_archive(self):
        self.assertEqual(len(self.run_backup([1])), 1)

    def test_failed_restore_validation_removes_unverified_archive(self):
        self.assertEqual(len(self.run_backup([0, 1])), 2)


if __name__ == '__main__':
    unittest.main()
