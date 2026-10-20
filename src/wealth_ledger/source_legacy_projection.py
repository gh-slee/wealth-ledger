"""Read-only native compatibility boundary for the canonical analysis model.

Legacy schema translation belongs here. New providers need no branches here or
in the shared source model. No historical rows, evidence or reports are rewritten.
"""
from copy import deepcopy
from datetime import datetime
from decimal import Context, Decimal as D, localcontext
import hashlib
import json
from pathlib import Path

from . import source_ingestion as store
from .source_projection import (ProjectionError, project_sources, _time, _key, _json,
                                _serialize, _position, _precision, _values)
from .wallet_reconciliation import reconcile_wallet, btc, sats

ZERO = D(0)


def _evidence(project, name, expected):
    root = Path(project).resolve()
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or not name.startswith("data/raw/"):
        raise ProjectionError("legacy_evidence_unsafe")
    path = root / relative
    if any(item.is_symlink() for item in (path, *path.parents) if item.is_relative_to(root)):
        raise ProjectionError("legacy_evidence_unsafe")
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ProjectionError("legacy_evidence_integrity")


def _legacy(project):
    conn = store._open(project)
    try:
        if conn:
            conn.execute("BEGIN")
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or conn.execute("PRAGMA foreign_key_check").fetchone():
                raise ProjectionError("legacy_database_integrity")
        names = ("accounts", "sources", "snapshots", "positions", "cash_flows", "manual_cash_flows", "flow_periods", "crypto_accounts",
                 "crypto_sources", "crypto_order_revisions", "crypto_opening_revisions", "wallet_revisions", "combined_observations")
        result = {name: store._rows(conn, name) for name in names}
        if any(row["provider"] != "bullbitcoin" for row in result["crypto_accounts"]):
            raise ProjectionError("unsupported_legacy_crypto_schema")
        for table, path, digest in (("sources", "path", "sha256"), ("crypto_sources", "path", "sha256"),
                                    ("crypto_opening_revisions", "source_path", "source_sha256"),
                                    ("wallet_revisions", "source_path", "sha256")):
            for row in result[table]:
                _evidence(project, row[path], row[digest])
        for row in result["crypto_order_revisions"]:
            order = json.loads(row["payload_json"])
            if (order["payin_currency"] != "CAD" or order["order_type"] not in {"Funding", "Buy Bitcoin"}
                    or order["order_type"] == "Funding" and order["payout_currency"] != "CAD"
                    or order["order_type"] == "Buy Bitcoin" and
                    (order["payout_currency"], order["network"]) not in {("BTC", "bitcoin"), ("LBTC", "liquid")}):
                raise ProjectionError("unsupported_legacy_crypto_schema")
            if hashlib.sha256(row["payload_json"].encode()).hexdigest() != row["content_hash"]:
                raise ProjectionError("legacy_order_integrity")
        for row in result["wallet_revisions"]:
            if hashlib.sha256((row["payload_json"] + "\n").encode()).hexdigest() != row["sha256"]:
                raise ProjectionError("legacy_wallet_integrity")
        return result
    finally:
        if conn:
            conn.close()


def _native_position(row, snapshot, provider):
    currency = row["currency"]
    if currency not in {"CAD", "USD"}:
        raise ProjectionError("unsupported_legacy_currency")
    for key in ("quantity", "price", "book_native", "book_cad", "market_native", "unrealized_native"):
        if row.get(key) is not None and not D(str(row[key])).is_finite():
            raise ProjectionError("legacy_position_integrity")
    if D(row["quantity"]) < 0 or D(row["market_native"]) < 0:
        raise ProjectionError("unsupported_legacy_position")
    asset = {"kind": "cash" if row["security_type"] == "CURRENCY" else "security", "symbol": row["symbol"],
             "currency": currency, "market": row["mic"] or None, "network": None, "identifier": None}
    if asset["kind"] == "cash":
        asset["market"] = None
    money = lambda key, unit: {"amount": row[key], "currency": unit} if row.get(key) is not None else None
    return {"kind": "holdings", "key": {"source_id": row["security_id"], "revision": str(snapshot["revision"])},
            "observation_id": "legacy:snapshot:" + str(snapshot["id"]), "as_of": snapshot["as_of"],
            "asset": asset, "name": row["name"], "instrument_type": row["security_type"], "exchange": row["exchange"],
            "quantity": row["quantity"], "market_value": money("market_native", currency), "unit_price": money("price", currency),
            "cost_native": money("book_native", currency), "cost_cad": money("book_cad", "CAD"),
            "unrealized": money("unrealized_native", currency)}


def _position_signature(row):
    asset = row["asset"]
    def money(value):
        return (value["currency"], D(value["amount"])) if value is not None else None
    return (row["key"]["source_id"], _json(asset), D(row["quantity"]), money(row["market_value"]),
            money(row["unit_price"]), money(row["cost_native"]), money(row["cost_cad"]), money(row["unrealized"]))


def _display_sum(rows):
    return {unit: sum((D(row["market_values"][unit]) for row in rows), ZERO)
            if all(row["market_values"][unit] is not None for row in rows) else None for unit in ("CAD", "USD", "TWD")}


