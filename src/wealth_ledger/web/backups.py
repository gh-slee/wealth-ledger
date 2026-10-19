"""Private, versioned instance backups and verified empty-target restoration."""
from contextlib import closing, ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid
import zipfile

from ..locking import file_lock
from .config import WebSettings
from .jobs import engine_fingerprint
from .maintenance import maintenance
from .storage import SCHEMA_VERSION, ID, Store, contained, private_write

VERSION = 1
MAX_FILES = 100000
MAX_TOTAL = 8 * 1024**3
MAX_FILE = 2 * 1024**3
MAX_MANIFEST = 16 * 1024**2
ROOTS = {"admin", "secrets", "portfolios", "uploads", "cache"}


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_name(name):
    if (not isinstance(name, str) or not name or len(name) > 1024 or "\\" in name or ":" in name
            or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        raise ValueError("Unsafe backup path")
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or str(path) != name or any(p in {".", ".."} or p.endswith((" ", ".")) for p in path.parts):
        raise ValueError("Unsafe backup path")
    return name


def database_info(path):
    """Logical values, schema and relationships; independent of SQLite page layout."""
    deadline = time.monotonic() + 60
    with closing(sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)] or conn.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Database integrity or foreign-key verification failed")
        schema = conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
        digest = hashlib.sha256(json.dumps(schema, ensure_ascii=True).encode())
        counts = {}
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            quoted = '"' + name.replace('"', '""') + '"'
            row_hashes = []
            for row in conn.execute("SELECT * FROM " + quoted):
                encoded = [({"blob": value.hex()} if isinstance(value, bytes) else value) for value in row]
                row_hashes.append(hashlib.sha256(json.dumps(encoded, ensure_ascii=True, allow_nan=False).encode()).digest())
            counts[name] = len(row_hashes)
            digest.update(name.encode())
            for row_hash in sorted(row_hashes):
                digest.update(row_hash)
        return {"user_version": conn.execute("PRAGMA user_version").fetchone()[0],
                "logical_sha256": digest.hexdigest(), "table_rows": counts}


def snapshot_database(source, target):
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src, \
            closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
    target.chmod(0o600)
    result = database_info(target)
    if result != database_info(source):
        raise ValueError("Database changed while taking the snapshot")
    return result


