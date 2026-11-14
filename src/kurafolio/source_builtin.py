"""Trusted pure v2 parsers for the two implemented CSV grammars.

Legacy imports share the byte grammars, not storage or report projections. These
adapters do not discover accounts, infer opening balances or verify wallet totals.
"""
from datetime import datetime, timezone
from decimal import Decimal
import csv
import hashlib
import io
import json

from . import source_v2 as v2
from .source_formats import BULL_REQUIRED, WS_REQUIRED, parse_bull, parse_wealthsimple
from .source_protocol import AccountKey, AdapterInfo, AssetKey, CryptoLeg, Detection, Money, RecordKey
from .source_registry import AdapterRegistration, ProviderInfo

WS_FORMAT = "wealthsimple-holdings-footer-v1"
BULL_FORMAT = "bullbitcoin-orders-utc-v1"


def _number(value):
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _digest(value):
    def default(item):
        if isinstance(item, Decimal):
            return _number(item)
        raise TypeError("Unsupported source identity value")
    return hashlib.sha256(json.dumps(value, default=default, sort_keys=True,
        ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _detect(raw, required, version):
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= v2.MAX_RAW_BYTES:
            return Detection(False, None, "unsupported_input")
        headers = next(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        headers = [value.strip() for value in headers]
        matched = len(headers) == len(set(headers)) and set(required) <= set(headers)
        return Detection(matched, version if matched else None, "header_match" if matched else "header_mismatch")
    except (ValueError, UnicodeError, StopIteration, csv.Error):
        return Detection(False, None, "invalid_csv")


def _context(info, export_version, context, raw):
    if type(raw) is not bytes or not 0 < len(raw) <= v2.MAX_RAW_BYTES:
        raise ValueError("Expected bounded immutable source bytes")
    v2.validate_context(context)
    if export_version not in info.export_versions or context.format_selection not in {None, export_version}:
        raise ValueError("Unsupported explicit source format")


def _parent(context, account, kind, source_id, observation=""):
    return next((item.supersedes_revision for item in context.revisions
        if (item.account, item.kind, item.source_id, item.observation_id) == (account, kind, source_id, observation)), None)


def _scope_parent(context, kind, scope_id, account=None, record_kind=None, observation=""):
    return next((item.supersedes_revision for item in context.scope_revisions
        if (item.kind, item.scope_id, item.account, item.record_kind, item.observation_id)
        == (kind, scope_id, account, record_kind, observation)), None)


def _key(context, account, kind, source_id, revision, observation=""):
    parent = _parent(context, account, kind, source_id, observation)
    return RecordKey(account, source_id, revision, parent, "correction" if parent else "original")


def _reason(key):
    return "Host-selected source revision parent" if key.supersedes_revision else None


class WealthsimpleHoldings:
    info = AdapterInfo("wealthsimple", "wealthsimple.holdings", "0.1.0", (WS_FORMAT,), ("holdings",), api_version=2)

    def detect(self, raw):
        return _detect(raw, WS_REQUIRED, WS_FORMAT)

    def normalize(self, raw, *, export_version, context):
        _context(self.info, export_version, context, raw)
        if context.account_alias is not None:
            raise ValueError("Holdings account identities come from source account numbers")
        _, as_of, rows, metadata, findings = parse_wealthsimple(raw)
        if as_of > context.evidence_at:
            raise ValueError("Source observation follows its evidence time")
        rows = sorted(rows, key=lambda row: (row["account_id"], row["security_id"]))
        accounts = tuple(v2.Account(AccountKey(self.info.provider_id, aid), value["account_type"],
            value["label"], "investment", value["masked_number"]) for aid, value in sorted(metadata.items()))
        keys = tuple(item.key for item in accounts)
        utc = as_of.astimezone(timezone.utc).isoformat(timespec="seconds")
        observation = "holdings:" + utc
        revision = _digest({"as_of": utc, "accounts": metadata, "records": rows})
        snapshot = v2.Snapshot(observation, revision, as_of, keys,
            _scope_parent(context, "snapshot", observation))
        membership_id = "exported-accounts"
        membership = v2.Membership(membership_id, _digest(metadata), keys, "unknown",
            "Exported accounts only; absence does not establish portfolio completeness",
            _scope_parent(context, "membership", membership_id))
        coverage = tuple(v2.Coverage("holdings", account, as_of, as_of, "partial",
            "Rows present in this export; no activity or omitted-position inference", "exported-positions",
            revision, _scope_parent(context, "coverage", "exported-positions", account, "holdings", observation),
            observation) for account in keys)
        positions = []
        for row in rows:
            account = AccountKey(self.info.provider_id, row["account_id"])
            key = _key(context, account, "holdings", row["security_id"], revision, observation)
            currency = row["currency"]
            asset = (AssetKey("cash", currency, currency) if row["security_type"] == "CURRENCY" else
                AssetKey("security", row["symbol"], currency, market=row["mic"]))
            positions.append(v2.Position(key, observation, as_of, asset, row["name"], row["security_type"],
                row["exchange"], Decimal(_number(row["quantity"])), Money(Decimal(_number(row["market_native"])), currency), Money(Decimal(_number(row["price"])), currency),
                Money(Decimal(_number(row["book_native"])), currency), Money(Decimal(_number(row["book_cad"])), "CAD"),
                Money(Decimal(_number(row["unrealized_native"])), currency), _reason(key)))
        diagnostics = tuple(v2.Diagnostic(item["code"], item["severity"],
            tuple(sorted((key, str(value)) for key, value in item.items() if key not in {"code", "severity"}))) for item in findings)
        evidence = v2.Evidence(hashlib.sha256(raw).hexdigest(), context, as_of,
            "Legacy hashed account/security IDs; UTC observation and semantic snapshot hash; explicit correction parents",
            (("legacy_semantic_hash", revision),), diagnostics)
        batch = v2.NormalizedBatch(self.info, export_version, evidence, accounts, membership, (snapshot,), coverage, tuple(positions))
        v2.validate_batch(batch, raw, context=context)
        return batch


def _at(value):
    return datetime.fromisoformat(value) if value is not None else None


def _status(order):
    values = {order[field].casefold() for field in ("order_status", "payin_status", "payout_status")}
    if values == {"completed"}:
        return "completed"
    if values & {"cancelled", "canceled", "failed", "expired", "rejected"}:
        return "cancelled"
    if values <= {"completed", "pending", "processing", "new", "created", "waiting", "unpaid"}:
        return "pending"
    raise ValueError("Unsupported Bull order lifecycle status")


def _rate(order, prefix):
    amount, unit = order[prefix + "_amount"], order[prefix + "_currency"]
    return v2.Rate(Decimal(amount), unit) if amount is not None and unit else None


class BullBitcoinOrders:
    info = AdapterInfo("bullbitcoin", "bullbitcoin.orders", "0.1.0", (BULL_FORMAT,), ("cash_flows", "crypto_transactions"), api_version=2)

    def detect(self, raw):
        return _detect(raw, BULL_REQUIRED, BULL_FORMAT)

    def normalize(self, raw, *, export_version, context):
        _context(self.info, export_version, context, raw)
        alias = context.account_alias
        if alias is None or alias != alias.strip() or not 0 < len(alias) <= 160:
            raise ValueError("Bull orders require an explicit stable source account alias")
        _, orders, row_count, duplicates, semantic = parse_bull(raw, alias)
        orders = sorted(orders, key=lambda item: item["order_key"])
        crypto = AccountKey(self.info.provider_id, alias)
        funding = AccountKey(self.info.provider_id, alias + ":cad")
        accounts = (v2.Account(crypto, "crypto", "Bitcoin deliveries", "crypto"),
                    v2.Account(funding, "CAD balance", "Purchase funding", "funding"))
        membership_id = "source-accounts:" + _digest(alias)
        membership = v2.Membership(membership_id, _digest([alias, alias + ":cad"]), (crypto, funding), "unknown",
            "Named source order accounts only; neither wallet balances nor opening assumptions are declared",
            _scope_parent(context, "membership", membership_id))
        records = []
        for order in orders:
            status = _status(order)
            occurred = _at(order["completed_at"]) if status == "completed" else _at(order["created_at"])
            cad = AssetKey("cash", "CAD", "CAD")
            payout = (cad if order["payout_currency"] == "CAD" else
                AssetKey("crypto", order["payout_currency"], "CAD", network=order["network"]))
            lifecycle = v2.Lifecycle(_at(order["created_at"]), _at(order["completed_at"]), _at(order["sent_at"]),
                order["order_type"], order["order_subtype"], order["order_status"], order["payin_status"], order["payout_status"],
                v2.AssetAmount(cad, Decimal(order["payin_amount"]), order["payin_method"]),
                v2.AssetAmount(payout, Decimal(order["payout_amount"]), order["payout_method"]),
                _rate(order, "exchange_rate"), _rate(order, "index_rate"))
            audit = tuple((name, str(value) if value is not None else "") for name, value in sorted(order.items()))
            revision = _digest(order)
            if order["order_type"] == "Funding":
                key = _key(context, funding, "cash_flows", order["order_key"], revision)
                records.append(v2.CashFlow(key, occurred, "deposit", "in", Money(Decimal(order["payout_amount"]), "CAD"),
                    status, "unclassified", lifecycle=lifecycle, revision_reason=_reason(key), source_fields=audit))
            else:
                key = _key(context, crypto, "crypto_transactions", order["order_key"], revision)
                amount = Money(Decimal(order["payin_amount"]), "CAD")
                records.append(v2.CryptoTransaction(key, occurred, "purchase", status,
                    (CryptoLeg(funding, cad, amount.amount.copy_negate()),
                     CryptoLeg(crypto, payout, Decimal(order["payout_amount"]))), amount, amount, None,
                    lifecycle, revision_reason=_reason(key), source_fields=audit))
        coverage = []
        for account, kind in ((funding, "cash_flows"), (crypto, "crypto_transactions")):
            rows = [record for record in records if record.key.account == account and record.kind == kind]
            if rows:
                scope_id = "exported-orders"
                scope_revision = _digest([dict(record.source_fields) for record in rows])
                coverage.append(v2.Coverage(kind, account, min(r.occurred_at for r in rows), max(r.occurred_at for r in rows),
                    "partial", "Observed order rows only; gaps and external wallet events remain unverified", scope_id,
                    scope_revision, _scope_parent(context, "coverage", scope_id, account, kind)))
        effective = max(_at(order["completed_at"] or order["created_at"]) for order in orders)
        if effective > context.evidence_at:
            raise ValueError("Source order follows its evidence time")
        evidence = v2.Evidence(hashlib.sha256(raw).hexdigest(), context, effective,
            "Legacy provider/alias/order hash and normalized order content hash; explicit revision parents",
            (("legacy_semantic_hash", semantic),),
            (v2.Diagnostic("wallet_balance_unverified", "warning"),
             v2.Diagnostic("wallet_fees_unknown", "warning"),
             v2.Diagnostic("observed_order_rows", "info", (("rows", str(row_count)), ("duplicates", str(duplicates))))))
        batch = v2.NormalizedBatch(self.info, export_version, evidence, accounts, membership, (), tuple(coverage), tuple(records))
        v2.validate_batch(batch, raw, context=context)
        return batch


def registrations():
    """Explicit trusted built-ins; registry defaults and v1 plans stay unchanged."""
    return (AdapterRegistration(ProviderInfo("wealthsimple", "Wealthsimple"), WealthsimpleHoldings()),
            AdapterRegistration(ProviderInfo("bullbitcoin", "Bull Bitcoin"), BullBitcoinOrders()))
