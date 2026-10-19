"""Opt-in frozen source report preview, explicit confirmation and report-only retry."""
import argparse
import json
from pathlib import Path


def main():
    from .source_context_pipeline import CONTEXT_BYTES, contexts_from_document
    from .source_pipeline import bounded_read, _json
    from .source_publication import prepare_source_report, load_source_report, confirm_source_report, resume_source_report, _summary
    from .source_submission import parse_bindings
    from .operations import ReportOperationError
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest="command",required=True)
    preview=commands.add_parser("preview")
    preview.add_argument("files",nargs="*",type=Path)
    preview.add_argument("--context",type=Path)
    preview.add_argument("--bindings",type=Path)
    preview.add_argument("--valuation",type=Path,required=True)
    preview.add_argument("--config",type=Path)
    preview.add_argument("--plan-directory",type=Path,required=True)
    preview.add_argument("--select",action="append",default=[])
    preview.add_argument("--timeout",type=float,default=60)
    confirm=commands.add_parser("confirm")
    confirm.add_argument("--plan-directory",type=Path,required=True)
    confirm.add_argument("--approval-sha256",required=True)
    confirm.add_argument("--config",type=Path)
    inspect=commands.add_parser("inspect")
    inspect.add_argument("--plan-directory",type=Path,required=True)
    inspect.add_argument("--approval-sha256",required=True)
    resume=commands.add_parser("resume")
    resume.add_argument("--operation-id",required=True)
    for child in (preview,confirm,inspect,resume):child.add_argument("--workspace",type=Path,required=True)
    args=parser.parse_args()
    operation_id=getattr(args,"operation_id",None)
    try:
        if args.command=="preview":
            if bool(args.files)!=bool(args.context):raise ValueError("CSV inputs require matching explicit contexts")
            contexts=contexts_from_document(_json(bounded_read(args.context,CONTEXT_BYTES)),len(args.files)) if args.files else ()
            bindings=parse_bindings(_json(bounded_read(args.bindings,CONTEXT_BYTES))) if args.bindings else ()
            selections={}
            for entry in args.select:
                slot,adapter=entry.split("=",1)
                if slot in selections:raise ValueError("Duplicate parser selection")
                selections[slot]=adapter
            value=prepare_source_report(args.workspace,args.files,valuation=_json(bounded_read(args.valuation,CONTEXT_BYTES)),
                directory=args.plan_directory,contexts=contexts,bindings=bindings,config_path=args.config,selections=selections,timeout=args.timeout)
        elif args.command=="confirm":
            operation_id=load_source_report(args.workspace,args.plan_directory,args.approval_sha256)[0]["operation_id"]
            value=confirm_source_report(args.workspace,args.plan_directory,args.approval_sha256,config_path=args.config)
        elif args.command=="inspect":
            value={**_summary(load_source_report(args.workspace,args.plan_directory,args.approval_sha256)[0]),"freshness":"not_revalidated"}
        else:value=resume_source_report(args.workspace,args.operation_id)
        print(json.dumps(value,indent=2,sort_keys=True));return 0
    except (ValueError,OSError,RecursionError) as exc:
        value={"error":getattr(exc,"code","source_report_rejected"),"report_published":False}
        if isinstance(exc,ReportOperationError):
            value.update(error="source_report_failed",data_committed=True,retry="Resume the returned operation ID; do not reimport")
            value["operation_id"]=operation_id
        print(json.dumps(value));return 2


if __name__=="__main__":raise SystemExit(main())
