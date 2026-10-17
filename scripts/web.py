#!/usr/bin/env python3
"""Trusted host commands for the optional Web API; never claim an owner over HTTP."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys

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
    worker = commands.add_parser("worker", help="Run the single durable job consumer with isolated execution")
    worker.add_argument("--once", action="store_true", help="Reconcile and drain currently queued work, then exit")
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        from wealth_ledger.web.config import WebSettings
        root = args.data_root or os.environ.get("WEALTH_LEDGER_DATA_ROOT")
        if not root:
            raise ValueError("Specify --data-root or WEALTH_LEDGER_DATA_ROOT; no personal-ledger default")
        settings = WebSettings(Path(root), args.public_origin or os.environ.get("WEALTH_LEDGER_PUBLIC_ORIGIN", "http://localhost:8000"))
        if args.command == "upgrade":
            from wealth_ledger.web.storage import prepare_instance
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
            if args.command == "init-owner":
                prepare_instance(settings)
            store = Store(settings)
            store.set_owner(getattr(args, "username", None), hashed, reset=args.command == "reset-password")
            print(json.dumps({"status": "owner_initialized" if args.command == "init-owner" else "password_reset", "sessions_revoked": args.command == "reset-password"}))
    except ImportError:
        parser.error("Install optional Web dependencies from requirements-web.lock")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