def _holdings(model, legacy, canonical, cutoff):
    bindings = {row["ledger_account"]: row for row in canonical.get("bindings", []) if row["target_kind"] == "legacy_holdings"}
    native_ids = {row["account_id"] for row in legacy["accounts"]}
    if any(row["provider"] == "wealthsimple" and row["source_account"] in native_ids
           and (row["target_kind"] != "legacy_holdings" or row["ledger_account"] != row["source_account"])
           for row in canonical.get("bindings", [])):
        raise ProjectionError("legacy_binding_required")
    coverage_heads = {}
    for row in sorted(canonical.get("coverage", []), key=lambda row: row["id"]):
        coverage_heads[(row["provider"], row["scope_key"])] = row
    by_snapshot = {}
    for row in sorted(legacy["snapshots"], key=lambda row: row["id"]):
        if _time(row["as_of"]) <= cutoff:
            by_snapshot[_time(row["as_of"])] = row
    grouped = {}
    for row in legacy["positions"]:
        grouped.setdefault(row["snapshot_id"], {}).setdefault(row["account_id"], []).append(json.loads(row["payload_json"]))
    mapped = {(row["provider"], row["source_account"]): row["ledger_account"] for row in bindings.values()}
    current_groups, variants = {}, {}
    for record in canonical["records"]:
        token = _key(record["key"]["account"])
        if record["kind"] == "holdings" and token in mapped:
            group = (token[0], record["observation_id"], _time(record["as_of"]))
            current_groups.setdefault(group, set()).add((mapped[token], _position_signature(record)))
    for record in canonical["all_records"]:
        token = _key(record["key"]["account"])
        if record["kind"] == "holdings" and token in mapped:
            group = (token[0], record["observation_id"], _time(record["as_of"]))
            variants.setdefault((*group, record["key"]["revision"]), set()).add((mapped[token], _position_signature(record)))
    for group, signature in current_groups.items():
        active = by_snapshot.get(group[2])
        if active is None:
            continue
        def native_signature(snapshot):
            return {(aid, _position_signature(_native_position(row, snapshot, "legacy_holdings")))
                    for aid, rows in grouped.get(snapshot["id"], {}).items() for row in rows}
        current_signature = native_signature(active)
        old = [row for row in legacy["snapshots"] if _time(row["as_of"]) == group[2] and row["id"] != active["id"]]
        if signature != current_signature and any(signature == native_signature(row) for row in old):
            if not any(value == current_signature for key, value in variants.items() if key[:3] == group):
                raise ProjectionError("legacy_snapshot_replay_conflict")
    selected = {}
    for _, snapshot in sorted(by_snapshot.items()):
        for account, rows in grouped.get(snapshot["id"], {}).items():
            selected[account] = (snapshot, rows)
    accounts = {row["account_id"]: deepcopy(row) for row in model["accounts"]}
    positions = deepcopy(model["positions"])
    overlaps = []
    for metadata in sorted(legacy["accounts"], key=lambda row: row["account_id"]):
        aid = metadata["account_id"]
        if aid in accounts:
            accounts[aid]["label"] = metadata["label"]
            accounts[aid]["masked_identifier"] = metadata["masked_number"]
        if aid not in selected:
            if aid not in accounts:
                accounts[aid] = {"account_id": aid, "provider": "legacy_holdings", "source_account": aid,
                    "target_kind": "legacy_holdings", "account_type": metadata["account_type"], "label": metadata["label"],
                    "masked_identifier": metadata["masked_number"], "role": "investment", "observation_id": None,
                    "observed_as_of": None, "carried": False, "holdings_coverage": "unknown",
                    "observed_values": {unit: None for unit in ("CAD", "USD", "TWD")}, "unobserved_prior_assets": []}
            continue
        snapshot, old_rows = selected[aid]
        binding = bindings.get(aid)
        provider = binding["provider"] if binding else "legacy_holdings"
        temporary = {"ledger_account": aid, "provider": provider,
                     "source_account": binding["source_account"] if binding else aid}
        native = [_native_position(row, snapshot, provider) for row in old_rows]
        existing = accounts.get(aid)
        current_time = _time(existing["observed_as_of"]) if existing and existing["observed_as_of"] else None
        if current_time and current_time >= _time(snapshot["as_of"]):
            if current_time == _time(snapshot["as_of"]):
                token = (binding["provider"], binding["source_account"])
                variants = {}
                # Current heads alone cannot prove an earlier explicit correction.
                for record in canonical["all_records"]:
                    if record["kind"] == "holdings" and _key(record["key"]["account"]) == token and record["observation_id"] == existing["observation_id"]:
                        variants.setdefault(record["key"]["revision"], []).append(record)
                signatures = {_position_signature(row) for row in native}
                if not any({_position_signature(row) for row in rows} == signatures for rows in variants.values()):
                    raise ProjectionError("legacy_observation_conflict")
                existing["legacy_snapshot_id"] = snapshot["id"]
                overlaps.append({"account_id": aid, "legacy_snapshot_id": snapshot["id"], "observation_id": existing["observation_id"]})
            elif existing["holdings_coverage"] != "complete":
                observed = {_json(row["asset"]) for row in positions if row["account_id"] == aid}
                omitted = {_json(row["asset"]) for row in native} - observed
                # A complete canonical observation after the legacy one resets scope.
                completed = any(json.loads(row["payload_json"]).get("status") == "complete"
                                and json.loads(row["payload_json"]).get("kind") == "holdings"
                                and _key(json.loads(row["payload_json"])["account"]) == (binding["provider"], binding["source_account"])
                                and _time(snapshot["as_of"]) <= _time(json.loads(row["payload_json"])["end"]) <= current_time
                                for row in coverage_heads.values() if not row["scope_key"].startswith(("snapshot:", "membership:")))
                if omitted and not completed:
                    union = {_json(asset) for asset in existing["unobserved_prior_assets"]} | omitted
                    existing["unobserved_prior_assets"] = [json.loads(asset) for asset in sorted(union)]
            continue
        group = [_position(row, temporary, model["fx"]) for row in native]
        for row in group:
            row.update(origin="legacy", legacy_snapshot_id=snapshot["id"])
        positions = [row for row in positions if row["account_id"] != aid] + group
        accounts[aid] = {"account_id": aid, "provider": provider, "source_account": temporary["source_account"],
                         "target_kind": "legacy_holdings", "account_type": metadata["account_type"], "label": metadata["label"],
                         "role": "investment", "masked_identifier": metadata["masked_number"], "observation_id": native[0]["observation_id"], "observed_as_of": snapshot["as_of"],
                         "carried": _time(snapshot["as_of"]) < cutoff, "holdings_coverage": "partial",
                         "observed_values": _display_sum(group), "unobserved_prior_assets": [],
                         "legacy_snapshot_id": snapshot["id"]}
    model["positions"] = sorted(positions, key=lambda row: (row["account_id"], row["source_id"]))
    model["accounts"] = sorted(accounts.values(), key=lambda row: row["account_id"])
    model["observed_values"] = _display_sum(positions) if positions else model["observed_values"]
    has_observation = any(row["role"] != "funding" and row["observation_id"] is not None for row in accounts.values())
    model["native_observed_values"] = {unit: sum((D(row["market_native"]) for row in positions if row["currency"] == unit), ZERO)
                                       if has_observation else None for unit in ("CAD", "USD")}
    model["gaps"] = [{"code": "unobserved_prior_assets", "account_id": row["account_id"], "count": len(row["unobserved_prior_assets"])}
                     for row in accounts.values() if row["unobserved_prior_assets"]]
    model["gaps"].extend({"code": "missing_holdings_observation", "account_id": row["account_id"]}
                         for row in accounts.values() if row["role"] == "investment" and row["observation_id"] is None)
    return overlaps


