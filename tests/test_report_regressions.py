"""Financial report/export regressions; no database or external APIs required."""
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from openpyxl import load_workbook

from app.services.money_reports import (
    CASH_FIELDS, cash_and_employee_debt, format_money_report, get_money_report_for_user,
)
from app.services.report_exports import build_manager_report_workbook


NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def report_row(employee=1, project=1, closing='0'):
    row = dict.fromkeys(CASH_FIELDS, Decimal(0))
    row.update(employee_id=employee, project_id=project, first_name='Employee',
               last_name=None, project_name='Project', closing=Decimal(closing))
    return row


def report(rows=(), cards=()):
    return {
        'start': NOW - timedelta(days=1), 'end': NOW,
        'rows': list(rows), 'card_rows': list(cards),
        'totals': {key: sum((row[key] for row in rows), Decimal(0)) for key in CASH_FIELDS},
        'card_spent': Decimal(0), 'card_pending': Decimal(0),
    }


def workbook_for(money_report=None, projects=()):
    summary = SimpleNamespace(start_at=NOW, documents=0, total_amount=0,
                              exact_duplicates=0, probable_duplicates=0)
    _, payload = build_manager_report_workbook(
        'all_time', summary, projects, [], [], [], [], money_report=money_report,
    )
    return load_workbook(BytesIO(payload))


class ReportRegressionTests(unittest.TestCase):
    def test_ocr_control_characters_do_not_break_excel_or_restore_formulas(self):
        project = SimpleNamespace(project_id=1, project_name='=1+1\x0b\x1f',
                                  document_count=0, total_amount=0,
                                  exact_duplicate_count=0, probable_duplicate_count=0)
        wb = workbook_for(projects=[project])
        cell = wb['Projects']['B2']
        self.assertEqual(cell.value, '=1+1\ufffd\ufffd')
        self.assertEqual(cell.data_type, 's')

    def test_excel_preserves_bigint_identifier_exactly(self):
        identifier = 9007199254740993
        project = SimpleNamespace(project_id=identifier, project_name='Project',
                                  document_count=1, total_amount=100,
                                  exact_duplicate_count=0, probable_duplicate_count=0)
        wb = workbook_for(projects=[project])
        self.assertEqual(wb['Projects']['A2'].value, str(identifier))
        self.assertEqual(wb['Projects']['A2'].data_type, 's')
        self.assertEqual(wb['Projects']['D2'].data_type, 'n')

    def test_historical_pending_card_hides_later_approval_date(self):
        card = {
            'document_id': 1, 'card_name': 'Company', 'last4': '0012',
            'first_name': None, 'last_name': None, 'submitted_by': 12,
            'project_name': 'Project', 'amount': Decimal('100'),
            'accepted': False, 'approved_at': NOW + timedelta(days=1),
        }
        wb = workbook_for(report(cards=[card]))
        self.assertEqual(wb['BusinessCards']['G2'].value, 'На проверке')
        self.assertIsNone(wb['BusinessCards']['H2'].value)
        self.assertEqual(wb['BusinessCards']['C2'].value, '0012')
        self.assertEqual(wb['BusinessCards']['D2'].value, 'Сотрудник №12')

    def test_employee_debt_does_not_hide_another_employees_cash(self):
        # One employee has two project balances; only then split cash/debt.
        data = report([
            report_row(employee=1, project=1, closing='100'),
            report_row(employee=1, project=2, closing='-30'),
            report_row(employee=2, project=1, closing='-50'),
        ])
        self.assertEqual(cash_and_employee_debt(data), (Decimal('70'), Decimal('50')))
        text = format_money_report(data)
        self.assertIn('Расчётный остаток на конец: 20.00', text)
        self.assertIn('На руках у сотрудников: 70.00', text)
        self.assertIn('Компания должна сотрудникам: 50.00', text)
        wb = workbook_for(data)
        overview = {row[0].value: row[1].value for row in wb['Overview']}
        self.assertEqual(overview['Деньги: на руках у сотрудников RUB'], 70)
        self.assertEqual(overview['Деньги: компания должна сотрудникам RUB'], 50)


class ReportSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_cash_and_card_queries_share_a_readonly_snapshot_and_end(self):
        data = report()
        connection = MagicMock()
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=connection)
        connection.transaction.return_value.__aenter__ = AsyncMock()
        cash = MagicMock()
        cash.report = AsyncMock(return_value=data)
        cards = MagicMock()
        cards.report = AsyncMock(return_value=[{'amount': Decimal('12.34'), 'accepted': True}])
        with patch('app.services.money_reports.get_pool', return_value=pool), \
             patch('app.services.money_reports.AdvanceService', return_value=cash), \
             patch('app.services.money_reports.BusinessCardService', return_value=cards):
            result = await get_money_report_for_user(42, data['start'], NOW, project_id=3)
        connection.transaction.assert_called_once_with(isolation='repeatable_read', readonly=True)
        cash.report.assert_awaited_once_with(
            42, data['start'], NOW, connection=connection, project_id=3, employee_id=None,
        )
        cards.report.assert_awaited_once_with(
            42, data['start'], NOW, connection=connection, project_id=3, employee_id=None,
        )
        self.assertEqual(result['card_spent'], Decimal('12.34'))
        self.assertEqual(result['card_pending'], Decimal(0))
