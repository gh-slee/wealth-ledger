"""Deterministic source-neutral report inputs; daily publication stays gated.

The numeric portfolio view describes valued observed rows only. Missing account,
wallet and cash scope remains explicit; it is never filled into a zero position.
"""
from copy import deepcopy
from decimal import Context, Decimal as D, localcontext, getcontext
import hashlib

from .source_projection import ProjectionError, _time, _json, _serialize
from .source_legacy_projection import project_compatible_sources

MODEL = "source-neutral-1"
ZERO = D(0)


def _security_id(asset):
    if asset["kind"] == "cash":
        return "cash:" + asset["currency"]
    key = ":".join((asset.get("market") or "", asset["symbol"], asset["currency"]))
    return key + (":" + hashlib.sha256(_json(asset).encode()).hexdigest()[:16] if asset.get("identifier") else "")


def make_source_payload(project, *, as_of, period_start, fx, generated_at,
                        btc_price=None, kind="interim", btc_cost_policy=None):
    """Build read-only report inputs from verified compatible records and quotes."""
    if kind not in {"baseline", "monthly", "interim"}:
        raise ProjectionError("invalid_source_report_kind")
    if _time(generated_at) < _time(as_of):
        raise ProjectionError("source_report_generation_predates_cutoff")
    from .operations import input_fingerprint
    before = input_fingerprint(project)
    model = project_compatible_sources(project, as_of=as_of, period_start=period_start,
        fx=fx, btc_price=btc_price, btc_cost_policy=btc_cost_policy)
    if model["fx"] is None:
        raise ProjectionError("source_report_requires_display_fx")
    from .source_projection import _precision
    keys = {"quantity", "amount", "market_native", "cost_native", "cost_cad", "calculated_unrealized_native",
            "quantity_btc", "net_recorded_quantity_change", "CAD", "USD", "TWD", "close", "usd_cad", "usd_twd"}
    values = []
    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in keys and isinstance(item, str):
                    values.append({"payload_json": _json({"amount": item})})
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    collect(model)
    precision = max(128, _precision(values, model["fx"]))
    with localcontext(Context(prec=precision)):
        result = _serialize(_payload(model, as_of, period_start, generated_at, kind))
    from .source_valuation import attach_history, read_observations
    attach_history(result, read_observations(project))
    if input_fingerprint(project) != before:
        raise ProjectionError("source_report_inputs_changed")
    return result


