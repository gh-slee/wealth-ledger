"""ASGI byte-boundary tests, separate from future authenticated route acceptance."""
import asyncio
import time
import unittest

from wealth_ledger.ingestion.contracts import IngestionError, MAX_RAW
from wealth_ledger.web_v2.imports import receive_raw, upload_length


def headers(length=b'3'):
    return [(b'content-length', length), (b'content-type', b'application/octet-stream')]


class IngestionUploadHeaderTests(unittest.TestCase):
    def test_required_length_and_exact_media_type(self):
        self.assertEqual(3, upload_length(headers()))
        for values, code in (([], 'length_required'), (headers(b'0'), 'invalid_length'),
                (headers(b'-1'), 'invalid_length'), (headers(b'3.0'), 'invalid_length'),
                (headers(str(MAX_RAW + 1).encode()), 'import_limit'),
                (headers() + [(b'content-length', b'3')], 'invalid_length'),
                (headers() + [(b'transfer-encoding', b'chunked')], 'invalid_length'),
                (headers() + [(b'content-encoding', b'identity')], 'unsupported_media_type'),
                (headers() + [(b'expect', b'100-continue')], 'unsupported_media_type'),
                ([(b'content-length', b'3'), (b'content-type', b'multipart/form-data')],
                 'unsupported_media_type')):
            with self.subTest(code=code), self.assertRaises(IngestionError) as caught:
                upload_length(values)
            self.assertEqual(code, caught.exception.code)


class IngestionUploadStreamTests(unittest.IsolatedAsyncioTestCase):
    def reader(self, messages):
        queue = iter(messages)

        async def receive():
            return next(queue)
        return receive

    async def test_fragmented_exact_body_and_empty_final_chunk(self):
        for messages in ([{'type': 'http.request', 'body': b'abc'}],
                [{'type': 'http.request', 'body': b'a', 'more_body': True},
                 {'type': 'http.request', 'body': b'bc', 'more_body': True},
                 {'type': 'http.request', 'body': b''} ]):
            self.assertEqual(b'abc', await receive_raw(self.reader(messages), headers()))

    async def test_short_extra_trailing_disconnect_and_invalid_chunks(self):
        cases = [
            [{'type': 'http.request', 'body': b'ab'}],
            [{'type': 'http.request', 'body': b'abcd'}],
            [{'type': 'http.request', 'body': b'abc', 'more_body': True},
             {'type': 'http.request', 'body': b'd'}],
            [{'type': 'http.disconnect'}],
            [{'type': 'http.request', 'body': 'abc'}],
            [{'type': 'http.request', 'body': b'abc', 'more_body': 1}],
        ]
        for messages in cases:
            with self.subTest(messages=messages), self.assertRaises(IngestionError) as caught:
                await receive_raw(self.reader(messages), headers())
            self.assertEqual('invalid_length', caught.exception.code)

    async def test_rejected_headers_do_not_start_receiving(self):
        async def must_not_read():
            self.fail('Body was read before mandatory header rejection')
        with self.assertRaises(IngestionError):
            await receive_raw(must_not_read, headers() + [(b'content-length', b'3')])

    async def test_idle_deadline_cancels_the_pending_receive(self):
        finished = []

        async def never_finishes():
            try:
                await asyncio.sleep(60)
            finally:
                finished.append(True)
        with self.assertRaises(IngestionError) as caught:
            await receive_raw(never_finishes, headers(), idle_seconds=0.02)
        self.assertEqual('request_timeout', caught.exception.code)
        self.assertEqual([True], finished)

    async def test_total_budget_cannot_be_extended_by_many_progress_chunks(self):
        async def trickle():
            await asyncio.sleep(0.01)
            return {'type': 'http.request', 'body': b'a', 'more_body': True}
        with self.assertRaises(IngestionError) as caught:
            await receive_raw(trickle, headers(b'100'), total_seconds=0.035)
        self.assertEqual('request_timeout', caught.exception.code)

    async def test_empty_chunks_do_not_reset_idle_budget(self):
        async def empty():
            await asyncio.sleep(0.005)
            return {'type': 'http.request', 'body': b'', 'more_body': True}
        with self.assertRaises(IngestionError) as caught:
            await receive_raw(empty, headers(), idle_seconds=0.02)
        self.assertEqual('request_timeout', caught.exception.code)

    async def test_no_body_read_after_already_expired_total_budget(self):
        async def must_not_read():
            self.fail('Read attempted after deadline')
        with self.assertRaises(IngestionError) as caught:
            await receive_raw(must_not_read, headers(), entered=time.monotonic() - 31)
        self.assertEqual('request_timeout', caught.exception.code)

    async def test_caller_cannot_increase_production_budgets(self):
        with self.assertRaises(IngestionError):
            await receive_raw(self.reader([]), headers(), total_seconds=31)
        with self.assertRaises(IngestionError):
            await receive_raw(self.reader([]), headers(), idle_seconds=6)


if __name__ == '__main__':
    unittest.main()
