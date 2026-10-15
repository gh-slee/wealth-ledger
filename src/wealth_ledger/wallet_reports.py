"""Shared BTC reconciliation report tables and reproducible audit exports."""
from .i18n import tr, LabelCatalog, localized, sheet_title, legacy_text
import csv
from decimal import Decimal
from pathlib import Path

KNOWN_CHANGES_NOTE = 'message.675ca198b56f'


def quantity_basis_label(crypto):
    """Distinguish a reported baseline from later ledger-derived quantities."""
    from .crypto import _time
    cutoff = _time(crypto["meta"]["as_of"])
    wallet = crypto.get("wallet", {})
    anchor = wallet.get("anchor")
    if anchor:
        return (tr('message.20470eb51638') if _time(anchor["as_of"]) == cutoff
                else tr('message.1a60f8b93fea'))
    if wallet:
        return tr('message.31f1e8c93ab7')
    opening = crypto.get("opening")
    if opening:
        total = opening.get("reported_total_btc_equivalent")
        reference = opening.get("reference_as_of")
        if (reference and total is not None and _time(reference) == cutoff
                and Decimal(str(total)) == Decimal(str(crypto["btc_equivalent_qty"]))):
            return tr('message.560f9f59dce2')
        return tr('message.78afb1def798')
    return tr('message.2283f7bca4b4')


def display_time(value):
    from zoneinfo import ZoneInfo
    from .prices import parse_time
    return parse_time(value).astimezone(ZoneInfo("America/Toronto")).isoformat()


def time_basis_label(observation):
    return tr('message.3af9d0380bed') if observation.get("time_basis") == "execution_time" else tr('message.e9ffc96ac233')


def anchor_difference_status(wallet):
    """Explain why no observed-versus-ledger comparison is available."""
    if not wallet.get("anchor"):
        return tr('message.2f9d340018e5')
    return tr('message.445362f346d2')


def reconciliation_section(crypto, charts):
    from .reporting import ReportSection, ReportTable, _quantity
    wallet = crypto.get("wallet", {})
    section = ReportSection(tr('message.214910fbe5a9'), [
        tr('message.d918d56a49ed'),
        tr('message.de726d10c3f6')])
    if crypto.get("opening"):
        section.introduction.append(tr('message.c2c5c3454ee7'))
    rows = wallet.get("reconciliations", [])
    if not rows:
        section.blocks.append(("paragraph", tr('message.9b2ed7d332f4')))
    else:
        section.blocks.append(("table", ReportTable(
            [tr('message.408f0321e4da'), tr('message.bc219dcdbcb9'), tr('message.d96c5597df4b'), tr('message.2c8d97f42177'), tr('message.1f8dd6cfee21'), tr('message.e01b94ddd5d5')],
            [[r["balance_id"], display_time(r["as_of"]), _quantity(r["reported_btc"]), _quantity(r["expected_btc"]),
              _quantity(r["residual_btc"]), r["status_label"]] for r in rows], [.7,1.7,1,1,1,1.3])))
        observations = {b["record_id"]: b for b in wallet.get("observations", [])}
        section.blocks.append(("table", ReportTable([tr('message.408f0321e4da'), tr('message.91c587e1ca01'), tr('message.3a68ce95632e')],
            [[r["balance_id"], observations[r["balance_id"]]["source"],
              time_basis_label(observations[r["balance_id"]])] for r in rows])))
        section.blocks.append(("subheading", tr('message.387e19b4f2b9')))
        section.blocks.append(("table", ReportTable(
            [tr('message.408f0321e4da'), tr('message.f8950d4ecec5'), tr('message.0f8a617fca24'), tr('message.68a2e7ec154f'), tr('message.abfe430ecc23')],
            [[r["balance_id"], str(r["balance_revision"]), _quantity(r["recorded_expected_btc"]),
              _quantity(r["recorded_residual_btc"]), ", ".join(r["event_ids"]) or "—"] for r in rows])))
    anchor = wallet.get("anchor")
    section.blocks.append(("table", ReportTable([tr('message.25fbdbc6de88'), tr('message.21e5bce6a622')], [
        [tr('message.26de4e2afff5'), anchor["record_id"] if anchor else tr('message.8b7506735483')],
        [tr('message.5e307f69ff0c'), _quantity(crypto["btc_equivalent_qty"])],
        [tr('message.c2c9a3fd5caa'), _quantity(wallet.get("ledger_expected_btc", crypto['btc_equivalent_qty']))],
        [tr('message.e97d40d37222'), _quantity(wallet["anchor_ledger_residual_btc"]) if wallet.get("anchor_ledger_residual_btc") is not None else anchor_difference_status(wallet)],
        [tr('message.7c118c3bbffa'), str(wallet.get("unresolved_count",0))],
        [tr('message.de944e3c82f7'), ", ".join(wallet.get("link_conflicts", [])) or (tr('message.3374f434b16c') if wallet.get("opening_overlap") else tr('message.a2720f3f0784'))],
    ], [1,2.6])))
    if wallet.get("events"):
        section.blocks.append(("subheading", tr('message.0a8a85f13fd4')))
        section.blocks.append(("table", ReportTable([tr('message.7e92f223e8a6'), tr('message.1588dd8c9e73'), tr('message.cdac1b99b96c'), tr('message.3bb6a1067a37'), tr('message.72d7dfc469a6')],
            [[e["record_id"], e["type"], display_time(e["occurred_at"]), _quantity(e["quantity_btc"]), e.get("balance_id") or tr('message.7409a608060f')]
             for e in wallet["events"]], [.75,.85,1.6,1,1])))
        section.blocks.append(("table", ReportTable([tr('message.7e92f223e8a6'), tr('message.c21db84c0653'), tr('message.0c247218b3d7'), tr('message.97850a2a41d0')],
            [[e["record_id"], e["source"], e["reference"], tr('message.1dd0070a380f')] for e in wallet["events"]])))
    if "16_btc_wallet_reconciliation" in charts:
        section.blocks.append(("chart",charts["16_btc_wallet_reconciliation"]))
    return section


