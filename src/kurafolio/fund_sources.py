"""Download and parse public issuer holdings; never submit portfolio data."""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from decimal import Decimal
from html import unescape
from html.parser import HTMLParser
from http.cookiejar import CookieJar
import io
import json
from pathlib import Path
import re
import hashlib
import urllib.request
from urllib.parse import urljoin
import zipfile
import xml.etree.ElementTree as ET

from .prices import tls_context

VERSION = "issuer-holdings-2"
D = Decimal
REGISTRY = {
    "XTSE:VEQT": {"issuer": "Vanguard", "adapter": "vanguard", "port": "9692", "expected_name": "all-equity", "max_age": 95,
                  "url": "https://www.vanguard.ca/en/product/etf/asset-allocation/9692/vanguard-all-equity-etf-portfolio"},
    "XTSE:VFV": {"issuer": "Vanguard", "adapter": "vanguard", "port": "9563", "expected_name": "s&p 500", "max_age": 95,
                 "url": "https://www.vanguard.ca/en/product/etf/equity/9563/vanguard-sp-500-index-etf"},
    "XTSE:XCHP": {"issuer": "BlackRock", "adapter": "blackrock", "max_age": 14,
                  "url": "https://www.blackrock.com/ca/investors/en/products/332756/ishares-semiconductor-index-etf"},
    "XNAS:SMH": {"issuer": "VanEck", "adapter": "vaneck", "max_age": 14,
                 "url": "https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/holdings/"},
    "XTSE:ZNQ": {"issuer": "BMO", "adapter": "bmo", "max_age": 14,
                 "url": "https://www.bmogam.com/ca-en/products/exchange-traded-fund/bmo-nasdaq-100-equity-index-etf-znq/"},
    "XTSE:FBTC": {"issuer": "Fidelity Canada", "adapter": "fidelity", "max_age": 185,
                  "url": "https://www.fidelity.ca/en/products/etfs/fbtc/"},
    "XTSE:QQC": {"issuer": "CI Global Asset Management", "adapter": "ci", "max_age": 95,
                 "url": "https://funds.cifinancial.com/en/create-html-for-pdf.html?series_id=49756"},
    "XNAS:QQQM": {"issuer": "Invesco US", "adapter": "invesco", "max_age": 14,
                  "url": "https://www.invesco.com/us/en/financial-products/etfs/invesco-nasdaq-100-etf.html"},
}


def weight(value, percent=True):
    result = D(str(value).strip().replace(",", "").replace("%", ""))
    if not result.is_finite():
        raise ValueError("Non-finite holding weight")
    result = result / 100 if percent else result
    if abs(result) > 2:
        raise ValueError("Holding weight outside supported range")
    return result


def holding(name, value, kind="equity", ticker="", country="", identifiers=None, fund_id=None, percent=True,
            gics_sector=None, icb_sector=None, issuer_sector=None):
    if not name or not str(name).strip():
        raise ValueError("Missing holding name")
    return {"name": str(name).strip(), "weight": str(weight(value, percent)), "kind": kind,
            "ticker": ticker or "", "country": country or "", "identifiers": identifiers or {}, "fund_id": fund_id,
            "gics_sector": gics_sector or "", "icb_sector": icb_sector or "", "issuer_sector": issuer_sector or ""}


def classify(asset):
    text = str(asset or "").lower()
    if any(term in text for term in ("common stock", "preferred stock", "equity", "stock", "eq.", "reit", "depositary receipt", "depository receipt", "ordinary shares")):
        return "equity"
    if any(term in text for term in ("cash", "currency", "money market")):
        return "cash"
    if any(term in text for term in ("bond", "fixed income")):
        return "bond"
    return "unknown"