def validate_instance(root):
    """Validate registries against evidence; no financial import or regeneration."""
    store = Store(WebSettings(root))
    if not store.owner():
        raise ValueError("Backup must contain an initialized owner")
    with closing(store.connect()) as conn:
        portfolios = [row[0] for row in conn.execute("SELECT id FROM portfolios")]
        if set(p.name for p in (root / "portfolios").iterdir()) != set(portfolios):
            raise ValueError("Portfolio registry and directory scope differ")
        for pid in portfolios:
            _, project = store.portfolio(pid)
            store.reporting_settings(pid)
            database = contained(project, "data/db/portfolio.sqlite3")
            if database.is_file():
                from ..source_ingestion import verify_store
                verify_store(project)
                with closing(sqlite3.connect(database.as_uri()+"?mode=ro", uri=True)) as ledger:
                    tables = {r[0] for r in ledger.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    for table, column in (("sources","path"),("crypto_sources","path"),("wallet_revisions","source_path")):
                        if table in tables:
                            for relative, expected in ledger.execute(f'SELECT "{column}",sha256 FROM "{table}"'):
                                if not relative.startswith("data/raw/"):
                                    raise ValueError("Archived source scope differs")
                                source = contained(project, relative)
                                if not source.is_file() or file_hash(source) != expected:
                                    raise ValueError("Archived source evidence is missing or changed")
                    if "fund_sources" in tables:
                        for (raw,) in ledger.execute("SELECT payload_json FROM fund_sources"):
                            for evidence in json.loads(raw).get("evidence",[]):
                                source = contained(project,evidence["path"])
                                if not evidence["path"].startswith("data/raw/") or not source.is_file() or file_hash(source)!=evidence["sha256"]:
                                    raise ValueError("Official reference evidence is missing or changed")
            pointer = contained(project, "reports/latest.json")
            if pointer.is_file():
                relative = json.loads(pointer.read_text())["path"]
                if not relative.startswith("reports/") or not contained(project,relative).is_dir():
                    raise ValueError("Latest report pointer needs local review")
                latest = project / "reports/latest"
                if latest.is_symlink() and latest.resolve() != contained(project,relative).resolve():
                    raise ValueError("Latest report pointers disagree")
        for row in conn.execute("SELECT * FROM artifacts"):
            _, project = store.portfolio(row["portfolio_id"])
            if not row["relative_path"].startswith(("reports/", "data/raw/")):
                raise ValueError("Invalid registered artifact scope")
            path = contained(project, row["relative_path"])
            if not path.is_file() or path.stat().st_size != row["byte_size"] or file_hash(path) != row["sha256"]:
                raise ValueError("Registered artifact integrity failed")
        from .report_evidence import legacy_evidence
        for row in conn.execute("SELECT id,portfolio_id FROM jobs WHERE kind='update' AND status='published'"):
            legacy_evidence(store,row["portfolio_id"],row["id"])
        from .uploads import verified_upload
        for row in conn.execute("SELECT * FROM uploads"):
            verified_upload(store, dict(row))


def active_database(name):
    parts = PurePosixPath(name).parts
    return name in {"admin/app.sqlite3", "admin/queue.sqlite3"} or (
        len(parts)==5 and parts[0]=="portfolios" and ID.fullmatch(parts[1])
        and parts[2:]==("data","db","portfolio.sqlite3"))


def transient(name):
    """Exclude known runtime locations, never arbitrary source-file extensions."""
    parts = PurePosixPath(name).parts
    if parts[0]=="cache" or name=="admin/maintenance.json":
        return True
    if len(parts)==2 and parts[0]=="admin" and (
            parts[1] in {"maintenance.guard","maintenance-control.guard","worker.guard"}
            or re.fullmatch(r"job-[a-f0-9]{32}\.guard",parts[1])):
        return True
    if len(parts)==4 and parts[0]=="portfolios" and ID.fullmatch(parts[1]) and parts[2]=="work" and parts[3] in {"update.guard","update.lock"}:
        return True
    for suffix in ("-wal","-shm","-journal"):
        if name.endswith(suffix) and active_database(name[:-len(suffix)]):
            return True
    return False


def inventory(root):
    """All private durable content; omit only caches, lock files and SQLite sidecars."""
    files, directories, links = [], [], {}
    if any(p.name not in ROOTS for p in root.iterdir()):
        raise ValueError("Unexpected instance root content needs local review")
    def walk(directory):
        for path in sorted(directory.iterdir()):
            name = path.relative_to(root).as_posix()
            safe_name(name)
            if transient(name):
                continue
            if path.is_symlink():
                parts = PurePosixPath(name).parts
                if len(parts) != 4 or parts[0] != "portfolios" or not ID.fullmatch(parts[1]) or parts[2:] != ("reports", "latest"):
                    raise ValueError("Unexpected instance symlink")
                target = os.readlink(path)
                safe_name(target)
                resolved = path.parent / target
                if not resolved.is_dir() or not resolved.resolve().is_relative_to(path.parent.resolve()):
                    raise ValueError("Invalid latest report pointer")
                links[name] = target
            elif path.is_dir():
                directories.append(name)
                walk(path)
            elif path.is_file() and stat.S_ISREG(path.stat().st_mode):
                files.append(name)
            else:
                raise ValueError("Unsupported instance entry")
    walk(root)
    return files, directories, links


def backup_instance(settings, output, *, timeout=30, internal=False):
    root = settings.data_root
    store = Store(settings)
    output = Path(output).expanduser().absolute()
    if output.is_symlink() or output.exists():
        raise ValueError("Choose a new backup filename; existing paths are never overwritten")
    if output.resolve().is_relative_to(root) and not (internal and output.parent == root / "cache"):
        raise ValueError("Keep the backup outside the instance volume")
    if not output.parent.is_dir():
        raise ValueError("Create the private backup destination directory first")
    temporary = output.with_name("." + output.name + "-" + uuid.uuid4().hex)
    try:
        with maintenance(root, timeout=timeout), ExitStack() as locks:
            for row in store.portfolios():
                _, project = store.portfolio(row["id"])
                # The instance gate already drained all standard portfolio writers.
                locks.enter_context(file_lock(contained(project, "work/update.guard")))
                marker = contained(project, "work/update.lock")
                if marker.exists():
                    try:
                        lock = json.loads(marker.read_text())
                        if lock.get("lock_protocol") != 2 or not isinstance(lock.get("token"), str):
                            raise ValueError("Unknown lock protocol")
                    except (ValueError, AttributeError) as exc:
                        raise ValueError("Unknown legacy portfolio lock needs local review before backup") from exc
            validate_instance(root)
            files, directories, links = inventory(root)
            if len(files) + len(directories) + len(links) > MAX_FILES or sum(contained(root, p).stat().st_size for p in files) > MAX_TOTAL:
                raise ValueError("Instance exceeds the documented backup limit")
            with tempfile.TemporaryDirectory(prefix="backup-stage-", dir=contained(root, "cache")) as stage:
                stage = Path(stage)
                hashes, databases = {}, {}
                with temporary.open("xb") as handle:
                    temporary.chmod(0o600)
                    with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                        for name in files:
                            source = contained(root, name)
                            if source.stat().st_size > MAX_FILE:
                                raise ValueError("A file exceeds the documented backup limit")
                            active = active_database(name)
                            selected = source
                            if active:
                                selected = stage / (uuid.uuid4().hex + ".sqlite3")
                                databases[name] = snapshot_database(source, selected)
                            hashes[name] = {"sha256": file_hash(selected), "bytes": selected.stat().st_size}
                            archive.write(selected, "instance/" + name)
                        manifest = {"format": "wealth-ledger-private-instance", "version": VERSION,
                            "web_schema": SCHEMA_VERSION, "engine": engine_fingerprint(),
                            "created_at": datetime.now(timezone.utc).isoformat(), "source_root": str(root),
                            "files": hashes, "directories": directories, "links": links, "databases": databases,
                            "scope": "Full private instance; excludes replaceable root cache, kernel locks and SQLite sidecars"}
                        encoded = json.dumps(manifest, sort_keys=True, indent=2).encode()
                        if len(encoded) > MAX_MANIFEST:
                            raise ValueError("Backup manifest exceeds the limit")
                        archive.writestr("backup-manifest.json", encoded)
                    handle.flush(); os.fsync(handle.fileno())
                # Validate the serialized archive, not just the source inventory.
                with zipfile.ZipFile(temporary) as archive:
                    checked_manifest(archive)
                    for name, metadata in hashes.items():
                        with archive.open("instance/" + name) as stream:
                            if hashlib.file_digest(stream, "sha256").hexdigest() != metadata["sha256"]:
                                raise ValueError("Serialized backup checksum differs")
                os.link(temporary, output)
                temporary.unlink()
        return {"status": "backup_created", "files": len(hashes), "sha256": file_hash(output),
                "bytes": output.stat().st_size, "encrypted": False}
    finally:
        temporary.unlink(missing_ok=True)


def checked_manifest(archive):
    try:
        return _checked_manifest(archive)
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError, UnicodeError, zipfile.BadZipFile) as exc:
        raise ValueError("Invalid backup manifest or archive") from exc


