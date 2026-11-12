"""Read-only source-neutral analysis model, preceding report/cutover acceptance.

This internal model contains observed positions and recorded movements, not an
assertion of complete wealth or wallet balances. It never books legacy rows,
fetches prices, calls a parser or publishes a report. Normal reports remain gated.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Context, Decimal, localcontext
import hashlib
import json

from . import source_ingestion as store
from . import source_v2 as v2

ZERO = Decimal(0)
CURRENCIES = ("CAD", "USD", "TWD")


class ProjectionError(ValueError):
    """A source model cannot be projected without guessing financial meaning."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _time(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ProjectionError("invalid_projection_time") from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ProjectionError("invalid_projection_time")
    return value.astimezone(timezone.utc)


def _key(account):
    return account["provider"], account["account_id"]


def _reference(record):
    return (*_key(record["key"]["account"]), record["kind"], record["key"]["source_id"])


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _serialize(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


def _load(project):
    """Read verified facts and metadata without importing any source adapter."""
    before = store.state_fingerprint(project)
    store.verify_store(project)
    conn = store._open(project)
    try:
        if conn:
            conn.execute("BEGIN")
        bindings = store._rows(conn, "src_bindings")
        records = sorted(store._rows(conn, "src_records"), key=lambda row: row["id"])
        scopes = sorted(store._rows(conn, "src_scopes"), key=lambda row: row["id"])
        effects = store._rows(conn, "src_effects")
        batches = store._rows(conn, "src_batches")
        legacy = any(store._rows(conn, name) for name in
                     ("snapshots", "positions", "crypto_accounts", "crypto_order_revisions", "wallet_records", "wallet_revisions", "cash_flows"))
        accounts = {}
        for row in sorted(batches, key=lambda item: item["batch_id"]):
            raw = store._archive_path(project, row["raw_path"]).read_bytes()
            encoded = store._archive_path(project, row["canonical_path"]).read_bytes()
            if hashlib.sha256(encoded).hexdigest() != row["canonical_sha256"]:
                raise ProjectionError("projection_evidence_changed")
            batch = v2.decode_batch(encoded, raw)
            for account in batch.accounts:
                token = (account.key.provider, account.key.account_id)
                candidate = (batch.evidence.context.evidence_at, row["batch_id"], account)
                if token not in accounts or candidate[:2] > accounts[token][:2]:
                    accounts[token] = candidate
        return before, bindings, records, scopes, effects, accounts, legacy
    finally:
        if conn:
            conn.close()


def _precision(records, fx):
    numbers = []

    def collect(value):
        if isinstance(value, dict):
            for name, item in value.items():
                if name in {"source_fields", "lifecycle"}:
                    continue
                if name in {"quantity", "amount"} and isinstance(item, str):
                    numbers.append(Decimal(item))
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    for row in records:
        collect(json.loads(row["payload_json"]))
    if fx:
        numbers.extend((Decimal(fx["usd_cad"]), Decimal(fx["usd_twd"])))
    # Bound analysis arithmetic; the canonical store itself remains lossless.
    high = max((number.adjusted() for number in numbers), default=0)
    low = min((number.as_tuple().exponent for number in numbers), default=0)
    precision = max(80, 2 * (high - low) + 32 + len(str(len(numbers))))
    if precision > 4096 or max(abs(high), abs(low)) > 4096:
        raise ProjectionError("projection_numeric_range")
    return precision


def _rates(fx, cutoff):
    if fx is None:
        return None
    from .core import _fx
    if not isinstance(fx, dict) or any(type(fx.get(key)) not in {str, Decimal} for key in ("usd_cad", "usd_twd")):
        raise ProjectionError("invalid_projection_fx")
    try:
        if any(not isinstance(fx.get(key), str) or not fx[key].strip() or len(fx[key]) > 4096
               for key in ("usd_cad_date", "usd_twd_date", "usd_cad_source", "usd_twd_source")):
            raise ProjectionError("invalid_projection_fx")
        with localcontext(Context(prec=_precision([], fx))):
            return _fx(fx, cutoff)
    except (ValueError, TypeError, ArithmeticError):
        raise ProjectionError("invalid_projection_fx") from None


def _values(amount, currency, fx):
    values = {unit: None for unit in CURRENCIES}
    values[currency] = amount
    if fx:
        usd = amount if currency == "USD" else amount / Decimal(fx["usd_cad"])
        values.update(CAD=amount if currency == "CAD" else amount * Decimal(fx["usd_cad"]),
                      USD=usd, TWD=usd * Decimal(fx["usd_twd"]))
    return values


def _sum_values(rows, field):
    return {unit: sum((row[field][unit] for row in rows), ZERO)
            if all(row[field][unit] is not None for row in rows) else None for unit in CURRENCIES}


def _coverage(rows, token, kind, start, end, observation=None):
    matching = [row for row in rows if _key(row.get("account", {})) == token and row.get("kind") == kind
                and (observation is None or row["observation_id"] == observation)]
    intervals = sorted((_time(row["start"]), _time(row["end"])) for row in matching if row["status"] == "complete")
    cursor = start
    for first, last in intervals:
        if first > cursor:
            break
        if last >= cursor:
            cursor = last
            if cursor >= end:
                return "complete"
    return "partial" if any(row["status"] == "partial" and _time(row["end"]) >= start and _time(row["start"]) <= end
                            for row in matching) else "unknown"


def _position(record, binding, fx):
    native = Decimal(record["market_value"]["amount"])
    currency = record["market_value"]["currency"]
    cost = record["cost_native"]
    cost_cad = record["cost_cad"]
    cost_native = Decimal(cost["amount"]) if cost is not None else None
    book_cad = Decimal(cost_cad["amount"]) if cost_cad is not None else None
    return {"account_id": binding["ledger_account"], "provider": binding["provider"],
            "source_account": binding["source_account"], "source_id": record["key"]["source_id"],
            "source_revision": record["key"]["revision"], "observation_id": record["observation_id"],
            "observed_as_of": record["as_of"], "asset": record["asset"], "name": record["name"],
            "instrument_type": record["instrument_type"], "exchange": record["exchange"],
            "quantity": Decimal(record["quantity"]), "currency": currency, "market_native": native,
            "unit_price": record["unit_price"], "cost_native": cost_native, "cost_cad": book_cad,
            "source_unrealized": record["unrealized"], "market_values": _values(native, currency, fx),
            "calculated_unrealized_native": native - cost_native if cost_native is not None else None}


def _positions(bindings, scopes, heads, metadata, cutoff, fx):
    snapshots, coverage, memberships = {}, [], []
    for (provider, name), row in scopes.items():
        payload = json.loads(row["payload_json"])
        if name.startswith("snapshot:"):
            snapshots[(provider, payload["header"]["source_id"])] = payload["header"]
        elif name.startswith("membership:"):
            memberships.append({"provider": provider, **payload})
        else:
            coverage.append(payload)
    candidates = defaultdict(list)
    record_groups = defaultdict(list)
    for _, record in heads.values():
        if record["kind"] == "holdings":
            record_groups[(_key(record["key"]["account"]), record["observation_id"], record["key"]["revision"])].append(record)
    for (provider, _), snapshot in snapshots.items():
        if _time(snapshot["as_of"]) <= cutoff:
            for account in snapshot["accounts"]:
                candidates[_key(account)].append(snapshot)
    positions, accounts, funding, gaps = [], [], [], []
    for token, binding in sorted(bindings.items()):
        account = metadata[token][2]
        available = candidates[token]
        selected = None
        if available:
            if len({_time(snapshot["as_of"]) for snapshot in available}) != len(available):
                raise ProjectionError("ambiguous_projection_observation")
            latest = max(_time(snapshot["as_of"]) for snapshot in available)
            choices = [snapshot for snapshot in available if _time(snapshot["as_of"]) == latest]
            if len(choices) != 1:
                raise ProjectionError("ambiguous_projection_observation")
            selected = choices[0]
        group = []
        if selected:
            group = [_position(record, binding, fx) for record in
                     record_groups[(token, selected["source_id"], selected["revision"])]]
            status = _coverage(coverage, token, "holdings", _time(selected["as_of"]),
                               _time(selected["as_of"]), selected["source_id"])
        else:
            status = "unknown"
        group.sort(key=lambda row: row["source_id"])
        current_assets = {_json(row["asset"]) for row in group}
        potential = set()
        if selected and status != "complete":
            for snapshot in sorted(available, key=lambda item: (_time(item["as_of"]), item["source_id"])):
                snapshot_records = record_groups[(token, snapshot["source_id"], snapshot["revision"])]
                assets = {_json(record["asset"]) for record in snapshot_records}
                complete = _coverage(coverage, token, "holdings", _time(snapshot["as_of"]),
                                     _time(snapshot["as_of"]), snapshot["source_id"]) == "complete"
                potential = assets if complete else potential | assets
        # Omission in a partial export is a gap; a complete snapshot resets scope.
        unseen = sorted(potential - current_assets)
        values = _sum_values(group, "market_values") if selected else {unit: None for unit in CURRENCIES}
        if account.role == "funding":
            funding.extend(group)
        else:
            positions.extend(group)
        accounts.append({"account_id": binding["ledger_account"], "provider": token[0], "source_account": token[1],
                         "target_kind": binding["target_kind"], "account_type": account.account_type,
                         "label": account.label, "role": account.role,
                         "observation_id": selected["source_id"] if selected else None,
                         "observed_as_of": selected["as_of"] if selected else None,
                         "carried": bool(selected and _time(selected["as_of"]) < cutoff),
                         "holdings_coverage": status, "observed_values": values,
                         "unobserved_prior_assets": [json.loads(asset) for asset in unseen]})
        if unseen:
            gaps.append({"code": "unobserved_prior_assets", "account_id": binding["ledger_account"], "count": len(unseen)})
    return positions, accounts, funding, coverage, memberships, gaps


def _flows(heads, bindings, coverage, start, cutoff, fx):
    available = {_reference(record): record for _, record in heads.values()
                 if record["kind"] != "holdings" and _time(record["occurred_at"]) <= cutoff}
    rows, unresolved = [], 0
    for _, record in heads.values():
        if record["kind"] != "cash_flows" or not start < _time(record["occurred_at"]) <= cutoff:
            continue
        token = _key(record["key"]["account"])
        contribution = ZERO
        classification = "noncapital"
        if record["status"] != "completed":
            classification = "inactive"
        elif record["cash_leg_of"] is not None:
            link = record["cash_leg_of"]
            target = available.get((*_key(link["account"]), link["kind"], link["source_id"]))
            classification = "purchase_cash_leg" if target and target["status"] == "completed" else "unresolved_purchase_cash_leg"
            if classification == "unresolved_purchase_cash_leg":
                contribution = None
        elif record["type"] == "transfer":
            counterpart = record["counterpart"]
            target = available.get((*_key(counterpart["account"]), counterpart["kind"], counterpart["source_id"])) if counterpart else None
            classification = "internal_transfer" if target and target["status"] == "completed" else "unresolved_transfer"
            if classification == "unresolved_transfer":
                contribution = None
        elif record["type"] in {"deposit", "withdrawal"}:
            if record["boundary"] == "external":
                classification = "external_contribution"
                contribution = Decimal(record["amount"]["amount"])
                if record["direction"] == "out":
                    contribution = contribution.copy_negate()
            else:
                classification = "unclassified_funding"
                contribution = None
        if contribution is None:
            unresolved += 1
        rows.append({"account_id": bindings[token]["ledger_account"], "provider": token[0],
                     "source_account": token[1], "source_id": record["key"]["source_id"],
                     "source_revision": record["key"]["revision"], "occurred_at": record["occurred_at"],
                     "type": record["type"], "direction": record["direction"], "status": record["status"],
                     "amount": record["amount"], "boundary": record["boundary"], "classification": classification,
                     "contribution_native": contribution,
                     "contribution_values": _values(contribution, record["amount"]["currency"], fx) if contribution is not None
                     else {unit: None for unit in CURRENCIES}})
    rows.sort(key=lambda row: (_time(row["occurred_at"]), row["account_id"], row["source_id"]))
    account_coverage = [{"account_id": row["ledger_account"], "status": _coverage(coverage, token, "cash_flows", start, cutoff)}
                        for token, row in sorted(bindings.items())]
    complete = bool(account_coverage) and all(row["status"] == "complete" for row in account_coverage) and not unresolved
    known = [row for row in rows if row["classification"] == "external_contribution"]
    native = {unit: sum((row["contribution_native"] for row in known if row["amount"]["currency"] == unit), ZERO)
              for unit in ("CAD", "USD")}
    return {"scope": "canonical_bound_accounts_only", "period_start_exclusive": start,
            "period_end_inclusive": cutoff, "records": rows,
            "account_coverage": account_coverage, "unresolved_count": unresolved,
            "known_external_net_native": native, "known_external_net_values": _sum_values(known, "contribution_values"),
            "conversion_basis": "explicit_cutoff_fx_not_historical_cash_flow_fx" if fx else "native_only",
            "period_coverage_complete": complete, "period_net_external_values": None,
            "performance_ready": False}


def _movements(heads, effects, bindings, cutoff):
    active = {record_id: record for record_id, record in heads.values() if record["kind"] != "holdings"
              and record["status"] == "completed" and _time(record["occurred_at"]) <= cutoff}
    groups = defaultdict(lambda: ZERO)
    event_quantities = defaultdict(lambda: ZERO)
    for effect in effects:
        if effect["record_id"] in active:
            token = (effect["provider"], effect["source_account"], effect["asset_json"])
            groups[token] += Decimal(effect["quantity"])
            event_quantities[(effect["record_id"], *token)] += Decimal(effect["quantity"])
    changes = [{"account_id": bindings[(provider, account)]["ledger_account"], "provider": provider,
                "source_account": account, "asset": json.loads(asset), "quantity_change": quantity,
                "quantity_basis": "recorded_effects_not_total_balance"}
               for (provider, account, asset), quantity in sorted(groups.items())]
    purchases = []
    for record_id, record in sorted(active.items()):
        if record["kind"] != "crypto_transactions":
            continue
        crypto = next(leg for leg in record["legs"] if leg["asset"]["kind"] == "crypto")
        cash = next(leg for leg in record["legs"] if leg["asset"]["kind"] == "cash")
        source_quantity = Decimal(crypto["quantity"])
        net_quantity = event_quantities[(record_id, *_key(crypto["account"]), _json(crypto["asset"]))]
        spend = Decimal(cash["quantity"]).copy_negate()
        cost = record["acquisition_cost_cad"]
        cost = Decimal(cost["amount"]) if cost is not None else None
        fees_known = record["fees"] is not None
        extra_cash_fee = sum((Decimal(fee["quantity"]) for fee in record["fees"] or []
                              if fee["asset"]["kind"] == "cash" and not fee["included_in_cost"]), ZERO)
        unknown_fee_value = any(fee["asset"]["kind"] == "crypto" and Decimal(fee["quantity"]) > 0
                                and not fee["included_in_cost"] for fee in record["fees"] or [])
        purchases.append({"account_id": bindings[_key(record["key"]["account"])]["ledger_account"],
                          "source_id": record["key"]["source_id"], "source_revision": record["key"]["revision"],
                          "occurred_at": record["occurred_at"], "asset": crypto["asset"], "source_leg_quantity": source_quantity,
                          "net_recorded_quantity_change": net_quantity,
                          "purchase_cash_spend_cad": spend, "source_acquisition_cost_cad": cost,
                          "all_in_acquisition_cost_cad": cost + extra_cash_fee if cost is not None and fees_known and not unknown_fee_value else None,
                          "purchase_rate_cad_per_btc": spend / source_quantity,
                          "purchase_rate_basis": "cash_leg_spend_per_source_crypto_leg_quantity",
                          "fees_known": fees_known})
    purchases.sort(key=lambda row: (_time(row["occurred_at"]), row["account_id"], row["source_id"]))
    return {"changes": changes, "purchases": purchases,
            "end_inclusive": cutoff, "opening_balance_included": False,
            "btc_equivalent_change": sum((row["quantity_change"] for row in changes if row["asset"]["kind"] == "crypto"
                                          and (row["asset"]["symbol"], row["asset"]["network"]) in
                                          {("BTC", "bitcoin"), ("LBTC", "liquid")}), ZERO),
            "wallet_balance": None, "wallet_balance_verified": False}


def project_sources(project, *, as_of, period_start, fx=None):
    """Build a deterministic internal model from current revisions at a cutoff.

    This is NOT historical report replay or the production report payload. FX is
    explicit, with source/effective dates, and is only a display conversion here.
    Cash-flow performance requires separate historical FX and coverage acceptance.
    Legacy facts are not merged until overlap/declaration compatibility is proven.
    """
    cutoff, start = _time(as_of), _time(period_start)
    if start >= cutoff:
        raise ProjectionError("invalid_projection_period")
    rates = _rates(fx, cutoff)
    before, raw_bindings, records, raw_scopes, effects, metadata, legacy = _load(project)
    bindings = {(row["provider"], row["source_account"]): row for row in raw_bindings}
    heads, scopes = {}, {}
    for row in records:
        record = json.loads(row["payload_json"])
        heads[store._identity(record)] = (row["id"], record)
    for row in raw_scopes:
        scopes[(row["provider"], row["scope_key"])] = row
    with localcontext(Context(prec=_precision(records, rates))):
        positions, accounts, funding, coverage, membership, gaps = _positions(bindings, scopes, heads, metadata, cutoff, rates)
        flows = _flows(heads, bindings, coverage, start, cutoff, rates)
        movements = _movements(heads, effects, bindings, cutoff)
        has_observation = any(account["role"] != "funding" and account["observation_id"] is not None for account in accounts)
        observed = _sum_values(positions, "market_values") if positions or has_observation else {unit: None for unit in CURRENCIES}
        model = {"format": "wealth-ledger-source-projection", "schema_version": 1, "as_of": cutoff,
                 "state_sha256": before, "revision_basis": "current_recorded_revisions_at_economic_cutoff",
                 "report_projection_ready": False, "report_published": False, "review_only": True,
                 "fx": rates, "positions": positions, "accounts": accounts, "funding_observations": funding,
                 "observed_values": observed,
                 "native_observed_values": {unit: sum((row["market_native"] for row in positions if row["currency"] == unit), ZERO)
                                            if has_observation else None for unit in ("CAD", "USD")},
                 "complete_portfolio_values": None,
                 "membership": membership, "gaps": gaps, "cash_flows": flows, "movements": movements,
                 "legacy_state_present": legacy,
                 "legacy_bindings": [{"account_id": row["ledger_account"], "target_kind": row["target_kind"]}
                                     for row in raw_bindings if row["target_kind"].startswith("legacy_")],
                 "legacy_merge_ready": False, "history_replay_ready": False}
        result = _serialize(model)
    if store.state_fingerprint(project) != before:
        raise ProjectionError("projection_state_changed")
    result["projection_sha256"] = hashlib.sha256(_json(result).encode()).hexdigest()
    return result