def _order_signature(record):
    life = record.get("lifecycle")
    if not life:
        return None
    return (life["source_type"], D(life["payin"]["quantity"]), life["payin"]["asset"]["symbol"],
            D(life["payout"]["quantity"]), life["payout"]["asset"]["symbol"], life["payout"]["asset"].get("network"),
            _time(life["created_at"]), _time(life["completed_at"]) if life["completed_at"] else None)


def _acquisitions(model, legacy, canonical, cutoff):
    from .source_formats import _complete
    latest = {}
    for row in sorted(legacy["crypto_order_revisions"], key=lambda row: row["id"]):
        latest[(row["provider"], row["source_account"], row["order_key"])] = row
    accounts = {(row["provider"], row["source_account"]): row for row in legacy["crypto_accounts"]}
    bindings = {row["ledger_account"]: row for row in canonical.get("bindings", []) if row["target_kind"] == "legacy_crypto"}
    if any((row["provider"], row["source_account"]) in accounts and
           (row["target_kind"] != "legacy_crypto" or row["ledger_account"] != accounts[(row["provider"], row["source_account"])]["account_id"])
           for row in canonical.get("bindings", [])):
        raise ProjectionError("legacy_binding_required")
    purchases = {(row["account_id"], row["source_id"]): deepcopy(row) for row in model["movements"]["purchases"]}
    records = {(*_key(row["key"]["account"]), row["kind"], row["key"]["source_id"]): row for row in canonical["records"]}
    canonical_account = {row["account_id"]: row for row in model["accounts"]}
    proxy_accounts = {row["ledger_account"] for row in canonical.get("bindings", [])
                      if (row["provider"], row["source_account"]) in canonical["bull_accounts"]}
    funding = []
    overlaps = []
    cash_links = {}
    for record in canonical["records"]:
        if record["kind"] != "crypto_transactions":
            continue
        owner = next((row["ledger_account"] for row in canonical.get("bindings", [])
                      if (row["provider"], row["source_account"]) == _key(record["key"]["account"])), None)
        if owner not in bindings:
            continue
        for leg in record["legs"]:
            if leg["asset"]["kind"] == "cash":
                token = _key(leg["account"])
                if token in cash_links and cash_links[token] != owner:
                    raise ProjectionError("legacy_cash_binding_ambiguous")
                cash_links[token] = owner
    for (provider, alias, source_id), stored in latest.items():
        old = json.loads(stored["payload_json"])
        account = accounts[(provider, alias)]
        aid = account["account_id"]
        proxy_accounts.add(aid)
        binding = bindings.get(aid)
        incoming = None
        if old["order_type"] == "Buy Bitcoin":
            incoming = records.get((binding["provider"], binding["source_account"], "crypto_transactions", source_id)) if binding else None
        elif binding:
            candidates = [row for row in canonical["records"] if row["kind"] == "cash_flows"
                          and row["key"]["account"]["provider"] == binding["provider"] and row["key"]["source_id"] == source_id]
            if len(candidates) > 1:
                raise ProjectionError("legacy_funding_identity_ambiguous")
            incoming = candidates[0] if candidates else None
            if incoming:
                token = _key(incoming["key"]["account"])
                if token in cash_links and cash_links[token] != aid:
                    raise ProjectionError("legacy_cash_binding_ambiguous")
                cash_links[token] = aid
        if incoming is not None:
            if _complete(old):
                signature = (old["order_type"], D(old["payin_amount"]), old["payin_currency"], D(old["payout_amount"]),
                             old["payout_currency"], old["network"] or None, _time(old["created_at"]), _time(old["completed_at"]))
                economic_match = False
                if incoming["kind"] == "cash_flows":
                    economic_match = (incoming["type"] == "deposit" and incoming["direction"] == "in"
                                      and incoming["amount"]["currency"] == "CAD"
                                      and D(incoming["amount"]["amount"]) == D(old["payin_amount"])
                                      and incoming["boundary"] == "unclassified")
                else:
                    cash_legs = [leg for leg in incoming["legs"] if leg["asset"]["kind"] == "cash"]
                    crypto_legs = [leg for leg in incoming["legs"] if leg["asset"]["kind"] == "crypto"]
                    economic_match = (incoming["type"] == "purchase" and len(cash_legs) == len(crypto_legs) == 1
                                      and D(cash_legs[0]["quantity"]) == D(old["payin_amount"]).copy_negate()
                                      and D(crypto_legs[0]["quantity"]) == D(old["payout_amount"])
                                      and crypto_legs[0]["asset"]["symbol"] == old["payout_currency"]
                                      and crypto_legs[0]["asset"]["network"] == old["network"]
                                      and incoming["acquisition_cost_cad"] is not None
                                      and D(incoming["acquisition_cost_cad"]["amount"]) == D(old["payin_amount"]))
                if incoming["status"] != "completed" or _order_signature(incoming) != signature or not economic_match:
                    raise ProjectionError("legacy_completed_order_conflict")
            overlaps.append({"account_id": aid, "source_id": source_id, "legacy_order_revision_id": stored["id"]})
            continue
        if not _complete(old) or _time(old["completed_at"]) > cutoff:
            continue
        if old["order_type"] == "Funding":
            funding.append({"account_id": aid, "source_id": source_id, "occurred_at": old["completed_at"],
                            "amount_cad": old["payin_amount"], "direction": "in", "boundary": "unclassified", "legacy_revision_id": stored["id"]})
            continue
        purchases[(aid, source_id)] = {"account_id": aid, "source_id": source_id, "source_revision": str(stored["revision"]),
            "occurred_at": old["completed_at"], "asset": {"kind": "crypto", "symbol": old["payout_currency"],
            "currency": "CAD", "network": old["network"], "market": None, "identifier": None},
            "source_leg_quantity": old["payout_amount"], "net_recorded_quantity_change": old["payout_amount"],
            "purchase_cash_spend_cad": old["payin_amount"], "source_acquisition_cost_cad": old["payin_amount"],
            "all_in_acquisition_cost_cad": None, "fees_known": False, "origin": "legacy", "legacy_order_revision_id": stored["id"]}
    if any(sum(owner == selected for owner in cash_links.values()) > 1 for selected in set(cash_links.values())):
        raise ProjectionError("legacy_cash_binding_ambiguous")
    native_tokens = {(row["provider"], row["source_account"]) for row in bindings.values()}
    for record in canonical["records"]:
        if record["kind"] != "cash_flows" or record["status"] != "completed" or _time(record["occurred_at"]) > cutoff:
            continue
        token = _key(record["key"]["account"])
        is_funding = any((row["provider"], row["source_account"]) == token and row["role"] == "funding" for row in canonical_account.values())
        if token not in cash_links and is_funding and any(token in group and native_tokens.intersection(group) for group in canonical["account_groups"]):
            raise ProjectionError("legacy_cash_binding_required")
        if token in cash_links:
            if record["amount"]["currency"] != "CAD" or record["cash_leg_of"] is not None:
                continue
            funding.append({"account_id": cash_links[token], "source_id": record["key"]["source_id"],
                            "occurred_at": record["occurred_at"], "amount_cad": record["amount"]["amount"],
                            "direction": record["direction"], "boundary": record["boundary"]})
    purchases = sorted(purchases.values(), key=lambda row: (_time(row["occurred_at"]), row["account_id"], row["source_id"]))
    # Native assumptions never become defaults for a new canonical source account.
    native_ids = {row["account_id"] for row in legacy["crypto_accounts"]}
    unknown_accounts = ({row["account_id"] for row in canonical_account.values() if row["role"] == "crypto"}
                        | {row["account_id"] for row in purchases}) - native_ids
    for account in legacy["crypto_accounts"]:
        if account["account_id"] not in canonical_account:
            model["accounts"].append({"account_id": account["account_id"], "provider": account["provider"],
                "source_account": account["source_account"], "target_kind": "legacy_crypto", "account_type": "crypto",
                "label": "Bitcoin acquisitions", "role": "crypto", "observation_id": None, "observed_as_of": None,
                "carried": False, "holdings_coverage": "unknown", "unobserved_prior_assets": [],
                "observed_values": {unit: None for unit in ("CAD", "USD", "TWD")}})
    model["accounts"].sort(key=lambda row: row["account_id"])
    from .crypto import _assumptions
    known_openings = bool(native_ids) and all(_assumptions(json.loads(row["opening_json"])) is not None
        and any(source["source_account"] == row["source_account"] and source["provider"] == row["provider"]
                and _time(source["first_created_at"]) <= cutoff for source in legacy["crypto_sources"])
        for row in legacy["crypto_accounts"])
    cash = {}
    for account in legacy["crypto_accounts"]:
        aid = account["account_id"]
        paid = ZERO
        for purchase in purchases:
            if purchase["account_id"] != aid:
                continue
            paid += D(purchase["purchase_cash_spend_cad"])
            binding = bindings.get(aid)
            event = records.get((binding["provider"], binding["source_account"], "crypto_transactions", purchase["source_id"])) if binding else None
            paid += sum((D(fee["quantity"]) for fee in (event.get("fees") or [])
                         if fee["asset"]["kind"] == "cash" and not fee["included_in_leg"]), ZERO) if event else ZERO
        received = sum((D(row["amount_cad"]) * (1 if row["direction"] == "in" else -1) for row in funding if row["account_id"] == aid), ZERO)
        cash[aid] = received - paid if _assumptions(json.loads(account["opening_json"])) is not None else None
    return purchases, funding, overlaps, proxy_accounts, not unknown_accounts and known_openings, cash


