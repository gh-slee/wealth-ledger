"""Invented holdings format: never use this as a real institution parser."""
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import io

from wealth_ledger.source_protocol import (
    AccountKey, AdapterInfo, AssetKey, Coverage, Detection, Holding, Money,
    NormalizedBatch, RecordKey, SourceEvidence, validate_batch,
)
from wealth_ledger.source_registry import AdapterRegistration, ProviderInfo, MAX_INPUT_BYTES

FIELDS = ("format", "account", "id", "revision", "supersedes", "change", "as_of",
          "symbol", "market", "currency", "quantity", "value", "cost", "scope_revision")
VERSION = "synthetic-holdings-v1"


def _reader(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_INPUT_BYTES or b"\0" in raw:
        raise ValueError("Invalid synthetic input")
    try:
        return csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
    except UnicodeError as exc:
        raise ValueError("Invalid synthetic encoding") from exc


class SyntheticHoldings:
    info = AdapterInfo("synthetic", "synthetic.holdings", "0.1.0", (VERSION,), ("holdings",))

    def detect(self, raw):
        try:
            reader = _reader(raw)
            row = next(reader, None)
            matched = tuple(reader.fieldnames or ()) == FIELDS and bool(row) and row.get("format") == VERSION
        except (ValueError, csv.Error):
            matched = False
        return Detection(matched, VERSION if matched else None, "Synthetic format marker and exact header")

    def normalize(self, raw, *, export_version):
        if export_version != VERSION:
            raise ValueError("Unsupported synthetic format version")
        try:
            reader = _reader(raw)
            if tuple(reader.fieldnames or ()) != FIELDS:
                raise ValueError("Unexpected synthetic columns")
            records, scopes = [], {}
            for index, row in enumerate(reader):
                if index >= 10000 or None in row or any(value is None for value in row.values()) or row["format"] != VERSION:
                    raise ValueError("Malformed synthetic row")
                account = AccountKey("synthetic", row["account"])
                at = datetime.fromisoformat(row["as_of"])
                key = RecordKey(account, row["id"], row["revision"], row["supersedes"] or None, row["change"])
                record = Holding(key, at, AssetKey("security", row["symbol"], row["currency"], market=row["market"]),
                                 Decimal(row["quantity"]), Money(Decimal(row["value"]), row["currency"]),
                                 Money(Decimal(row["cost"]), row["currency"]) if row["cost"] else None)
                records.append(record)
                token = (account, row["scope_revision"])
                scopes.setdefault(token, []).append(at)
            if not records:
                raise ValueError("Synthetic format requires at least one holding")
            if len({account for account, revision in scopes}) != len(scopes):
                raise ValueError("Conflicting scope revisions for one synthetic account")
            records.sort(key=lambda record: (record.key.account.account_id, record.key.source_id))
            coverage = tuple(Coverage("holdings", account, min(times), max(times), "partial",
                                     "Positions only; cash and activity not exported", "synthetic-positions", revision)
                             for (account, revision), times in sorted(scopes.items(), key=lambda item: item[0][0].account_id))
            effective = max(record.as_of for record in records)
            evidence = SourceEvidence(hashlib.sha256(raw).hexdigest(), effective, effective,
                                      "synthetic-fixture", tuple((field, field) for field in FIELDS),
                                      ("Synthetic format; fetched_at is a deterministic source-time placeholder",),
                                      "Required provider-issued position ID; revisions explicit")
            batch = NormalizedBatch(self.info, VERSION, evidence, coverage, tuple(records))
            validate_batch(batch, raw)
            return batch
        except (csv.Error, InvalidOperation, OverflowError, TypeError) as exc:
            raise ValueError("Invalid synthetic values") from exc


def register():
    return AdapterRegistration(ProviderInfo("synthetic", "Synthetic Example Provider"), SyntheticHoldings())
