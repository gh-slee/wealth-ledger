"""Spike probe for official keyed quote providers (WL-P0-009E).

For each provider whose key file exists, request the latest quote and recent
daily history for a fixed set of public listings and print a summary of what
came back. Only public market data is summarized: price, currency, time, bar
count and status. Keys are read from files outside the repository and never
printed, logged or written; URLs are never printed because some providers carry
the key in the query string.

    PYTHONPATH=src python scripts/market_provider_spike.py \
        --key-dir ~/.config/kurafolio-spike --output work/market-spike.json

The key directory holds one file per provider, named ``<provider>.key``
(for example ``alphavantage.key``). A missing file skips that provider.
Each run spends about two requests per listing per provider; see the
budget table in docs/market-provider-spike.md before running it.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

CLIENT_NAME = "Kurafolio-spike/0.1"
MAX_BYTES = 2 << 20
TIMEOUT = 20

# (MIC, symbol, role). Two Toronto ETFs, two US ETFs, one stock per market and
# a bond ETF on each market.
LISTINGS = (
    ("XTSE", "VEQT", "Toronto ETF"),
    ("XTSE", "XIC", "Toronto ETF"),
    ("ARCX", "VTI", "US ETF"),
    ("ARCX", "SPY", "US ETF"),
    ("XTSE", "RY", "Toronto stock"),
    ("XNAS", "AAPL", "US stock"),
    ("XTSE", "ZAG", "Toronto bond ETF"),
    ("XNAS", "BND", "US bond ETF"),
)
RATE_HEADERS = ("retry-after", "x-ratelimit-limit", "x-ratelimit-remaining",
                "api-credits-used", "api-credits-left")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_get(url, headers=None):
    """Return (status, rate headers, parsed JSON or None). Never raises with the URL."""
    request = Request(url, headers={"User-Agent": CLIENT_NAME, "Accept": "application/json", **(headers or {})})
    try:
        from kurafolio.prices import tls_context
        opener = build_opener(HTTPSHandler(context=tls_context()), _NoRedirect)
    except ImportError:
        opener = build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            status, head, raw = response.status, response.headers, response.read(MAX_BYTES + 1)
    except HTTPError as error:
        status, head, raw = error.code, error.headers, error.read(MAX_BYTES + 1)
    except (URLError, OSError, ValueError):
        return None, {}, None
    rate = {name: head.get(name) for name in RATE_HEADERS if head and head.get(name) is not None}
    if len(raw) > MAX_BYTES:
        return status, rate, None
    try:
        return status, rate, json.loads(raw)
    except ValueError:
        return status, rate, None


def _dec(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() and result > 0 else None


def _iso(value):
    return value.astimezone(timezone.utc).isoformat() if value else None


def _bars(rows):
    """rows: iterable of (date string, close). Returns a short summary."""
    clean = sorted((day, close) for day, close in rows if _dec(close) is not None)
    if not clean:
        return {"bars": 0}
    return {"bars": len(clean), "first_day": clean[0][0], "last_day": clean[-1][0], "last_close": str(_dec(clean[-1][1]))}


def _note(body):
    """Short provider message for refusals, trimmed; bodies never carry the key."""
    if isinstance(body, dict):
        for field in ("Note", "Information", "Error Message", "message", "error"):
            if isinstance(body.get(field), str):
                return body[field][:160]
    if isinstance(body, str):
        return body[:160]
    return None


class AlphaVantage:
    name = "alphavantage"
    base = "https://www.alphavantage.co/query?"
    suffix = {"XTSE": ".TRT", "XTSX": ".TRV"}

    def __init__(self, key):
        self._key = key

    def symbol(self, mic, symbol):
        return symbol + self.suffix.get(mic, "")

    def latest(self, mic, symbol):
        status, rate, body = http_get(self.base + urlencode(
            {"function": "GLOBAL_QUOTE", "symbol": self.symbol(mic, symbol), "apikey": self._key}))
        quote = (body or {}).get("Global Quote") if isinstance(body, dict) else None
        if quote and _dec(quote.get("05. price")):
            return {"status": status, "rate": rate, "price": str(_dec(quote["05. price"])),
                    "currency": None, "as_of": quote.get("07. latest trading day")}
        return {"status": status, "rate": rate, "error": _note(body) or "no_quote"}

    def history(self, mic, symbol):
        status, rate, body = http_get(self.base + urlencode(
            {"function": "TIME_SERIES_DAILY", "symbol": self.symbol(mic, symbol), "outputsize": "compact", "apikey": self._key}))
        series = (body or {}).get("Time Series (Daily)") if isinstance(body, dict) else None
        if isinstance(series, dict):
            return {"status": status, "rate": rate, **_bars((day, row.get("4. close")) for day, row in series.items())}
        return {"status": status, "rate": rate, "error": _note(body) or "no_history"}


class TwelveData:
    name = "twelvedata"
    base = "https://api.twelvedata.com/"

    def __init__(self, key):
        self._key = key

    def _get(self, path, params):
        return http_get(self.base + path + "?" + urlencode(params), {"Authorization": "apikey " + self._key})

    def latest(self, mic, symbol):
        status, rate, body = self._get("quote", {"symbol": symbol, "mic_code": mic})
        if isinstance(body, dict) and _dec(body.get("close")):
            stamp = body.get("last_quote_at") or body.get("timestamp")
            as_of = datetime.fromtimestamp(int(stamp), timezone.utc) if str(stamp).isdigit() else None
            return {"status": status, "rate": rate, "price": str(_dec(body["close"])), "currency": body.get("currency"),
                    "as_of": _iso(as_of) or body.get("datetime"), "is_market_open": body.get("is_market_open")}
        return {"status": status, "rate": rate, "error": _note(body) or "no_quote"}

    def history(self, mic, symbol):
        status, rate, body = self._get("time_series", {"symbol": symbol, "mic_code": mic, "interval": "1day", "outputsize": 30})
        if isinstance(body, dict) and isinstance(body.get("values"), list):
            meta = body.get("meta") or {}
            return {"status": status, "rate": rate, "currency": meta.get("currency"),
                    **_bars((row.get("datetime"), row.get("close")) for row in body["values"])}
        return {"status": status, "rate": rate, "error": _note(body) or "no_history"}


class Finnhub:
    name = "finnhub"
    base = "https://finnhub.io/api/v1/"
    suffix = {"XTSE": ".TO", "XTSX": ".V"}

    def __init__(self, key):
        self._key = key

    def _get(self, path, params):
        return http_get(self.base + path + "?" + urlencode(params), {"X-Finnhub-Token": self._key})

    def latest(self, mic, symbol):
        status, rate, body = self._get("quote", {"symbol": symbol + self.suffix.get(mic, "")})
        if isinstance(body, dict) and _dec(body.get("c")):
            stamp = body.get("t")
            as_of = datetime.fromtimestamp(int(stamp), timezone.utc) if isinstance(stamp, int) and stamp > 0 else None
            return {"status": status, "rate": rate, "price": str(_dec(body["c"])), "currency": None, "as_of": _iso(as_of)}
        return {"status": status, "rate": rate, "error": _note(body) or "no_quote"}

    def history(self, mic, symbol):
        end = datetime.now(timezone.utc)
        status, rate, body = self._get("stock/candle", {
            "symbol": symbol + self.suffix.get(mic, ""), "resolution": "D",
            "from": int((end - timedelta(days=45)).timestamp()), "to": int(end.timestamp())})
        if isinstance(body, dict) and body.get("s") == "ok":
            days = [datetime.fromtimestamp(t, timezone.utc).date().isoformat() for t in body.get("t", [])]
            return {"status": status, "rate": rate, **_bars(zip(days, body.get("c", [])))}
        return {"status": status, "rate": rate, "error": _note(body) or "no_history"}


class Eodhd:
    name = "eodhd"
    base = "https://eodhd.com/api/"
    suffix = {"XTSE": ".TO", "XTSX": ".V"}

    def __init__(self, key):
        self._key = key

    def symbol(self, mic, symbol):
        return symbol + self.suffix.get(mic, ".US")

    def latest(self, mic, symbol):
        status, rate, body = http_get(self.base + "real-time/" + self.symbol(mic, symbol) + "?" + urlencode(
            {"api_token": self._key, "fmt": "json"}))
        if isinstance(body, dict) and _dec(body.get("close")):
            stamp = body.get("timestamp")
            as_of = datetime.fromtimestamp(int(stamp), timezone.utc) if isinstance(stamp, int) and stamp > 0 else None
            return {"status": status, "rate": rate, "price": str(_dec(body["close"])), "currency": None, "as_of": _iso(as_of)}
        return {"status": status, "rate": rate, "error": _note(body) or "no_quote"}

    def history(self, mic, symbol):
        start = (date.today() - timedelta(days=45)).isoformat()
        status, rate, body = http_get(self.base + "eod/" + self.symbol(mic, symbol) + "?" + urlencode(
            {"api_token": self._key, "fmt": "json", "from": start}))
        if isinstance(body, list):
            return {"status": status, "rate": rate, **_bars((row.get("date"), row.get("close")) for row in body if isinstance(row, dict))}
        return {"status": status, "rate": rate, "error": _note(body) or "no_history"}


PROVIDERS = {cls.name: cls for cls in (AlphaVantage, TwelveData, Finnhub, Eodhd)}


def _scrub(value, secrets):
    text = json.dumps(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return json.loads(text)


def _delay(fetched, as_of):
    try:
        observed = datetime.fromisoformat(as_of)
    except (TypeError, ValueError):
        return None
    if observed.tzinfo is None:
        return None
    return int((fetched - observed).total_seconds())


def run(key_dir, only=None, listings=LISTINGS, now=datetime.now):
    results, secrets = [], []
    for name, cls in PROVIDERS.items():
        if only and name not in only:
            continue
        path = Path(key_dir).expanduser() / f"{name}.key"
        if not path.is_file():
            results.append({"provider": name, "skipped": "no_key_file"})
            continue
        key = path.read_text(encoding="utf-8").strip()
        secrets.append(key)
        provider = cls(key)
        rows = []
        for mic, symbol, role in listings:
            latest = provider.latest(mic, symbol)
            fetched = now(timezone.utc)
            latest["fetched_at"] = fetched.isoformat()
            latest["observed_delay_seconds"] = _delay(fetched, latest.get("as_of"))
            rows.append({"listing": f"{mic}:{symbol}", "role": role, "latest": latest,
                         "history": provider.history(mic, symbol)})
        results.append({"provider": name, "listings": rows})
    return _scrub({"run_at": now(timezone.utc).isoformat(), "results": results}, secrets)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--key-dir", required=True, help="directory outside the repository with <provider>.key files")
    parser.add_argument("--output", type=Path, help="write the JSON summary here (keep it outside tracked paths)")
    parser.add_argument("--provider", action="append", choices=sorted(PROVIDERS), help="limit to these providers")
    args = parser.parse_args(argv)
    report = run(args.key_dir, set(args.provider or ()))
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