def _wallet(project, model, legacy, canonical, purchases, history_known, cutoff):
    from .wallet import records
    from .source_formats import _complete
    openings = {}
    for row in sorted(legacy["crypto_opening_revisions"], key=lambda row: row["id"]):
        openings[row["source_account"]] = row
    eligible = [row for row in openings.values() if _time(json.loads(row["payload_json"])["applies_from"]) <= cutoff]
    if len(eligible) > 1:
        raise ProjectionError("ambiguous_all_wallet_opening")
    opening = {**json.loads(eligible[0]["payload_json"]), **{key: eligible[0][key] for key in ("id", "revision", "source_path", "source_sha256")}} if eligible else None
    overlap = False
    if opening:
        from .wallet_basis import purchase_footprint, event_footprint
        known_events = opening.get("reference_known_event_btc", "0")
        if sats(opening["opening_btc_equivalent_qty"]) + sats(opening["reference_purchased_btc_equivalent"]) + sats(known_events) != sats(opening["reported_total_btc_equivalent"]):
            raise ProjectionError("legacy_opening_integrity")
        if "reference_purchases" in opening:
            reference_time = min(cutoff, _time(opening["reference_as_of"]))
            current = purchase_footprint([row for row in purchases if _time(row["occurred_at"]) <= reference_time])
            current_events = event_footprint([row for row in records(project, "event", include_void=False)
                                             if _time(row["occurred_at"]) <= reference_time])
            expected_purchases = [row for row in opening["reference_purchases"] if _time(row["occurred_at"]) <= reference_time]
            expected_events = [row for row in opening["reference_events"] if _time(row["occurred_at"]) <= reference_time]
            overlap = current != expected_purchases or current_events != expected_events
        else:
            ids = {row["id"] for row in opening["reference_sources"]}
            referenced = {row["order_key"] for row in legacy["crypto_order_revisions"] if row["source_id"] in ids
                          and _complete(json.loads(row["payload_json"]))}
            overlap = any(row["source_id"] not in referenced and _time(row["occurred_at"]) <= _time(opening["reference_as_of"]) for row in purchases)
    quantities = [{"occurred_at": row["occurred_at"], "quantity_btc": row["net_recorded_quantity_change"]} for row in purchases]
    times = [row["first_created_at"] for row in legacy["crypto_sources"]]
    times += [row["lifecycle"]["created_at"] if row.get("lifecycle") else row["occurred_at"] for row in canonical["records"] if row["kind"] == "crypto_transactions"]
    result = reconcile_wallet(as_of=cutoff.isoformat(), changes=quantities, rows=records(project),
                              opening_quantity=opening["opening_btc_equivalent_qty"] if opening else "0" if history_known else None,
                              acquisition_history_known=history_known or opening is not None, history_start=min(times, key=_time) if times else None,
                              opening_overlap=overlap)
    result["acquisition_history_known"] = history_known
    result["history_start"] = min(times, key=_time) if times else None
    return result, opening


