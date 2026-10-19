"""One source-neutral table document shared by Markdown, PDF and ODS."""
from collections import defaultdict
from dataclasses import dataclass
from decimal import Context, Decimal as D, localcontext
from functools import wraps

from .i18n import tr, legacy_text
from .formatting import money, quantity, percent
from .reporting import ReportSection, ReportTable
from .workbook import ref, interval, literal

ZERO = D(0)


def label(key):
    return tr("source_report."+key)


@dataclass(frozen=True)
class Metric:
    value: object
    style: str = "money"
    formula: str | None = None


def table(headers, rows, widths=None):
    """Keep exact numeric ODS cells alongside their formatted prose equivalents."""
    values = {}
    rendered = []
    for index, row in enumerate(rows):
        cells = []
        for column, value in enumerate(row):
            if isinstance(value, Metric):
                number = D(value.value) if value.value is not None else None
                values[index, column] = Metric(number, value.style, value.formula if number is not None else None)
                formatter = percent if value.style == "percent" else quantity if value.style in {"quantity", "btc_quantity"} else money
                cells.append(formatter(number) if number is not None else label("unknown"))
            else:
                cells.append(str(value) if value is not None else label("unknown"))
        rendered.append(cells)
    result = ReportTable(headers, rendered, widths)
    result.source_values = values
    return result


def _sum(payload, key, *, account=None, security=None):
    rows = payload["positions"]+payload["cash_rows"]
    col = {"book_native": 8, "market_native": 10, "unrealized_native": 11, "market_cad": 12, "market_usd": 13, "market_twd": 14}[key]
    source = interval("positions", 6, max(6, len(rows)+5), col)
    criteria = []
    if account is not None:
        criteria.extend((interval("positions", 6, max(6, len(rows)+5), 3), literal(account)))
    if security is not None:
        criteria.extend((interval("positions", 6, max(6, len(rows)+5), 19), literal(security)))
    return "SUMIFS("+";".join([source, *criteria])+")" if criteria else "SUM("+source+")"


def _holdings(payload, indexed):
    rows = []
    for index, row in indexed:
        values = [row["symbol"], row["currency"], Metric(row["quantity"], "quantity", ref("positions", index, 6)),
                  Metric(row["price"], formula=ref("positions", index, 7)), Metric(row["book_native"], formula=ref("positions", index, 8)),
                  Metric(row["market_native"], formula=ref("positions", index, 10)), Metric(row["unrealized_native"], formula=ref("positions", index, 11)),
                  Metric(row["portfolio_weight"], "percent", ref("positions", index, 18))]
        rows.append(values)
    return table([label(key) for key in ("symbol", "currency", "quantity", "unit_price", "cost", "value", "unrealized", "weight")], rows,
                 [1,.55,.9,.8,.9,.9,.9,.65])


def financial_context(function):
    @wraps(function)
    def call(payload, *args, **kwargs):
        with localcontext(Context(prec=max(128, payload["meta"]["decimal_precision"]))):
            return function(payload, *args, **kwargs)
    return call


