"""Pure BTC-equivalent reconciliation shared by native and canonical projections."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

SCOPE = "all_wallets_btc_plus_lbtc"
SIGNS = {"fee": -1, "sale": -1, "spend": -1, "external_out": -1,
         "external_in": 1, "own_transfer": 0, "conversion": 0}
STATUS_LABELS = {
    "unexplained": "差額待釐清", "partially_explained": "部分說明，仍有差額",
    "arithmetic_match": "目前已知資料算術相符", "expected_unknown": "帳本預期量未知",
    "link_conflict": "關聯待重查", "ledger_conflict": "期初／來源重疊待核對",
}



def _at(value):
    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Reconciliation time requires an offset")
    return value.astimezone(timezone.utc)


def sats(value):
    amount = Decimal(str(value))
    if not amount.is_finite() or abs(amount.adjusted()) > 4096 or abs(amount.as_tuple().exponent) > 4096:
        raise ValueError("BTC amount must be finite")
    numerator, denominator = amount.as_integer_ratio()
    units, remainder = divmod(numerator * 100000000, denominator)
    if remainder:
        raise ValueError("BTC amount must have satoshi precision")
    return units


def btc(value):
    if type(value) is not int:
        raise ValueError("Expected integer satoshis")
    whole, fraction = divmod(abs(value), 100000000)
    return ("-" if value < 0 else "") + str(whole) + "." + f"{fraction:08d}"


def reconcile_wallet(*, as_of, changes, rows, opening_quantity=None,
                     acquisition_history_known=False, history_start=None, opening_overlap=False):
    """Project current quantity and every unresolved interval without IO or prices.

    Changes have signed quantity_btc and occurred_at fields. They already represent
    identity-deduplicated acquisition effects, including separately recorded fees.
    Observations/events use the existing append-only wallet declaration schema.
    No zero opening is inferred when opening_quantity is absent.
    """
    cutoff = _at(as_of)
    all_rows = deepcopy(rows)
    if any(row.get("scope") != SCOPE for row in all_rows):
        raise ValueError("Unsupported wallet reconciliation scope")
    balances = sorted((r for r in all_rows if r["kind"] == "balance" and not r["void"]
                       and _at(r["as_of"]) <= cutoff), key=lambda r: _at(r["as_of"]))
    events = [r for r in all_rows if r["kind"] == "event" and not r["void"] and _at(r["occurred_at"]) <= cutoff]
    changes = tuple(changes)

    def net(start, end):
        left, right = _at(start) if start else None, _at(end)
        return (sum(sats(r["quantity_btc"]) for r in changes if (left is None or _at(r["occurred_at"]) > left)
                    and _at(r["occurred_at"]) <= right)
                + sum(SIGNS[r["type"]] * sats(r["quantity_btc"]) for r in events
                      if (left is None or _at(r["occurred_at"]) > left) and _at(r["occurred_at"]) <= right))

    prehistory = [e for e in events if history_start and _at(e["occurred_at"]) < _at(history_start)]
    unknown_history = any(b.get("unknown_prior_history") for b in balances)
    known_base = (acquisition_history_known and opening_quantity is not None
                  and not opening_overlap and not prehistory and not unknown_history)
    opening_sats = sats(opening_quantity) if opening_quantity is not None else None
    ledger_expected = opening_sats + net(None, as_of) if known_base else None
    reconciliations, previous = [], None
    for balance in balances:
        expected = (sats(previous["quantity_btc"]) + net(previous["as_of"], balance["as_of"])) if previous else (
            opening_sats + net(None, balance["as_of"]) if known_base else None)
        relevant = [e for e in events if (previous is None or _at(e["occurred_at"]) > _at(previous["as_of"]))
                    and _at(e["occurred_at"]) <= _at(balance["as_of"])]
        linked = [e for e in events if e.get("balance_id") == balance["record_id"]]
        stale = any(e not in relevant or e.get("linked_previous_balance_id") != (previous["record_id"] if previous else None) for e in linked)
        residual = sats(balance["quantity_btc"]) - expected if expected is not None else None
        status = ("link_conflict" if stale else "ledger_conflict" if not previous and (opening_overlap or prehistory) else
                  "expected_unknown" if expected is None else "arithmetic_match" if residual == 0 else
                  "partially_explained" if any(SIGNS[e["type"]] for e in relevant) else "unexplained")
        reconciliations.append({"balance_id": balance["record_id"], "balance_revision": balance["revision"],
                               "as_of": balance["as_of"], "reported_btc": balance["quantity_btc"],
                               "expected_btc": btc(expected) if expected is not None else None,
                               "residual_btc": btc(residual) if residual is not None else None,
                               "recorded_expected_btc": balance["recorded_expected_btc"],
                               "recorded_residual_btc": balance["recorded_residual_btc"],
                               "previous_balance_id": previous["record_id"] if previous else None,
                               "event_ids": [e["record_id"] for e in relevant], "linked_event_ids": [e["record_id"] for e in linked],
                               "status": status, "status_label": STATUS_LABELS[status], "verification": "user_reported"})
        previous = balance
    anchor = balances[-1] if balances else None
    current = sats(anchor["quantity_btc"]) + net(anchor["as_of"], as_of) if anchor else ledger_expected
    conflicts = [e["record_id"] for e in events if e.get("balance_id") and not any(b["record_id"] == e["balance_id"] for b in balances)]
    corrupt = [r["record_id"] for r in all_rows if _at(r.get("as_of") or r.get("occurred_at")) <= cutoff and not r["integrity_ok"]]
    wallet = {"scope": SCOPE, "anchor": anchor, "observations": balances, "events": events,
              "reconciliations": reconciliations, "ledger_expected_btc": btc(ledger_expected) if ledger_expected is not None else None,
              "anchor_ledger_residual_btc": btc(sats(anchor["quantity_btc"]) - (opening_sats + net(None, anchor["as_of"]))) if anchor and known_base else None,
              "unresolved_count": sum(r["status"] != "arithmetic_match" for r in reconciliations),
              "link_conflicts": conflicts, "opening_overlap": opening_overlap,
              "prehistory_event_ids": [e["record_id"] for e in prehistory], "integrity_errors": corrupt,
              "verification": "user_reported_not_independently_verified"}
    return {"current_sats": current, "wallet": wallet,
            "quantity_status": "user_reported_balance" if anchor and _at(anchor["as_of"]) == cutoff else
                               "balance_plus_known_changes_estimate" if anchor else "ledger_plus_events_estimate",
            "estimation_method": "latest_observed_balance_plus_later_known_changes" if anchor else "opening_orders_and_known_events",
            "cost_unknown": bool(anchor or events or not acquisition_history_known or opening_overlap),
            "valuation_blocked": current is None or current < 0 or bool(corrupt) or bool(not anchor and (opening_overlap or prehistory))}