def _covered_periods(project, legacy, rows, canonical_rows, historical, start, cutoff):
    from .core import _flow_coverage
    first, last = start.date(), cutoff.date()
    values = []
    originals = {(row["account_id"], row["source_id"]): row["amount_cad"] for row in historical}
    conn = store._open(project)
    try:
        from .source_profiles import investment_accounts
        accounts = {row['account_id']: row for row in investment_accounts(project)}
        accounts.update({row['account_id']: row for row in legacy['accounts']})
        for account in accounts.values():
            aid = account["account_id"]
            status, segments = _flow_coverage(conn, first, last, aid)
            selected = [row for row in rows if row["account_id"] == aid and first.isoformat() < row["date"] <= last.isoformat()]
            net = sum((D(row["amount_cad"]) * (1 if row["flow_type"] == "deposit" else -1)
                       for row in selected if row["flow_type"] in {"deposit", "withdrawal"}), ZERO)
            has_external = any(row["flow_type"] in {"deposit", "withdrawal"} for row in selected)
            missing, unclassified = False, False
            for (owner, source_id), row in canonical_rows.items():
                day = _time(row["occurred_at"]).astimezone(cutoff.tzinfo).date()
                if owner != aid or not first < day <= last or row["status"] != "completed":
                    continue
                if row["type"] not in {"deposit", "withdrawal"}:
                    continue
                if row["boundary"] != "external":
                    unclassified = True
                    continue
                has_external = True
                amount = row["amount"]["amount"] if row["amount"]["currency"] == "CAD" else originals.get((aid, source_id))
                if amount is None:
                    missing = True
                else:
                    net += D(amount) * (1 if row["direction"] == "in" else -1)
            if last <= first:
                status = "invalid_date_interval"
            elif missing:
                status = "historical_fx_missing"
            elif unclassified:
                status = "unclassified_source_flow"
            elif status == "no_external" and has_external:
                status = "no_external_conflicts_with_flows"
            available = status in {"complete", "no_external"}
            values.append({"account_id": aid, "start_date_exclusive": first.isoformat(), "end_date_inclusive": last.isoformat(),
                           "status": status, "available": available, "external_net_cad": net if available else None,
                           "basis": "explicit_legacy_date_coverage_and_historical_values",
                           "declaration_ids": sorted({row["id"] for _, _, row in segments}), "performance_ready": False})
    finally:
        if conn:
            conn.close()
    return values


