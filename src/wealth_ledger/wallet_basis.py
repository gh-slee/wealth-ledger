"""Source-aware declaration arithmetic without prices, parsers or publication.

Native-only workspaces retain their historical contract. Canonical workspaces use
verified identity-deduplicated facts and never interpret unknown quantity as zero.
"""
from .wallet_reconciliation import SIGNS, btc, sats


def has_canonical_sources(project):
    """Inspect the actual store, without initializing a financial database."""
    from . import source_ingestion as store
    conn = store._open(project)
    try:
        return bool(store._schema(conn) and conn.execute("SELECT 1 FROM src_batches LIMIT 1").fetchone())
    finally:
        if conn:
            conn.close()


def compatible_basis(project, as_of):
    """Read a verified declaration model; no display FX or cost proxy is needed."""
    from datetime import timedelta
    from .source_projection import _time
    from .source_legacy_projection import project_compatible_sources
    # The model requires a nonempty interval; declarations consume no flow totals.
    start = _time(as_of) - timedelta(microseconds=1)
    return project_compatible_sources(project, as_of=as_of, period_start=start,
                                      btc_cost_policy="actual_only")


def declaration_basis(project, as_of):
    """Return current expectation and interval boundaries for an append-only edit."""
    if has_canonical_sources(project):
        model = compatible_basis(project, as_of)
        asset = model["btc"]
        return {"expected_btc": asset["quantity_btc"], "wallet": model["wallet"],
                "history_start": asset["history_start"],
                "acquisition_history_known": asset["acquisition_history_known"] or asset["opening"] is not None,
                "calculation_basis": {"format": "wealth-ledger-compatible-declaration", "schema_version": 1,
                                      "projection_sha256": model["projection_sha256"], "state_sha256": model["state_sha256"]}}
    from . import wallet
    view = wallet.make_crypto_view(project, as_of, strict=False)
    known = wallet.has_bull(project)
    anchor = view.get("wallet", {}).get("anchor")
    return {"expected_btc": view["btc_equivalent_qty"] if known or anchor is not None else None,
            "wallet": view.get("wallet", {}), "history_start": view["source"].get("earliest_created_at"),
            "acquisition_history_known": known, "calculation_basis": None}


def purchase_footprint(purchases):
    """Freeze financial identity independently of native/canonical archive spelling."""
    from .source_projection import _time
    return sorted(({"account_id": row["account_id"], "source_id": row["source_id"],
                    "occurred_at": _time(row["occurred_at"]).isoformat(),
                    "quantity_btc": btc(sats(row["net_recorded_quantity_change"]))}
                   for row in purchases), key=lambda row: (row["account_id"], row["source_id"]))


def event_footprint(events):
    """Link/reason revisions alone do not change a fixed opening's quantity basis."""
    from .source_projection import _time
    return sorted(({"record_id": row["record_id"], "type": row["type"],
                    "occurred_at": _time(row["occurred_at"]).isoformat(),
                    "quantity_btc": btc(sats(row["quantity_btc"]))}
                   for row in events), key=lambda row: row["record_id"])


def opening_basis(project, as_of):
    """Freeze recorded acquisitions/events once; a balance observation is not a buy."""
    model = compatible_basis(project, as_of)
    asset = model["btc"]
    if not asset["purchases"] or asset["history_start"] is None:
        raise ValueError("Opening requires eligible acquisition history; otherwise record a balance")
    if model["wallet"]["prehistory_event_ids"]:
        raise ValueError("Pre-source events require reconciliation before deriving an opening")
    if model["wallet"]["integrity_errors"]:
        raise ValueError("Wallet evidence must be verified before deriving an opening")
    purchases = purchase_footprint(asset["purchases"])
    events = event_footprint(model["wallet"]["events"])
    return {"account_id": asset["scope_account_id"], "applies_from": asset["history_start"],
            "reference_purchases": purchases, "reference_events": events,
            "reference_purchased_btc_equivalent": btc(sum(sats(row["quantity_btc"]) for row in purchases)),
            "reference_known_event_btc": btc(sum(SIGNS[row["type"]] * sats(row["quantity_btc"]) for row in events)),
            "reference_projection_sha256": model["projection_sha256"],
            "reference_state_sha256": model["state_sha256"]}
