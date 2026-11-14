import base64
import hashlib
import hmac
import unittest

from kurafolio.ingestion import cursors
from kurafolio.ingestion.codec import IngestionError


SECRET = b'synthetic-cursor-secret-for-tests-only-0001'
PAYLOAD = {'version': 1, 'user_id': '10000000-0000-4000-8000-000000000001',
           'portfolio_id': '10000000-0000-4000-8000-000000000002', 'realm_digest': 'a' * 64,
           'resource_id': None, 'resource_revision': None, 'review_digest': None, 'filter': 'READY',
           'after_key': '1700000000000000:20000000-0000-4000-8000-000000000001',
           'expires_at': '2026-11-05T12:00:00.000000+00:00'}


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


class CursorTests(unittest.TestCase):
    def setUp(self):
        self.key = cursors.derive_key(SECRET)

    def test_round_trip_uses_a_dedicated_purpose_key(self):
        token = cursors.sign(self.key, PAYLOAD)
        self.assertEqual(PAYLOAD, cursors.verify(self.key, token))
        self.assertNotEqual(SECRET, self.key)
        self.assertEqual(hmac.new(SECRET, b'wealth-ledger/ingestion-cursor-v1', hashlib.sha256).digest(), self.key)
        # The instance secret itself is not a valid cursor key.
        with self.assertRaises(IngestionError):
            cursors.verify(SECRET, token)
        with self.assertRaises(ValueError):
            cursors.derive_key(b'short')

    def test_any_tampering_rejects_before_the_payload_is_used(self):
        token = cursors.sign(self.key, PAYLOAD)
        body, mac = token.split('.')
        changed = dict(PAYLOAD, portfolio_id='10000000-0000-4000-8000-000000000003')
        forged = b64(cursors.encode(changed)) + '.' + mac
        for bad in (forged, body + '.' + mac[:-1] + ('A' if mac[-1] != 'A' else 'B'), body, body + '.' + mac + '.x',
                    '', body + '.' + mac + '=', 'é' + token, token + ' ', 'x' * 1025):
            with self.subTest(token=bad[:40]):
                with self.assertRaises(IngestionError):
                    cursors.verify(self.key, bad)

    def test_authentic_but_noncanonical_or_open_payloads_reject(self):
        def signed(data):
            return b64(data) + '.' + b64(hmac.new(self.key, data, hashlib.sha256).digest())
        canonical = cursors.encode(PAYLOAD)
        spaced = canonical.replace(b',', b', ', 1)
        extra = cursors.encode(dict(PAYLOAD, tenant_override='x'))
        float_version = canonical.replace(b'"version":1', b'"version":1.0')
        for name, data in (('spaced', spaced), ('extra', extra), ('float', float_version),
                           ('duplicate', canonical[:-1] + b',"version":1}')):
            with self.subTest(case=name):
                with self.assertRaises(IngestionError):
                    cursors.verify(self.key, signed(data))
        self.assertEqual(PAYLOAD, cursors.verify(self.key, signed(canonical)))

    def test_alternative_base64_spellings_of_the_same_bytes_reject(self):
        token = cursors.sign(self.key, PAYLOAD)
        body, mac = token.split('.')
        # The final character of a 43-character MAC carries two unused bits.
        alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
        index = alphabet.index(mac[-1])
        twin = mac[:-1] + alphabet[index ^ 1]
        self.assertEqual(base64.urlsafe_b64decode(mac + '='), base64.urlsafe_b64decode(twin + '='))
        with self.assertRaises(IngestionError):
            cursors.verify(self.key, body + '.' + twin)

    def test_sign_checks_the_closed_shape(self):
        cases = (dict(PAYLOAD, filter='UNKNOWN'), dict(PAYLOAD, version=2), dict(PAYLOAD, version=True),
                 dict(PAYLOAD, resource_id='20000000-0000-4000-8000-000000000001'),
                 dict(PAYLOAD, after_key=None), dict(PAYLOAD, expires_at='2026-11-05T12:00:00+00:00'),
                 {k: v for k, v in PAYLOAD.items() if k != 'filter'}, dict(PAYLOAD, user_id='Z' * 36))
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(IngestionError):
                    cursors.sign(self.key, case)
        page = dict(PAYLOAD, filter=None, resource_id='20000000-0000-4000-8000-000000000001',
                    resource_revision='3', review_digest='b' * 64, after_key='10')
        self.assertEqual(page, cursors.verify(self.key, cursors.sign(self.key, page)))
        self.assertLessEqual(len(cursors.sign(self.key, page)), cursors.MAX_TOKEN)


if __name__ == '__main__':
    unittest.main()