def _flows(project, model, legacy, start, cutoff, canonical):
    # Date-only legacy evidence retains original dated CAD conversions, never an
    # invented midnight timestamp or today's display FX.
    result, overlap = [], []
    bindings = {row["ledger_account"]: row for row in canonical.get("bindings", []) if row["target_kind"] in {"legacy_holdings", "canonical"}}
    current = {(row["account_id"], row["source_id"]): row for row in model["cash_flows"]["records"]}
    lookup = {(row["provider"], row["source_account"]): row["ledger_account"] for row in canonical.get("bindings", [])}
    all_current = {(lookup[_key(row["key"]["account"])], row["key"]["source_id"]): row
                   for row in canonical["records"] if row["kind"] == "cash_flows" and _time(row["occurred_at"]) <= cutoff}
    historical = []
    for stored in [*legacy["cash_flows"], *legacy["manual_cash_flows"]]:
        row = json.loads(stored["payload_json"])
        if row["date"] > cutoff.date().isoformat():
            continue
        aid = row["account_id"]
        incoming = (current.get((aid, row["flow_id"])) or all_current.get((aid, row["flow_id"]))) if aid in bindings else None
        if incoming:
            expected_direction = "out" if row["flow_type"] in {"withdrawal", "transfer_out", "fee"} else "in"
            kind = "transfer" if row["flow_type"].startswith("transfer_") else row["flow_type"]
            if (incoming["type"] != kind or incoming["direction"] != expected_direction
                    or incoming["amount"]["currency"] != row["currency"] or D(incoming["amount"]["amount"]) != D(row["amount"])
                    or incoming["status"] != "completed" or _time(incoming["occurred_at"]).astimezone(cutoff.tzinfo).date().isoformat() != row["date"]
                    or kind in {"deposit", "withdrawal"} and incoming["boundary"] != "external"):
                raise ProjectionError("legacy_flow_conflict")
            incoming["historical_amount_cad"] = row["amount_cad"]
            incoming["historical_fx_source"] = row.get("fx_source")
            overlap.append(row["flow_id"])
            historical.append({"account_id": aid, "source_id": row["flow_id"], "date": row["date"],
                               "amount_cad": row["amount_cad"], "fx_date": row.get("fx_date"), "fx_source": row.get("fx_source")})
        else:
            result.append({key: row.get(key) for key in ("flow_id", "account_id", "date", "flow_type", "currency", "amount", "amount_cad", "fx_date", "fx_source", "transfer_id")})
    legacy_subtotal = sum((D(row["amount_cad"]) * (1 if row["flow_type"] == "deposit" else -1)
                           for row in result if row["flow_type"] in {"deposit", "withdrawal"}
                           and start.date().isoformat() < row["date"] <= cutoff.date().isoformat()), ZERO)
    canonical_subtotal, unknown = ZERO, []
    for row in model["cash_flows"]["records"]:
        if row["classification"] != "external_contribution":
            continue
        amount = row["amount"]["amount"] if row["amount"]["currency"] == "CAD" else row.get("historical_amount_cad")
        if amount is None:
            unknown.append({"account_id": row["account_id"], "source_id": row["source_id"]})
        else:
            canonical_subtotal += D(amount) * (1 if row["direction"] == "in" else -1)
    return {"records": result, "canonical_overlap_ids": overlap, "canonical_historical_values": historical,
            "covered_account_periods": _covered_periods(project, legacy, result, all_current, historical, start, cutoff),
            "known_recorded_external_cad": legacy_subtotal + canonical_subtotal,
            "unknown_historical_cad_records": unknown, "full_period_net_external_cad": None,
            "subtotal_basis": "recorded_external_flows_with_explicit_date_and_instant_precision",
            "time_basis": "source_calendar_date_only", "cutoff_date_basis": "explicit_report_offsets",
            "period_start_date_exclusive": start.date().isoformat(), "period_end_date_inclusive": cutoff.date().isoformat(),
            "period_records": [row for row in result if start.date().isoformat() < row["date"] <= cutoff.date().isoformat()],
            "periods": deepcopy(legacy["flow_periods"]), "performance_ready": False}


