"""Unofficial Yahoo chart adapter against recorded synthetic responses.

The bodies below copy the endpoint's shape only; every price, time and name is
synthetic. Connections and DNS are blocked for every test.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from kurafolio.market import (DelayClass, Listing, MarketSettings, NoData, ProviderError, QuoteStatus,
                              build_quote_service)
from kurafolio.market import unofficial_yahoo
from kurafolio.market.unofficial_yahoo import YahooChartProvider, yahoo_symbol
from test_market_quotes import Clock, NetworkBlocked, OfflineTestCase

TORONTO = Listing("XTSE", "VEQT")
NEW_YORK = Listing("ARCX", "VTI")
NOW = datetime(2026, 11, 6, 21, 5, tzinfo=timezone.utc)
# 2026-11-06 20:45:00 UTC and the market opens (14:30 UTC) of 2026-11-03..06.
MARKET_TIME = 1793997900
OPENS = [1793716200, 1793802600, 1793889000, 1793975400]


def chart(symbol, currency="CAD", price=Decimal("41.27"), zone="America/Toronto", closes=None,
          stamps=None, hint=2):
    meta = {"currency": currency, "symbol": symbol, "exchangeName": "SYN", "instrumentType": "ETF",
            "regularMarketTime": MARKET_TIME, "exchangeTimezoneName": zone, "regularMarketPrice": price,
            "priceHint": hint, "dataGranularity": "1d"}
    result = {"meta": meta}
    if closes is not None:
        result["timestamp"] = OPENS if stamps is None else stamps
        result["indicators"] = {"quote": [{"close": closes}]}
    return {"chart": {"result": [result], "error": None}}


def encode(body):
    # Serialize Decimal values as JSON numbers, as the endpoint does.
    return json.dumps(body, default=lambda value: float(value)).encode()


class Transport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []

    def __call__(self, url, timeout):
        self.urls.append(url)
        status, body = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return status, body if isinstance(body, bytes) else encode(body)


def provider(*responses):
    transport = Transport(*responses)
    return YahooChartProvider(transport, clock=lambda: NOW), transport


def after_close():
    # The first moment of 2026-11-07 in Toronto: every bar through 2026-11-06 is final.
    return datetime(2026, 11, 7, 5, 0, tzinfo=timezone.utc)


class SymbolTests(OfflineTestCase):
    def test_exchange_suffixes_and_class_shares(self):
        self.assertEqual(yahoo_symbol(TORONTO), "VEQT.TO")
        self.assertEqual(yahoo_symbol(Listing("XTSX", "ABC")), "ABC.V")
        self.assertEqual(yahoo_symbol(NEW_YORK), "VTI")
        self.assertEqual(yahoo_symbol(Listing("XTSE", "RCI.B")), "RCI-B.TO")
        self.assertEqual(yahoo_symbol(Listing("XNYS", "BRK.B")), "BRK-B")
        self.assertIsNone(yahoo_symbol(Listing("XLON", "VWRL")))

    def test_unsupported_exchange_makes_no_request(self):
        source, transport = provider((200, chart("VWRL")))
        self.assertEqual(source.fetch_latest([Listing("XLON", "VWRL")]),
                         {Listing("XLON", "VWRL"): NoData("unsupported_exchange")})
        self.assertEqual(transport.urls, [])


class SuccessTests(OfflineTestCase):
    def test_latest_toronto_and_us_quotes(self):
        source, transport = provider((200, chart("VEQT.TO")),
                                     (200, chart("VTI", "USD", Decimal("287.153"), "America/New_York", hint=3)))
        answer = source.fetch_latest([TORONTO, NEW_YORK])
        toronto, us = answer[TORONTO], answer[NEW_YORK]
        self.assertEqual((toronto.price, toronto.currency, toronto.source, toronto.delay_class),
                         (Decimal("41.27"), "CAD", "Yahoo Finance unofficial", DelayClass.DELAYED))
        self.assertEqual(toronto.as_of, datetime(2026, 11, 6, 20, 45, tzinfo=timezone.utc))
        self.assertEqual(toronto.fetched_at, NOW)
        self.assertRegex(toronto.evidence_sha256, "^[0-9a-f]{64}$")
        self.assertEqual((us.price, us.currency), (Decimal("287.153"), "USD"))
        first = urlsplit(transport.urls[0])
        self.assertEqual((first.scheme, first.netloc, first.path),
                         ("https", "query1.finance.yahoo.com", "/v8/finance/chart/VEQT.TO"))
        self.assertEqual(parse_qs(first.query), {"range": ["1d"], "interval": ["1d"]})

    def test_history_rounds_float_noise_skips_gaps_and_uses_exchange_days(self):
        closes = [Decimal("40.900001525878906"), None, Decimal("41.119998931884766"), Decimal("41.27")]
        source, transport = provider((200, chart("VEQT.TO", closes=closes)))
        source.clock = after_close
        bars = source.fetch_history(TORONTO, date(2026, 11, 3), date(2026, 11, 6))
        self.assertEqual([(bar.day, bar.close, bar.currency, bar.delay_class) for bar in bars],
                         [(date(2026, 11, 3), Decimal("40.90"), "CAD", DelayClass.END_OF_DAY),
                          (date(2026, 11, 5), Decimal("41.12"), "CAD", DelayClass.END_OF_DAY),
                          (date(2026, 11, 6), Decimal("41.27"), "CAD", DelayClass.END_OF_DAY)])
        query = parse_qs(urlsplit(transport.urls[0]).query)
        self.assertEqual(query["interval"], ["1d"])
        self.assertLess(int(query["period1"][0]), OPENS[0])
        self.assertGreater(int(query["period2"][0]), OPENS[-1])

    def test_history_drops_bars_outside_the_requested_days(self):
        source, _ = provider((200, chart("VEQT.TO", closes=[Decimal("40.9"), Decimal("41.05"),
                                                             Decimal("41.12"), Decimal("41.27")])))
        source.clock = after_close
        bars = source.fetch_history(TORONTO, date(2026, 11, 4), date(2026, 11, 5))
        self.assertEqual([bar.day for bar in bars], [date(2026, 11, 4), date(2026, 11, 5)])

    def test_history_leaves_out_todays_unfinished_bar(self):
        source, _ = provider((200, chart("VEQT.TO", closes=[Decimal("40.9"), Decimal("41.05"),
                                                             Decimal("41.12"), Decimal("41.31")])))
        # NOW is 2026-11-06 16:05 in Toronto, during trading: the 2026-11-06 bar is live.
        bars = source.fetch_history(TORONTO, date(2026, 11, 3), date(2026, 11, 6))
        self.assertEqual([bar.day for bar in bars], [date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5)])


class FailureShapeTests(OfflineTestCase):
    def latest(self, status, body):
        source, _ = provider((status, body))
        return source.fetch_latest([TORONTO])

    def assert_error(self, status, body, code):
        with self.assertRaises(ProviderError) as caught:
            self.latest(status, body)
        self.assertEqual(caught.exception.code, code)

    def test_http_errors(self):
        self.assert_error(429, b"Edge: Too Many Requests", "upstream_rate_limited")
        self.assert_error(500, b"oops", "http_error")
        self.assert_error(401, {"finance": {"result": None, "error": {"code": "Unauthorized"}}}, "http_error")
        self.assert_error(200, b"x" * (unofficial_yahoo.MAX_RESPONSE_BYTES + 1), "response_too_large")

    def test_unknown_listing_and_empty_answers(self):
        not_found = {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found"}}}
        self.assertEqual(self.latest(404, not_found), {TORONTO: NoData("unknown_listing")})
        self.assertEqual(self.latest(200, {"chart": {"result": [], "error": None}}), {TORONTO: NoData("no_data")})
        self.assertEqual(self.latest(200, chart("VEQT.TO", price=None)), {TORONTO: NoData("no_data")})
        source, _ = provider((200, chart("VEQT.TO", closes=[None, None, None, None])))
        self.assertEqual(source.fetch_history(TORONTO, date(2026, 11, 3), date(2026, 11, 6)), NoData("no_data"))
        source, _ = provider((200, chart("VEQT.TO")))
        self.assertEqual(source.fetch_history(TORONTO, date(2026, 11, 3), date(2026, 11, 6)), NoData("no_data"))

    def test_malformed_answers(self):
        for body in (b"<html>not json</html>", b"[]", {"chart": {}},
                     {"chart": {"result": None, "error": {"code": "Internal"}}},
                     chart("OTHER.TO"), chart("VEQT.TO", currency="cad"), chart("VEQT.TO", currency=None),
                     chart("VEQT.TO", price=Decimal("0")), chart("VEQT.TO", price=Decimal("-1")),
                     chart("VEQT.TO", price="41.27"), chart("VEQT.TO", price=True)):
            with self.subTest(body=body), self.assertRaises(ProviderError):
                self.latest(200, body)
        bad_time = chart("VEQT.TO")
        bad_time["chart"]["result"][0]["meta"]["regularMarketTime"] = "2026-11-06"
        with self.assertRaises(ProviderError):
            self.latest(200, bad_time)

    def test_malformed_history(self):
        for body in (chart("VEQT.TO", closes=[Decimal("1")]),
                     chart("VEQT.TO", closes=[Decimal("1")] * 4, zone="Not/AZone"),
                     chart("VEQT.TO", closes=["41"] * 4)):
            source, _ = provider((200, body))
            with self.subTest(body=body), self.assertRaises(ProviderError):
                source.fetch_history(TORONTO, date(2026, 11, 3), date(2026, 11, 6))


class TransportTests(OfflineTestCase):
    def test_client_name_bound_and_error_mapping(self):
        from io import BytesIO
        from urllib.error import HTTPError, URLError

        class Response(BytesIO):
            status = 200

        seen = {}

        def fake_open(request, timeout):
            seen["agent"] = request.get_header("User-agent")
            seen["timeout"] = timeout
            return Response(b"{}")

        with patch.object(unofficial_yahoo, "_open", fake_open):
            self.assertEqual(unofficial_yahoo.urllib_transport("https://example.test/x", 15), (200, b"{}"))
        self.assertEqual(seen, {"agent": "Kurafolio/0.1", "timeout": 15})
        not_found = HTTPError("https://example.test/x", 404, "Not Found", {}, BytesIO(b'{"chart":{}}'))
        with patch.object(unofficial_yahoo, "_open", side_effect=not_found):
            self.assertEqual(unofficial_yahoo.urllib_transport("https://example.test/x", 15), (404, b'{"chart":{}}'))
        for error in (URLError("down"), TimeoutError("slow"), ConnectionResetError()):
            with patch.object(unofficial_yahoo, "_open", side_effect=error), self.assertRaises(ProviderError) as caught:
                unofficial_yahoo.urllib_transport("https://example.test/x", 15)
            self.assertEqual(caught.exception.code, "network_error")

    def test_redirects_are_refused(self):
        from urllib.error import HTTPError
        handler = unofficial_yahoo._NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "Found", {}, "https://elsewhere.test/"))
        moved = HTTPError("https://example.test/x", 302, "Found", {}, None)
        with patch.object(unofficial_yahoo, "_open", side_effect=moved):
            self.assertEqual(unofficial_yahoo.urllib_transport("https://example.test/x", 15), (302, b""))


class IntegrationTests(OfflineTestCase):
    def enabled(self, transport, clock):
        settings = MarketSettings(provider="unofficial-yahoo-chart", accept_unofficial_terms=True)
        registry = {"unofficial-yahoo-chart": lambda s: YahooChartProvider(transport, clock=clock)}
        registry["unofficial-yahoo-chart"].unofficial = True
        return build_quote_service(settings, registry, clock=clock)

    def test_registered_but_not_started_without_operator_acceptance(self):
        with self.assertRaisesRegex(ValueError, "accept_unofficial_terms"):
            build_quote_service(MarketSettings(provider="unofficial-yahoo-chart"))

    def test_shipped_configuration_sends_nothing(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("no request expected")):
            quotes = build_quote_service()
            self.assertEqual(quotes.latest([TORONTO])[TORONTO].status, QuoteStatus.NO_PROVIDER)

    def test_real_transport_is_stopped_by_the_network_guard(self):
        quotes = build_quote_service(MarketSettings(provider="unofficial-yahoo-chart", accept_unofficial_terms=True),
                                     clock=Clock(NOW))
        with self.assertRaises(NetworkBlocked):
            quotes.latest([TORONTO])
        self.assertTrue(self.network_attempts)
        self.network_attempts.clear()

    def test_two_users_in_the_cache_window_cause_one_request(self):
        transport, clock = Transport((200, chart("VEQT.TO"))), Clock(NOW)
        quotes = self.enabled(transport, clock)
        quotes.latest([TORONTO])
        clock.advance(30)
        self.assertEqual(quotes.latest([TORONTO])[TORONTO].quote.price, Decimal("41.27"))
        self.assertEqual(len(transport.urls), 1)

    def test_failure_after_success_is_stale_and_logged_without_url(self):
        transport, clock = Transport((200, chart("VEQT.TO")), (500, b"secret body")), Clock(NOW)
        quotes = self.enabled(transport, clock)
        quotes.latest([TORONTO])
        clock.advance(61)
        with self.assertLogs("kurafolio.market", "WARNING") as logs:
            result = quotes.latest([TORONTO])[TORONTO]
        self.assertEqual((result.status, result.reason, result.quote.price),
                         (QuoteStatus.STALE, "http_error", Decimal("41.27")))
        joined = "\n".join(logs.output)
        self.assertNotIn("https://", joined)
        self.assertNotIn("secret body", joined)


if __name__ == "__main__":
    unittest.main()
