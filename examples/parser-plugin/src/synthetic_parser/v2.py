"""Invented protocol-v2 positions; not a real broker or a complete account export."""
import csv
from datetime import datetime
from decimal import Decimal
import hashlib

from wealth_ledger import source_v2 as v2
from wealth_ledger.source_registry import AdapterRegistration, ProviderInfo
from . import FIELDS, _reader

VERSION="synthetic-holdings-v2"


class SyntheticHoldingsV2:
    info=v2.AdapterInfo("synthetic","synthetic.holdings-v2","0.1.0",(VERSION,),("holdings",),api_version=2)

    def detect(self,raw):
        try:
            reader=_reader(raw);row=next(reader,None)
            matched=tuple(reader.fieldnames or ())==FIELDS and bool(row) and row.get("format")==VERSION
        except (ValueError,csv.Error):matched=False
        return v2.Detection(matched,VERSION if matched else None,"Synthetic v2 exact header and marker")

    def normalize(self,raw,*,export_version,context):
        v2.validate_context(context)
        if export_version!=VERSION:raise ValueError("Unsupported synthetic version")
        reader=_reader(raw)
        if tuple(reader.fieldnames or ())!=FIELDS:raise ValueError("Unexpected synthetic columns")
        accounts={};groups={};records=[];membership=set()
        for index,row in enumerate(reader):
            if index>=10000 or None in row or any(value is None for value in row.values()) or row["format"]!=VERSION:raise ValueError("Malformed synthetic row")
            account=v2.AccountKey("synthetic",row["account"])
            accounts[account]=v2.Account(account,"investment","Synthetic account","investment")
            at=datetime.fromisoformat(row["as_of"])
            observation="synthetic-snapshot:"+row["as_of"]
            key=v2.RecordKey(account,row["id"],row["revision"],row["supersedes"] or None,row["change"])
            cost=v2.Money(Decimal(row["cost"]),row["currency"]) if row["cost"] else None
            records.append(v2.Position(key,observation,at,v2.AssetKey("security",row["symbol"],row["currency"],market=row["market"]),
                row["symbol"],"STOCK",row["market"],Decimal(row["quantity"]),v2.Money(Decimal(row["value"]),row["currency"]),None,
                cost,cost if row["currency"]=="CAD" else None,None,source_fields=tuple(sorted(row.items()))))
            groups.setdefault(observation,[]).append(records[-1]);membership.add(row["scope_revision"])
        if not records or len(membership)!=1:raise ValueError("Missing holdings or conflicting membership")
        snapshots=tuple(v2.Snapshot(name,rows[0].key.revision,rows[0].as_of,tuple(sorted({r.key.account for r in rows},key=lambda key:key.account_id)),rows[0].key.supersedes_revision) for name,rows in sorted(groups.items()))
        coverage=tuple(v2.Coverage("holdings",account,s.as_of,s.as_of,"partial","Synthetic positions; cash/activity omitted",s.source_id,s.revision,s.supersedes_revision,s.source_id) for s in snapshots for account in s.accounts)
        batch=v2.NormalizedBatch(self.info,VERSION,v2.Evidence(hashlib.sha256(raw).hexdigest(),context,max(r.as_of for r in records),"Explicit provider position IDs and dated snapshots"),
            tuple(accounts[key] for key in sorted(accounts,key=lambda key:key.account_id)),
            v2.Membership("synthetic-accounts",next(iter(membership)),tuple(sorted(accounts,key=lambda key:key.account_id)),"partial","Only exported accounts"),
            snapshots,coverage,tuple(sorted(records,key=lambda row:(row.observation_id,row.key.account.account_id,row.key.source_id))))
        v2.validate_batch(batch,raw,context=context)
        return batch


def register():
    return AdapterRegistration(ProviderInfo("synthetic","Synthetic Example Provider"),SyntheticHoldingsV2())
