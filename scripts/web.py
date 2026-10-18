#!/usr/bin/env python3
"""Trusted host commands for the optional Web API; never claim an owner over HTTP."""
import argparse
from contextlib import nullcontext
import getpass
import json
import os
from pathlib import Path
import sys
import sqlite3
import zipfile
import uuid

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, help="Dedicated absolute Web instance directory; or WEALTH_LEDGER_DATA_ROOT")
    parser.add_argument("--public-origin", help="Exact browser origin; default http://localhost:8000")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("init-owner", help="Initialize a dedicated instance and its sole owner offline")
    create.add_argument("--username", default="owner")
    reset = commands.add_parser("reset-password", help="Replace the owner password and revoke every session")
    for command in (create, reset):
        command.add_argument("--password-stdin", action="store_true", help="Read one password line from private stdin for automation; never pass passwords in argv/env")
    commands.add_parser("upgrade", help="Back up and upgrade only Web metadata while services are stopped")
    backup = commands.add_parser("backup", help="Create a full private consistent instance ZIP")
    destination = backup.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output", type=Path, help="New private archive outside the instance")
    destination.add_argument("--stdout", action="store_true", help="Write binary ZIP to stdout; use a private file and -T in Docker")
    backup.add_argument("--timeout", type=float, default=30, help="Maximum seconds to drain active work (0-300)")
    restore = commands.add_parser("restore", help="Verify and restore into a new empty instance; revoke sessions")
    source = restore.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive", type=Path)
    source.add_argument("--stdin", action="store_true", help="Read a bounded private ZIP from stdin")
    commands.add_parser("maintenance-clear", help="Clear an interrupted backup barrier only when no coordinator or active work holds it")
    worker = commands.add_parser("worker", help="Run the single durable job consumer with isolated execution")
    worker.add_argument("--once", action="store_true", help="Reconcile and drain currently queued work, then exit")
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        from wealth_ledger.web.config import WebSettings
        from wealth_ledger.web.storage import WebError
        root = args.data_root or os.environ.get("WEALTH_LEDGER_DATA_ROOT")
        if not root:
            raise ValueError("Specify --data-root or WEALTH_LEDGER_DATA_ROOT; no personal-ledger default")
        settings = WebSettings(Path(root), args.public_origin or os.environ.get("WEALTH_LEDGER_PUBLIC_ORIGIN", "http://localhost:8000"))
        if args.command == "backup":
            from wealth_ledger.web.backups import backup_instance
            if args.stdout:
                import shutil
                target = settings.data_root / "cache" / ("backup-" + uuid.uuid4().hex + ".zip")
                try:
                    result = backup_instance(settings, target, timeout=args.timeout, internal=True)
                    with target.open("rb") as stream:
                        shutil.copyfileobj(stream, sys.stdout.buffer)
                    sys.stdout.buffer.flush()
                    print(json.dumps(result), file=sys.stderr)
                finally:
                    target.unlink(missing_ok=True)
            else:
                print(json.dumps(backup_instance(settings, args.output, timeout=args.timeout)))
        elif args.command == "restore":
            from wealth_ledger.web.backups import restore_instance, MAX_TOTAL, MAX_MANIFEST
            if args.stdin:
                root = settings.data_root
                if root.exists() and any(root.iterdir()):
                    raise ValueError("Restore requires a new empty dedicated data directory")
                root.mkdir(parents=True, exist_ok=True, mode=0o700)
                target = root / (".incoming-" + uuid.uuid4().hex)
                try:
                    size = 0
                    with target.open("xb") as stream:
                        target.chmod(0o600)
                        while chunk := sys.stdin.buffer.read(1024 * 1024):
                            size += len(chunk)
                            if size > MAX_TOTAL + MAX_MANIFEST:
                                raise ValueError("Backup archive exceeds the limit")
                            stream.write(chunk)
                    print(json.dumps(restore_instance(settings, target, incoming=True)))
                finally:
                    target.unlink(missing_ok=True)
            else:
                print(json.dumps(restore_instance(settings, args.archive)))
        elif args.command == "maintenance-clear":
            from wealth_ledger.web.maintenance import clear_maintenance
            from wealth_ledger.web.storage import Store
            Store(settings)
            clear_maintenance(settings.data_root)
            print(json.dumps({"status":"maintenance_cleared"}))
        elif args.command == "upgrade":
            from wealth_ledger.web.storage import prepare_instance
            from wealth_ledger.web.maintenance import instance_activity
            with instance_activity(settings.data_root):
                prepare_instance(settings)
            print(json.dumps({"status": "metadata_ready"}))
        elif args.command == "worker":
            from wealth_ledger.web.worker import run_worker
            run_worker(settings, once=args.once)
        elif args.command == "serve":
            import uvicorn
            from wealth_ledger.web.api import create_app
            uvicorn.run(create_app(settings), host=args.host, port=args.port, proxy_headers=False,
                        access_log=False, server_header=False, workers=1)
        else:
            from wealth_ledger.web.auth import password_hash, valid_username
            from wealth_ledger.web.storage import prepare_instance, Store
            if args.command == "init-owner" and not valid_username(args.username):
                raise ValueError("Username must be 1-64 ASCII letters, numbers, dots, hyphens or underscores")
            if args.password_stdin:
                supplied = sys.stdin.readline(2049)
                if not supplied.endswith("\n"):
                    raise ValueError("Password stdin must contain one bounded newline-terminated line")
                supplied = supplied[:-1].removesuffix("\r")
            else:
                supplied = getpass.getpass("New owner password: ")
                if supplied != getpass.getpass("Confirm password: "):
                    raise ValueError("Passwords do not match")
            hashed = password_hash(supplied)
            del supplied
            from wealth_ledger.web.maintenance import instance_activity
            existing = (settings.data_root / "admin/instance.json").is_file()
            with instance_activity(settings.data_root) if existing else nullcontext():
                if args.command == "init-owner":
                    prepare_instance(settings)
                store = Store(settings)
                store.set_owner(getattr(args, "username", None), hashed, reset=args.command == "reset-password")
            print(json.dumps({"status": "owner_initialized" if args.command == "init-owner" else "password_reset", "sessions_revoked": args.command == "reset-password"}))
    except ImportError:
        parser.error("Install optional Web dependencies from requirements-web.lock")
    except WebError:
        parser.error("Instance storage validation failed; review the trusted host paths and evidence")
    except (ValueError, OSError, sqlite3.DatabaseError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
