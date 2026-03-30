import json
import unittest
from pathlib import Path

from app.schemas.document import DocumentSchema
from app.services.document_financials import DocumentFinancialNormalizationService
from app.services.json_formatter import format_document_preview


CASES_PATH = Path(__file__).with_name("golden").joinpath("upd_financial_cases.json")


def _assert_optional_amount(testcase: unittest.TestCase, actual, expected, *, msg: str) -> None:
    if expected is None:
        testcase.assertIsNone(actual, msg)
        return
    testcase.assertIsNotNone(actual, msg)
    testcase.assertAlmostEqual(float(actual), float(expected), places=2, msg=msg)


class UPDFinancialNormalizationGoldenTest(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.service = DocumentFinancialNormalizationService()
        cls.cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))

    def test_upd_financial_golden_cases(self) -> None:
        for case in self.cases:
            with self.subTest(case=case["id"]):
                document = DocumentSchema.model_validate(case["document"])
                result = self.service.normalize_document(document)
                expected = case["expected"]

                _assert_optional_amount(
                    self,
                    result.document.total,
                    expected.get("total"),
                    msg=f'{case["id"]}: unexpected total',
                )
                _assert_optional_amount(
                    self,
                    result.document.vat_total_amount,
                    expected.get("vat_total_amount"),
                    msg=f'{case["id"]}: unexpected vat_total_amount',
                )
                self.assertEqual(
                    result.document.vat_scope,
                    expected.get("vat_scope"),
                    f'{case["id"]}: unexpected vat_scope',
                )

                expected_provenance = expected.get("provenance", {})
                self.assertEqual(
                    result.provenance.total_source,
                    expected_provenance.get("total_source"),
                    f'{case["id"]}: unexpected total source',
                )
                self.assertEqual(
                    result.provenance.vat_total_amount_source,
                    expected_provenance.get("vat_total_amount_source"),
                    f'{case["id"]}: unexpected vat source',
                )
                self.assertEqual(
                    list(result.provenance.warnings),
                    expected_provenance.get("warnings", []),
                    f'{case["id"]}: unexpected warnings',
                )
                self.assertEqual(
                    list(result.provenance.suppressed_values),
                    expected_provenance.get("suppressed_values", []),
                    f'{case["id"]}: unexpected suppressed values',
                )

                preview = format_document_preview(result.document)
                for fragment in expected.get("preview_contains", []):
                    self.assertIn(fragment, preview, f'{case["id"]}: preview missing "{fragment}"')
                for fragment in expected.get("preview_not_contains", []):
                    self.assertNotIn(fragment, preview, f'{case["id"]}: preview unexpectedly contains "{fragment}"')


if __name__ == "__main__":
    unittest.main()