def write_exports(payload, output):
    crypto = payload.get("crypto")
    if not crypto:
        return
    wallet = crypto.get("wallet", {})
    for name, fields, rows in (
        ("btc-reconciliation.csv", ("balance_id","balance_revision","as_of","reported_btc","expected_btc","residual_btc",
                                     "recorded_expected_btc","recorded_residual_btc","status","verification"), wallet.get("reconciliations", [])),
        ("btc-events.csv", ("record_id","revision","type","occurred_at","quantity_btc","source","reference","balance_id","verification"), wallet.get("events", [])),
    ):
        with (Path(output)/name).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fields, extrasaction="ignore")
            writer.writeheader(); writer.writerows(rows)


def build_sheet(sheet, crypto):
    from .workbook import ref, number
    wallet = crypto.get("wallet", {})
    sheet.widths.update({2:4,3:9,4:8.5,5:5,6:5,7:9,8:8,9:7})
    sheet.frozen_rows = 7
    sheet.put(5,2,tr('message.113d2ab73771'),style="note")
    sheet.section(6,tr('message.9450761c0031'))
    sheet.header(7,[tr('message.408f0321e4da'),tr('message.bc219dcdbcb9'),tr('message.d96c5597df4b'),tr('message.2c8d97f42177'),tr('message.1f8dd6cfee21'),tr('message.e01b94ddd5d5')])
    rows = wallet.get("reconciliations", [])
    for row, item in enumerate(rows,8):
        sheet.put(row,2,item["balance_id"])
        sheet.put(row,3,display_time(item["as_of"]))
        for col,key in ((4,"reported_btc"),(5,"expected_btc"),(6,"residual_btc")):
            formula = f"{ref(sheet.name,row,4)}-{ref(sheet.name,row,5)}" if col==6 and item[key] is not None else None
            sheet.put(row,col,number(item[key]) if item[key] is not None else tr('message.4d8c1c5b4283'),formula,style="btc_quantity")
        sheet.put(row,7,item["status_label"])
    if not rows:
        sheet.put(8,2,tr('message.c6abad7824b8') if crypto.get("opening") else tr('message.ae46f82b2683'),style="note")
    row = max(11, len(rows)+11)
    sheet.section(row,tr('message.b4cf2b8b66cf'))
    sheet.header(row+1,[tr('message.408f0321e4da'),tr('message.f8950d4ecec5'),tr('message.0f8a617fca24'),tr('message.68a2e7ec154f'),tr('message.abfe430ecc23')])
    for offset,item in enumerate(rows,2):
        sheet.row(row+offset,[item["balance_id"],item["balance_revision"],
            number(item["recorded_expected_btc"]) if item["recorded_expected_btc"] is not None else tr('message.4d8c1c5b4283'),
            number(item["recorded_residual_btc"]) if item["recorded_residual_btc"] is not None else tr('message.4d8c1c5b4283'), ", ".join(item["event_ids"]) or "—"])
        for col in (4,5):
            sheet.cells[row+offset,col].style="btc_quantity"
    row += len(rows)+4
    if rows:
        observations = {b["record_id"]: b for b in wallet.get("observations", [])}
        sheet.header(row,[tr('message.408f0321e4da'),tr('message.91c587e1ca01'),tr('message.3a68ce95632e')])
        for offset,item in enumerate(rows,1):
            observation = observations[item["balance_id"]]
            sheet.row(row+offset,[item["balance_id"],observation["source"],time_basis_label(observation)])
        row += len(rows)+3
    for offset,(label,value) in enumerate([
        (tr('message.d7b82211894a'),wallet.get("ledger_expected_btc",crypto['btc_equivalent_qty'])),
        (tr('message.15420ba6aba6'),wallet.get("anchor_ledger_residual_btc") if wallet.get("anchor_ledger_residual_btc") is not None else anchor_difference_status(wallet))]):
        sheet.put(row+offset,2,label)
        sheet.put(row+offset,4,value if isinstance(value,str) and value.startswith(tr('message.0532228251bb')) else number(value) if value is not None else tr('message.756762e293f2'),style="wrapped_body" if isinstance(value,str) and value.startswith(tr('message.0532228251bb')) else "btc_quantity")
    row += 4
    sheet.section(row,tr('message.d3cb3f4b445a'))
    sheet.header(row+1,[tr('message.7e92f223e8a6'),tr('message.1588dd8c9e73'),tr('message.cdac1b99b96c'),tr('message.3bb6a1067a37'),tr('message.72d7dfc469a6'),tr('message.c21db84c0653'),tr('message.0c247218b3d7'),tr('message.97850a2a41d0')])
    for offset,event in enumerate(wallet.get("events",[]),2):
        sheet.row(row+offset,[event["record_id"],event["type"],display_time(event["occurred_at"]),number(event["quantity_btc"]),
            event.get("balance_id") or tr('message.7409a608060f'),event["source"],event["reference"],tr('message.70412a1fb99e')])
        sheet.cells[row+offset,5].style="btc_quantity"
        for col in (8,9):
            sheet.cells[row+offset,col].style="wrapped_body"
