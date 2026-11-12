"""Quote adapter contract, fake provider, cache, rate limit and failure handling.

Every test here runs with outbound connections blocked; a test that tries to
reach the network fails.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from kurafolio.market import (DailyBar, DelayClass, Listing, MarketSettings, NoData, ProviderError,
                              Quote, QuoteResult, QuoteService, QuoteStatus, build_quote_service)
from kurafolio.market.fake import (NEW_YORK, ORACLE_AS_OF, ORACLE_FETCHED_AT, TORONTO,
                                   FakeQuoteProvider)

NOW = datetime(2026, 11, 6, 21, 5, tzinfo=timezone.utc)
UNKNOWN = Listing("XTSE", "NOPE")


class NetworkBlocked(AssertionError):
    pass


def _refuse(*args, **kwargs):
    raise NetworkBlocked("Tests must not open network connections")


class OfflineTestCase(unittest.TestCase):
    """Blocks socket connections and DNS lookups for the duration of each test."""

    def setUp(self):
        for target in ("socket.socket.connect", "socket.socket.connect_ex",
                       "socket.create_connection", "socket.getaddrinfo"):
            patcher = patch(target, _refuse)
            patcher.start()
            self.addCleanup(patcher.stop)


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


def service(provider=None, clock=None, **options):
    return QuoteService(provider, clock=clock or Clock(), **options)


class NetworkGuardTests(OfflineTestCase):
    def test_guard_fails_any_connection_attempt(self):
        with self.assertRaises(NetworkBlocked):
            socket.create_connection(("example.test", 443), timeout=1)
        with self.assertRaises(NetworkBlocked):
            socket.getaddrinfo("example.test", 443)
        with socket.socket() as raw, self.assertRaises(NetworkBlocked):
            raw.connect(("192.0.2.1", 443))


class ContractTests(OfflineTestCase):
    def test_listing_requires_exchange_and_symbol(self):
        self.assertEqual(Listing.of(" xtse ", "veqt"), TORONTO)
        self.assertEqual(TORONTO.key(), "XTSE:VEQT")
        self.assertNotEqual(Listing("XTSE", "VTI"), Listing("ARCX", "VTI"))
        for mic, symbol in (("", "VEQT"), ("TSX", "VEQT"), ("XTSE", ""), ("XTSE", "VE QT"), ("xtse", "VEQT")):
            with self.assertRaises(ValueError):
                Listing(mic, symbol)

    def test_quote_rejects_zero_float_naive_and_future_values(self):
        good = dict(listing=TORONTO, price=Decimal("1"), currency="CAD", as_of=ORACLE_AS_OF,
                    source="Synthetic fake", delay_class=DelayClass.DELAYED, fetched_at=ORACLE_FETCHED_AT)
        Quote(**good)
        for change in ({"price": Decimal("0")}, {"price": Decimal("-1")}, {"price": Decimal("NaN")},
                       {"price": 1.5}, {"currency": "cad"}, {"as_of": ORACLE_AS_OF.replace(tzinfo=None)},
                       {"as_of": ORACLE_FETCHED_AT + timedelta(hours=1)}, {"delay_class": "delayed"},
                       {"source": ""}, {"evidence_sha256": "abc"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                Quote(**{**good, **change})

    def test_result_never_pairs_unavailable_with_a_price(self):
        quote = FakeQuoteProvider().fetch_latest([TORONTO])[TORONTO]
        with self.assertRaises(ValueError):
            QuoteResult(TORONTO, QuoteStatus.UNAVAILABLE, NOW, quote, "no_data")
        with self.assertRaises(ValueError):
            QuoteResult(TORONTO, QuoteStatus.UNAVAILABLE, NOW)
        with self.assertRaises(ValueError):
            QuoteResult(TORONTO, QuoteStatus.STALE, NOW, quote)
        with self.assertRaises(ValueError):
            NoData("Has spaces and https://secret")
        self.assertEqual(ProviderError("https://x?key=1").code, "provider_error")


class FakeProviderOracleTests(OfflineTestCase):
    def test_latest_quote_for_toronto_and_us_listings(self):
        results = service(FakeQuoteProvider()).latest([TORONTO, NEW_YORK])
        expected = {TORONTO: (Decimal("41.27"), "CAD"), NEW_YORK: (Decimal("287.15"), "USD")}
        for listing, (price, currency) in expected.items():
            result = results[listing]
            self.assertEqual(result.status, QuoteStatus.FRESH)
            self.assertIsNone(result.reason)
            self.assertEqual(result.quote.price, price)
            self.assertIsInstance(result.quote.price, Decimal)
            self.assertEqual(result.quote.currency, currency)
            self.assertEqual(result.quote.as_of, ORACLE_AS_OF)
            self.assertEqual(result.quote.source, "Synthetic fake")
            self.assertEqual(result.quote.delay_class, DelayClass.DELAYED)
            self.assertEqual(result.checked_at, NOW)

    def test_daily_history_for_toronto_and_us_listings(self):
        quotes = service(FakeQuoteProvider())
        toronto = quotes.history(TORONTO, date(2026, 11, 4), date(2026, 11, 6))
        self.assertEqual(toronto.status, QuoteStatus.FRESH)
        self.assertEqual([(bar.day, bar.close, bar.currency) for bar in toronto.bars],
                         [(date(2026, 11, 4), Decimal("41.05"), "CAD"),
                          (date(2026, 11, 5), Decimal("41.12"), "CAD"),
                          (date(2026, 11, 6), Decimal("41.27"), "CAD")])
        us = quotes.history(NEW_YORK, date(2026, 11, 3), date(2026, 11, 3))
        self.assertEqual([(bar.day, bar.close, bar.currency, bar.delay_class) for bar in us.bars],
                         [(date(2026, 11, 3), Decimal("284.10"), "USD", DelayClass.END_OF_DAY)])


class DisabledProviderTests(OfflineTestCase):
    def test_default_configuration_makes_no_request_and_reports_no_provider(self):
        self.assertEqual(MarketSettings().provider, "none")
        quotes = build_quote_service()
        self.assertFalse(quotes.enabled)
        result = quotes.latest([TORONTO, NEW_YORK])
        self.assertEqual({item.status for item in result.values()}, {QuoteStatus.NO_PROVIDER})
        self.assertTrue(all(item.quote is None and item.reason == "no_provider" for item in result.values()))
        history = quotes.history(TORONTO, date(2026, 11, 1), date(2026, 11, 6))
        self.assertEqual((history.status, history.bars, history.reason), (QuoteStatus.NO_PROVIDER, (), "no_provider"))

    def test_configuration_file_is_strict(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.json"
            path.write_text(json.dumps({"provider": "none", "cache_seconds": 120}), encoding="utf-8")
            self.assertEqual(MarketSettings.from_file(path).cache_seconds, 120)
            for bad in ({"provider": "none", "api_key": "x"}, {"cache_seconds": -1},
                        {"max_requests_per_minute": 0}, {"cache_seconds": "60"},
                        {"accept_unofficial_terms": "yes"}):
                path.write_text(json.dumps(bad), encoding="utf-8")
                with self.subTest(bad=bad), self.assertRaises((ValueError, TypeError)):
                    MarketSettings.from_file(path)
        with self.assertRaisesRegex(ValueError, "Unknown market provider"):
            build_quote_service(MarketSettings(provider="not-registered"))

    def test_unofficial_provider_needs_explicit_operator_acceptance(self):
        def factory(settings):
            return FakeQuoteProvider()
        factory.unofficial = True
        registry = {"unofficial-test": factory}
        with self.assertRaisesRegex(ValueError, "accept_unofficial_terms"):
            build_quote_service(MarketSettings(provider="unofficial-test"), registry)
        quotes = build_quote_service(MarketSettings(provider="unofficial-test", accept_unofficial_terms=True),
                                     registry, clock=Clock())
        self.assertEqual(quotes.latest([TORONTO])[TORONTO].status, QuoteStatus.FRESH)


class CacheAndRateLimitTests(OfflineTestCase):
    def test_two_users_within_the_cache_window_cause_one_upstream_request(self):
        provider, clock = FakeQuoteProvider(), Clock()
        quotes = service(provider, clock, cache_seconds=60)
        first = quotes.latest([TORONTO, NEW_YORK])     # user A
        clock.advance(30)
        second = quotes.latest([NEW_YORK, TORONTO])    # user B
        self.assertEqual(len(provider.latest_calls), 1)
        self.assertEqual(first[TORONTO], second[TORONTO])
        clock.advance(31)
        quotes.latest([TORONTO])
        self.assertEqual(provider.latest_calls[-1], (TORONTO,))
        self.assertEqual(len(provider.latest_calls), 2)

    def test_concurrent_users_share_one_upstream_request(self):
        provider = FakeQuoteProvider()
        quotes = service(provider)
        barrier = threading.Barrier(8)
        results = []

        def ask():
            barrier.wait()
            results.append(quotes.latest([TORONTO])[TORONTO])

        threads = [threading.Thread(target=ask) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(provider.latest_calls), 1)
        self.assertEqual(len(set(results)), 1)

    def test_requests_are_batched_to_the_provider_batch_size(self):
        provider = FakeQuoteProvider(max_batch_size=1)
        service(provider).latest([TORONTO, NEW_YORK, TORONTO])
        self.assertEqual(provider.latest_calls, [(TORONTO,), (NEW_YORK,)])

    def test_rate_limit_caps_upstream_calls_without_inventing_prices(self):
        provider, clock = FakeQuoteProvider(max_batch_size=1), Clock()
        quotes = service(provider, clock, max_requests=1, per_seconds=60)
        with self.assertLogs("kurafolio.market", "WARNING"):
            result = quotes.latest([TORONTO, NEW_YORK])
        self.assertEqual(len(provider.latest_calls), 1)
        self.assertEqual(result[TORONTO].status, QuoteStatus.FRESH)
        self.assertEqual((result[NEW_YORK].status, result[NEW_YORK].reason, result[NEW_YORK].quote),
                         (QuoteStatus.UNAVAILABLE, "rate_limited", None))
        clock.advance(60)
        self.assertEqual(quotes.latest([NEW_YORK])[NEW_YORK].status, QuoteStatus.FRESH)


class FailureTests(OfflineTestCase):
    def prime(self):
        provider, clock = FakeQuoteProvider(), Clock()
        quotes = service(provider, clock, cache_seconds=60)
        self.assertEqual(quotes.latest([TORONTO])[TORONTO].status, QuoteStatus.FRESH)
        clock.advance(61)
        return provider, clock, quotes

    def assert_stale(self, result, reason):
        self.assertEqual(result.status, QuoteStatus.STALE)
        self.assertEqual(result.reason, reason)
        self.assertEqual(result.quote.price, Decimal("41.27"))
        self.assertEqual(result.quote.as_of, ORACLE_AS_OF)

    def test_upstream_error_keeps_last_valid_price_marked_stale(self):
        provider, clock, quotes = self.prime()
        provider.fail_with = "http_error"
        with self.assertLogs("kurafolio.market", "WARNING") as logs:
            result = quotes.latest([TORONTO])[TORONTO]
        self.assert_stale(result, "http_error")
        self.assertEqual(result.checked_at, clock.now)
        self.assertIn("reason=http_error", logs.output[0])

    def test_unexpected_shape_keeps_last_valid_price_marked_stale(self):
        provider, _, quotes = self.prime()
        provider.fetch_latest = lambda listings: {TORONTO: {"price": "41.27"}}
        with self.assertLogs("kurafolio.market", "WARNING"):
            self.assert_stale(quotes.latest([TORONTO])[TORONTO], "unexpected_shape")

    def test_missing_listing_in_answer_is_an_unexpected_shape(self):
        provider, _, quotes = self.prime()
        provider.fetch_latest = lambda listings: {}
        with self.assertLogs("kurafolio.market", "WARNING"):
            self.assert_stale(quotes.latest([TORONTO])[TORONTO], "unexpected_shape")

    def test_empty_answer_keeps_last_valid_price_marked_stale(self):
        provider, _, quotes = self.prime()
        provider.no_data.add(TORONTO)
        with self.assertLogs("kurafolio.market", "WARNING"):
            self.assert_stale(quotes.latest([TORONTO])[TORONTO], "no_data")

    def test_unexpected_exception_is_logged_without_its_message(self):
        provider, _, quotes = self.prime()

        def explode(listings):
            raise OSError("GET https://quotes.example.test/v1?apikey=SECRET-TOKEN failed")
        provider.fetch_latest = explode
        with self.assertLogs("kurafolio.market", "WARNING") as logs:
            self.assert_stale(quotes.latest([TORONTO])[TORONTO], "provider_error")
        joined = "\n".join(logs.output)
        self.assertNotIn("SECRET", joined)
        self.assertNotIn("https://", joined)

    def test_failure_without_a_previous_price_is_unavailable_never_zero(self):
        provider = FakeQuoteProvider()
        provider.fail_with = "http_error"
        with self.assertLogs("kurafolio.market", "WARNING"):
            result = service(provider).latest([TORONTO])[TORONTO]
        self.assertEqual((result.status, result.quote, result.reason), (QuoteStatus.UNAVAILABLE, None, "http_error"))

    def test_unknown_listing_is_unavailable_with_a_reason(self):
        quotes = service(FakeQuoteProvider())
        with self.assertLogs("kurafolio.market", "WARNING"):
            result = quotes.latest([UNKNOWN])[UNKNOWN]
            history = quotes.history(UNKNOWN, date(2026, 11, 1), date(2026, 11, 6))
        self.assertEqual((result.status, result.quote, result.reason),
                         (QuoteStatus.UNAVAILABLE, None, "unknown_listing"))
        self.assertEqual((history.status, history.bars, history.reason),
                         (QuoteStatus.UNAVAILABLE, (), "unknown_listing"))

    def test_older_answer_does_not_replace_a_newer_valid_quote(self):
        provider, _, quotes = self.prime()
        older = Quote(TORONTO, Decimal("39"), "CAD", ORACLE_AS_OF - timedelta(days=1), "Synthetic fake",
                      DelayClass.DELAYED, ORACLE_FETCHED_AT)
        provider.fetch_latest = lambda listings: {TORONTO: older}
        result = quotes.latest([TORONTO])[TORONTO]
        self.assertEqual(result.status, QuoteStatus.FRESH)
        self.assertEqual(result.quote.price, Decimal("41.27"))

    def test_history_failure_returns_last_valid_bars_marked_stale(self):
        provider, clock = FakeQuoteProvider(), Clock()
        quotes = service(provider, clock, cache_seconds=60)
        start, end = date(2026, 11, 3), date(2026, 11, 6)
        fresh = quotes.history(TORONTO, start, end)
        clock.advance(61)
        provider.fetch_history = lambda listing, s, e: [
            DailyBar(TORONTO, date(2026, 11, 6), Decimal("1"), "CAD", "x"),
            DailyBar(TORONTO, date(2026, 11, 5), Decimal("1"), "CAD", "x")]
        with self.assertLogs("kurafolio.market", "WARNING"):
            stale = quotes.history(TORONTO, start, end)
        self.assertEqual((stale.status, stale.reason, stale.bars), (QuoteStatus.STALE, "unexpected_shape", fresh.bars))

    def test_history_out_of_range_or_foreign_bars_are_rejected(self):
        for bars in ([DailyBar(NEW_YORK, date(2026, 11, 4), Decimal("1"), "USD", "x")],
                     [DailyBar(TORONTO, date(2026, 10, 1), Decimal("1"), "CAD", "x")],
                     [{"day": "2026-11-04", "close": "1"}]):
            provider = FakeQuoteProvider()
            provider.fetch_history = lambda listing, s, e, bars=bars: bars
            with self.subTest(bars=bars), self.assertLogs("kurafolio.market", "WARNING"):
                result = service(provider).history(TORONTO, date(2026, 11, 3), date(2026, 11, 6))
            self.assertEqual((result.status, result.reason), (QuoteStatus.UNAVAILABLE, "unexpected_shape"))


if __name__ == "__main__":
    unittest.main()
