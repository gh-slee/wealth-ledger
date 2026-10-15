"""Append auditable, unknown-cost pre-Bull quantities without inventing trades."""
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import hashlib
import json
import sqlite3

from .crypto import _time, _now, _json, _text, _account_id


def latest_opening(project, source_account='bullbitcoin-main', cutoff=None):
    db = Path(project)/'data/db/portfolio.sqlite3'
    if not db.exists():
        return None
    with sqlite3.connect(f'file:{db}?mode=ro', uri=True) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='crypto_opening_revisions'").fetchone():
            return None
        row = conn.execute('SELECT id,revision,payload_json,source_path,source_sha256 FROM crypto_opening_revisions WHERE source_account=? ORDER BY revision DESC LIMIT 1', (source_account,)).fetchone()
    if not row:
        return None
    value = json.loads(row[2])
    if cutoff and _time(cutoff) < value['applies_from']:
        return None
    source = Path(project)/row[3]
    return {**value, 'id':row[0], 'revision':row[1], 'source_path':row[3], 'source_sha256':row[4],
            'integrity_ok':source.exists() and hashlib.sha256(source.read_bytes()).hexdigest()==row[4]}


def import_opening(project, json_path, source_account='bullbitcoin-main'):
    """Freeze a user-attributed total-minus-purchases difference once per input."""
    from .crypto import make_crypto_view
    project, json_path = Path(project), Path(json_path)
    raw = json_path.read_bytes()
    data = json.loads(raw)
    required = ('reported_total_btc_equivalent', 'reference_as_of', 'declared_on', 'balance_scope', 'basis', 'confirmed_by')
    if not isinstance(data, dict) or any(data.get(key) is None or not str(data.get(key, '')).strip() for key in required):
        raise ValueError('Opening declaration requires total, reference time, date, scope, basis and confirmation')
    if data['balance_scope'] != 'all_wallets_btc_plus_lbtc':
        raise ValueError('Confirm the combined BTC and LBTC total covers all tracked wallets')
    try:
        total = Decimal(str(data['reported_total_btc_equivalent']))
    except InvalidOperation as exc:
        raise ValueError('Invalid BTC equivalent total') from exc
    if not total.is_finite() or total < 0 or total*Decimal(100000000) != (total*Decimal(100000000)).to_integral_value():
        raise ValueError('BTC equivalent total must be finite, nonnegative and have satoshi precision')
    cutoff = _time(data['reference_as_of'])
    declared = date.fromisoformat(data['declared_on'])
    if cutoff[:10] > declared.isoformat():
        raise ValueError('Reference date cannot follow declaration date')
    sha = hashlib.sha256(raw).hexdigest()
    db = project/'data/db/portfolio.sqlite3'
    if not db.exists():
        raise ValueError('Import Bull orders before recording pre-Bull holdings')
    with sqlite3.connect(db) as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='crypto_opening_revisions'").fetchone()
        if exists:
            same = conn.execute('SELECT id,revision,payload_json FROM crypto_opening_revisions WHERE source_account=? AND source_sha256=?', (source_account, sha)).fetchone()
            if same:
                return {'status':'duplicate', 'id':same[0], 'revision':same[1], **json.loads(same[2])}
    view = make_crypto_view(project, cutoff, source_account)
    if any(not source['integrity_ok'] for source in view['source']['sources']):
        raise ValueError('Verify archived Bull source integrity before deriving opening holdings')
    purchased = Decimal(view['qty_btc'])+Decimal(view['qty_lbtc'])
    opening = total-purchased
    if opening < 0:
        raise ValueError('Reported total is below purchased quantity; record a reconciliation instead of negative opening')
    first = view['source']['earliest_created_at']
    if cutoff < first:
        raise ValueError('Reference time must include the imported Bull order range')
    declaration = {'record_type':'user_attributed_pre_bull_quantity', 'source_account':source_account,
                   'account_id':_account_id(source_account), 'declared_on':declared.isoformat(),
                   'reference_as_of':cutoff, 'reported_total_btc_equivalent':_text(total),
                   'reference_purchased_btc_equivalent':_text(purchased), 'opening_btc_equivalent_qty':_text(opening),
                   'cost_cad':None, 'historical_contribution_cad':None, 'network_distribution':'unknown',
                   'applies_from':first, 'basis':data['basis'], 'confirmed_by':data['confirmed_by'],
                   'balance_scope':data['balance_scope'], 'created_at':_now(),
                   'reference_sources':[{key:s[key] for key in ('id','sha256','path')} for s in view['source']['sources']],
                   'wallet_fees_accounted':False}
    directory = project/'data/raw/crypto/opening'/declared.strftime('%Y/%m')
    directory.mkdir(parents=True, exist_ok=True)
    target = directory/f'{json_path.stem}-{sha[:16]}.json'
    if target.exists():
        if target.read_bytes()!=raw:
            raise ValueError('Opening source archive collision')
    else:
        with target.open('xb') as handle:
            handle.write(raw)
    target.chmod(0o400)
    with sqlite3.connect(db) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('''CREATE TABLE IF NOT EXISTS crypto_opening_revisions(
          id INTEGER PRIMARY KEY, source_account TEXT NOT NULL, revision INTEGER NOT NULL,
          payload_json TEXT NOT NULL, source_path TEXT NOT NULL, source_sha256 TEXT NOT NULL,
          created_at TEXT NOT NULL, UNIQUE(source_account,revision), UNIQUE(source_account,source_sha256))''')
        conn.execute('BEGIN IMMEDIATE')
        revision = conn.execute('SELECT COALESCE(MAX(revision),0)+1 FROM crypto_opening_revisions WHERE source_account=?', (source_account,)).fetchone()[0]
        cursor = conn.execute('INSERT INTO crypto_opening_revisions(source_account,revision,payload_json,source_path,source_sha256,created_at) VALUES(?,?,?,?,?,?)',
                              (source_account, revision, _json(declaration), str(target.relative_to(project)), sha, declaration['created_at']))
    db.chmod(0o600)
    return {'status':'recorded', 'id':cursor.lastrowid, 'revision':revision, **declaration}