@financial_context
def sections(payload, charts):
    """No source dispatch or financial calculation from formatted strings."""
    model = payload["source_projection"]
    pairs = list(enumerate(payload["positions"]+payload["cash_rows"], 6))
    result = []
    overview = ReportSection(label("overview"), [label("scope_note"), label("source_dates_note"), label("weights_note"),
        label("valuation_saved_note") if payload["meta"]["source_report_observation_id"] is not None else label("valuation_preview_note")])
    overview.blocks.append(("table", table([label("measure"), "CAD", "USD", "TWD"], [
        [label("observed_subtotal"), *[Metric(payload["totals"]["total_"+unit.lower()], formula=_sum(payload,"market_"+unit.lower())) for unit in ("CAD","USD","TWD")]]], [1.5,1,1,1])))
    overview.blocks.append(("table", table([label("account"), "CAD", "USD", "TWD"], [
        [row["label"], *[Metric(row["total_"+unit.lower()], formula=_sum(payload,"market_"+unit.lower(),account=row["account_id"])) for unit in ("CAD","USD","TWD")] ] for row in payload["accounts"]])))
    overview.blocks.append(("table",table([label("measure"),label("value")],[[label("complete_wealth"),label("unknown")],[label("as_of"),payload["meta"]["as_of"]],[label("generated_at"),payload["meta"]["generated_at"]],
        [label("id"),payload["meta"]["source_report_observation_id"]],[label("revision"),str(payload["meta"]["revision"])]])))
    result.append(("overview",overview))
    currencies = ReportSection(label("currency_holdings"),[label("currency_note")])
    for unit in ("CAD","USD"):
        currencies.blocks.extend([("subheading",unit),("table",_holdings(payload,[(i,row) for i,row in pairs if row["currency"]==unit and row["security_type"] not in {"CURRENCY","CRYPTO"}]))])
    result.append(("currency_holdings",currencies))
    accounts = ReportSection(label("account_holdings"))
    for row in payload["accounts"]:
        accounts.blocks.extend([("subheading",row["label"]),("table",_holdings(payload,[(i,p) for i,p in pairs if p["account_id"]==row["account_id"] and p["security_type"]!="CRYPTO"]))])
    result.append(("account_holdings",accounts))
    analysis = ReportSection(label("analysis"),[label("weights_note"),label("no_performance")])
    analysis.blocks.append(("table",table([label(key) for key in ("rank","symbol","currency","quantity","avg_cost","cost","value","unrealized","weight")],[
        [str(index),row["symbol"],row["currency"],Metric(row["quantity"],"quantity"),Metric(row["avg_cost"]),
         Metric(row["book_native"],formula=_sum(payload,"book_native",security=row["security_id"])),
         Metric(row["market_native"],formula=_sum(payload,"market_native",security=row["security_id"])),
         Metric(row["unrealized_native"],formula=_sum(payload,"unrealized_native",security=row["security_id"])),Metric(row["portfolio_weight"],"percent")]
        for index,row in enumerate(payload["securities"],1)])))
    analysis.blocks.append(("table",table([label("instrument"),"CAD",label("weight")],[[legacy_text(row["label"]),Metric(row["total_cad"]),Metric(row["weight"],"percent")] for row in payload["instrument_types"]])))
    analysis.blocks.append(("table",table([label("symbol"),*[a["label"] for a in payload["matrix"]["accounts"]]],[[row["symbol"],*[Metric(row["values"][a["account_id"]]) for a in payload["matrix"]["accounts"]]] for row in payload["matrix"]["rows"]])))
    result.append(("portfolio_analysis",analysis))
    if payload.get("lookthrough"):
        from .lookthrough_reports import report_section
        exposure = report_section(payload,charts)
        exposure.introduction.insert(0,label("weights_note"))
        top = next(block for kind,block in exposure.blocks if kind=="table")
        top.source_values = {(i,col):Metric(D(row[key]),"percent" if col>=5 else "money")
            for i,row in enumerate(payload["lookthrough"]["top20"])
            for col,key in ((2,"direct_cad"),(3,"indirect_cad"),(4,"total_cad"),(5,"investment_weight"),(6,"asset_weight"),(7,"company_weight")) if row[key] is not None}
        result.append(("portfolio_analysis",exposure))
        if payload["lookthrough"].get("classification"):
            from .classification_reports import report_section as classifications
            result.append(("portfolio_analysis",classifications(payload,charts)))
    if payload["source_crypto"]["in_scope"]:
        result.extend(_btc_sections(payload))
    history = ReportSection(label("history"),[label("history_note"),label("no_performance")])
    if payload["meta"]["source_report_observation_id"] is None:
        history.introduction.append(label("valuation_preview_note"))
    history.blocks.append(("table",table([label("as_of"),label("revision"),"CAD","USD","TWD"],[[row["as_of"],str(row["revision"]),*[Metric(row["totals"]["total_"+unit.lower()]) for unit in ("CAD","USD","TWD")]] for row in payload["history"]])))
    prior = model["frozen_combined_observations"]
    if prior:
        history.blocks.append(("paragraph",label("legacy_history_note")))
        history.blocks.append(("table",table([label("id"),label("as_of"),"CAD","USD","TWD"],[[str(row["id"]),row["record"]["as_of"],*[Metric(row["record"]["view"]["totals"]["total_"+unit.lower()]) for unit in ("CAD","USD","TWD")]] for row in prior])))
    result.append(("history",history))
    flows = ReportSection(label("flows"),[label("no_performance"),label("purchases_note")])
    flows.blocks.append(("table",table([label("measure"),"CAD"],[[label("recorded_external"),Metric(model["legacy_cash_flows"]["known_recorded_external_cad"])],[label("complete_contributions"),label("unknown")]])))
    native = model["legacy_cash_flows"]["records"]
    flows.blocks.append(("table",table([label("as_of"),label("account_id"),label("type"),label("currency"),label("amount"),"CAD"],[[row["date"],row["account_id"],row["flow_type"],row["currency"],Metric(row["amount"]),Metric(row["amount_cad"])] for row in native])))
    flows.blocks.append(("table",table([label("as_of"),label("account_id"),label("type"),label("currency"),label("amount"),label("classification")],[[row["occurred_at"],row["account_id"],row["type"],row["amount"]["currency"],Metric(row["amount"]["amount"]),row["classification"]] for row in model["cash_flows"]["records"]])))
    result.append(("cash_flows",flows))
    quality = ReportSection(label("quality"),[label("scope_note"),label("source_dates_note"),label("audit_note")])
    quality.blocks.append(("table",table([label("account"),label("provider"),label("role"),label("as_of"),label("coverage")],[[row["label"],row["provider"],row["role"],row.get("observed_as_of"),row["holdings_coverage"]] for row in model["accounts"]])))
    quality.blocks.append(("table",table([label("measure"),label("value"),label("as_of"),label("source")],[["CAD / USD",Metric(payload["fx"]["usd_cad"]),payload["fx"]["usd_cad_date"],payload["fx"]["usd_cad_source"]],["TWD / USD",Metric(payload["fx"]["usd_twd"]),payload["fx"]["usd_twd_date"],payload["fx"]["usd_twd_source"]]])))
    quality.blocks.append(("table",table([label("measure"),label("value")],[["Projection SHA-256",model["projection_sha256"]],["Financial state SHA-256",model["state_sha256"]],[label("performance"),label("unknown")]])))
    for row in model["gaps"]:
        quality.blocks.append(("paragraph",row["code"]+" / "+row["account_id"]))
    result.append(("rates_notes",quality))
    chart_section = ReportSection(label("charts"),[label("weights_note"),label("history_note")])
    used={path for _,section in result for kind,path in section.blocks if kind=="chart"}
    for key,path in charts.items():
        if path in used: continue
        chart_section.blocks.append(("chart",path))
    result.append(("charts",chart_section))
    return result


