"""SRC-004A canonical ingestion foundation; no CLI/Web/report projection switch.

Facts/effects live in the existing financial database and existing atomic-operation
boundary. There is no second portfolio database or implicit contribution inference.
The compatibility projections and production importer migration remain SRC-004B/C.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from . import source_v2 as v2
from .source_environment import environment_fingerprint
from .source_protocol import AccountKey, AssetKey

SCHEMA_VERSION = 1
POLICY = "canonical-v2-facts-1"
TABLES = {"src_schema", "src_bindings", "src_batches", "src_records", "src_batch_records", "src_scopes",
          "src_snapshot_records", "src_effects"}
SHA = re.compile(r"[a-f0-9]{64}")


class IngestionError(ValueError):
    """Stable diagnostics; never include an account, source row or plugin error."""
    def __init__(self, code):
        self.code = code
        super().__init__("Canonical ingestion rejected: " + code)


@dataclass(frozen=True)
class Binding:
    account: AccountKey
    ledger_account_id: str
    target_kind: str = "canonical"


@dataclass(frozen=True)
class SourceInput:
    batch: v2.NormalizedBatch
    raw: bytes


@dataclass(frozen=True)
class IngestionPlan:
    inputs: tuple[SourceInput, ...]
    bindings: tuple[Binding, ...]
    state_sha256: str
    environment_sha256: str
    policy: str
    fingerprint: str


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def new_binding(account):
    """Suggested identity for a new canonical account, never a legacy ID rewrite."""
    if not isinstance(account, AccountKey) or not isinstance(account.provider, str) or not isinstance(account.account_id, str):
        raise IngestionError("invalid_binding")
    return Binding(account, "src_" + _hash(_json(asdict(account)).encode())[:32])


def _database(project):
    return Path(project) / "data/db/portfolio.sqlite3"


def _open(project):
    path = _database(project)
    if path.is_symlink():
        raise IngestionError("unsafe_evidence")
    if not path.exists():
        return None
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _schema(conn):
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} if conn else set()
    if "src_schema" not in names:
        if any(name.startswith("src_") for name in names):
            raise IngestionError("schema_invalid")
        return 0
    try:
        rows = conn.execute("SELECT version FROM src_schema").fetchall()
        if len(rows) != 1 or rows[0][0] != SCHEMA_VERSION or {name for name in names if name.startswith("src_")} != TABLES:
            raise IngestionError("schema_incompatible")
    except sqlite3.Error:
        raise IngestionError("schema_invalid") from None
    return SCHEMA_VERSION


def _rows(conn, name):
    if conn is None or not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone():
        return []
    return [dict(row) for row in conn.execute('SELECT * FROM "' + name.replace('"', '""') + '"')]


def state_fingerprint(project):
    """Logical financial state, including bindings; no writes or empty-DB ambiguity."""
    conn = _open(project)
    try:
        version = _schema(conn)
        values = []
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} if conn else set()
        financial = {"sources", "accounts", "snapshots", "positions", "cash_flows", "flow_periods", "flow_coverage", "coverage_declarations"}
        for name in sorted(names):
            if name in financial or name.startswith(("src_", "crypto_", "wallet_")):
                rows = sorted(_rows(conn, name), key=_json)
                if rows:
                    values.append((name, rows))
        return _hash(_json({"schema": version, "values": values}).encode())
    finally:
        if conn:
            conn.close()


def _archive_path(project, relative):
    root = Path(project).resolve()
    if not isinstance(relative, str) or not re.fullmatch(r"data/raw/source-v2/[a-f0-9]{64}\.(csv|json)", relative):
        raise IngestionError("unsafe_evidence")
    path = root / relative
    if any(part.is_symlink() for part in (path, *path.parents) if part.is_relative_to(root)):
        raise IngestionError("unsafe_evidence")
    return path


def _binding_document(row):
    return _json({"format":"wealth-ledger-source-binding", "schema_version":1, "policy":POLICY,
                  **{key:row[key] for key in ("provider","source_account","ledger_account","target_kind","identity_json")}}).encode()


def verify_store(project):
    """Check archives, facts, scope membership and effects without loading a parser."""
    conn = _open(project)
    try:
        if not _schema(conn):
            return {"schema_version": 0, "batches": 0}
        if conn.execute("PRAGMA foreign_key_check").fetchone():
            raise IngestionError("store_integrity")
        batches = _rows(conn, "src_batches")
        records = {row["id"]:row for row in _rows(conn,"src_records")}
        versions = {(row["provider"],row["source_account"],row["kind"],row["observation_id"],row["source_id"],row["revision"]):row
                    for row in records.values()}
        scopes = {(row["provider"],row["scope_key"],row["revision"]):row for row in _rows(conn,"src_scopes")}
        expected_links, expected_scopes, expected_snapshots, expected_effects = set(), set(), set(), set()
        witnessed_records, witnessed_scopes = {}, {}
        account_identities = {}
        for batch in batches:
            expected_raw = "data/raw/source-v2/" + batch["raw_sha256"] + ".csv"
            expected_canonical = "data/raw/source-v2/" + batch["batch_id"] + ".json"
            if (batch["batch_id"] != batch["canonical_sha256"] or batch["raw_path"] != expected_raw
                    or batch["canonical_path"] != expected_canonical or batch["policy"] != POLICY
                    or not SHA.fullmatch(batch["environment_sha256"])):
                raise IngestionError("store_integrity")
            raw = _archive_path(project,batch["raw_path"]).read_bytes()
            canonical = _archive_path(project,batch["canonical_path"]).read_bytes()
            if _hash(raw) != batch["raw_sha256"] or _hash(canonical) != batch["canonical_sha256"]:
                raise IngestionError("source_integrity")
            decoded = v2.decode_batch(canonical, raw)
            if (decoded.adapter.provider_id != batch["provider"] or decoded.adapter.adapter_id != batch["adapter_id"]
                    or _hash(v2.canonical_json(decoded.evidence.context).encode()) != batch["context_sha256"]):
                raise IngestionError("store_integrity")
            for account in decoded.accounts:
                token = (account.key.provider,account.key.account_id)
                identity = _json((account.account_type,account.role,account.masked_identifier))
                if token in account_identities and account_identities[token] != identity:
                    raise IngestionError("store_integrity")
                account_identities[token] = identity
            for record in decoded.records:
                payload = v2.canonical_json(record)
                token = (*_identity(json.loads(payload)),record.key.revision)
                row = versions.get(token)
                if (not row or row["payload_json"] != payload or row["record_sha256"] != _hash(payload.encode())
                        or row["parent_revision"] != record.key.supersedes_revision or row["change"] != record.key.change):
                    raise IngestionError("store_integrity")
                record_id = row["id"]
                expected_links.add((batch["batch_id"],record_id))
                witnessed_records.setdefault(record_id,set()).add(batch["batch_id"])
                if isinstance(record,v2.Position):
                    expected_snapshots.add((record.key.account.provider,record.observation_id,record.key.revision,record_id))
                for ordinal,(account,asset,quantity,role) in enumerate(_effect_rows(record)):
                    expected_effects.add((record_id,ordinal,account.provider,account.account_id,v2.canonical_json(asset),str(quantity),role))
            for provider,key,revision,parent,sha_payload in _scope_entries(decoded):
                token = (provider,key,revision)
                row = scopes.get(token)
                if not row or row["payload_json"] != sha_payload or row["scope_sha256"] != _hash(sha_payload.encode()) or row["parent_revision"] != parent:
                    raise IngestionError("store_integrity")
                expected_scopes.add(token)
                witnessed_scopes.setdefault(token,set()).add(batch["batch_id"])
        if (set(records) != set(witnessed_records) or set(scopes) != expected_scopes
                or any(row["first_batch"] not in witnessed_records[row["id"]] for row in records.values())
                or any(row["first_batch"] not in witnessed_scopes[token] for token,row in scopes.items())
                or expected_links != {(r["batch_id"],r["record_id"]) for r in _rows(conn,"src_batch_records")}
                or expected_snapshots != {tuple(r[k] for k in ("provider","observation_id","revision","record_id")) for r in _rows(conn,"src_snapshot_records")}
                or expected_effects != {tuple(r[k] for k in ("record_id","ordinal","provider","source_account","asset_json","quantity","role")) for r in _rows(conn,"src_effects")}
                or account_identities != {(r["provider"],r["source_account"]):r["identity_json"] for r in _rows(conn,"src_bindings")}):
            raise IngestionError("store_integrity")
        for row in _rows(conn,"src_bindings"):
            declaration = _binding_document(row)
            if (row["declaration_sha256"] != _hash(declaration)
                    or row["declaration_path"] != "data/raw/source-v2/" + row["declaration_sha256"] + ".json"
                    or _archive_path(project,row["declaration_path"]).read_bytes() != declaration):
                raise IngestionError("store_integrity")
        heads = {}
        for row in sorted(records.values(),key=lambda r:r["id"]):
            value = json.loads(row["payload_json"]); identity = _identity(value)
            previous = heads.get(identity)
            if value["key"]["supersedes_revision"] != (previous["key"]["revision"] if previous else None):
                raise IngestionError("store_integrity")
            heads[identity] = value
        scope_heads = {}
        for row in sorted(scopes.values(),key=lambda r:r["id"]):
            token = (row["provider"],row["scope_key"])
            if row["parent_revision"] != scope_heads.get(token):
                raise IngestionError("store_integrity")
            scope_heads[token] = row["revision"]
        _links(heads)
        return {"schema_version":SCHEMA_VERSION, "batches":len(batches)}
    except (OSError, sqlite3.Error, UnicodeError, ValueError, TypeError, KeyError) as exc:
        if isinstance(exc,IngestionError):
            raise
        raise IngestionError("store_integrity") from None
    finally:
        if conn:
            conn.close()


def _identity(record):
    account = record["key"]["account"]
    return (account["provider"], account["account_id"], record["kind"], record.get("observation_id", ""), record["key"]["source_id"])


def _reference(reference):
    return (reference["account"]["provider"], reference["account"]["account_id"], reference["kind"], "", reference["source_id"])


def _scope_entries(batch):
    provider = batch.adapter.provider_id
    yield provider, "membership:" + batch.membership.scope_id, batch.membership.revision, batch.membership.supersedes_revision, v2.canonical_json(batch.membership)
    for scope in batch.coverage:
        key = _json(["coverage", scope.account.account_id, scope.kind, scope.scope_id, scope.observation_id])
        yield provider, key, scope.revision, scope.supersedes_revision, v2.canonical_json(scope)
    for snapshot in batch.snapshots:
        records = sorted((_identity(json.loads(v2.canonical_json(record))), _hash(v2.canonical_json(record).encode()))
                         for record in batch.records if isinstance(record, v2.Position) and record.observation_id == snapshot.source_id)
        payload = _json({"header": json.loads(v2.canonical_json(snapshot)), "records": records})
        yield provider, "snapshot:" + snapshot.source_id, snapshot.revision, snapshot.supersedes_revision, payload


def _capabilities(record):
    if isinstance(record, v2.Position):
        if record.asset.kind not in {"security", "cash"} or record.asset.currency not in {"CAD", "USD"} or record.quantity < 0 or record.market_value.amount < 0:
            raise IngestionError("unsupported_effect")
    elif record.status == "completed" and isinstance(record, v2.CashFlow):
        if record.amount.currency not in {"CAD", "USD"} or record.counterpart is not None and record.type != "transfer":
            raise IngestionError("unsupported_effect")
    elif record.status == "completed" and isinstance(record, v2.CryptoTransaction):
        legs = record.legs
        cash = [leg for leg in legs if leg.asset == AssetKey("cash", "CAD", "CAD") and leg.quantity < 0]
        crypto = [leg for leg in legs if leg.asset.kind == "crypto" and (leg.asset.symbol, leg.asset.network) in {("BTC", "bitcoin"), ("LBTC", "liquid")} and leg.quantity > 0 and leg.asset.currency == "CAD"]
        if (record.type != "purchase" or record.counterpart is not None or len(legs) != 2 or len(cash) != 1 or len(crypto) != 1
                or any(leg.account != record.key.account for leg in legs)
                or any(cost is not None and (cost.currency != "CAD" or cost.amount < 0) for cost in (record.acquisition_cost, record.acquisition_cost_cad))):
            raise IngestionError("unsupported_effect")
        for fee in record.fees or ():
            if fee.account != record.key.account or fee.asset not in {cash[0].asset, crypto[0].asset}:
                raise IngestionError("unsupported_effect")


def _binding_rows(conn, inputs, bindings):
    accounts = {}
    for source in inputs:
        for account in source.batch.accounts:
            token = (account.key.provider, account.key.account_id)
            identity = (account.account_type, account.role, account.masked_identifier)
            if token in accounts and accounts[token][1] != identity:
                raise IngestionError("account_metadata_conflict")
            accounts[token] = (account, identity)
    existing = {(row["provider"], row["source_account"]):row for row in _rows(conn, "src_bindings")}
    targets = {(row["target_kind"], row["ledger_account"]): token for token, row in existing.items()}
    proposals, supplied = [], {}
    for binding in bindings:
        if (not isinstance(binding, Binding) or not isinstance(binding.account, AccountKey)
                or binding.target_kind not in {"canonical", "legacy_holdings", "legacy_crypto"}
                or not isinstance(binding.ledger_account_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", binding.ledger_account_id)):
            raise IngestionError("invalid_binding")
        token = (binding.account.provider, binding.account.account_id)
        if token not in accounts or token in supplied:
            raise IngestionError("invalid_binding")
        supplied[token] = binding
    for token, (account, identity) in accounts.items():
        old = existing.get(token)
        selected = supplied.get(token)
        if old:
            if selected is not None and (selected.target_kind != old["target_kind"] or selected.ledger_account_id != old["ledger_account"]):
                raise IngestionError("binding_conflict")
            if _json(identity) != old["identity_json"]:
                raise IngestionError("account_metadata_conflict")
            continue
        if selected is None:
            raise IngestionError("binding_required")
        target = (selected.target_kind, selected.ledger_account_id)
        if target in targets and targets[target] != token:
            raise IngestionError("binding_collision")
        # A different target kind cannot be used to alias the same financial identity.
        if any(ledger == selected.ledger_account_id and owner != token for (_, ledger), owner in targets.items()):
            raise IngestionError("binding_collision")
        holdings = next((row for row in _rows(conn, "accounts") if row["account_id"] == selected.ledger_account_id), None)
        crypto = next((row for row in _rows(conn, "crypto_accounts") if row["account_id"] == selected.ledger_account_id), None)
        if selected.target_kind == "legacy_holdings":
            if not holdings or crypto or account.role != "investment" or holdings["account_type"] != account.account_type or holdings["masked_number"] != account.masked_identifier:
                raise IngestionError("legacy_binding_mismatch")
        elif selected.target_kind == "legacy_crypto":
            if (not crypto or holdings or account.role != "crypto" or crypto["provider"] != token[0] or crypto["source_account"] != token[1]):
                raise IngestionError("legacy_binding_mismatch")
        elif holdings or crypto:
            raise IngestionError("legacy_binding_required")
        targets[target] = token
        proposals.append((token[0], token[1], selected.ledger_account_id, selected.target_kind, _json(identity)))
    return proposals


def _effect_rows(record):
    """Canonical source changes only; external contributions are not calculated."""
    if isinstance(record, v2.Position) or record.status != "completed":
        return []
    if isinstance(record, v2.CashFlow):
        if record.cash_leg_of is not None:
            return []  # Verified equivalent cash leg is retained only as evidence.
        amount = record.amount.amount if record.direction == "in" else record.amount.amount.copy_negate()
        return [(record.key.account, AssetKey("cash", record.amount.currency, record.amount.currency), amount, "source_cash_flow")]
    result = [(leg.account, leg.asset, leg.quantity, "crypto_leg") for leg in record.legs]
    result += [(fee.account, fee.asset, fee.quantity.copy_negate(), "separate_fee") for fee in record.fees or () if not fee.included_in_leg and fee.quantity]
    return result


def _links(heads):
    claimed, unresolved = {}, 0
    for identity, record in heads.items():
        if record["kind"] != "cash_flows" or record["status"] != "completed":
            continue
        link = record["cash_leg_of"]
        if link is not None:
            target_id = _reference(link)
            target = heads.get(target_id)
            if not target or target["kind"] != "crypto_transactions" or target["status"] != "completed":
                raise IngestionError("cash_leg_unresolved")
            matches = [leg for leg in target["legs"] if leg["account"] == record["key"]["account"]
                       and leg["asset"]["kind"] == "cash" and leg["asset"]["currency"] == record["amount"]["currency"]]
            signed = Decimal(record["amount"]["amount"])
            if record["direction"] == "out":
                signed = signed.copy_negate()
            if len(matches) != 1 or Decimal(matches[0]["quantity"]) != signed:
                raise IngestionError("cash_leg_mismatch")
            token = (target_id, _json(matches[0]["account"]), record["amount"]["currency"])
            if token in claimed:
                raise IngestionError("duplicate_cash_leg")
            claimed[token] = identity
        counterpart = record["counterpart"]
        if record["type"] == "transfer":
            target = heads.get(_reference(counterpart)) if counterpart is not None else None
            if target is None:
                unresolved += 1
            elif (target["kind"] != "cash_flows" or target["type"] != "transfer" or target["status"] != "completed"
                  or record["boundary"] != "internal" or target["boundary"] != "internal"
                  or target["direction"] == record["direction"] or target["amount"]["currency"] != record["amount"]["currency"]
                  or Decimal(target["amount"]["amount"]) != Decimal(record["amount"]["amount"])
                  or target["transfer_reference"] != record["transfer_reference"]
                  or target["counterpart"] is None or _reference(target["counterpart"]) != identity):
                raise IngestionError("transfer_mismatch")
    return unresolved


def _proposal(conn, inputs, bindings):
    _schema(conn)
    binding_rows = _binding_rows(conn, inputs, bindings)
    existing_records = _rows(conn, "src_records")
    versions, heads = {}, {}
    for row in sorted(existing_records, key=lambda item:item["id"]):
        record = json.loads(row["payload_json"]); token = _identity(record)
        versions[(token, row["revision"])] = row
        heads[token] = record
    scope_versions, scope_heads = {}, {}
    for row in sorted(_rows(conn, "src_scopes"), key=lambda item:item["id"]):
        token = (row["provider"], row["scope_key"])
        scope_versions[(token, row["revision"])] = row
        scope_heads[token] = row["revision"]
    facts, scopes, seen_facts, seen_scopes = [], [], {}, {}
    for source in inputs:
        if any(item.severity == "error" for item in source.batch.evidence.diagnostics):
            raise IngestionError("source_errors")
        for provider, key, revision, parent, payload in _scope_entries(source.batch):
            token = (provider, key); sha = _hash(payload.encode())
            if token in seen_scopes and seen_scopes[token] != (revision, sha):
                raise IngestionError("input_scope_conflict")
            seen_scopes[token] = (revision, sha)
            prior = scope_versions.get((token, revision))
            if prior:
                if prior["scope_sha256"] != sha:
                    raise IngestionError("scope_revision_conflict")
                continue
            if parent != scope_heads.get(token):
                raise IngestionError("scope_lineage_conflict")
            scopes.append((provider, key, revision, parent, sha, payload, _hash(v2.canonical_json(source.batch).encode())))
            scope_versions[(token, revision)] = {"scope_sha256":sha}
            scope_heads[token] = revision
        for record in source.batch.records:
            _capabilities(record)
            payload = v2.canonical_json(record); value = json.loads(payload)
            token, sha = _identity(value), _hash(payload.encode())
            revision, parent = record.key.revision, record.key.supersedes_revision
            if token in seen_facts and seen_facts[token] != (revision, sha):
                raise IngestionError("input_scope_conflict")
            seen_facts[token] = (revision, sha)
            prior = versions.get((token, revision))
            if prior:
                if prior["record_sha256"] != sha:
                    raise IngestionError("record_revision_conflict")
                continue  # Replaying a historical revision never rolls the head back.
            head = heads.get(token)
            if (head is None and record.key.change != "original" or head is not None and
                    (record.key.change == "original" or parent != head["key"]["revision"])):
                raise IngestionError("record_lineage_conflict")
            facts.append((source, record, token, sha, payload))
            versions[(token, revision)] = {"record_sha256":sha}
            heads[token] = value
    return {"bindings":binding_rows, "scopes":scopes, "facts":facts, "unresolved_transfers":_links(heads)}


def _fingerprint(plan):
    body = {"inputs":[{"batch":_hash(v2.canonical_json(source.batch).encode()), "raw":_hash(source.raw)} for source in plan.inputs],
            "bindings":[asdict(item) for item in plan.bindings], "state":plan.state_sha256,
            "environment":plan.environment_sha256, "policy":plan.policy}
    return _hash(_json(body).encode())


def _validate_plan(plan):
    if (not isinstance(plan, IngestionPlan) or plan.policy != POLICY or not isinstance(plan.inputs, tuple)
            or not 1 <= len(plan.inputs) <= 5 or not isinstance(plan.bindings, tuple)
            or len(plan.bindings) > 200 or any(not isinstance(value, str) or not SHA.fullmatch(value)
                for value in (plan.state_sha256, plan.environment_sha256, plan.fingerprint))):
        raise IngestionError("invalid_plan")
    total = 0
    for source in plan.inputs:
        if not isinstance(source, SourceInput):
            raise IngestionError("invalid_plan")
        try:
            v2.validate_batch(source.batch, source.raw)
        except (ValueError, TypeError, AttributeError, OverflowError):
            raise IngestionError("invalid_batch") from None
        total += len(source.raw)
    if total > 25 * 1024 * 1024 or _fingerprint(plan) != plan.fingerprint:
        raise IngestionError("invalid_plan")


def prepare_ingestion(project, inputs, *, bindings=()):
    """Readonly stateful plan. Binding choices are private and portfolio-scoped."""
    from dataclasses import replace
    from .workspace import resolve_workspace
    project = resolve_workspace(explicit=project).workspace_root
    provisional = IngestionPlan(inputs, bindings, state_fingerprint(project), environment_fingerprint(), POLICY, "0"*64)
    try:
        provisional = replace(provisional, fingerprint=_fingerprint(provisional))
        _validate_plan(provisional)
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise IngestionError("invalid_batch") from None
    verify_store(project)
    conn = _open(project)
    try:
        _proposal(conn, inputs, bindings)
    finally:
        if conn:
            conn.close()
    if state_fingerprint(project) != provisional.state_sha256 or environment_fingerprint() != provisional.environment_sha256:
        raise IngestionError("stale_plan")
    return provisional


def _initialize(conn):
    if _schema(conn):
        return
    statements = (
        "CREATE TABLE src_schema(version INTEGER NOT NULL)",
        "INSERT INTO src_schema VALUES(1)",
        """CREATE TABLE src_bindings(provider TEXT NOT NULL,source_account TEXT NOT NULL,ledger_account TEXT NOT NULL UNIQUE,
             target_kind TEXT NOT NULL,identity_json TEXT NOT NULL,declaration_sha256 TEXT NOT NULL,
             declaration_path TEXT NOT NULL,PRIMARY KEY(provider,source_account))""",
        """CREATE TABLE src_batches(batch_id TEXT PRIMARY KEY,raw_sha256 TEXT NOT NULL,canonical_sha256 TEXT NOT NULL,
             raw_path TEXT NOT NULL,canonical_path TEXT NOT NULL,provider TEXT NOT NULL,adapter_id TEXT NOT NULL,context_sha256 TEXT NOT NULL,
             environment_sha256 TEXT NOT NULL,policy TEXT NOT NULL)""",
        """CREATE TABLE src_records(id INTEGER PRIMARY KEY,provider TEXT NOT NULL,source_account TEXT NOT NULL,kind TEXT NOT NULL,
             observation_id TEXT NOT NULL,source_id TEXT NOT NULL,revision TEXT NOT NULL,parent_revision TEXT,change TEXT NOT NULL,
             record_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL,first_batch TEXT NOT NULL REFERENCES src_batches(batch_id),
             FOREIGN KEY(provider,source_account) REFERENCES src_bindings(provider,source_account),
             UNIQUE(provider,source_account,kind,observation_id,source_id,revision))""",
        """CREATE TABLE src_batch_records(batch_id TEXT NOT NULL REFERENCES src_batches(batch_id),
             record_id INTEGER NOT NULL REFERENCES src_records(id),PRIMARY KEY(batch_id,record_id))""",
        """CREATE TABLE src_scopes(id INTEGER PRIMARY KEY,provider TEXT NOT NULL,scope_key TEXT NOT NULL,revision TEXT NOT NULL,
             parent_revision TEXT,scope_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL,first_batch TEXT NOT NULL REFERENCES src_batches(batch_id),
             UNIQUE(provider,scope_key,revision))""",
        """CREATE TABLE src_snapshot_records(provider TEXT NOT NULL,observation_id TEXT NOT NULL,revision TEXT NOT NULL,
             record_id INTEGER NOT NULL REFERENCES src_records(id),PRIMARY KEY(provider,observation_id,revision,record_id))""",
        """CREATE TABLE src_effects(record_id INTEGER NOT NULL REFERENCES src_records(id),ordinal INTEGER NOT NULL,
             provider TEXT NOT NULL,source_account TEXT NOT NULL,asset_json TEXT NOT NULL,quantity TEXT NOT NULL,role TEXT NOT NULL,
             FOREIGN KEY(provider,source_account) REFERENCES src_bindings(provider,source_account),PRIMARY KEY(record_id,ordinal))""",
    )
    for statement in statements:
        conn.execute(statement)


def _write(project, relative, raw):
    path = _archive_path(project, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise IngestionError("source_integrity")
        return
    with path.open("xb") as stream:
        stream.write(raw)
    path.chmod(0o400)


def _apply(project, plan):
    verify_store(project)
    if state_fingerprint(project) != plan.state_sha256 or environment_fingerprint() != plan.environment_sha256:
        raise IngestionError("stale_plan")
    with closing(sqlite3.connect(_database(project))) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        proposal = _proposal(conn, plan.inputs, plan.bindings)
        conn.execute("BEGIN IMMEDIATE")
        try:
            _initialize(conn)
            for values in proposal["bindings"]:
                declaration = _binding_document(dict(zip(("provider","source_account","ledger_account","target_kind","identity_json"),values)))
                sha = _hash(declaration)
                relative = "data/raw/source-v2/" + sha + ".json"
                _write(project,relative,declaration)
                conn.execute("INSERT INTO src_bindings VALUES(?,?,?,?,?,?,?)", (*values,sha,relative))
            for source in plan.inputs:
                canonical = v2.canonical_json(source.batch).encode()
                batch_id, raw_id = _hash(canonical), _hash(source.raw)
                raw_path = "data/raw/source-v2/" + raw_id + ".csv"
                canonical_path = "data/raw/source-v2/" + batch_id + ".json"
                _write(project, raw_path, source.raw); _write(project, canonical_path, canonical)
                conn.execute("INSERT OR IGNORE INTO src_batches VALUES(?,?,?,?,?,?,?,?,?,?)", (batch_id,raw_id,batch_id,
                    raw_path,canonical_path,source.batch.adapter.provider_id,source.batch.adapter.adapter_id,
                    _hash(v2.canonical_json(source.batch.evidence.context).encode()),plan.environment_sha256,POLICY))
            for values in proposal["scopes"]:
                conn.execute("INSERT INTO src_scopes(provider,scope_key,revision,parent_revision,scope_sha256,payload_json,first_batch) VALUES(?,?,?,?,?,?,?)", values)
            for source, record, token, sha, payload in proposal["facts"]:
                record_id = conn.execute("""INSERT INTO src_records(provider,source_account,kind,observation_id,source_id,revision,
                    parent_revision,change,record_sha256,payload_json,first_batch) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (*token,record.key.revision,record.key.supersedes_revision,record.key.change,sha,payload,
                     _hash(v2.canonical_json(source.batch).encode()))).lastrowid
                for ordinal, (account, asset, quantity, role) in enumerate(_effect_rows(record)):
                    conn.execute("INSERT INTO src_effects VALUES(?,?,?,?,?,?,?)", (record_id,ordinal,account.provider,
                        account.account_id,v2.canonical_json(asset),str(quantity),role))
            for source in plan.inputs:
                batch_id = _hash(v2.canonical_json(source.batch).encode())
                for record in source.batch.records:
                    identity = _identity(json.loads(v2.canonical_json(record)))
                    record_id = conn.execute("""SELECT id FROM src_records WHERE provider=? AND source_account=? AND kind=?
                        AND observation_id=? AND source_id=? AND revision=?""", (*identity,record.key.revision)).fetchone()[0]
                    conn.execute("INSERT OR IGNORE INTO src_batch_records VALUES(?,?)", (batch_id,record_id))
                    if isinstance(record, v2.Position):
                        conn.execute("INSERT OR IGNORE INTO src_snapshot_records VALUES(?,?,?,?)",
                            (record.key.account.provider,record.observation_id,record.key.revision,record_id))
            if environment_fingerprint() != plan.environment_sha256:
                raise IngestionError("stale_plan")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    verify_store(project)
    return {"status":"canonical_committed", "new_records":len(proposal["facts"]),
            "unresolved_transfers":proposal["unresolved_transfers"], "report_projection_ready":False,
            "contributions_calculated":False, "policy":POLICY, "environment_sha256":plan.environment_sha256}


