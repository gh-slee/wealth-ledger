"""Verify date-only manual declarations for canonical investment identities."""
from decimal import Context, localcontext
import hashlib
import json
from pathlib import Path

from . import source_ingestion as ingestion
from .source_pipeline import bounded_read, INPUT_BYTES


def verify_manual_flows(project, conn):
    """Replay archived declarations without a parser, write, price or timestamp guess."""
    try:
        rows = ingestion._rows(conn, 'manual_cash_flows')
        if not rows: return
        from .core import _cash_flow_rows
        native = {row['account_id'] for row in ingestion._rows(conn, 'accounts')}
        canonical = {row['ledger_account'] for row in ingestion._rows(conn, 'src_bindings')
                     if json.loads(row['identity_json'])[1] == 'investment'}
        sources = {row['id']: row for row in ingestion._rows(conn, 'sources')}
        native_flows = {row['flow_id'] for row in ingestion._rows(conn, 'cash_flows')}
        cached = {}
        for stored in rows:
            sid = stored['source_id']
            if sid not in cached:
                source = sources[sid]
                root = Path(project).resolve()
                relative = Path(source['path'])
                if relative.is_absolute() or '..' in relative.parts or not source['path'].startswith('data/raw/activity/'):
                    raise ValueError('evidence scope')
                archive = root / relative
                if any(part.is_symlink() for part in (archive, *archive.parents) if part.is_relative_to(root)):
                    raise ValueError('evidence link')
                raw = bounded_read(archive, INPUT_BYTES)
                if hashlib.sha256(raw).hexdigest() != source['sha256']: raise ValueError('evidence')
                with localcontext(Context(prec=60)):
                    cached[sid] = {row['flow_id']: row for row in _cash_flow_rows(raw, native | canonical)}
            row = cached[sid][stored['flow_id']]
            if (row != json.loads(stored['payload_json']) or row['account_id'] not in canonical
                    or row['account_id'] in native or row['flow_id'] in native_flows
                    or any(stored[key] != row.get(field) for key,field in
                           [('flow_date','date'),('account_id','account_id'),('flow_type','flow_type'),('amount_cad','amount_cad')])
                    or stored['transfer_id'] != (row.get('transfer_id') or None)):
                raise ValueError('declaration')
    except (ValueError, KeyError, TypeError, OSError):
        raise ingestion.IngestionError('manual_flow_integrity') from None
