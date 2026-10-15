"""Block report publication when current BTC state is presented misleadingly."""
from .i18n import tr, LabelCatalog, localized, sheet_title, legacy_text
from decimal import Decimal
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET
from pypdf import PdfReader

NS = {"t": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
      "o": "urn:oasis:names:tc:opendocument:xmlns:office:1.0"}


@localized
def validate_report_presentation(payload, output):
    """Check all three formats against active quantities and cost completeness."""
    from .i18n import display_payload
    original_payload = payload
    payload = display_payload(payload)
    crypto = payload.get("crypto")
    if not crypto:
        return {"status": "not_applicable", "checks": 0}
    output = Path(output)
    md = (output/"report.md").read_text(encoding="utf-8")
    pdf = "\n".join(page.extract_text() or "" for page in PdfReader(output/"report.pdf").pages)
    with zipfile.ZipFile(output/"portfolio.ods") as archive:
        xml = ET.fromstring(archive.read("content.xml"))
    sheets = {sheet.get("{"+NS["t"]+"}name"): sheet for sheet in xml.findall(".//t:table", NS)}
    btc = sheets[tr('message.b73b53a54517')]
    rows = btc.findall("t:table-row", NS)
    checks = 0

    def require(condition, message):
        nonlocal checks
        if not condition:
            raise ValueError("Report presentation check failed: " + message)
        checks += 1

    def cell(row, col):
        return rows[row-1].findall("t:table-cell", NS)[col-1]

    def numeric(element, expected, label):
        value = element.get("{"+NS["o"]+"}value")
        require(value is not None and Decimal(value) == Decimal(str(expected)), label)

    numeric(cell(8, 3), crypto["btc_equivalent_qty"], "effective BTC quantity differs from payload")
    from .wallet_reports import quantity_basis_label
    basis = quantity_basis_label(crypto)
    require(basis == "".join(cell(21,3).itertext()), "ODS BTC quantity basis differs")
    require(basis in md and "".join(basis.split()) in "".join(pdf.split()), "BTC quantity basis differs across formats")
    require(tr('message.a516220595db') in md and "".join(tr('message.a516220595db').split()) in "".join(pdf.split())
            and tr('message.a516220595db') in "".join(cell(24,4).itertext()), "fee coverage policy missing")
    numeric(cell(18, 3), crypto["total_buy_cost_cad"], "known Bull purchase cost was lost")
    for format_name, text in [("Markdown", md), ("PDF", pdf)]:
        require(tr('message.687923f71c66') in text, format_name + " omits known Bull purchase cost")
        amount = f'{Decimal(str(crypto["total_buy_cost_cad"])):,.2f}'
        matching_cost = tr('message.13e2efce292c', value0=amount) in text if format_name == "Markdown" else (tr('message.d8b290040f38') + amount) in "".join(text.split())
        require(matching_cost, format_name + " reports an incorrect known Bull purchase amount")
    from .btc_performance import btc_cost_estimate
    from .reporting import _money, _percent
    from .workbook import ref
    estimate = btc_cost_estimate(original_payload["crypto"])
    for format_name, text in [("Markdown", md), ("PDF", pdf), ("ODS", "".join(xml.itertext()))]:
        require(tr('message.175bbf9f3fdf') in text, format_name + " omits the estimated cost scope")
        require(tr('message.187f8d0709fc').casefold() in text.casefold(), format_name + " omits the proxy scope for unexplained quantities")
        if estimate["status"] == "proxy_disabled":
            require(tr('message.14a99dace84e').casefold() in text.casefold(), format_name + " omits the disabled proxy policy")
    metrics = [(31, "average_price_cad_per_btc", tr('message.9d9ed2aa01ac'), _money),
               (9, "estimated_cost_cad", tr('message.ab4aaf32040f'), _money),
               (15, "estimated_gain_cad", tr('message.5c00f5d9c098'), _money),
               (16, "estimated_return", tr('message.19cbcfc5d23f'), _percent)]
    for row, key, label, formatter in metrics:
        expected = estimate[key]
        if expected is None:
            require(cell(row,3).get("{"+NS["o"]+"}value") is None, "unavailable BTC estimate was turned into a number")
        else:
            numeric(cell(row,3), expected, "BTC cost estimate differs from selected Bull average method")
            amount = formatter(expected)
            require(f"| {label} | {amount} |" in md, "Markdown reports an incorrect BTC estimate")
            require(("".join(label.split()) + amount) in "".join(pdf.split()), "PDF reports an incorrect BTC estimate")
        if row != 31:
            require(tr('message.175bbf9f3fdf') in "".join(cell(row,2).itertext()), "ODS labels estimated BTC costs as actual")
    formulas = {31: f'IF({ref('btc_tracking', 29, 3)}<=0;"n.a.";{ref('btc_tracking', 18, 3)}/{ref('btc_tracking', 29, 3)})',
                9: f'{ref('btc_tracking', 8, 3)}*{ref('btc_tracking', 31, 3)}',
                15: f'{ref('btc_tracking', 12, 3)}-{ref('btc_tracking', 9, 3)}',
                16: f'IF({ref('btc_tracking', 9, 3)}<=0;"n.a.";{ref('btc_tracking', 15, 3)}/{ref('btc_tracking', 9, 3)})'}
    for row, formula in formulas.items():
        applicable = row == 31 or (estimate["estimated_cost_cad"] is not None if row==9 else estimate["estimated_gain_cad"] is not None)
        actual = cell(row,3).get("{"+NS["t"]+"}formula")
        require(actual == "of:="+formula if applicable else actual is None,
                "BTC proxy formula uses an incorrect cost or quantity basis")
    estimate_audit = json.loads((output/"btc-cost-estimate.json").read_text(encoding="utf-8"))
    require(estimate_audit["estimate"] == json.loads(json.dumps(estimate,default=str)), "BTC cost estimate audit differs")
    require(estimate_audit["report_as_of"] == payload["meta"]["as_of"], "BTC cost estimate audit has a different date")
    opening = crypto.get("opening")
    if opening:
        for format_name, text in [("Markdown", md), ("PDF", pdf), ("ODS", "".join(xml.itertext()))]:
            require(tr('message.5b484e67db14') not in text and tr('message.28f660534af5') not in text,
                    format_name + " includes superseded original assumptions")
            from .reporting import _quantity
            amount = _quantity(opening["opening_btc_equivalent_qty"])
            matching_opening = (tr('message.b0f7104b4b15', value0=amount) in text if format_name == "Markdown"
                                else (tr('message.a47f9c077f54') + amount) in "".join(text.split()) if format_name == "PDF"
                                else tr('message.b7fe9fecaf0d') in text)
            require(tr('message.b7fe9fecaf0d') in text and matching_opening, format_name + " omits or misstates effective opening")
        numeric(cell(34, 3), opening["opening_btc_equivalent_qty"], "effective opening quantity differs")
        audit = json.loads((output/"btc-opening-audit.json").read_text(encoding="utf-8"))
        require(audit["original_bull_ledger_assumptions"] == crypto["assumptions"], "original assumptions audit differs")
        require(audit["effective_pre_bull_opening_declaration"] == opening, "active opening audit differs")
    status = crypto.get("valuation", {}).get("cost_status")
    if status in ("partial_unknown_opening", "unknown_wallet_cost"):
        crypto_symbols = {legacy_text(p["symbol"]) for p in payload["positions"] if p["security_type"] == "CRYPTO"}
        for sheet_name, symbol_col, cost_cols in [(tr('message.484a63a94233'), 3, (10,11,13,14,15)),
                                                (tr('message.663bc1877993'), 2, (5,6,8,9))]:
            matched = 0
            for row in sheets[sheet_name].findall("t:table-row", NS):
                cells = row.findall("t:table-cell", NS)
                is_position_row = sheet_name == tr('message.484a63a94233') or (len(cells) >= 3 and tr('message.51ee25980084') in "".join(cells[2].itertext()))
                if is_position_row and len(cells) >= max(cost_cols) and "".join(cells[symbol_col-1].itertext()) in crypto_symbols:
                    matched += 1
                    for col in cost_cols:
                        require(cells[col-1].get("{"+NS["o"]+"}value") is None
                                and cells[col-1].get("{"+NS["t"]+"}formula") is None,
                                sheet_name + " turns missing BTC cost/return into numeric data")
            require(matched > 0, sheet_name + " omits crypto cost-completeness rows")
        require(''.join(tr('message.c7d4571af139').casefold().split()) in ''.join(md.casefold().split()) and ''.join(tr('message.c7d4571af139').casefold().split()) in ''.join(pdf.casefold().split()), "cost completeness reason missing")
    wallet = crypto.get("wallet", {})
    residual = wallet.get("anchor_ledger_residual_btc")
    reconciliation = sheets[tr('message.81a4766e262f')]
    for row in reconciliation.findall("t:table-row", NS):
        cells = row.findall("t:table-cell", NS)
        if len(cells) >= 4 and tr('message.15420ba6aba6') in "".join(cells[1].itertext()):
            if residual is not None:
                numeric(cells[3], residual, "observed difference, including zero, must remain numeric")
            else:
                from .wallet_reports import anchor_difference_status
                label = anchor_difference_status(wallet)
                require(label in "".join(cells[3].itertext()), "missing observation/ledger reason omitted")
                require(label in md and label in pdf, "formats disagree about unavailable comparison")
            break
    else:
        require(False, "observed-versus-ledger comparison row missing")
    selected_policy = crypto.get("cost_estimate_policy", "bull_average_proxy")
    return {"status": "passed", "checks": checks, "btc_cost_policy": selected_policy,
            "policy": "active_state_actual_costs_only" if selected_policy == "actual_only"
            else "active_state_bull_average_estimate_and_separate_actual_costs"}
