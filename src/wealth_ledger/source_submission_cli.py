"""Explicit canonical data-only preview/confirmation and receipt-only recovery."""
import argparse
import json
from pathlib import Path


def main():
    from .source_context_pipeline import CONTEXT_BYTES, contexts_from_document
    from .source_ingestion import IngestionError
    from .source_pipeline import SourcePlanError, _json, bounded_read
    from .source_submission import (SubmissionError, parse_bindings, prepare_submission,
        load_submission, submission_summary, confirm_submission, recover_submission)
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest="command",required=True)
    preview=commands.add_parser("preview")
    preview.add_argument("files",nargs="+",type=Path)
    preview.add_argument("--context",type=Path,required=True)
    preview.add_argument("--bindings",type=Path)
    preview.add_argument("--config",type=Path,required=True)
    preview.add_argument("--plan-directory",type=Path,required=True)
    preview.add_argument("--select",action="append",default=[])
    preview.add_argument("--timeout",type=float,default=60)
    confirm=commands.add_parser("confirm")
    confirm.add_argument("--plan-directory",type=Path,required=True)
    confirm.add_argument("--approval-sha256",required=True)
    confirm.add_argument("--config",type=Path,required=True)
    confirm.add_argument("--acknowledge-no-reports",action="store_true")
    inspect=commands.add_parser("inspect")
    inspect.add_argument("--plan-directory",type=Path,required=True)
    inspect.add_argument("--approval-sha256",required=True)
    recover=commands.add_parser("recover")
    recover.add_argument("--operation-id",required=True)
    recover.add_argument("--plan-sha256",required=True)
    for child in (preview,confirm,inspect,recover):child.add_argument("--workspace",type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.command=="preview":
            contexts=contexts_from_document(_json(bounded_read(args.context,CONTEXT_BYTES)),len(args.files))
            bindings=parse_bindings(_json(bounded_read(args.bindings,CONTEXT_BYTES))) if args.bindings else ()
            selections={}
            for choice in args.select:
                slot,adapter=choice.split("=",1)
                if slot in selections:raise SubmissionError("invalid_selection")
                selections[slot]=adapter
            value=prepare_submission(args.workspace,args.files,contexts=contexts,bindings=bindings,directory=args.plan_directory,
                config_path=args.config,selections=selections,timeout=args.timeout)
        elif args.command=="confirm":
            value=confirm_submission(args.workspace,args.plan_directory,args.approval_sha256,
                acknowledge_no_reports=args.acknowledge_no_reports,config_path=args.config)
        elif args.command=="inspect":
            value={**submission_summary(*load_submission(args.workspace,args.plan_directory,args.approval_sha256)),
                "status":"frozen_preview","freshness":"not_revalidated"}
        else:
            value=recover_submission(args.workspace,args.operation_id,args.plan_sha256)
            if value is None:raise SubmissionError("completion_not_proven")
        print(json.dumps(value,indent=2,sort_keys=True))
        return 0
    except (SubmissionError,SourcePlanError,IngestionError,ValueError,OSError,RecursionError) as exc:
        print(json.dumps({"error":exc.code if isinstance(exc,(SubmissionError,SourcePlanError,IngestionError)) else "submission_rejected","report_published":False}))
        return 2


if __name__=="__main__":raise SystemExit(main())
