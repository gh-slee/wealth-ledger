"""Shared CLI contract for balances and economic events."""
from .cli import make_parser
from .i18n import presentation_context, legacy_text
import json
import shlex
from pathlib import Path

from . import wallet
from .prices import parse_time


def run(project, kind):
    parser = make_parser(project, description="Append/revise BTC-equivalent records; never invent a cause or publish a report")
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list")
    if kind == "event":
        listing.add_argument("--balance-id")
    show = sub.add_parser("show"); show.add_argument("record_id")
    add = sub.add_parser("add")
    add.add_argument("--quantity-btc", required=True)
    add.add_argument("--source", required=kind == "event", default="user_reported_total" if kind == "balance" else None)
    if kind == "balance":
        add.add_argument("--as-of", required=True)
        add.add_argument("--replaces-balance-id")
    else:
        add.add_argument("--type", choices=tuple(wallet.SIGNS), required=True)
        add.add_argument("--occurred-at", required=True)
        add.add_argument("--reference", required=True)
        add.add_argument("--balance-id")
        add.add_argument("--replaces-event-id")
        batch = sub.add_parser("import"); batch.add_argument("file", type=Path)
    edit = sub.add_parser("revise")
    edit.add_argument("--quantity-btc")
    if kind == "balance":
        edit.add_argument("--source")
    else:
        edit.add_argument("--type", choices=tuple(wallet.SIGNS))
        edit.add_argument("--occurred-at")
    mutation = [edit, sub.add_parser("void")]
    if kind == "event":
        link = sub.add_parser("link"); link.add_argument("--balance-id", required=True)
        mutation.extend([link, sub.add_parser("unlink")])
    for command in mutation:
        command.add_argument("record_id")
        command.add_argument("--expected-revision", type=int, required=True)
        command.add_argument("--reason", required=True)
    args = parser.parse_args()
    from .application import ApplicationService
    project = parser.workspace.workspace_root
    service = ApplicationService(parser.workspace)
    try:
        if args.command == "list":
            result = wallet.records(project, kind)
            if kind == "event" and args.balance_id:
                wallet.balance_detail(project, args.balance_id)
                result = [r for r in result if r.get("balance_id") == args.balance_id]
        elif args.command == "show":
            row = wallet.get_record(project, args.record_id)
            if row["kind"] != kind:
                raise ValueError("Record ID has the wrong kind for this command")
            result = wallet.balance_detail(project, args.record_id) if kind == "balance" else {
                "record": row, "revisions": wallet.revision_history(project, args.record_id)}
        else:
            def action(stage):
                if args.command == "add":
                    if kind == "balance":
                        return wallet.add_balance(stage, args.quantity_btc, args.as_of, source=args.source,
                                                  replaces=args.replaces_balance_id)
                    return wallet.add_event(stage, type=args.type, quantity_btc=args.quantity_btc,
                        occurred_at=args.occurred_at, source=args.source, reference=args.reference,
                        balance_id=args.balance_id, replaces=args.replaces_event_id)
                if args.command == "import":
                    return wallet.import_events(stage, args.file)
                row = wallet.get_record(stage, args.record_id)
                if row["kind"] != kind:
                    raise ValueError("Record ID has the wrong kind for this command")
                changes = {key: getattr(args, key) for key in ("quantity_btc", "type", "occurred_at", "source")
                           if getattr(args, key, None) is not None}
                if args.command in ("link", "unlink"):
                    changes = {"balance_id": args.balance_id if args.command == "link" else None}
                return wallet.revise(stage, args.record_id, expected_revision=args.expected_revision,
                                     reason=args.reason, action=args.command, **changes)
            result = service.record(vars(args), action, label="before-btc-" + kind)
            if kind == "balance" and result.get("record_id"):
                result["reconciliation"] = wallet.balance_detail(project, result["record_id"])["reconciliation"]
            pointer = Path(project)/"reports/latest.json"
            from .wallet_basis import has_canonical_sources
            if pointer.exists() and not has_canonical_sources(project):
                target = json.loads(pointer.read_text(encoding="utf-8"))["path"]
                saved = json.loads((Path(project)/target/"data.json").read_text(encoding="utf-8"))["meta"]["as_of"]
                occurred = result.get("occurred_at") or result.get("as_of")
                if occurred and parse_time(occurred) > parse_time(saved):
                    with presentation_context(parser.locale):
                        result["report_note"] = legacy_text("目前報告時間早於此紀錄；裸 update.py 不會自動新增今日估值。")
                    result["suggested_command"] = shlex.join([
                        'scripts/update.py', '--workspace', str(project), '--valuation-as-of', occurred])
            result["report_published"] = False
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
