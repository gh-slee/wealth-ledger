"""Deterministic company look-through, issuer evidence, and frozen analysis runs."""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
import uuid

from .fund_sources import REGISTRY, fetch_fund

getcontext().prec = 60
D = Decimal
VERSION = "company-exposure-2"
KINDS = ("equity", "cash", "crypto", "bond", "unknown", "adjustment")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def portfolio_signature(payload):
    fields = ("symbol", "mic", "currency", "security_type", "name", "quantity", "market_cad")
    securities = [{key: row.get(key) for key in fields} for row in payload["securities"]]
    return digest({"as_of": payload["meta"]["as_of"], "totals": payload["totals"],
                   "securities": sorted(securities, key=lambda row: (row["symbol"], row["mic"], row["currency"]))})


def normalize_name(name):
    text = unicodedata.normalize("NFKC", name).lower()
    text = " ".join(re.sub(r"[^\w\s]", " ", text).split())
    # Strip share/legal descriptors only at the end, retaining issuer words
    # such as Preferred Bank or ADS-TEC Energy at the start of a name.
    legal = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "nv", "sa", "ag"}
    while True:
        previous = text
        text = re.sub(r"\b(?:cap stk\s+)?(?:class|cl)\s+[a-z]\s*$", "", text).strip()
        text = re.sub(r"\b(?:sponsored\s+)?(?:adr|ads|pfd|preferred|ordinary shares|american depositary share|american depository share)\s*$", "", text).strip()
        tokens = text.split()
        while tokens and tokens[-1] in legal:
            tokens.pop()
        text = " ".join(tokens)
        if text == previous:
            return text


COUNTRIES = {"United States": "US", "Canada": "CA", "Taiwan": "TW", "Korea (South)": "KR",
             "Japan": "JP", "China": "CN", "Hong Kong": "HK", "United Kingdom": "GB", "Netherlands": "NL"}


class Identities:
    """Resolve identifiers and conservative issuer names, with reviewable overrides."""
    def __init__(self, rows, aliases):
        self.aliases, self.names, self.countries, self.security_aliases = {}, {}, defaultdict(set), {}
        for company in aliases["companies"]:
            key = "company:" + company["id"]
            self.names[key] = company["name"]
            for alias in company["aliases"] + [company["name"]]:
                normalized = normalize_name(alias)
                if normalized in self.aliases and self.aliases[normalized] != key:
                    raise ValueError("Conflicting company aliases")
                self.aliases[normalized] = key
        for row in rows:
            country = COUNTRIES.get(row.get("country"), row.get("country", ""))
            if country:
                self.countries[normalize_name(row["name"])].add(country)
        # A security identifier can link issuer spelling differences. It does not
        # by itself equate different share classes: aliases/names do that step.
        self.groups, self.row_index = {}, {}
        parents = list(range(len(rows)))
        def root(i):
            while parents[i] != i:
                parents[i] = parents[parents[i]]
                i = parents[i]
            return i
        seen = {}
        for i, row in enumerate(rows):
            self.row_index[id(row)] = i
            identifiers = dict(row.get("identifiers", {}))
            isin = identifiers.get("isin") or ""
            if isin.startswith("US") and len(isin) == 12:
                identifiers["cusip"] = isin[2:11]
            for kind, value in identifiers.items():
                if not value or str(value).upper() in {"--", "N/A", "-"}:
                    continue
                token = kind, str(value)
                if token in seen:
                    parents[root(i)] = root(seen[token])
                else:
                    seen[token] = i
        members = defaultdict(list)
        for i, row in enumerate(rows):
            members[root(i)].append(row)
        for i, group in members.items():
            keys = {self.aliases[normalize_name(row["name"])] for row in group if normalize_name(row["name"]) in self.aliases}
            if len(keys) > 1:
                raise ValueError("Security identifier conflicts with company aliases")
            if keys:
                key = keys.pop()
                method = "explicit_alias_and_security_id" if len(group) > 1 else "explicit_alias"
            else:
                normalized = normalize_name(group[0]["name"])
                countries = self.countries[normalized]
                if len(countries) > 1:
                    country = COUNTRIES.get(group[0].get("country"), group[0].get("country", ""))
                    key = "issuer:" + digest([normalized, country])[:24] if country else None
                else:
                    key = "issuer:" + digest([normalized, next(iter(countries), "")])[:24]
                method = "security_id_and_issuer_name" if len(group) > 1 else "normalized_issuer_name"
                if key:
                    self.names[key] = group[0]["name"]
            self.groups[i] = key, method
        self.roots = [root(i) for i in range(len(rows))]

    def resolve(self, row):
        i = self.row_index[id(row)]
        return self.groups[self.roots[i]]