def _working_precision(legacy, canonical, rates, price):
    values = [{"payload_json": _json(row)} for row in canonical["all_records"]]
    keys = {"quantity", "price", "book_native", "book_cad", "market_native", "unrealized_native", "amount_cad",
            "payin_amount", "payout_amount", "quantity_btc", "opening_btc_equivalent_qty",
            "reference_purchased_btc_equivalent", "reported_total_btc_equivalent"}
    for name in ("positions", "cash_flows", "manual_cash_flows", "crypto_order_revisions", "wallet_revisions", "crypto_opening_revisions"):
        for stored in legacy[name]:
            row = json.loads(stored["payload_json"])
            values.extend({"payload_json": _json({"amount": str(value)})} for key, value in row.items()
                          if key in keys and value is not None)
    if price is not None:
        if not isinstance(price, dict) or type(price.get("close")) not in (str, D):
            raise ProjectionError("invalid_projection_price")
        values.append({"payload_json": _json({"amount": str(price["close"])})})
    return max(128, _precision(values, rates))


def project_compatible_sources(project, *, as_of, period_start, fx=None, btc_price=None, btc_cost_policy=None):
    """Compose legacy and canonical analysis without changing a daily workspace.

    Explicit bindings, source identities and compatible financial signatures prove
    overlaps. Equal amounts or dates alone never merge events. Report publication,
    complete wealth and investment performance remain gated until C3 acceptance.
    """
    btc_price = deepcopy(btc_price)
    if btc_price is not None:
        from .prices import validate_quote
        try:
            if not isinstance(btc_price, dict) or type(btc_price.get("close")) not in (str, D):
                raise ValueError("Expected decimal price")
            validate_quote(btc_price, _time(as_of).isoformat())
        except (ValueError, KeyError, TypeError, ArithmeticError):
            raise ProjectionError("invalid_projection_price") from None
    settings_path = Path(project) / "config/local.toml"
    if settings_path.is_symlink() or settings_path.parent.is_symlink():
        raise ProjectionError("projection_settings_unsafe")
    settings_before = hashlib.sha256(settings_path.read_bytes() if settings_path.exists() else b"").hexdigest()
    model = project_sources(project, as_of=as_of, period_start=period_start, fx=fx)
    before = model["state_sha256"]
    canonical = store.read_facts(project)
    canonical.setdefault("records", [])
    canonical.setdefault("bindings", [])
    conn = store._open(project)
    try:
        canonical["all_records"] = [json.loads(row["payload_json"]) for row in store._rows(conn, "src_records")]
        canonical["bull_accounts"] = set()
        canonical["account_groups"] = []
        for row in store._rows(conn, "src_batches"):
            encoded = store._archive_path(project, row["canonical_path"]).read_bytes()
            if hashlib.sha256(encoded).hexdigest() != row["canonical_sha256"]:
                raise ProjectionError("projection_evidence_changed")
            batch = json.loads(encoded)
            canonical["account_groups"].append({_key(account["key"]) for account in batch["accounts"]})
            if row["adapter_id"] == "bullbitcoin.orders":
                canonical["bull_accounts"].update(_key(account["key"]) for account in batch["accounts"] if account["role"] == "crypto")
    finally:
        if conn:
            conn.close()
    legacy = _legacy(project)
    cutoff, start = _time(as_of), _time(period_start)
    source_cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00")) if isinstance(as_of, str) else as_of
    source_start = datetime.fromisoformat(period_start.replace("Z", "+00:00")) if isinstance(period_start, str) else period_start
    with localcontext(Context(prec=_working_precision(legacy, canonical, model["fx"], btc_price))):
        holdings_overlap = _holdings(model, legacy, canonical, cutoff)
        purchases, funding, order_overlap, proxy_accounts, history_known, cash = _acquisitions(model, legacy, canonical, cutoff)
        reconciliation, opening = _wallet(project, model, legacy, canonical, purchases, history_known, cutoff)
        current = reconciliation["current_sats"]
        quantity = D(btc(current)) if current is not None else None
        eligible_history = sorted((row for row in legacy["combined_observations"] if _time(row["as_of_utc"]) <= cutoff),
                                  key=lambda row: (_time(row["as_of_utc"]), row["revision"]))
        saved_accounts = {row["account_id"] for row in json.loads(eligible_history[-1]["payload_json"]).get("view", {}).get("positions", [])
                          if row.get("security_type") == "CRYPTO"} if eligible_history else set()
        if len(saved_accounts) > 1:
            raise ProjectionError("legacy_wallet_scope_ambiguous")
        scope_account = (next(iter(saved_accounts)) if saved_accounts else legacy["crypto_accounts"][0]["account_id"]
                         if len(legacy["crypto_accounts"]) == 1 else "wallet:all_wallets_btc_plus_lbtc")
        from .settings import btc_cost_policy as policy
        selected = policy(project, btc_cost_policy)
        proxy = [row for row in purchases if row["account_id"] in proxy_accounts]
        purchased = sum((D(row["source_leg_quantity"]) for row in proxy), ZERO)
        spend = sum((D(row["purchase_cash_spend_cad"]) for row in proxy), ZERO)
        average = spend / purchased if purchased else None
        estimate = quantity * average if quantity is not None and average is not None and selected == "bull_average_proxy" and not reconciliation["valuation_blocked"] else None
        valuation = {unit: None for unit in ("CAD", "USD", "TWD")}
        if btc_price is not None:
            if quantity is not None and not reconciliation["valuation_blocked"]:
                valuation = _values(quantity * D(btc_price["close"]), "USD", model["fx"])
        model.update(format="wealth-ledger-compatible-projection", schema_version=1,
                     legacy_merge_ready=True, history_replay_ready=False,
                     legacy_overlap={"holdings": holdings_overlap, "orders": order_overlap},
                     legacy_cash_flows=_flows(project, model, legacy, source_start, source_cutoff, canonical),
                     wallet=reconciliation["wallet"],
                     btc={"scope_account_id": scope_account, "quantity_btc": quantity, "quantity_status": reconciliation["quantity_status"],
                          "valuation_blocked": reconciliation["valuation_blocked"], "opening": opening,
                          "acquisition_history_known": reconciliation["acquisition_history_known"],
                          "history_start": reconciliation["history_start"],
                          "in_scope": bool(purchases or legacy["crypto_accounts"] or reconciliation["wallet"]["observations"] or reconciliation["wallet"]["events"]),
                          "purchases": purchases, "funding_records": funding, "legacy_cash_cad_by_account": cash,
                          "cash_valuation_blocked": any(value is not None and value < 0 for value in cash.values()),
                          "market_values": valuation, "price": deepcopy(btc_price), "actual_full_cost_cad": None,
                          "cost_policy": selected, "proxy_purchase_quantity_btc": purchased, "proxy_purchase_spend_cad": spend,
                          "proxy_average_cad_per_btc": average, "estimated_full_cost_cad": estimate,
                          "estimated_gain_cad": D(valuation["CAD"])-estimate if valuation["CAD"] is not None and estimate is not None else None},
                     legacy_snapshot_history=[{key: row[key] for key in ("id", "as_of", "kind", "revision", "supersedes_id", "is_complete", "fx_json", "source_id")}
                                              for row in legacy["snapshots"] if _time(row["as_of"]) <= cutoff],
                     frozen_combined_observations=[{"id": row["id"], "revision": row["revision"], "record": json.loads(row["payload_json"])}
                                                   for row in legacy["combined_observations"] if _time(row["as_of_utc"]) <= cutoff])
        model["settings_sha256"] = settings_before
        model.pop("projection_sha256", None)
        result = _serialize(model)
    if store.state_fingerprint(project) != before:
        raise ProjectionError("projection_state_changed")
    if settings_path.is_symlink() or settings_path.parent.is_symlink() or hashlib.sha256(settings_path.read_bytes() if settings_path.exists() else b"").hexdigest() != settings_before:
        raise ProjectionError("projection_settings_changed")
    conn = store._open(project)
    try:
        if _json(store._rows(conn, "combined_observations")) != _json(legacy["combined_observations"]):
            raise ProjectionError("projection_history_changed")
    finally:
        if conn:
            conn.close()
    result["projection_sha256"] = hashlib.sha256(_json(result).encode()).hexdigest()
    return result
