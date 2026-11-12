"""Optional adapter for the unofficial Yahoo Finance chart endpoint.

The owner approved this endpoint on 2026-11-12 (WL-P0-009A). It is not a
documented public API: it can change or disappear without notice, and whether
its terms of use allow a given use is the instance operator's responsibility.
It is off unless the operator sets ``provider: unofficial-yahoo-chart`` and
``accept_unofficial_terms: true``.

A request carries only the listing's symbol and a date range. The adapter sends
its own client name and never imitates a browser.
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote as url_quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .contract import DailyBar, DelayClass, NoData, ProviderError, Quote

NAME = "unofficial-yahoo-chart"
SOURCE = "Yahoo Finance unofficial"
BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
CLIENT_NAME = "Kurafolio/0.1"
MAX_RESPONSE_BYTES = 1 << 20
TIMEOUT_SECONDS = 15
# MIC -> Yahoo suffix. Other exchanges are answered "unsupported_exchange"
# without a request.
SUFFIXES = {
    "XTSE": ".TO",   # Toronto Stock Exchange
    "XTSX": ".V",    # TSX Venture Exchange
    "XNYS": "", "XNAS": "", "ARCX": "", "BATS": "", "XASE": "",  # US exchanges
}


def yahoo_symbol(listing):
    """Return the endpoint's symbol for a listing, or None when unsupported.
    Class shares use a dash on the endpoint (``RCI.B`` on XTSE is ``RCI-B.TO``)."""
    suffix = SUFFIXES.get(listing.mic)
    if suffix is None:
        return None
    return listing.symbol.replace(".", "-") + suffix


def urllib_transport(url, timeout):
    """GET ``url``; return ``(status, body)`` with the body bounded."""
    from kurafolio.prices import tls_context
    request = Request(url, headers={"User-Agent": CLIENT_NAME, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout, context=tls_context()) as response:
            return response.status, response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        try:
            body = error.read(MAX_RESPONSE_BYTES + 1) if error.fp else b""
        except OSError:
            body = b""
        finally:
            error.close()
        return error.code, body
    except (URLError, OSError, ValueError):
        raise ProviderError("network_error") from None


class YahooChartProvider:
    name = SOURCE
    delay_class = DelayClass.DELAYED
    max_batch_size = 1  # the multi-symbol endpoint needs a session; one symbol per request

    def __init__(self, transport=urllib_transport, clock=None):
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def fetch_latest(self, listings):
        return {listing: self._latest(listing) for listing in listings}

    def fetch_history(self, listing, start, end):
        symbol = yahoo_symbol(listing)
        if symbol is None:
            return NoData("unsupported_exchange")
        # Pad by a day on each side so exchange-local days near midnight UTC are
        # included; bars outside start..end are dropped below.
        period1 = datetime.combine(start - timedelta(days=1), time(), timezone.utc)
        period2 = datetime.combine(end + timedelta(days=2), time(), timezone.utc)
        query = {"period1": int(period1.timestamp()), "period2": int(period2.timestamp()), "interval": "1d"}
        result, _ = self._chart(symbol, query)
        if isinstance(result, NoData):
            return result
        meta = result["meta"]
        currency = _currency(meta)
        zone = _zone(meta)
        stamps = result.get("timestamp") or []
        try:
            closes = result["indicators"]["quote"][0]["close"]
        except (KeyError, IndexError, TypeError):
            if not stamps:
                return NoData("no_data")
            raise ProviderError("unexpected_shape") from None
        if not isinstance(stamps, list) or not isinstance(closes, list) or len(stamps) != len(closes):
            raise ProviderError("unexpected_shape")
        hint = _price_hint(meta)
        bars = {}
        for stamp, close in zip(stamps, closes):
            if close is None:  # the endpoint leaves holidays and gaps empty
                continue
            day = _instant(stamp).astimezone(zone).date()
            if start <= day <= end:
                bars[day] = DailyBar(listing, day, _decimal(close, hint), currency, SOURCE)
        if not bars:
            return NoData("no_data")
        return [bars[day] for day in sorted(bars)]

    def _latest(self, listing):
        symbol = yahoo_symbol(listing)
        if symbol is None:
            return NoData("unsupported_exchange")
        result, raw = self._chart(symbol, {"range": "1d", "interval": "1d"})
        if isinstance(result, NoData):
            return result
        meta = result["meta"]
        if meta.get("regularMarketPrice") is None or meta.get("regularMarketTime") is None:
            return NoData("no_data")
        try:
            return Quote(listing, _decimal(meta["regularMarketPrice"], _price_hint(meta)), _currency(meta),
                         _instant(meta["regularMarketTime"]), SOURCE, self.delay_class, self.clock(),
                         hashlib.sha256(raw).hexdigest())
        except ValueError:
            raise ProviderError("unexpected_shape") from None

    def _chart(self, symbol, query):
        url = BASE_URL + url_quote(symbol, safe="") + "?" + urlencode(query)
        status, raw = self.transport(url, TIMEOUT_SECONDS)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderError("response_too_large")
        if status == 429:
            raise ProviderError("upstream_rate_limited")
        if status == 404:
            return NoData("unknown_listing"), raw
        if status != 200:
            raise ProviderError("http_error")
        try:
            body = json.loads(raw, parse_float=Decimal)
            chart = body["chart"]
            if chart.get("error"):
                raise ProviderError("upstream_error")
            results = chart["result"]
            if not results:
                return NoData("no_data"), raw
            result = results[0]
            meta = result["meta"]
            if not isinstance(meta, dict) or meta.get("symbol") != symbol:
                raise ProviderError("unexpected_shape")
            return result, raw
        except ProviderError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError, IndexError):
            raise ProviderError("unexpected_shape") from None


def _currency(meta):
    currency = meta.get("currency")
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isascii() or not currency.isupper():
        raise ProviderError("unexpected_shape")  # also rejects minor units such as "GBp"
    return currency


def _zone(meta):
    try:
        return ZoneInfo(str(meta["exchangeTimezoneName"]))
    except (KeyError, ZoneInfoNotFoundError, ValueError):
        raise ProviderError("unexpected_shape") from None


def _price_hint(meta):
    hint = meta.get("priceHint")
    return hint if type(hint) is int and 0 <= hint <= 6 else None


def _instant(value):
    if type(value) is not int or value <= 0:
        raise ProviderError("unexpected_shape")
    return datetime.fromtimestamp(value, timezone.utc)


def _decimal(value, hint):
    """Read a JSON number as Decimal from its text. History closes carry binary
    noise (62.15999984741211), so round to the listing's price hint when given."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise ProviderError("unexpected_shape")
    try:
        number = Decimal(value)
        if hint is not None:
            number = number.quantize(Decimal(1).scaleb(-hint))
    except InvalidOperation:
        raise ProviderError("unexpected_shape") from None
    if not number.is_finite() or number <= 0:
        raise ProviderError("unexpected_shape")
    return number


def factory(settings):
    return YahooChartProvider()


factory.unofficial = True
