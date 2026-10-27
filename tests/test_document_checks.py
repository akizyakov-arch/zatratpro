import os
import unittest
from app.schemas.document import DocumentSchema
from app.services.document_checks import document_warnings, review_fingerprint
from app.services.json_formatter import format_document_preview
from db_fixture import DatabaseFixture
from app.state.pending_documents import get_pending_document, store_pending_document
from app.handlers import documents as handlers
from app.ui.projects import PROJECT_CALLBACK_PREFIX, DOCUMENT_DUPLICATE_SAVE_CALLBACK


def invoice(quantity=5, **changes):
    item = dict(name='Точка доступа Wi-Fi',quantity=quantity,price=3305.08,line_total=19500,
                vat_rate=18,vat_amount=2974.58,line_total_without_vat=16525.42,price_includes_vat=False)
    item.update(changes)
    return DocumentSchema(document_type='goods_invoice',total=19500,items=[item])


class ArithmeticTests(unittest.TestCase):
    def test_user_example_wrong_quantity_is_flagged_without_changing_it(self):
        doc=invoice(1)
        warnings=document_warnings(doc)
        self.assertTrue(any('Wi-Fi' in warning and 'не согласуется' in warning for warning in warnings))
        self.assertEqual(doc.items[0].quantity,1)
        self.assertIn('Нужна проверка',format_document_preview(doc))
        self.assertEqual(document_warnings(invoice()),[])

    def test_vat_rates_are_explicit_and_rounding_is_tolerated(self):
        for rate in (0,5,7,10,18,20,22):
            doc=invoice(2,price=100,line_total=200*(1+rate/100),vat_rate=rate,
                        vat_amount=rate*2,line_total_without_vat=200)
            doc.total=doc.items[0].line_total
            self.assertEqual(document_warnings(doc),[],rate)
        doc=invoice(2,price=1694.92,line_total=4000,vat_amount=610.17,line_total_without_vat=3389.83)
        doc.total=4000
        self.assertEqual(document_warnings(doc),[])

    def test_inclusive_prices_and_fractional_quantity(self):
        doc=invoice(2.5,price=120,line_total=300,vat_rate=20,vat_amount=50,
                    line_total_without_vat=250,price_includes_vat=True)
        doc.total=300
        self.assertEqual(document_warnings(doc),[])

    def test_unknown_vat_does_not_silently_guess_a_rate(self):
        doc=invoice(5,vat_rate=None,vat_amount=None,line_total_without_vat=None,price_includes_vat=None)
        self.assertTrue(document_warnings(doc))
        self.assertIsNone(doc.items[0].vat_rate)

    def test_missing_and_nonfinite_fields_are_reported(self):
        for value in (None,float('nan'),float('inf'),0,-1):
            self.assertTrue(document_warnings(invoice(value)))

    def test_tax_and_document_totals_are_checked(self):
        self.assertTrue(document_warnings(invoice(vat_amount=50)))
        doc=invoice();doc.total=100
        self.assertTrue(any('итогом документа' in warning for warning in document_warnings(doc)))

    def test_fingerprint_changes_when_extracted_values_change(self):
        self.assertNotEqual(review_fingerprint(invoice(1)),review_fingerprint(invoice(5)))


@unittest.skipUnless(os.environ.get('RUN_DATABASE_TESTS')=='1','PostgreSQL tests disabled')
class ReviewFlowTests(DatabaseFixture):
    async def wrong_draft(self):
        draft=await self.make_draft()
        draft.extracted_document.items[0].quantity=5
        await store_pending_document(self.employee.id,draft)
        return draft

    async def test_project_selection_requires_review_then_saves_once(self):
        draft=await self.wrong_draft()
        await handlers.process_project_selection(self.callback(f'{PROJECT_CALLBACK_PREFIX}{self.project.id}:{draft.upload_id}'))
        self.assertEqual(await self.document_count(),0)
        # Draft is reloaded from PostgreSQL, as after a restart.
        pending=await get_pending_document(self.employee.id)
        self.assertIsNone(pending.reviewed_fingerprint)
        callback=self.callback('document:review:'+draft.upload_id)
        await handlers.review_document_callback(callback)
        self.assertEqual(await self.document_count(),1)
        await handlers.review_document_callback(callback)
        self.assertEqual(await self.document_count(),1)

    async def test_stale_review_does_not_confirm_new_upload(self):
        draft=await self.wrong_draft()
        await handlers.review_document_callback(self.callback('document:review:old-upload'))
        self.assertEqual(await self.document_count(),0)
        self.assertIsNone((await get_pending_document(self.employee.id)).reviewed_fingerprint)

    async def test_arithmetic_review_cannot_bypass_duplicate_confirmation(self):
        await handlers.document_service.save_document(self.employee,self.project,'preview',self.document,upload_id='first')
        draft=await self.wrong_draft()
        await handlers.process_project_selection(self.callback(f'{PROJECT_CALLBACK_PREFIX}{self.project.id}:{draft.upload_id}'))
        await handlers.review_document_callback(self.callback('document:review:'+draft.upload_id))
        self.assertEqual(await self.document_count(),1)
        self.assertIsNone((await get_pending_document(self.employee.id)).reviewed_fingerprint)
        await handlers.duplicate_save_callback(self.callback(f'{DOCUMENT_DUPLICATE_SAVE_CALLBACK}:{draft.upload_id}'))
        self.assertEqual(await self.document_count(),1)
        await handlers.review_document_callback(self.callback('document:review:'+draft.upload_id))
        self.assertEqual(await self.document_count(),2)
