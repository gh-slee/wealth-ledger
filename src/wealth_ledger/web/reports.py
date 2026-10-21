"""Read selected registered publications; viewing never imports, values or renders."""
from contextlib import closing
from datetime import datetime
import json
from typing import Literal

from fastapi import Depends, Query
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from .storage import ID, WebError

Locale = Literal["en-CA", "zh-TW", "zh-CN"]


class ViewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Artifact(ViewModel):
    id: str
    filename: str
    media_type: str
    byte_size: int
    sha256: str


class ReportSummary(ViewModel):
    id: str
    valuation_as_of: str
    published_at: float
    verification_basis: Literal["publication_manifest", "migration_capture"] = "publication_manifest"
    artifacts: list[Artifact]
    scope_key: str | None = None
    scope_labels: list[str] = Field(default_factory=list)
    report_locale: Locale | None = None
    edition_label: str | None = None


class ReportList(ViewModel):
    reports: list[ReportSummary]
    next_cursor: str | None


class Account(ViewModel):
    account_id: str
    label: str
    account_type: str
    source_provider: str | None = None
    observed_as_of: str | None = None
    total_cad: str | None = None
    total_usd: str | None = None
    total_twd: str | None = None
    portfolio_weight: str | None = None
    cash_ratio: str | None = None


class Holding(ViewModel):
    account_id: str | None = None
    account_label: str | None = None
    security_id: str
    symbol: str
    name: str
    security_type: str
    currency: str
    quantity: str | None = None
    source_provider: str | None = None
    observed_as_of: str | None = None
    source_id: str | None = None
    source_revision: str | None = None
    observation_id: str | None = None
    avg_cost: str | None = None
    book_native: str | None = None
    unrealized_native: str | None = None
    unrealized_pct: str | None = None
    market_native: str | None = None
    market_cad: str | None = None
    market_usd: str | None = None
    market_twd: str | None = None
    portfolio_weight: str | None = None


class SourceDate(ViewModel):
    provider: str
    as_of: str | None
    usage: str


class Observation(ViewModel):
    snapshot_id: int | None = None
    revision: int | None = None
    as_of: str
    kind: str
    is_complete: bool
    data_status: str | None = None
    total_cad: str | None = None
    total_usd: str | None = None
    total_twd: str | None = None


class Company(ViewModel):
    rank: int
    name: str
    total_cad: str | None
    direct_cad: str | None
    indirect_cad: str | None
    asset_weight: str | None
    investment_weight: str | None


class DimensionRow(ViewModel):
    name: str
    kind: str
    market_cad: str | None
    investment_weight: str | None
    equity_weight: str | None


class Dimension(ViewModel):
    rows: list[DimensionRow]
    equity_coverage: str | None
    investment_coverage: str | None
    as_of_min: str | None
    as_of_max: str | None


class ReportView(ViewModel):
    schema_version: int
    report: ReportSummary
    locale: Locale
    as_of: str
    kind: str
    is_complete: bool
    data_status: str | None
    source_dates: list[SourceDate]
    source_basis: dict[str, JsonValue] | None = None
    totals: dict[str, str | None]
    fx: dict[str, str | None]
    accounts: list[Account]
    holdings: list[Holding]
    history: list[Observation]
    findings: list[str]
    issues: list[dict[str, JsonValue]]
    companies: list[Company]
    dimensions: dict[str, Dimension]
    exposure_status: str | None
    exposure_sources: list[dict[str, JsonValue]]
    btc: dict[str, JsonValue] | None
    cash_flows: list[dict[str, JsonValue]]
    missing_official_months: list[str]


def pick(model, value):
    return {key: value[key] for key in model.model_fields if key in value}