class Client:
    """Cookie-aware HTTPS client with bounded downloads and immutable evidence."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=tls_context()),
                                                 urllib.request.HTTPCookieProcessor(CookieJar()))
        self.evidence = []

    def get(self, url, body=None, headers=None):
        request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                  headers={"User-Agent": "Mozilla/5.0 WealthLedger/1", "Accept": "*/*",
                           **({"Content-Type": "application/json"} if body is not None else {}), **(headers or {})})
        with self.opener.open(request, timeout=35) as response:
            data = response.read(24_000_001)
            final_url = response.geturl()
        if len(data) > 24_000_000:
            raise ValueError("Issuer response exceeds size limit")
        sha = hashlib.sha256(data).hexdigest()
        path = self.directory / f"{len(self.evidence)+1:02d}-{sha}.bin"
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError("Immutable evidence hash mismatch")
        else:
            path.write_bytes(data)
            path.chmod(0o400)
        self.evidence.append({"url": url, "final_url": final_url, "sha256": sha, "path": str(path),
                              "retrieved_at": datetime.now(timezone.utc).isoformat(),
                              "method": "POST" if body is not None else "GET"})
        return data

    def json(self, url, body=None, headers=None):
        result = json.loads(self.get(url, body, headers), parse_float=D)
        if isinstance(result, dict) and result.get("errors"):
            raise ValueError("Official GraphQL response contains errors")
        return result


def parse_blackrock(data):
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    as_of = datetime.strptime(rows[0][1], "%b %d, %Y").date().isoformat()
    start = next(i for i, r in enumerate(rows) if r[:2] == ["Ticker", "Name"])
    headers = rows[start]
    result = []
    for raw in rows[start+1:]:
        if not raw or len(raw) < len(headers):
            continue  # Issuer disclaimer and empty footer, not holdings rows.
        row = dict(zip(headers, raw))
        result.append(holding(row["Name"], row["Weight (%)"], classify(row["Asset Class"]),
                              row["Ticker"], row["Location"], issuer_sector=row.get("Sector")))
    if not result:
        raise ValueError("Missing BlackRock holdings")
    return as_of, result


def xlsx_rows(data):
    """Read the small issuer XLSX download using only ZIP and XML."""
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(item.file_size for item in archive.infolist()) > 24_000_000:
            raise ValueError("Oversized XLSX")
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            for node in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("s:si", ns):
                strings.append("".join(node.itertext()))
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        rows = []
        for node in root.findall(".//s:row", ns):
            row = []
            for cell in node.findall("s:c", ns):
                col = 0
                for char in re.match(r"[A-Z]+", cell.get("r")).group():
                    col = col * 26 + ord(char) - 64
                row += [""] * (col - len(row))
                value = cell.find("s:v", ns)
                if cell.get("t") == "s":
                    text = strings[int(value.text)]
                elif cell.get("t") == "inlineStr":
                    text = "".join(cell.find("s:is", ns).itertext())
                else:
                    text = value.text if value is not None else ""
                row[col-1] = text
            rows.append(row)
        return rows


def parse_vaneck(data):
    rows = xlsx_rows(data)
    match = re.search(r"(\d{2}/\d{2}/\d{4})", rows[0][0])
    if not match:
        raise ValueError("Missing VanEck date")
    as_of = datetime.strptime(match.group(1), "%m/%d/%Y").date().isoformat()
    start = next(i for i, row in enumerate(rows) if "Identifier (FIGI)" in row)
    headers = rows[start]
    result = []
    for raw in rows[start+1:]:
        if len(raw) < len(headers) or not raw[0].isdigit():
            continue
        row = dict(zip(headers, raw))
        result.append(holding(row["Holding Name"] or row["Ticker"], row["% of Net Assets"], classify(row["Asset Class"]),
                              row["Ticker"], identifiers={"figi": row["Identifier (FIGI)"]}))
    if not result:
        raise ValueError("Missing VanEck holdings")
    return as_of, result


def parse_bmo(data):
    profile = data["data"]["webProfiles"][0]
    if profile["entityId"] != "ZNQ-a":
        raise ValueError("Wrong BMO fund")
    portfolio = profile["fund"]["portfolios"][0]
    rows = [holding(row["holding"], row["allocation"], classify(row["assetClass"]), row.get("ticker"),
                    identifiers={"isin": row.get("isin")}, percent=False) for row in portfolio["allHoldings"]]
    if len(rows) < portfolio["numberOfHoldings"]:
        raise ValueError("Incomplete BMO holdings response")
    return portfolio["effectiveDate"][:10], rows


def parse_invesco(data):
    if data["cusip"] != "46138G649":
        raise ValueError("Wrong Invesco fund")
    if len(data["holdings"]) != data["totalNumberOfHoldings"]:
        raise ValueError("Incomplete Invesco holdings")
    result = []
    for row in data["holdings"]:
        if row["percentageOfTotalNetAssets"] is None:
            continue  # Unweighted entries are retained in raw evidence; residual stays unknown.
        result.append(holding(row["issuerName"], row["percentageOfTotalNetAssets"], classify(row["securityTypeName"]),
                              row.get("ticker"), identifiers={"cusip": row.get("cusip")}, issuer_sector=row.get("sectorName")))
    return data.get("effectiveBusinessDate", data["effectiveDate"])[:10], result


def parse_fidelity(data):
    if data["axisCode"] != "FBTC":
        raise ValueError("Wrong Fidelity fund")
    categories = data["holdings"]["holdingsByCategory"]
    dates = {value["asOfDate"][:10] for value in categories.values()}
    if len(dates) != 1:
        raise ValueError("Mixed Fidelity holdings dates")
    rows = []
    for category in categories.values():
        for row in category["holdings"]:
            name = row["name"]
            kind = "crypto" if name.upper() == "BITCOIN" else "cash" if "dollar" in name.lower() else "unknown"
            rows.append(holding(name, row["netPercent"], kind))
    return dates.pop(), rows


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.stack, self.cell = [], [], None
    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.stack.append({"attrs": dict(attrs), "rows": []})
        elif tag == "tr" and self.stack:
            self.stack[-1]["rows"].append([])
        elif tag in ("td", "th") and self.stack:
            self.cell = []
    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None and self.stack:
            if self.stack[-1]["rows"]:
                self.stack[-1]["rows"][-1].append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "table" and self.stack:
            self.tables.append(self.stack.pop())


def parse_ci(data):
    text = data.decode()
    if "TSX TICKER : QQC" not in text:
        raise ValueError("Wrong CI fund share class")
    parser = Tables()
    parser.feed(text)
    table = next(table for table in parser.tables if "holdings" in table["attrs"].get("class", ""))
    # CI's holdings section inherits its monthly factsheet date, not the daily NAV date.
    prefix = text[:re.search(r'<table[^>]*class="holdings"', text).start()]
    dates = re.findall(r"As at\s*(\d{4}-\d{2}-\d{2})", prefix, re.I)
    if not dates:
        raise ValueError("Missing CI holdings effective date")
    as_of = date.fromisoformat(dates[-1]).isoformat()
    rows = []
    for row in table["rows"]:
        if len(row) != 3 or not re.match(r"^\d+\.", row[0]):
            continue
        name = re.sub(r"^\d+\.\s*", "", row[0])
        fund_id = "XNAS:QQQM" if name == "Invesco NASDAQ 100 ETF (QQQM)" else None
        rows.append(holding(name, row[2], "fund" if fund_id else "unknown", fund_id=fund_id))
    if not rows:
        raise ValueError("Missing CI disclosed holdings")
    return as_of, rows


VG_QUERY = """query($portIds:[String!],$lastItemKey:String){
 funds(portIds:$portIds){profile{fundFullName primarySectorEquityClassification}}
 borHoldings(portIds:$portIds){delayeredHoldings(limit:1500,lastItemKey:$lastItemKey){
 items{issuerName marketValuePercentage sedol1 ticker securityType effectiveDate bloombergIsoCountry
 icbIndustryDescription gicsSectorDescription}
 totalHoldings lastItemKey}}}"""
BMO_QUERY = """query($locale:String,$entityId:String){webProfiles(locale:$locale,entityId:$entityId,take:1){
 entityId fundName fund{portfolios(sortDirection:\"D\",take:1){effectiveDate numberOfHoldings
 allHoldings:kb2Holdings(sortBy:\"allocation\",sortDirection:\"D\"){holding allocation ticker isin assetClass}}}}}"""


def vanguard(client, config):
    # Seed the official site's cookies before the same public GraphQL requests.
    if hasattr(client, "get"):
        client.get(config["url"])
    rows, dates, seen_keys, seen_pages = [], set(), set(), set()
    key, expected = None, None
    for _ in range(30):
        data = client.json("https://www.vanguard.ca/gpx/graphql",
                           {"query": VG_QUERY, "variables": {"portIds": [config["port"]], "lastItemKey": key}},
                           {"X-Consumer-ID": "ca0", "Origin": "https://www.vanguard.ca", "Referer": config["url"]})
        name = data["data"]["funds"][0]["profile"]["fundFullName"]
        if config["expected_name"] not in name.lower():
            raise ValueError("Wrong Vanguard fund")
        page = data["data"]["borHoldings"][0]["delayeredHoldings"]
        page_hash = hashlib.sha256(json.dumps(page["items"],sort_keys=True,default=str).encode()).hexdigest()
        if page_hash in seen_pages:
            raise ValueError("Repeated Vanguard holdings page")
        seen_pages.add(page_hash)
        if expected is not None and expected != page["totalHoldings"]:
            raise ValueError("Vanguard holdings changed during pagination")
        expected = page["totalHoldings"]
        for row in page["items"]:
            dates.add(row["effectiveDate"][:10])
            kind = "fund" if row["securityType"] == "MF.MF" else "cash" if row["securityType"] == "CRNY" else classify(row["securityType"])
            if kind == "equity" and not row["issuerName"]:
                kind = "unknown"
            rows.append(holding(row["issuerName"] or f"{row['securityType']} {row['ticker'] or 'unidentified'}", row["marketValuePercentage"], kind, row["ticker"],
                                row["bloombergIsoCountry"], {"sedol": row["sedol1"]},
                                gics_sector=row.get("gicsSectorDescription"), icb_sector=row.get("icbIndustryDescription")))
        key = page["lastItemKey"]
        if not key:
            break
        if key in seen_keys or not page["items"]:
            raise ValueError("Invalid Vanguard pagination cursor")
        seen_keys.add(key)
    else:
        raise ValueError("Vanguard pagination limit exceeded")
    if len(rows) != expected or len(dates) != 1:
        raise ValueError("Incomplete or mixed-date Vanguard holdings")
    return dates.pop(), rows


def fetch_fund(fund_id, directory, today=None):
    client = Client(directory)
    try:
        return _fetch_fund(fund_id,client,today)
    except Exception as error:
        error.issuer_evidence = client.evidence
        raise


def _fetch_fund(fund_id, client, today):
    config = REGISTRY[fund_id]
    adapter = config["adapter"]
    if adapter == "vanguard":
        as_of, rows = vanguard(client, config)
    elif adapter == "blackrock":
        page = client.get(config["url"]).decode()
        links = re.findall(r'href="([^"]+)"', page)
        url = next(unescape(link) for link in links if "fileType=csv" in link and "dataType=fund" in link)
        url = urljoin(config["url"], url)
        as_of, rows = parse_blackrock(client.get(url))
    elif adapter == "vaneck":
        client.get(config["url"])
        as_of, rows = parse_vaneck(client.get("https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/downloads/holdings/"))
    elif adapter == "bmo":
        text = client.get("https://df.bmogam.com/api/sca/etf-fund-profile-comp?profileId=ZNQ-a&locale=en-US&env=prod").decode()
        marker = re.search(r"window\[['\"]dfsb-preloaded-state['\"]\]\s*=\s*", text)
        state, _ = json.JSONDecoder().raw_decode(text[marker.end():])
        token = state["graphQLClient"]["authorizationToken"]
        as_of, rows = parse_bmo(client.json("https://df.bmogam.com/api/graphql/etf-funds-production",
                        {"query": BMO_QUERY, "variables": {"locale": "en-US", "entityId": "ZNQ-a"}},
                        {"Authorization": "bearer " + token}))
    elif adapter == "fidelity":
        as_of, rows = parse_fidelity(client.json("https://fidcaproductsapi.fidelity.ca/FidcaProductsAPI/api/fundPage/fund/EN/FBTC"))
    elif adapter == "ci":
        as_of, rows = parse_ci(client.get(config["url"]))
    elif adapter == "invesco":
        as_of, rows = parse_invesco(client.json("https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/46138G649/holdings/fund?idType=cusip&productType=ETF"))
    else:
        raise ValueError("Unsupported issuer adapter")
    if not rows:
        raise ValueError("Empty holdings response")
    age = ((today or datetime.now(timezone.utc).date()) - date.fromisoformat(as_of)).days
    if age < 0:
        raise ValueError("Issuer holdings date is in the future")
    return {"fund_id": fund_id, "issuer": config["issuer"], "official_url": config["url"], "as_of": as_of,
            "retrieved_at": datetime.now(timezone.utc).isoformat(), "parser_version": VERSION,
            "latest_checked": True, "status": "stale" if age > config["max_age"] else "ok", "age_days": age,
            "mode": "issuer_delayered" if adapter == "vanguard" else "disclosed_top_holdings" if adapter == "ci" else "holdings",
            "rows": rows, "evidence": client.evidence}