def _checked_manifest(archive):
    items = archive.infolist()
    if len(items) > MAX_FILES + 1 or sum(i.file_size for i in items if i.filename != "backup-manifest.json") > MAX_TOTAL:
        raise ValueError("Backup archive exceeds the size/count limits")
    names = set()
    for item in items:
        name = safe_name(item.filename)
        mode = item.external_attr >> 16
        if (name.casefold() in names or item.is_dir() or item.flag_bits & 1 or item.file_size > MAX_FILE
                or stat.S_IFMT(mode) not in {0, stat.S_IFREG} or item.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}):
            raise ValueError("Unsupported or duplicate backup member")
        names.add(name.casefold())
    info = archive.getinfo("backup-manifest.json")
    if info.file_size > MAX_MANIFEST:
        raise ValueError("Backup manifest exceeds the limit")
    def unique_object(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("Duplicate backup manifest key")
            result[key] = item
        return result
    value = json.loads(archive.read(info), object_pairs_hook=unique_object)
    if (value.get("format") != "wealth-ledger-private-instance" or type(value.get("version")) is not int
            or value["version"] != VERSION or value.get("web_schema") != SCHEMA_VERSION
            or value.get("engine") != engine_fingerprint()):
        raise ValueError("Backup format/schema/code differs; restore with its matching application version")
    files = value["files"]
    expected = {"backup-manifest.json"} | {"instance/" + safe_name(name) for name in files}
    if {i.filename for i in items} != expected:
        raise ValueError("Backup member scope differs from its manifest")
    for name, metadata in files.items():
        if PurePosixPath(name).parts[0] not in ROOTS or not isinstance(metadata, dict):
            raise ValueError("Invalid backup scope")
        if (type(metadata.get("bytes")) is not int or not 0 <= metadata["bytes"] <= MAX_FILE
                or not isinstance(metadata.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", metadata["sha256"])
                or archive.getinfo("instance/"+name).file_size != metadata["bytes"]):
            raise ValueError("Invalid backup file metadata")
    for name in value["directories"]:
        if PurePosixPath(safe_name(name)).parts[0] not in ROOTS or name in files:
            raise ValueError("Invalid backup directory")
    for name, target in value["links"].items():
        parts = PurePosixPath(safe_name(name)).parts
        if len(parts)!=4 or parts[0]!="portfolios" or not ID.fullmatch(parts[1]) or parts[2:]!=("reports","latest"):
            raise ValueError("Unexpected backup link")
        safe_name(target)
        if name in files or name in value["directories"]:
            raise ValueError("Overlapping backup entries")
    entries = [*files, *value["directories"], *value["links"]]
    if len(entries) > MAX_FILES or len(entries) != len({name.casefold() for name in entries}):
        raise ValueError("Overlapping or case-ambiguous backup paths")
    for name in entries:
        if transient(name):
            raise ValueError("Runtime locks and SQLite sidecars cannot be restored")
        if any(str(parent) not in value["directories"] or str(parent) in files or str(parent) in value["links"] for parent in PurePosixPath(name).parents if str(parent)!="."):
            raise ValueError("Backup file/directory prefixes overlap")
    if not Path(value["source_root"]).is_absolute() or set(value["databases"]) != {name for name in files if active_database(name)}:
        raise ValueError("Invalid backup instance metadata")
    return value


def restore_instance(settings, archive_path, *, incoming=False):
    """Validate into a private staging directory; publish the instance marker last."""
    root = settings.data_root
    allowed = {Path(archive_path)} if incoming and Path(archive_path).parent == root else set()
    if root.is_symlink() or (root.exists() and (not root.is_dir() or any(p not in allowed for p in root.iterdir()))):
        raise ValueError("Restore requires a new empty dedicated data directory")
    archive_path = Path(archive_path)
    if archive_path.is_symlink() or not archive_path.is_file() or archive_path.stat().st_size > MAX_TOTAL + MAX_MANIFEST:
        raise ValueError("Invalid or oversized backup archive")
    root.mkdir(parents=True, exist_ok=True, mode=0o700); root.chmod(0o700)
    stage = Path(tempfile.mkdtemp(prefix=".restore-", dir=root))
    installed = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            manifest = checked_manifest(archive)
            restored = stage / "instance"; restored.mkdir(mode=0o700)
            for name in manifest["directories"]:
                contained(restored, name).mkdir(parents=True, exist_ok=True, mode=0o700)
            for name, metadata in manifest["files"].items():
                target = contained(restored, name)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with archive.open("instance/" + name) as source, target.open("xb") as destination:
                    target.chmod(0o600)
                    size = 0; digest = hashlib.sha256()
                    while chunk := source.read(1024 * 1024):
                        size += len(chunk)
                        if size > metadata["bytes"]:
                            raise ValueError("Expanded file exceeds declared size")
                        digest.update(chunk); destination.write(chunk)
                if size != metadata["bytes"] or digest.hexdigest() != metadata["sha256"]:
                    raise ValueError("Backup checksum differs")
            for name, expected in manifest["databases"].items():
                if database_info(contained(restored, name)) != expected:
                    raise ValueError("Restored database logical values differ")
            validate_instance(restored)
            for name, target in manifest["links"].items():
                link = contained(restored, name)
                if not (link.parent / target).is_dir():
                    raise ValueError("Restored latest report target is missing")
                link.symlink_to(target, target_is_directory=True)
            # Restore affects only auth/recovery metadata, never financial DBs/files.
            with closing(sqlite3.connect(restored / "admin/app.sqlite3")) as conn, conn:
                conn.execute("DELETE FROM sessions")
                conn.execute("DELETE FROM throttle")
                conn.execute("UPDATE jobs SET status='interrupted',error_code='restore_preview_expired' WHERE kind IN ('preview','record_preview','source_plan','source_preview') AND status IN ('queued','running','ready')")
                conn.execute("UPDATE jobs SET status='needs_review',error_code='restore_source_confirmation_expired' WHERE kind='source_commit' AND status IN ('queued','running')")
                conn.execute("UPDATE jobs SET enqueued_at=NULL WHERE status='queued'")
            old_receipt = restored / "admin/restore.json"
            if old_receipt.exists() and old_receipt.stat().st_size > 65536:
                raise ValueError("Restored runtime mapping exceeds its limit")
            previous = json.loads(old_receipt.read_text()).get("source_roots", []) if old_receipt.exists() else []
            roots = list(dict.fromkeys([manifest["source_root"], *previous]))
            if any(not isinstance(p, str) or not Path(p).is_absolute() for p in roots) or len(roots)>100:
                raise ValueError("Invalid restored runtime mappings")
            private_write(old_receipt, json.dumps({"version":1, "source_roots":roots,
                "restored_at":datetime.now(timezone.utc).isoformat(), "backup_sha256":file_hash(archive_path),
                "sessions_revoked":True, "previews_expired":True}).encode())
            (restored / "cache").mkdir(exist_ok=True, mode=0o700)
            validate_instance(restored)
            # Financial files and frozen reports remain byte-identical to manifest.
            for name, metadata in manifest["files"].items():
                if name.startswith("portfolios/") and file_hash(contained(restored,name)) != metadata["sha256"]:
                    raise ValueError("Restoration changed financial evidence")
            marker = restored / "admin/instance.json"
            marker_bytes = marker.read_bytes(); marker.unlink()
            for child in sorted(restored.iterdir()):
                os.replace(child, root / child.name); installed.append(root / child.name)
            private_write(root / "admin/instance.json", marker_bytes)
        return {"status":"restored", "files":len(manifest["files"]), "sessions_revoked":True,
                "financial_values_verified":True, "jobs":"Reconcile durable job states on the next worker start"}
    except BaseException:
        for path in reversed(installed):
            shutil.rmtree(path) if path.is_dir() else path.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def restored_report_path(store, portfolio_id, target):
    """Map old runtime outputs without rewriting historical financial operation rows."""
    _, project = store.portfolio(portfolio_id)
    target = Path(target)
    if target.is_relative_to(project / "reports"):
        return target
    adoption = contained(store.root, "admin/adoptions/" + portfolio_id + ".json")
    if adoption.is_file():
        old = Path(json.loads(adoption.read_text())["source_root"]) / "reports"
        if target.is_relative_to(old):
            return project / "reports" / target.relative_to(old)
    receipt = contained(store.root, "admin/restore.json")
    if receipt.exists():
        for source in json.loads(receipt.read_text()).get("source_roots", []):
            old = Path(source) / "portfolios" / portfolio_id / "reports"
            if target.is_relative_to(old):
                return project / "reports" / target.relative_to(old)
    raise ValueError("Published operation output is outside its portfolio")
