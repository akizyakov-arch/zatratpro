"""Official MAX CA is scoped, additive and never disables TLS verification."""
import hashlib
import ssl
import unittest
from unittest.mock import patch

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from app.max_bot.client import MaxClient, MaxAPIError, ROOT_CA

FINGERPRINT = 'd26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31'


class MaxTrustTests(unittest.TestCase):
    def test_bundled_certificate_matches_official_identity_and_is_self_signed_ca(self):
        cert = x509.load_pem_x509_certificate(ROOT_CA.read_bytes())
        self.assertEqual(cert.fingerprint(hashes.SHA256()).hex(), FINGERPRINT)
        self.assertTrue(cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
        cert.verify_directly_issued_by(cert)
        self.assertEqual(cert.not_valid_after_utc.year, 2032)

    def test_max_context_adds_root_without_removing_system_trust_or_hostname_check(self):
        system_roots = set(ssl.create_default_context().get_ca_certs(binary_form=True))
        with patch('app.max_bot.client.httpx.AsyncClient') as constructor:
            MaxClient('private-test-token')
        context = constructor.call_args.kwargs['verify']
        roots = set(context.get_ca_certs(binary_form=True))
        self.assertTrue(system_roots.issubset(roots))
        self.assertIn(FINGERPRINT, {hashlib.sha256(root).hexdigest() for root in roots})
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertFalse(constructor.call_args.kwargs['follow_redirects'])


class MaxNetworkDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_errors_are_classified_without_leaking_exception_details(self):
        errors = (
            (httpx.ConnectError('CERTIFICATE_VERIFY_FAILED private-token'), 'сертификат'),
            (httpx.ReadTimeout('private-token'), 'ожидания'),
            (httpx.ConnectError('DNS unavailable private-token'), 'DNS'),
        )
        for failure, expected in errors:
            def fail(request):
                raise failure
            async with MaxClient('private-token', transport=httpx.MockTransport(fail)) as client:
                with self.assertRaises(MaxAPIError) as caught:
                    await client.me()
                self.assertIn(expected, str(caught.exception))
                self.assertNotIn('private-token', str(caught.exception))
