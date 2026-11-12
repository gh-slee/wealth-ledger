"""Read-only native migration policies; no CSV parsing or legacy-row rewriting.

Keep these source-specific compatibility checks separate from canonical storage.
They preserve current native guarantees during the opt-in migration phase.
"""
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import json
import sqlite3

from .source_ingestion import IngestionError, _database


def _at(value):
    return datetime.fromisoformat(value.replace("Z","+00:00")).astimezone(timezone.utc)


def _signature(record):
    lifecycle = record["lifecycle"]
    return (lifecycle["source_type"], Decimal(lifecycle["payin"]["quantity"]), lifecycle["payin"]["asset"]["symbol"],
        Decimal(lifecycle["payout"]["quantity"]), lifecycle["payout"]["asset"]["symbol"],
        lifecycle["payin"]["method"], lifecycle["payout"]["method"], lifecycle["payout"]["asset"]["network"],
        _at(lifecycle["created_at"]),_at(lifecycle["completed_at"]))


def validate_native_compatibility(project, inputs):
    from . import source_v2 as v2
    database = _database(project)
    if not database.exists():return
    with closing(sqlite3.connect(database.as_uri()+"?mode=ro",uri=True)) as conn:
        conn.row_factory=sqlite3.Row
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        old_crypto={}
        if "crypto_order_revisions" in tables:
            for row in conn.execute("SELECT * FROM crypto_order_revisions ORDER BY id"):
                old_crypto[(row["provider"],row["source_account"],row["order_key"])]=json.loads(row["payload_json"])
        current={};versions=set();snapshot_times=[]
        if "src_records" in tables:
            for row in conn.execute("SELECT payload_json FROM src_records ORDER BY id"):
                record=json.loads(row[0]);key=record["key"]
                token=(key["account"]["provider"],key["account"]["account_id"],record["kind"],key["source_id"])
                current[token]=record
                versions.add((*token,key["revision"],row[0]))
                if key["account"]["provider"]=="wealthsimple" and record["kind"]=="holdings":snapshot_times.append(_at(record["as_of"]))
        first=None
        if "snapshots" in tables:
            first=conn.execute("SELECT MIN(as_of_utc) FROM snapshots").fetchone()[0]
        earliest=min(([_at(first)] if first else [])+snapshot_times) if first or snapshot_times else None
        for source in inputs:
            if source.batch.adapter.adapter_id=="wealthsimple.holdings" and earliest and any(s.as_of<earliest for s in source.batch.snapshots):
                raise IngestionError("native_backfill_disabled")
            if source.batch.adapter.adapter_id!="bullbitcoin.orders":continue
            for incoming in source.batch.records:
                record=json.loads(v2.canonical_json(incoming));key=record["key"]
                token=(key["account"]["provider"],key["account"]["account_id"],record["kind"],key["source_id"])
                if (*token,key["revision"],v2.canonical_json(incoming)) in versions:continue
                old=current.get(token)
                if old and old["status"]=="completed":
                    if record["status"]!="completed" or not record["lifecycle"] or _signature(record)!=_signature(old):
                        raise IngestionError("native_completed_order_conflict")
                alias=source.batch.evidence.context.account_alias
                legacy=old_crypto.get(("bullbitcoin",alias,key["source_id"]))
                if legacy and all(legacy[k].casefold()=="completed" for k in ("order_status","payin_status","payout_status")):
                    expected=(legacy["order_type"],Decimal(legacy["payin_amount"]),legacy["payin_currency"],
                        Decimal(legacy["payout_amount"]),legacy["payout_currency"],legacy["payin_method"],legacy["payout_method"],legacy["network"],
                        _at(legacy["created_at"]),_at(legacy["completed_at"]))
                    if record["status"]!="completed" or not record["lifecycle"] or _signature(record)!=expected:
                        raise IngestionError("native_completed_order_conflict")
