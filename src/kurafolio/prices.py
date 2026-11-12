"""Freeze a public BTC reference price at or before a portfolio valuation."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import hashlib
import json
import ssl


def tls_context():
    import certifi
    return ssl.create_default_context(cafile=certifi.where())


def parse_time(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Valuation timestamp must include a timezone")
    return stamp.astimezone(timezone.utc)


def select_candle(rows, as_of):
    cutoff = parse_time(as_of)
    eligible = []
    for row in rows:
        if len(row) != 6:
            raise ValueError("Invalid Coinbase candle structure")
        start = datetime.fromtimestamp(int(row[0]), timezone.utc)
        end = start + timedelta(seconds=60)
        close = Decimal(str(row[4]))
        if not close.is_finite() or close <= 0:
            raise ValueError("Invalid BTC reference price")
        if end <= cutoff:
            eligible.append((end, start, close))
    if not eligible:
        raise ValueError("No completed BTC candle at or before the valuation")
    end, start, close = max(eligible)
    if cutoff - end > timedelta(minutes=5):
        raise ValueError("BTC reference candle is more than five minutes old")
    return {"candle_start": start.isoformat(), "candle_end": end.isoformat(),
            "close": str(close), "granularity_seconds": 60,
            "price_age_seconds": int((cutoff-end).total_seconds())}


def validate_quote(quote, as_of):
    if parse_time(quote["as_of"]) != parse_time(as_of):
        raise ValueError("BTC quote belongs to a different valuation timestamp")
    if quote.get("pair") != "BTC-USD" or not quote.get("provider") or not quote.get("source_url"):
        raise ValueError("BTC quote requires provider, source URL, and BTC-USD pair")
    close = Decimal(str(quote["close"]))
    if not close.is_finite() or close <= 0:
        raise ValueError("BTC quote must be positive and finite")
    start, end = parse_time(quote["candle_start"]), parse_time(quote["candle_end"])
    if end-start != timedelta(seconds=60) or end > parse_time(as_of):
        raise ValueError("BTC quote must use a completed one-minute candle")
    if parse_time(as_of)-end > timedelta(minutes=5):
        raise ValueError("BTC quote is more than five minutes old")
    return quote


def read_saved_quote(project, as_of, override=None):
    """Validate a supplied or exact-cutoff quote; never fetch or save a price."""
    project = Path(project)
    key = parse_time(as_of).strftime("%Y-%m-%dT%H%M%S%z")
    target = Path(override) if override else project / "data/prices" / f"btc-usd-{key}.json"
    if not target.exists() and not override:
        return None
    quote = validate_quote(json.loads(target.read_text(encoding="utf-8")), as_of)
    if not override:
        evidence = project / quote["evidence_path"]
        if not evidence.exists() or hashlib.sha256(evidence.read_bytes()).hexdigest() != quote["evidence_sha256"]:
            raise ValueError("Frozen BTC quote evidence is missing or has changed")
    return quote


def resolve_btc_price(project, as_of, override=None):
    project = Path(project)
    stamp = parse_time(as_of)
    key = stamp.strftime("%Y-%m-%dT%H%M%S%z")
    target = project / "data/prices" / f"btc-usd-{key}.json"
    saved = read_saved_quote(project, as_of, override)
    if saved is not None:
        return saved
    start = stamp-timedelta(minutes=10)
    query = urlencode({"granularity": 60, "start": start.isoformat(), "end": stamp.isoformat()})
    url = "https://api.exchange.coinbase.com/products/BTC-USD/candles?"+query
    with urlopen(Request(url, headers={"User-Agent": "WealthLedger/1.0"}),
                 context=tls_context(), timeout=30) as response:
        raw = response.read()
        status = response.status
    candle = select_candle(json.loads(raw, parse_float=Decimal), as_of)
    evidence = target.parent / "evidence" / f"coinbase-{key}.json"
    quote = {"provider": "Coinbase Exchange", "pair": "BTC-USD", "as_of": as_of,
             **candle, "source_url": url, "http_status": status,
             "fetched_at": datetime.now(timezone.utc).isoformat(),
             "evidence_path": str(evidence.relative_to(project)),
             "evidence_sha256": hashlib.sha256(raw).hexdigest(),
             "policy": "last_completed_one_minute_candle_on_or_before_valuation"}
    validate_quote(quote, as_of)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_bytes(raw)
    evidence.chmod(0o600)
    target.write_text(json.dumps(quote, indent=2)+"\n", encoding="utf-8")
    target.chmod(0o600)
    return quote
