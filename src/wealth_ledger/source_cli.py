"""Preview or revalidate trusted parser evidence without importing a financial ledger."""
import argparse
import json
from pathlib import Path


def main():
    from wealth_ledger.source_pipeline import PLAN_BYTES, SourcePlanError, _json, bounded_read, plan_sources
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--config", required=True, type=Path, help="Trusted host JSON, never an uploaded plugin")
    parser.add_argument("--select", action="append", default=[], help="Explicit 1-based input slot=enabled-adapter-id")
    parser.add_argument("--verify", type=Path, help="Revalidate a saved JSON plan; reject any changed evidence/environment")
    parser.add_argument("--timeout", type=float, default=60, help="Child wall-clock limit in seconds, at most 60")
    args = parser.parse_args()
    try:
        if not args.config.is_file():
            raise SourcePlanError("invalid_configuration")
        choices = {}
        for value in args.select:
            slot, adapter = value.split("=", 1)
            if slot in choices:
                raise SourcePlanError("invalid_inputs")
            choices[slot] = adapter
        previous = _json(bounded_read(args.verify, PLAN_BYTES)) if args.verify else None
        result = plan_sources(args.files, config_path=args.config, selections=choices,
                              previous=previous, timeout=args.timeout)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (SourcePlanError, ValueError, OSError, RecursionError) as exc:
        print(json.dumps({"error": exc.code if isinstance(exc, SourcePlanError) else "invalid_request", "ingestible": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