@financial_context
def monthly_purchases(payload):
    months = defaultdict(lambda:{"quantity":ZERO,"net_quantity":ZERO,"spend":ZERO})
    for row in payload["source_crypto"]["purchases"]:
        from .source_projection import _time
        from zoneinfo import ZoneInfo
        month = _time(row["occurred_at"]).astimezone(ZoneInfo("America/Toronto")).strftime("%Y-%m")
        months[month]["quantity"] += D(row["source_leg_quantity"])
        months[month]["net_quantity"] += D(row["net_recorded_quantity_change"])
        months[month]["spend"] += D(row["purchase_cash_spend_cad"])
    return [{"month":month,**row,"rate":row["spend"]/row["quantity"] if row["quantity"]>0 else None} for month,row in sorted(months.items())]


def _btc_sections(payload):
    asset = payload["source_crypto"]
    wallet = payload["source_projection"]["wallet"]
    btc = ReportSection(label("btc"),[label("btc_note"),label("purchases_note")])
    values = [("btc_total",Metric(asset["quantity_btc"],"btc_quantity")),("quantity_status",label("status_"+asset["quantity_status"]) if asset["quantity_btc"] is not None else label("unknown")),
              ("opening",Metric(asset["opening"]["opening_btc_equivalent_qty"] if asset["opening"] else "0" if asset["acquisition_history_known"] else None,"btc_quantity")),
              ("actual_cost",Metric(asset["actual_full_cost_cad"])),("actual_gain",Metric(None)),("actual_return",Metric(None,"percent")),("cost_policy",label("cost_proxy" if asset["cost_policy"]=="bull_average_proxy" else "cost_actual_only")),
              ("proxy_quantity",Metric(asset["proxy_purchase_quantity_btc"],"btc_quantity")),("proxy_spend",Metric(asset["proxy_purchase_spend_cad"])),
              ("proxy_average",Metric(asset["proxy_average_cad_per_btc"])),("estimated_cost",Metric(asset["estimated_full_cost_cad"])),("estimated_gain",Metric(asset["estimated_gain_cad"])),("estimated_return",Metric(asset["estimated_return"],"percent"))]
    btc.blocks.append(("table",table([label("measure"),label("value")],[[label(name),value] for name,value in values])))
    quote=asset.get("price")
    btc.blocks.append(("table",table([label("measure"),label("value")],[["BTC / USD",Metric(quote["close"] if quote else None)],
        [label("price_time"),quote["candle_end"] if quote else None],[label("quote_source"),quote["source_url"] if quote else None]])))
    btc.blocks.append(("paragraph",label("proxy_note")))
    btc.blocks.append(("table",table([label("measure"),"CAD","USD","TWD"],[[label("btc_value"),*[Metric(asset["market_values"][unit]) for unit in ("CAD","USD","TWD")]]])))
    btc.blocks.append(("table",table([label("account_id"),label("cash_cad")],[[aid,Metric(value)] for aid,value in asset["legacy_cash_cad_by_account"].items()])))
    btc.blocks.append(("paragraph",label("cash_unknown_note")))
    btc.blocks.append(("subheading",label("monthly")))
    btc.blocks.append(("table",table([label("month"),label("purchased_btc"),label("net_btc"),label("purchase_cad"),label("rate")],[[row["month"],Metric(row["quantity"],"btc_quantity"),Metric(row["net_quantity"],"btc_quantity"),Metric(row["spend"]),Metric(row["rate"])] for row in monthly_purchases(payload)])))
    reconciliation = ReportSection(label("reconciliation"),[label("btc_note")])
    reconciliation.blocks.append(("table",table([label("id"),label("as_of"),label("reported"),label("recorded_gap"),label("current_gap"),label("status")],[[row["balance_id"],row["as_of"],Metric(row["reported_btc"],"btc_quantity"),Metric(row["recorded_residual_btc"],"btc_quantity"),Metric(row["residual_btc"],"btc_quantity"),legacy_text(row["status_label"])] for row in wallet["reconciliations"]])))
    reconciliation.blocks.append(("table",table([label("measure"),label("value")],[[label("ledger_expected"),Metric(wallet["ledger_expected_btc"],"btc_quantity")],[label("opening_overlap"),label("yes" if wallet["opening_overlap"] else "no")]])))
    return [("btc_tracking",btc),("btc_reconciliation",reconciliation)]
