"""Fetch and freeze official reference exchange rates; never send portfolio data."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import hashlib
import json
import re
import urllib.request
from .prices import tls_context

BOC_URL = "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json"
CBC_URL = "https://www.cbc.gov.tw/tw/mp-1.html"


def _download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "WealthLedger/1.0"})
    with urllib.request.urlopen(request, timeout=25, context=tls_context()) as response:
        return response.read().decode("utf-8-sig")


def _select(rows, requested):
    eligible = [(day, value) for day, value in rows if day <= requested]
    if not eligible:
        raise ValueError("No published exchange rate on or before the snapshot date")
    day, value = max(eligible)
    if (requested - day).days > 10:
        raise ValueError("Latest applicable rate is more than 10 days old; supply a verified FX file")
    return day.isoformat(), str(Decimal(value))


def parse_cbc_html(html):
    """Read the first official homepage chart's paired date/value arrays."""
    values = re.search(r"var\s+chartNum\s*=\s*\[\s*\[([^\]]+)\]", html)
    dates = re.search(r"var\s+chartDate\s*=\s*\[\s*\[([^\]]+)\]", html)
    if values and dates:
        numbers = [x.strip() for x in values.group(1).split(",")]
        days = re.findall(r"['\"](\d{4}/\d{2}/\d{2})['\"]", dates.group(1))
        if len(numbers) != len(days) or not days:
            raise ValueError("CBC chart dates and values do not match")
        return [(date.fromisoformat(day.replace("/", "-")), str(Decimal(value)))
                for day, value in zip(days, numbers)]
    match = re.search(r"新臺幣/美元銀行間收盤匯率</h3>\s*<span class=\"date\">(\d{4}-\d{2}-\d{2})</span>\s*<span class=\"info\"><em>([0-9.]+)</em>", html)
    if not match:
        raise ValueError("CBC page format changed; supply a verified FX file")
    return [(date.fromisoformat(match.group(1)), match.group(2))]


def validate_rates(data, snapshot_date):
    requested = date.fromisoformat(snapshot_date)
    for prefix in ("usd_cad", "usd_twd"):
        rate = Decimal(str(data[prefix]))
        if not rate.is_finite() or rate <= 0:
            raise ValueError(f"Invalid {prefix} exchange rate")
        effective = date.fromisoformat(data[prefix + "_date"])
        if effective > requested or (requested - effective).days > 10:
            raise ValueError(f"Inapplicable {prefix} effective date")
        if not data.get(prefix + "_source"):
            raise ValueError(f"Missing {prefix} source")
    return data


def read_saved_rates(project, snapshot_date, override=None):
    """Validate an override or exact-date cache without network or file writes."""
    target = Path(override) if override else Path(project) / "data/fx" / f"{snapshot_date}.json"
    if not target.exists() and not override:
        return None
    return validate_rates(json.loads(target.read_text(encoding="utf-8")), snapshot_date)


def resolve_rates(project, snapshot_date, override=None):
    """Reuse frozen date cache, otherwise fetch public rates and archive evidence."""
    project = Path(project)
    requested = date.fromisoformat(snapshot_date)
    target = project / "data" / "fx" / f"{snapshot_date}.json"
    saved = read_saved_rates(project, snapshot_date, override)
    if saved is not None:
        return saved
    start = (requested - timedelta(days=10)).isoformat()
    boc_query = f"{BOC_URL}?start_date={start}&end_date={snapshot_date}"
    boc_text = _download(boc_query)
    cbc_text = _download(CBC_URL)
    observations = json.loads(boc_text)["observations"]
    cad_date, cad = _select([(date.fromisoformat(item["d"]), item["FXUSDCAD"]["v"])
                             for item in observations if "FXUSDCAD" in item], requested)
    twd_date, twd = _select(parse_cbc_html(cbc_text), requested)
    result = validate_rates({
        "usd_cad": cad, "usd_twd": twd,
        "usd_cad_date": cad_date, "usd_twd_date": twd_date,
        "usd_cad_source": "https://www.bankofcanada.ca/rates/exchange/daily-exchange-rates/",
        "usd_twd_source": CBC_URL,
        "requested_date": snapshot_date,
        "policy": "latest_published_on_or_before_snapshot_date",
        "evidence_sha256": {
            "boc": hashlib.sha256(boc_text.encode()).hexdigest(),
            "cbc": hashlib.sha256(cbc_text.encode()).hexdigest()
        }
    }, snapshot_date)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    target.chmod(0o600)
    evidence = target.parent / "evidence" / snapshot_date
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "bank-of-canada.json").write_text(boc_text, encoding="utf-8")
    (evidence / "cbc.html").write_text(cbc_text, encoding="utf-8")
    return result
