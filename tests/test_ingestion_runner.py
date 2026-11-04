"""Actual frame and peer-identity checks; these are not native containment tests."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import socket
import ssl
import struct
import subprocess
import tempfile
import threading
import unittest

from wealth_ledger.ingestion.codec import encode, sha256
from wealth_ledger.ingestion.contracts import IngestionError, MAX_MINIMAL
from wealth_ledger.ingestion.runner_client import (ChildOutputCollector, PeerTLS,
    pack_input, pack_result, unpack_input, unpack_result)

ORACLE = json.loads((Path(__file__).parent / 'fixtures/ingestion/oracle.json').read_text())


def fixture(name):
    return deepcopy(ORACLE[name])


class IngestionRunnerTests(unittest.TestCase):
    def test_literal_child_result_headers_and_payloads(self):
        for case in fixture('child-result-cases.json')['cases']:
            with self.subTest(payload=case['payload_file']):
                payload = encode(fixture(case['payload_file']))
                header = case['result']
                self.assertEqual(case['header_bytes'], len(encode(header)))
                frame = pack_result(header, payload, child=True)
                got_header, got_payload = unpack_result(frame, header, child=True)
                self.assertEqual(header, got_header)
                self.assertEqual(payload, got_payload)

    def test_parent_handle_is_required_and_not_child_selected(self):
        case = fixture('child-result-cases.json')['cases'][0]
        payload, header = encode(fixture(case['payload_file'])), case['result']
        child_frame = pack_result(header, payload, child=True)
        with self.assertRaises(IngestionError):
            unpack_result(child_frame, header)
        header['handle'] = 'a' * 64
        frame = pack_result(header, payload)
        self.assertEqual(payload, unpack_result(frame, header)[1])
        expected = dict(header, handle='b' * 64)
        with self.assertRaises(IngestionError):
            unpack_result(frame, expected)

    def test_size_truncation_trailing_bytes_and_hash_mismatch(self):
        case = fixture('child-result-cases.json')['cases'][0]
        payload, header = encode(fixture(case['payload_file'])), case['result']
        frame = pack_result(header, payload, child=True)
        for malformed in (b'', frame[:3], frame[:-1], frame + b'x',
                          struct.pack('!I', 4097) + frame[4:], frame[:-1] + b'x'):
            with self.subTest(size=len(malformed)), self.assertRaises(IngestionError):
                unpack_result(malformed, header, child=True)

    def test_all_caller_bindings_are_checked_before_payload_decode(self):
        case = fixture('child-result-cases.json')['cases'][0]
        payload, header = encode(fixture(case['payload_file'])), case['result']
        frame = pack_result(header, payload, child=True)
        for field in ('job_id', 'member_id', 'fence', 'installation_id', 'image_digest',
                      'wrapper_profile_digest', 'raw_sha256', 'context_sha256', 'payload_kind'):
            expected = dict(header, **{field: 'different'})
            with self.subTest(field=field), self.assertRaises(IngestionError):
                unpack_result(frame, expected, child=True)

    def test_nonzero_exit_and_overflow_win_over_json(self):
        with self.assertRaises(IngestionError) as caught:
            unpack_result(b'invalid json frame', {}, child=True, exit_code=1)
        self.assertEqual('import_runner_unavailable', caught.exception.code)
        with self.assertRaises(IngestionError) as caught:
            unpack_result(b'invalid json frame', {}, child=True, exit_code=1, overflow=True)
        self.assertEqual('import_limit', caught.exception.code)

    def test_stdout_is_bounded_and_stderr_never_stored(self):
        collector = ChildOutputCollector()
        collector.stdout(b'x' * (MAX_MINIMAL + 4096 + 5))
        self.assertTrue(collector.stdout_overflow)
        collector.stderr(b'SECRET_SENTINEL' * 10000)
        self.assertTrue(collector.stderr_overflow)
        self.assertNotIn('SECRET_SENTINEL', repr(collector.__dict__))
        with self.assertRaises(IngestionError):
            collector.finish({}, exit_code=0)
        self.assertEqual(bytearray(), collector._stdout)

    def test_fragmented_capture_retains_the_exact_frame(self):
        case = fixture('child-result-cases.json')['cases'][0]
        payload, header = encode(fixture(case['payload_file'])), case['result']
        frame = pack_result(header, payload, child=True)
        collector = ChildOutputCollector()
        for offset in range(0, len(frame), 7):
            collector.stdout(frame[offset:offset + 7])
            collector.stderr(b'private diagnostic')
        self.assertEqual((header, payload), collector.finish(header, exit_code=0))

    def launch(self):
        context = encode(fixture('child-context-parser2.json'))
        raw = fixture('trade.csv').encode()
        source = fixture('child-context-parser2.json')
        header = {k: source[k] for k in ('job_id', 'member_id', 'fence', 'installation_id',
                   'image_digest', 'wrapper_profile_digest', 'format_version')}
        header.update(version=1, operation='start',
            instance_id='60000000-0000-4000-8000-000000000001', realm_digest='a' * 64,
            credential_epoch='1', context_bytes=len(context), context_sha256=sha256(context),
            raw_bytes=len(raw), raw_sha256=sha256(raw),
            deadline={'tag': 'instant', 'token': '2026-02-02T13:02:00+00:00',
                      'zone': None, 'fractional_digits': 0}, nonce='b' * 64)
        return header, context, raw

    def test_input_frame_exact_lengths_hashes_and_closed_metadata(self):
        header, context, raw = self.launch()
        frame = pack_input(header, context, raw)
        self.assertEqual((header, context, raw), unpack_input(frame))
        for changed in (frame[:-1], frame + b'x', frame[:-1] + b'X'):
            with self.assertRaises(IngestionError):
                unpack_input(changed)
        with self.assertRaises(IngestionError):
            pack_input(dict(header, command='arbitrary'), context, raw)
        with self.assertRaises(IngestionError):
            pack_input(dict(header, raw_sha256='0' * 64), context, raw)

    def test_valid_hash_does_not_allow_wrong_child_context_binding(self):
        header, context, raw = self.launch()
        obj = fixture('child-context-parser2.json')
        obj['job_id'] = '90000000-0000-4000-8000-000000000099'
        context = encode(obj)
        header.update(context_bytes=len(context), context_sha256=sha256(context))
        with self.assertRaises(IngestionError):
            unpack_input(pack_input(header, context, raw))

    def test_peer_requires_exact_dns_instance_role_and_tls13(self):
        tls = PeerTLS(Path('/unused'), Path('/unused'), Path('/unused'), 'worker.internal',
                      '60000000-0000-4000-8000-000000000001', 'worker')
        expected_uri = 'urn:wealth-ledger:instance:60000000-0000-4000-8000-000000000001:peer:worker'

        class Peer:
            def __init__(self, *, version='TLSv1.3', dns='worker.internal', uri=expected_uri):
                self.protocol, self.dns, self.uri = version, dns, uri

            def version(self):
                return self.protocol

            def getpeercert(self):
                return {'subjectAltName': [('DNS', self.dns), ('URI', self.uri)]}

        tls.verify_peer(Peer())
        for peer in (Peer(version='TLSv1.2'), Peer(dns='*.internal'),
                     Peer(uri=expected_uri.replace(':worker', ':api')),
                     Peer(uri=expected_uri.replace('000000000001', '000000000002'))):
            with self.assertRaises(IngestionError):
                tls.verify_peer(peer)


@unittest.skipUnless(shutil.which('openssl'), 'Actual mTLS test requires the OpenSSL command')
class IngestionTLSExecutionTests(unittest.TestCase):
    """Real TLS sockets with disposable invented certificates, no service deployment."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='wl007-dev-tls-')
        cls.root = Path(cls.directory.name)
        cls.instance = '60000000-0000-4000-8000-000000000001'
        cls.command('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-sha256', '-days', '1',
                    '-keyout', 'ca.key', '-out', 'ca.crt', '-subj', '/CN=SyntheticIngestionCA')
        for role in ('api', 'worker', 'wrong'):
            cls.command('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', role + '.key',
                        '-out', role + '.csr', '-subj', '/CN=' + role + '.internal')
            uri_role = 'launcher' if role == 'wrong' else role
            (cls.root / (role + '.ext')).write_text(
                'basicConstraints=critical,CA:FALSE\n'
                'keyUsage=critical,digitalSignature,keyEncipherment\n'
                'extendedKeyUsage=serverAuth,clientAuth\n'
                f'subjectAltName=DNS:{role}.internal,URI:urn:wealth-ledger:instance:{cls.instance}:peer:{uri_role}\n')
            cls.command('x509', '-req', '-in', role + '.csr', '-CA', 'ca.crt', '-CAkey', 'ca.key',
                        '-CAcreateserial', '-out', role + '.crt', '-days', '1', '-sha256',
                        '-extfile', role + '.ext')
            (cls.root / (role + '.key')).chmod(0o600)

    @classmethod
    def command(cls, *args):
        result = subprocess.run(['openssl', *args], cwd=cls.root, capture_output=True, timeout=15)
        if result.returncode:
            raise RuntimeError('Synthetic test certificate generation failed')

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def settings(self, own_role, peer_role, *, peer_dns=None):
        return PeerTLS(self.root / 'ca.crt', self.root / (own_role + '.crt'),
                       self.root / (own_role + '.key'), peer_dns or peer_role + '.internal',
                       self.instance, peer_role)

    def exchange(self, client, server):
        left, right = socket.socketpair()
        left.settimeout(3)
        right.settimeout(3)
        server_errors, client_errors = [], []

        def serve():
            try:
                with server.context(server=True).wrap_socket(left, server_side=True) as connection:
                    server.verify_peer(connection)
                    self.assertEqual(b'x', connection.recv(1))
                    connection.sendall(b'y')
            except Exception as error:
                server_errors.append(type(error))
            finally:
                left.close()

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            with client.context().wrap_socket(right, server_hostname=client.peer_dns) as connection:
                client.verify_peer(connection)
                connection.sendall(b'x')
                self.assertEqual(b'y', connection.recv(1))
        except Exception as error:
            client_errors.append(type(error))
        finally:
            right.close()
            thread.join(5)
        self.assertFalse(thread.is_alive(), 'Synthetic TLS thread did not terminate')
        return server_errors, client_errors

    def test_real_mutual_tls13_with_exact_peer_identity(self):
        self.assertEqual(([], []), self.exchange(self.settings('api', 'worker'),
                                               self.settings('worker', 'api')))

    def test_valid_ca_and_dns_do_not_authorize_wrong_uri_role(self):
        client = self.settings('api', 'worker', peer_dns='wrong.internal')
        server = self.settings('wrong', 'api')
        errors = self.exchange(client, server)
        self.assertTrue(errors[1])
        self.assertIn(IngestionError, errors[1])

    def test_readable_private_key_fails_before_connection(self):
        path = self.root / 'api.key'
        try:
            path.chmod(0o644)
            with self.assertRaises(IngestionError):
                self.settings('api', 'worker').context()
        finally:
            path.chmod(0o600)


if __name__ == '__main__':
    unittest.main()