def calculate(payload, funds, aliases, calculated_at=None):
    """Calculate exposures without network, database, or report side effects."""
    securities = payload["securities"]
    roots, direct = {}, []
    denominator = sum((D(row["market_cad"]) for row in securities), D(0))
    for row in securities:
        if D(row["market_cad"]) < 0:
            raise ValueError("Short portfolio positions are not supported by company look-through")
        if row["security_type"] in {"ETF", "EXCHANGE_TRADED_FUND"}:
            key = row["mic"] + ":" + row["symbol"]
            roots[key] = roots.get(key,D(0)) + D(row["market_cad"])
        elif row["security_type"] == "EQUITY":
            direct.append({**row, "kind": "equity", "weight": "1", "country": "US" if row["mic"] in {"XNAS", "XNYS"} else "",
                           "identifiers": {}, "fund_id": None})
    equity_rows = [row for fund in funds.values() for row in fund.get("rows", []) if row["kind"] == "equity"] + direct
    identities = Identities(equity_rows, aliases)
    companies = {}
    buckets = {kind: D(0) for kind in KINDS if kind != "equity"}
    fund_summary, issues, components, unresolved = [], [], [], []

    def record_unknown(root,path,name,amount):
        if amount:
            unresolved.append({"root":root,"path":path,"name":name,"market_cad":str(amount)})

    def add_equity(row, amount, root, path, coefficient):
        key, method = identities.resolve(row)
        if key is None:
            buckets["unknown"] += amount
            record_unknown(root,path,row["name"],amount)
            issues.append(f"公司名稱具有不同國別且無可靠識別：{row['name']}")
            return "unknown"
        company = companies.setdefault(key, {"company_id": key, "name": identities.names[key], "direct_cad": D(0),
                                             "indirect_cad": D(0), "by_fund": defaultdict(Decimal), "source_names": set(), "methods": set()})
        company["source_names"].add(row["name"])
        company["methods"].add(method)
        if root == "direct":
            company["direct_cad"] += amount
        else:
            company["indirect_cad"] += amount
            company["by_fund"][root] += amount
        components.append({"company_id": key, "root": root, "path": path, "source_name": row["name"],
                           "ticker": row.get("ticker", ""), "identifiers": row.get("identifiers", {}),
                           "method": method, "weight": str(coefficient), "market_cad": str(amount),
                           "source_fund": path[-1] if root != "direct" else None,
                           "gics_sector": row.get("gics_sector", ""),
                           "icb_sector": row.get("icb_sector", ""), "issuer_sector": row.get("issuer_sector", ""),
                           "official_country": row.get("country", "") if root != "direct" else ""})
        return "equity"

    def expand(fund_id, amount, root, path, coefficient=D(1)):
        subtotal = {kind: D(0) for kind in KINDS}
        if fund_id in path or len(path) > 10:
            issues.append(f"基金循環或超過深度限制：{' → '.join(path+[fund_id])}")
            subtotal["unknown"] = amount
            buckets["unknown"] += amount
            record_unknown(root,path+[fund_id],"Unresolved fund or cycle",amount)
            return subtotal
        source = funds.get(fund_id)
        if not source or source.get("status") == "failed":
            subtotal["unknown"] = amount
            buckets["unknown"] += amount
            record_unknown(root,path+[fund_id],"Unresolved fund or cycle",amount)
            return subtotal
        path = path + [fund_id]
        published_weight = D(0)
        for row in source["rows"]:
            w = D(row["weight"])
            published_weight += w
            kind = row["kind"]
            if kind == "equity" and w < 0:
                kind = "unknown"
                issues.append(f"{fund_id} 的空頭股份尚未解析：{row['name']}")
            if kind == "fund":
                child = row.get("fund_id")
                if child:
                    child_totals = expand(child, amount * w, root, path, coefficient * w)
                    for key, value in child_totals.items():
                        subtotal[key] += value
                else:
                    buckets["unknown"] += amount * w
                    record_unknown(root,path,row["name"],amount*w)
                    subtotal["unknown"] += amount * w
            elif kind == "equity":
                result_kind = add_equity(row, amount * w, root, path, coefficient * w)
                subtotal[result_kind] += amount * w
            else:
                if kind not in buckets:
                    kind = "unknown"
                buckets[kind] += amount * w
                if kind == "unknown":
                    record_unknown(root,path,row["name"],amount*w)
                subtotal[kind] += amount * w
        residual = D(1) - published_weight
        # Retain published rounding instead of silently normalizing positions.
        if residual < 0:
            if abs(residual) > D("0.005"):
                raise ValueError(f"Excessive over-allocation for {fund_id}")
            kind = "adjustment"
        else:
            kind = "unknown"
        buckets[kind] += amount * residual
        if kind == "unknown":
            record_unknown(root,path,"Unreported residual",amount*residual)
        subtotal[kind] += amount * residual
        return subtotal

    for fund_id, amount in sorted(roots.items()):
        totals = expand(fund_id, amount, fund_id, [])
        source = funds.get(fund_id, {})
        fund_summary.append({"fund_id": fund_id, "market_cad": str(amount), "as_of": source.get("as_of"),
                             "issuer": source.get("issuer", "未介接"), "status": source.get("status", "failed"),
                             "company_weight": str(totals["equity"] / amount if amount else 0),
                             "unknown_weight": str(totals["unknown"] / amount if amount else 0),
                             "noncompany_weight": str(sum((totals[k] for k in ("cash", "crypto", "bond")), D(0)) / amount if amount else 0),
                             "adjustment_weight": str(totals["adjustment"] / amount if amount else 0)})
        fund_summary[-1]["bucket_cad"] = {kind: str(value) for kind, value in totals.items()}
    for row in direct:
        add_equity(row, D(row["market_cad"]), "direct", [row["mic"]+":"+row["symbol"]], D(1))
    for row in securities:
        if row["security_type"] not in {"ETF", "EXCHANGE_TRADED_FUND", "EQUITY"}:
            kind = "crypto" if row["security_type"] == "CRYPTO" else "unknown"
            buckets[kind] += D(row["market_cad"])
            if kind == "unknown":
                record_unknown("direct",[row["mic"]+":"+row["symbol"]],row["name"],D(row["market_cad"]))
    company_total = sum((row["direct_cad"] + row["indirect_cad"] for row in companies.values()), D(0))
    if abs(company_total + sum(buckets.values(), D(0)) - denominator) > D("0.00000001"):
        raise ValueError("Company exposure reconciliation failed")
    rows = []
    for company in sorted(companies.values(), key=lambda row: (-(row["direct_cad"]+row["indirect_cad"]), row["company_id"])):
        amount = company["direct_cad"] + company["indirect_cad"]
        rows.append({**{key: str(company[key]) for key in ("company_id", "name", "direct_cad", "indirect_cad")},
                     "total_cad": str(amount), "investment_weight": str(amount/denominator) if denominator else None,
                     "asset_weight": str(amount/D(payload["totals"]["total_cad"])) if D(payload["totals"]["total_cad"]) else None,
                     "company_weight": str(amount/company_total) if company_total else None,
                     "by_fund": {key: str(value) for key, value in sorted(company["by_fund"].items())},
                     "source_names": sorted(company["source_names"]), "methods": sorted(company["methods"])})
    top = rows[:20]
    top_ids = {row["company_id"] for row in top}
    sources = [{key: value for key, value in fund.items() if key != "rows"} for _, fund in sorted(funds.items())]
    unavailable = [row["fund_id"] for row in sources if row["status"] != "ok"]
    unknown = buckets["unknown"]
    result = {"version": VERSION, "calculated_at": calculated_at or datetime.now(timezone.utc).isoformat(),
            "valuation_as_of": payload["meta"]["as_of"], "mode": "latest_official", "sources": sources,
            "investment_total_cad": str(denominator), "company_total_cad": str(company_total),
            "noncompany": {kind: str(value) for kind, value in buckets.items()},
            "unknown_weight": str(unknown/denominator) if denominator else None,
            "status": "partial" if unavailable or unresolved else "complete",
            "unresolved_positions": unresolved,
            "issues": sorted(set(issues)), "funds": fund_summary, "companies": rows, "top20": top,
            "top20_components": [row for row in components if row["company_id"] in top_ids],
            "top20_weight": str(sum((D(row["total_cad"]) for row in top),D(0))/denominator) if denominator else None,
            "rank20_gap_cad": str(D(rows[19]["total_cad"])-D(rows[20]["total_cad"])) if len(rows)>20 else None,
            "alias_sha256": digest(aliases)}
    from .classification import calculate_classification
    result["classification"] = calculate_classification(result, components, funds, identities, securities)
    return result