def _payload(model, as_of, start, generated_at, kind):
    from .combined import _views
    from .core import _ratio
    accounts = {row["account_id"]: row for row in model["accounts"]}
    records = []
    for row in model["positions"]:
        metadata = accounts[row["account_id"]]
        asset = row["asset"]
        instrument = {"STOCK": "EQUITY", "ETF": "EXCHANGE_TRADED_FUND"}.get(row["instrument_type"], row["instrument_type"])
        price = row["unit_price"]
        unrealized = row["source_unrealized"]
        records.append({"account_id": row["account_id"], "account_type": metadata["account_type"],
            "account_label": metadata["label"], "security_id": _security_id(asset),
            "source_id": row["source_id"], "source_revision": row["source_revision"],
            "observation_id": row["observation_id"], "source_provider": row["provider"],
            "observed_as_of": row["observed_as_of"], "asset": deepcopy(asset),
            "symbol": asset["symbol"], "name": row["name"], "security_type": "CURRENCY" if asset["kind"] == "cash" else instrument,
            "source_instrument_type": row["instrument_type"], "mic": asset.get("market") or "", "exchange": row["exchange"],
            "currency": row["currency"], "quantity": D(row["quantity"]),
            "price": D(price["amount"]) if price is not None else None,
            "book_native": D(row["cost_native"]) if row["cost_native"] is not None else None,
            "book_cad": D(row["cost_cad"]) if row["cost_cad"] is not None else None,
            "market_native": D(row["market_native"]),
            "unrealized_native": D(unrealized["amount"]) if unrealized is not None else
                D(row["calculated_unrealized_native"]) if row["calculated_unrealized_native"] is not None else None,
            "source_unrealized": deepcopy(unrealized), "legacy_snapshot_id": row.get("legacy_snapshot_id")})
    asset = model["btc"]
    scope_id = asset["scope_account_id"]
    metadata = [{"account_id": row["account_id"], "account_type": row["account_type"],
                 "label": row["label"], "masked_number": row.get("masked_identifier") or "", "source_provider": row["provider"],
                 "observed_as_of": row.get("observed_as_of")} for row in model["accounts"] if row["role"] == "investment"]
    if asset["in_scope"]:
        metadata.append({"account_id": scope_id, "account_type": "BTC", "label": "BTC + LBTC", "masked_number": "", "source_provider": "wallet", "observed_as_of": model["wallet"]["anchor"]["as_of"] if model["wallet"]["anchor"] else None})
        if asset["market_values"]["CAD"] is not None:
            records.append({"account_id": scope_id, "account_type": "BTC", "account_label": "BTC + LBTC", "security_id": "crypto:BTC-equivalent",
                "symbol": "BTC", "name": "BTC + LBTC", "security_type": "CRYPTO", "currency": "CAD", "mic": "CRYPTO", "exchange": "",
                "quantity": D(asset["quantity_btc"]), "price": D(asset["price"]["close"])*D(model["fx"]["usd_cad"]),
                "book_native": None, "book_cad": None, "market_native": D(asset["market_values"]["CAD"]), "unrealized_native": None,
                "asset_unit": "BTC", "valuation_currency": "CAD", "quantity_status": asset["quantity_status"], "observed_as_of": as_of,
                "source_provider": "wallet"})
    for aid, cash in sorted(asset["legacy_cash_cad_by_account"].items()):
        if cash is None or D(cash) < 0:
            continue
        if not any(row["account_id"] == aid for row in metadata):
            metadata.append({"account_id": aid, "account_type": "cash", "label": accounts[aid]["label"], "masked_number": "", "source_provider": accounts[aid]["provider"], "observed_as_of": as_of})
        records.append({"account_id": aid, "account_type": "cash", "account_label": next(row["label"] for row in metadata if row["account_id"] == aid),
            "security_id": "cash:CAD", "symbol": "CAD", "name": "CAD", "security_type": "CURRENCY", "currency": "CAD", "mic": "", "exchange": "",
            "quantity": D(cash), "price": D(1), "book_native": D(cash), "book_cad": D(cash), "market_native": D(cash), "unrealized_native": ZERO,
            "observed_as_of": as_of, "source_provider": accounts[aid]["provider"]})
    payload = {"fx": deepcopy(model["fx"]), "accounts": metadata}
    payload.update(_views(payload, records))
    # Aggregation must not promote an implied value/quantity ratio to a quoted price.
    for security in payload["securities"]:
        members=[row for row in payload["positions"] if row["security_id"]==security["security_id"]]
        prices={row["price"] for row in members}
        dates={row.get("observed_as_of") for row in members}
        security["price"]=next(iter(prices)) if len(prices)==1 and len(dates)==1 else None
        security["observed_as_of"]=next(iter(dates)) if len(dates)==1 else None
        security["source_observations"]=[{key:row.get(key) for key in ("account_id","source_id","observation_id","legacy_snapshot_id","observed_as_of")} for row in members]

    known = bool(records) or any(row["role"] == "investment" and row["observation_id"] is not None for row in model["accounts"])
    if not known:
        for key in payload["totals"]:
            payload["totals"][key] = None
    valued = {row["account_id"] for row in payload["accounts"]}
    for row in model["accounts"]:
        if row["role"] != "investment" or row["account_id"] in valued:
            continue
        empty = row["observation_id"] is not None
        payload["accounts"].append({"account_id": row["account_id"], "account_type": row["account_type"], "label": row["label"],
            "source_provider": row["provider"], "observed_as_of": row.get("observed_as_of"), "masked_number": row.get("masked_identifier") or "",
            **{key: ZERO if empty else None for key in ("total_cad", "total_usd", "total_twd", "native_cad", "native_usd", "cash_cad")},
            "portfolio_weight": _ratio(ZERO, payload["totals"]["total_cad"]) if empty and payload["totals"]["total_cad"] is not None else None,
            "position_count": 0, "cash_ratio": None})
    # Source acquisition accounts are not extra full-wallet positions.
    for row in payload["accounts"]:
        original = accounts.get(row["account_id"])
        row.setdefault("source_provider", original["provider"] if original else "wallet")
        row.setdefault("observed_as_of", original.get("observed_as_of") if original and original["role"] == "investment" else as_of)
    scope = {"accounts": sorted({row["account_id"] for row in payload["accounts"]} | ({scope_id} if asset["in_scope"] else set())),
             "missing_accounts": sorted(row["account_id"] for row in model["accounts"] if row["role"] == "investment" and row["observation_id"] is None),
             "wallet_in_scope": asset["in_scope"], "basis": "valued_observed_rows_not_complete_wealth"}
    payload.update({"meta": {"report_model": MODEL, "snapshot_id": None, "source_report_observation_id": None,
            "as_of": _time(as_of).isoformat(), "period_start": _time(start).isoformat(), "generated_at": _time(generated_at).isoformat(), "kind": kind,
            "revision": 1, "is_complete": False, "account_coverage_complete": False, "scope_id": hashlib.sha256(_json(scope).encode()).hexdigest(),
            "data_status": "observed_subtotal", "base_currency": "CAD", "display_currencies": ["CAD", "USD", "TWD"],
            "account_count": len(payload["accounts"]), "security_count": len(payload["securities"]), "position_count": len(payload["positions"]),
            "cash_row_count": len(payload["cash_rows"]), "missing_account_ids": scope["missing_accounts"], "full_portfolio_values": None,
            "report_published": False, "daily_workflow_ready": False, "decimal_precision": getcontext().prec},
        "source": {"filename": "Verified source evidence", "row_count": len(model["positions"]), "sha256": model["projection_sha256"], "integrity_ok": True},
        "source_projection": deepcopy(model), "source_crypto": deepcopy(asset), "source_coverage": deepcopy(model["accounts"]),
        "periods": [], "cash_flows": [], "history": [], "changes": {"available": False, "reason": "source_report.no_performance"},
        "issues": [{"code": "source_observed_scope", "severity": "warning", "message": "source_report.scope_note"}],
        "findings": ["source_report.scope_note", "source_report.no_performance", "source_report.source_dates_note"]})
    estimated_cost=payload["source_crypto"]["estimated_full_cost_cad"]
    estimated_gain=payload["source_crypto"]["estimated_gain_cad"]
    payload["source_crypto"]["estimated_return"] = D(estimated_gain)/D(estimated_cost) if estimated_cost is not None and D(estimated_cost)>0 and estimated_gain is not None else None
    if asset["in_scope"] and not any(row["account_id"]==scope_id for row in payload["accounts"]):
        payload["accounts"].append({"account_id":scope_id,"label":"BTC + LBTC","account_type":"BTC","source_provider":"wallet","observed_as_of":model["wallet"]["anchor"]["as_of"] if model["wallet"]["anchor"] else None,
            **{key:None for key in ("total_cad","total_usd","total_twd","native_cad","native_usd","cash_cad","cash_ratio","portfolio_weight")},"position_count":0})
        payload["meta"]["account_count"] = len(payload["accounts"])
    return payload