class Publications:
    def __init__(self, store):
        self.store = store

    def summary(self, row):
        from pathlib import PurePosixPath
        with closing(self.store.connect()) as conn:
            files = conn.execute("SELECT * FROM artifacts WHERE portfolio_id=? AND report_id=? ORDER BY relative_path",
                                 (row["portfolio_id"], row["id"])).fetchall()
        result = json.loads(row["result_json"])
        from .report_evidence import legacy_evidence
        verification = legacy_evidence(self.store,row["portfolio_id"],row["id"]) if result.get("adopted") is True else None
        metadata = {}
        payloads = [file for file in files if file["relative_path"].endswith("/data.json")]
        if len(payloads) == 1:
            raw, _, _ = self.store.read_artifact(row["portfolio_id"], payloads[0]["id"])
            try:
                from .report_document import edition_metadata
                data = json.loads(raw)
                if data["meta"]["as_of"] != result["valuation_as_of"]:
                    raise ValueError("Report cutoff differs")
                metadata = edition_metadata(data, payloads[0]["relative_path"])
            except (ValueError, KeyError, TypeError) as exc:
                raise WebError(409, "report_integrity", "Published report fields need local review") from exc
        return {**metadata, "id": row["id"], "valuation_as_of": result["valuation_as_of"], "published_at": datetime.fromisoformat(verification["evidence"]["published_at"]).timestamp() if verification else row["updated_at"],
                "verification_basis": "migration_capture" if verification is not None else "publication_manifest",
                "artifacts": [{"id": file["id"], "filename": PurePosixPath(file["relative_path"]).name,
                               **{key: file[key] for key in ("media_type", "byte_size", "sha256")}} for file in files]}

    def row(self, portfolio_id, report_id, owner_id=1):
        self.store.portfolio(portfolio_id, owner_id)
        if not isinstance(report_id, str) or not ID.fullmatch(report_id):
            raise WebError(404, "not_found", "Report not found")
        with closing(self.store.connect()) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=? AND portfolio_id=? AND kind='update' AND status='published'",
                               (report_id, portfolio_id)).fetchone()
        if not row:
            raise WebError(404, "not_found", "Report not found")
        return dict(row)

    def list(self, portfolio_id, owner_id=1, *, cursor=None, limit=50):
        self.store.portfolio(portfolio_id, owner_id)
        boundary = self.row(portfolio_id, cursor, owner_id) if cursor else None
        with closing(self.store.connect()) as conn:
            rows = conn.execute("""SELECT * FROM jobs WHERE portfolio_id=? AND kind='update' AND status='published'
                AND (? IS NULL OR updated_at<? OR (updated_at=? AND id<?))
                ORDER BY updated_at DESC,id DESC LIMIT ?""", (portfolio_id, cursor,
                boundary["updated_at"] if boundary else None, boundary["updated_at"] if boundary else None,
                cursor, limit+1)).fetchall()
        return {"reports": [self.summary(dict(row)) for row in rows[:limit]],
                "next_cursor": rows[limit-1]["id"] if len(rows)>limit else None}

    def view(self, portfolio_id, report_id, locale, owner_id=1):
        row = self.row(portfolio_id, report_id, owner_id)
        summary = self.summary(row)
        files = [artifact for artifact in summary["artifacts"] if artifact["filename"] == "data.json"]
        if len(files) != 1:
            raise WebError(409, "report_integrity", "Published report payload needs local review")
        raw, _, _ = self.store.read_artifact(portfolio_id, files[0]["id"], owner_id)
        try:
            data = json.loads(raw)
            if data["meta"]["as_of"] != summary["valuation_as_of"]:
                raise ValueError("Report cutoff differs")
            from ..i18n import display_payload, presentation_context, legacy_text
            with presentation_context(locale):
                data = display_payload(data)
                if data["meta"].get("report_model") == "source-neutral-1":
                    from .source_report_views import source_view
                    return ReportView.model_validate(source_view(data, summary, locale)).model_dump()
                meta, crypto, analysis = data["meta"], data.get("crypto"), data.get("lookthrough", {})
                updates = meta.get("source_updates") or {}
                sources = []
                if meta.get("wealthsimple_as_of") or not meta.get("is_combined"):
                    sources.append({"provider": "wealthsimple", "as_of": meta.get("wealthsimple_as_of", meta["as_of"]),
                                    "usage": updates.get("wealthsimple", {}).get("status", "snapshot")})
                if crypto:
                    if crypto.get("meta", {}).get("provider") != "wallet":
                        sources.append({"provider": "bullbitcoin", "as_of": crypto.get("source", {}).get("latest_completed_at"),
                                        "usage": updates.get("bullbitcoin", {}).get("status", "order_history")})
                    anchor = (crypto.get("wallet") or {}).get("anchor")
                    if anchor:
                        sources.append({"provider": "wallet", "as_of": anchor.get("as_of"), "usage": "observed_total"})
                dimensions = {}
                for name, dimension in analysis.get("classification", {}).get("dimensions", {}).items():
                    dimensions[name] = {"rows": [pick(DimensionRow, r) for r in dimension["rows"]],
                                        **{k: dimension.get(k) for k in ("equity_coverage", "investment_coverage", "as_of_min", "as_of_max")}}
                btc = None
                if crypto:
                    # Project public presentation fields, not assumptions, raw wallet
                    # addresses/order payloads, archive paths or internal registries.
                    btc = {"quantity_btc": crypto.get("btc_equivalent_qty"),
                           "purchased_btc": crypto.get("purchased_btc_equivalent_qty"),
                           "opening_btc": crypto.get("opening_btc_equivalent_qty"),
                           "quantity_status": crypto.get("meta", {}).get("quantity_status"),
                           "monthly": [{key:r.get(key) for key in ("month", "contribution_cad", "buy_cost_cad",
                               "average_purchase_price_cad_per_btc", "cumulative_btc_equivalent_qty")} for r in crypto.get("monthly", [])],
                           "valuation": {key:crypto.get("valuation", {}).get(key) for key in (
                               "market_cad", "market_usd", "market_twd", "unit_price_cad", "unit_price_usd",
                               "unrealized_cad", "cost_status", "known_bull_cost_cad")},
                           "cost_policy": crypto.get("cost_estimate_policy", "actual_only")}
                wallet_only = bool(crypto and crypto.get("meta", {}).get("provider") == "wallet")
                accounts = []
                for account in data["accounts"]:
                    item = {**pick(Account, account), "label": legacy_text(account["label"])}
                    if wallet_only and account.get("source_provider") == "bullbitcoin":
                        item.update(label=legacy_text(account["account_type"]), source_provider="wallet")
                    accounts.append(item)
                result = {"schema_version": 1, "report": summary, "locale": locale, "as_of": meta["as_of"],
                    "kind": meta["kind"], "is_complete": meta["is_complete"], "data_status": meta.get("data_status"),
                    "source_dates": sources, "totals": {k:v for k,v in data["totals"].items() if v is None or isinstance(v,str)},
                    "fx": {k:v for k,v in data.get("fx", {}).items() if v is None or isinstance(v,str)},
                    "accounts": accounts,
                    "holdings": [pick(Holding,r) for r in data["positions"]+data.get("cash_rows",[])],
                    "history": [{**pick(Observation,r), **{k:r.get("totals",{}).get(k) for k in ("total_cad","total_usd","total_twd")}}
                                for r in data.get("history",[])],
                    "findings": data.get("findings",[]), "issues": data.get("issues",[]),
                    "companies": [{"rank":index+1, **{key:r.get(key) for key in ("name","total_cad","direct_cad","indirect_cad","asset_weight","investment_weight")}}
                                  for index,r in enumerate(analysis.get("top20",[])[:20])],
                    "dimensions": dimensions, "exposure_status": analysis.get("status"),
                    "exposure_sources": [{key:r.get(key) for key in ("fund_id","status","as_of","retrieved_at","latest_checked")}
                                         for r in analysis.get("sources",[])],
                    "btc":btc, "cash_flows":[{key:r.get(key) for key in ("date", "amount_cad", "flow_type")} for r in data.get("cash_flows",[])],
                    "missing_official_months":meta.get("missing_official_months",[])}
                # Existing source prose remains source text. Translate only core
                # presentation labels; never translate numbers or user identifiers.
                result["issues"] = [{**issue, "message": legacy_text(issue.get("message", ""))} for issue in result["issues"]]
            return ReportView.model_validate(result).model_dump()
        except (ValueError, KeyError, TypeError) as exc:
            raise WebError(409, "report_integrity", "Published report fields need local review") from exc


def install_report_routes(app, store, require_owner):
    publications = Publications(store)
    @app.get("/api/v1/portfolios/{portfolio_id}/reports", response_model=ReportList)
    def reports(portfolio_id: str, cursor: str | None=None, limit: int=Query(default=50,ge=1,le=100), owner=Depends(require_owner)):
        return publications.list(portfolio_id,owner["owner_id"],cursor=cursor,limit=limit)

    @app.get("/api/v1/portfolios/{portfolio_id}/reports/{report_id}", response_model=ReportView)
    def report(portfolio_id: str, report_id: str, locale: Locale="en-CA", owner=Depends(require_owner)):
        return publications.view(portfolio_id,report_id,locale,owner["owner_id"])

    from .report_document import ReportDocument, read_document

    @app.get("/api/v1/portfolios/{portfolio_id}/reports/{report_id}/document", response_model=ReportDocument)
    def document(portfolio_id: str, report_id: str, owner=Depends(require_owner)):
        return read_document(publications, portfolio_id, report_id, owner["owner_id"])