def ensure_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS fund_sources(
      id INTEGER PRIMARY KEY, fund_id TEXT NOT NULL, source_hash TEXT NOT NULL,
      as_of TEXT NOT NULL, retrieved_at TEXT NOT NULL, payload_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS lookthrough_runs(
      id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, portfolio_signature TEXT NOT NULL,
      alias_sha256 TEXT NOT NULL, payload_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS lookthrough_run_sources(
      run_id INTEGER NOT NULL REFERENCES lookthrough_runs(id), source_id INTEGER NOT NULL REFERENCES fund_sources(id),
      PRIMARY KEY(run_id,source_id));
    """)


def attach_analysis(project, payload, run_id=None, fetcher=fetch_fund):
    """Query current official data, or replay a matching immutable analysis run."""
    project = Path(project)
    database = project / "data/db/portfolio.sqlite3"
    signature = portfolio_signature(payload)
    with sqlite3.connect(database) as conn:
        ensure_schema(conn)
        if run_id is not None:
            saved = conn.execute("SELECT portfolio_signature,payload_json FROM lookthrough_runs WHERE id=?", (run_id,)).fetchone()
            if not saved or saved[0] != signature:
                raise ValueError("Saved look-through run does not match this portfolio valuation")
            result = json.loads(saved[1])
            result["mode"] = "frozen_replay"
            payload["lookthrough"] = result
            return result
    from .resources import company_aliases
    aliases, alias_resources = company_aliases(project)
    root_ids = {row["mic"]+":"+row["symbol"] for row in payload["securities"] if row["security_type"] in {"ETF", "EXCHANGE_TRADED_FUND"}}
    directory = project / "data/raw/fund_holdings" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")+"-"+uuid.uuid4().hex[:8])
    funds, pending = {}, root_ids
    def download(fund_id):
        if fund_id not in REGISTRY:
            return fund_id, {"fund_id": fund_id, "status": "failed", "latest_checked": False,
                             "issuer": "未介接", "error": "No official adapter registered", "rows": [], "evidence": []}
        try:
            source = fetcher(fund_id, directory / fund_id.replace(":", "-"))
            for evidence in source["evidence"]:
                evidence["path"] = str(Path(evidence["path"]).relative_to(project))
            return fund_id, source
        except Exception as error:
            # Do not reuse a stale cache or disclose HTTP credentials/error bodies.
            evidence = getattr(error,"issuer_evidence",[])
            for item in evidence:
                item["path"] = str(Path(item["path"]).relative_to(project))
            return fund_id, {"fund_id": fund_id, "status": "failed", "latest_checked": False,
                             "issuer": REGISTRY[fund_id]["issuer"], "official_url": REGISTRY[fund_id]["url"],
                             "error": type(error).__name__ + ": official fetch/parse failed", "rows": [], "evidence": evidence}
    while pending:
        with ThreadPoolExecutor(max_workers=4) as executor:
            for fund_id, source in executor.map(download, sorted(pending)):
                funds[fund_id] = source
        pending = {row["fund_id"] for source in funds.values() for row in source.get("rows", [])
                   if row.get("fund_id") and row["fund_id"] not in funds}
    result = calculate(payload, funds, aliases)
    result["alias_resources"] = alias_resources
    with sqlite3.connect(database) as conn:
        ensure_schema(conn)
        source_ids = []
        for _, source in sorted(funds.items()):
            if source["status"] == "failed":
                continue
            source_ids.append(conn.execute("INSERT INTO fund_sources(fund_id,source_hash,as_of,retrieved_at,payload_json) VALUES(?,?,?,?,?)",
                        (source["fund_id"],digest(source),source["as_of"],source["retrieved_at"],json.dumps(source,ensure_ascii=False))).lastrowid)
        run_id = conn.execute("INSERT INTO lookthrough_runs(created_at,portfolio_signature,alias_sha256,payload_json) VALUES(?,?,?,?)",
                             (result["calculated_at"],signature,result["alias_sha256"],"{}")).lastrowid
        result["run_id"] = run_id
        conn.execute("UPDATE lookthrough_runs SET payload_json=? WHERE id=?",(json.dumps(result,ensure_ascii=False),run_id))
        conn.executemany("INSERT INTO lookthrough_run_sources VALUES(?,?)",[(run_id,source_id) for source_id in source_ids])
    payload["lookthrough"] = result
    return result
