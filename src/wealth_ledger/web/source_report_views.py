"""Bounded read projections of frozen source reports, without live ledger access."""
from decimal import Decimal

from ..source_presentation import label, monthly_purchases, financial_context
from ..source_projection import _serialize
from ..prices import parse_time


@financial_context
def source_view(data, summary, locale):
    from .reports import Account, Holding, Observation, DimensionRow, pick
    meta, model, asset = data["meta"], data["source_projection"], data["source_crypto"]
    analysis = data.get("lookthrough", {})
    sources = {(row["provider"], row.get("observed_as_of"), "holdings_observation")
               for row in model["accounts"] if row["role"] == "investment" and row.get("observed_as_of")}
    by_account = {row["account_id"]: row for row in model["accounts"]}
    purchases = {}
    for row in asset["purchases"]:
        provider = by_account[row["account_id"]]["provider"]
        if provider not in purchases or parse_time(row["occurred_at"]) > parse_time(purchases[provider]):
            purchases[provider] = row["occurred_at"]
    sources.update((provider, at, "recorded_purchase") for provider, at in purchases.items())
    anchor = model["wallet"]["anchor"]
    if anchor: sources.add(("wallet", anchor["as_of"], "observed_total"))
    dimensions = {name: {"rows": [pick(DimensionRow, row) for row in dimension["rows"]],
                   **{key: dimension.get(key) for key in ("equity_coverage", "investment_coverage", "as_of_min", "as_of_max")}}
                  for name, dimension in analysis.get("classification", {}).get("dimensions", {}).items()}
    btc = None
    if asset["in_scope"]:
        opening = asset["opening"]
        price = asset["price"]
        monthly = monthly_purchases(data)
        purchased = sum((row["quantity"] for row in monthly), Decimal(0))
        btc = {"quantity_btc": asset["quantity_btc"], "purchased_btc": purchased,
               "opening_btc": opening["opening_btc_equivalent_qty"] if opening else "0" if asset["acquisition_history_known"] else None,
               "quantity_status": asset["quantity_status"],
               "quantity_status_label": label("status_" + asset["quantity_status"]) if asset["quantity_btc"] is not None else label("unknown"),
               "known_purchase_spend_cad": sum((row["spend"] for row in monthly), Decimal(0)),
               "quantity_basis": asset["quantity_status"], "valuation_blocked": asset["valuation_blocked"],
               "monthly": [{"month": row["month"], "contribution_cad": None, "buy_cost_cad": row["spend"],
                            "purchased_btc": row["quantity"], "net_recorded_btc": row["net_quantity"],
                            "average_purchase_price_cad_per_btc": row["rate"], "cumulative_btc_equivalent_qty": None}
                           for row in monthly],
               "valuation": {"market_cad": asset["market_values"]["CAD"], "market_usd": asset["market_values"]["USD"],
                             "market_twd": asset["market_values"]["TWD"], "unit_price_usd": price["close"] if price else None,
                             "unit_price_cad": Decimal(price["close"]) * Decimal(data["fx"]["usd_cad"]) if price else None, "unrealized_cad": None, "cost_status": "actual_full_cost_unknown",
                             "known_bull_cost_cad": None},
               "cost_policy": asset["cost_policy"], "actual_full_cost_cad": asset["actual_full_cost_cad"],
               "proxy_purchase_spend_cad": asset["proxy_purchase_spend_cad"],
               "proxy_average_cad_per_btc": asset["proxy_average_cad_per_btc"],
               "estimated_full_cost_cad": asset["estimated_full_cost_cad"], "estimated_gain_cad": asset["estimated_gain_cad"],
               "estimated_return": asset["estimated_return"]}
    flows = [{key: row.get(key) for key in ("date", "account_id", "flow_type", "currency", "amount", "amount_cad")}
             for row in model["legacy_cash_flows"]["records"]]
    flows.extend({"date": row["occurred_at"], "account_id": row["account_id"], "flow_type": row["type"],
                  "currency": row["amount"]["currency"], "amount": row["amount"]["amount"], "amount_cad": row["amount"]["amount"] if row["amount"]["currency"] == "CAD" else row.get("historical_amount_cad"),
                  "direction": row["direction"],
                  "classification": row["classification"]} for row in model["cash_flows"]["records"])
    return _serialize({"schema_version": 1, "report": summary, "locale": locale, "as_of": meta["as_of"],
        "kind": meta["kind"], "is_complete": False, "data_status": meta["data_status"],
        "source_basis": {"report_model": meta["report_model"], "source_valuation_id": meta["source_report_observation_id"],
                         "revision": meta["revision"], "scope_id": meta["scope_id"],
                         "scope": "valued_observed_rows_not_complete_wealth", "complete_contributions_cad": None,
                         "complete_portfolio_returns": None, "known_recorded_external_cad": model["legacy_cash_flows"]["known_recorded_external_cad"]},
        "source_dates": [{"provider": provider, "as_of": at, "usage": usage} for provider, at, usage in sorted(sources)],
        "totals": data["totals"], "fx": data["fx"], "accounts": [pick(Account, row) for row in data["accounts"]],
        "holdings": [pick(Holding, row) for row in data["positions"] + data["cash_rows"]],
        "history": [{**pick(Observation, row), **{key: row["totals"].get(key) for key in ("total_cad", "total_usd", "total_twd")}}
                    for row in data["history"]],
        "findings": data["findings"], "issues": data["issues"],
        "companies": [{"rank": index + 1, **{key: row.get(key) for key in ("name", "total_cad", "direct_cad", "indirect_cad", "asset_weight", "investment_weight")}}
                      for index, row in enumerate(analysis.get("top20", [])[:20])],
        "dimensions": dimensions, "exposure_status": analysis.get("status"),
        "exposure_sources": [{key: row.get(key) for key in ("fund_id", "status", "as_of", "retrieved_at", "latest_checked")}
                             for row in analysis.get("sources", [])],
        "btc": btc, "cash_flows": flows, "missing_official_months": []})