def commit_ingestion(workspace, plan, *, operation_id=None):
    """Trusted core API; the existing service provides lock/backup/atomic recovery.

    Saved completed operations replay their receipt without calling parsers or
    requiring a newly installed parser version. No production CSV route uses this.
    """
    from .application import ApplicationService
    _validate_plan(plan)
    service = ApplicationService(workspace)
    return service.record({"type":"source_v2_canonical_ingestion", "plan_sha256":plan.fingerprint, "policy":POLICY},
                          lambda stage:_apply(stage,plan), label="before-source-v2", operation_id=operation_id)


def read_facts(project):
    """Readonly canonical observations and active effects, not a report payload.

    Holdings are constrained to the current revision of each snapshot. Omissions
    from partial snapshots never create disposal/zero records. Multiple dated
    observations remain separate; callers must not sum historical snapshots.
    """
    verify_store(project)
    conn = _open(project)
    try:
        if not _schema(conn):
            return {"records":[], "effects":[], "report_projection_ready":False}
        heads = {}
        for row in sorted(_rows(conn, "src_records"), key=lambda item:item["id"]):
            value = json.loads(row["payload_json"])
            heads[_identity(value)] = (row["id"], value)
        snapshots = {}
        for row in sorted(_rows(conn, "src_scopes"), key=lambda item:item["id"]):
            if row["scope_key"].startswith("snapshot:"):
                snapshots[(row["provider"],row["scope_key"][len("snapshot:"):])] = row["revision"]
        current = {record_id:value for record_id,value in heads.values()
                   if value["kind"] != "holdings" or value["key"]["revision"] == snapshots.get((value["key"]["account"]["provider"],value["observation_id"]))}
        effects = [row for row in _rows(conn, "src_effects") if row["record_id"] in current]
        return {"records":list(current.values()), "effects":effects, "bindings":_rows(conn,"src_bindings"),
                "coverage":_rows(conn,"src_scopes"), "report_projection_ready":False,
                "contributions_calculated":False}
    finally:
        if conn:
            conn.close()


def require_report_projection(project):
    """Fail closed until canonical facts have an implemented reporting projection.

    Existing frozen publications remain readable. This does not initialize a DB.
    Remove this phase gate only with SRC-004B/C parity and complete-scope acceptance.
    """
    conn = _open(project)
    try:
        if _schema(conn) and conn.execute("SELECT 1 FROM src_batches LIMIT 1").fetchone():
            raise IngestionError("report_projection_unavailable")
    finally:
        if conn:
            conn.close()
