"""Owner-scoped exports of frozen publications, never live ledger recalculation."""
from contextlib import closing
import csv
from datetime import date, datetime
import io
import json
from pathlib import PurePosixPath
import re
import tempfile
from typing import Literal
import zipfile
from zoneinfo import ZoneInfo

from fastapi import Depends
from starlette.responses import Response, StreamingResponse

from .reports import Publications
from .storage import WebError, contained

MAX_BUNDLE = 256 * 1024 * 1024
NUMERIC = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")


def csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, allow_nan=False)
    text = str(value)
    if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")) and not NUMERIC.fullmatch(text):
        return "'" + text
    return text


def export_data(store, portfolio, report, dataset, *, start=None, end=None, owner_id=1):
    if start and end and start > end:
        raise WebError(422, "invalid_export_range", "Export start must not follow end")
    if (start or end) and dataset not in {"history", "cash_flows", "btc_monthly"}:
        raise WebError(422, "invalid_export_range", "Date ranges apply only to dated datasets")
    data = Publications(store).view(portfolio, report, "en-CA", owner_id)
    rows = data.get("btc", {}).get("monthly", []) if dataset == "btc_monthly" and data.get("btc") else data.get(dataset, [])
    if start or end:
        key = {"history":"as_of", "cash_flows":"date", "btc_monthly":"month"}[dataset]
        length = 7 if dataset == "btc_monthly" else 10
        lower = start.isoformat()[:length] if start else None
        upper = end.isoformat()[:length] if end else None
        def observed_day(row):
            value = row.get(key)
            if value and key == "as_of":
                try:
                    stamp = datetime.fromisoformat(value)
                    if stamp.utcoffset() is None:
                        raise ValueError("Observation offset is missing")
                    value = stamp.astimezone(ZoneInfo("America/Toronto")).date().isoformat()
                except ValueError as exc:
                    raise WebError(409,"report_integrity","Observation timestamp needs local review") from exc
            return value[:length] if value else None
        rows = [row for row in rows if (day := observed_day(row)) is not None
                and (lower is None or day >= lower) and (upper is None or day <= upper)]
    return {"schema_version":1, "report_id":report, "valuation_as_of":data["as_of"],
            "dataset":dataset, "scope":"Selected frozen report; not all ledger revisions or a backup",
            "data_status":data["data_status"], "is_complete":data["is_complete"],
            "start":start.isoformat() if start else None, "end":end.isoformat() if end else None,
            "range_semantics":"inclusive months" if dataset=="btc_monthly" else "inclusive observation dates in report timezone",
            "rows":rows}


def report_zip(store, portfolio, report, owner_id=1):
    publications = Publications(store)
    row = publications.row(portfolio, report, owner_id)
    with closing(store.connect()) as conn:
        artifacts = [dict(r) for r in conn.execute(
            "SELECT * FROM artifacts WHERE portfolio_id=? AND report_id=? ORDER BY relative_path", (portfolio,report))]
    payload = [r for r in artifacts if PurePosixPath(r["relative_path"]).name=="data.json"]
    if len(payload)!=1 or not payload[0]["relative_path"].startswith("reports/"):
        raise WebError(409, "report_integrity", "Report bundle needs local review")
    directory = PurePosixPath(payload[0]["relative_path"]).parent
    expected = {}
    for artifact in artifacts:
        path = PurePosixPath(artifact["relative_path"])
        if not path.is_relative_to(directory):
            raise WebError(409, "report_integrity", "Report bundle scope differs")
        name = path.relative_to(directory).as_posix()
        if name in expected or name in {".",".."}:
            raise WebError(409, "report_integrity", "Report bundle scope differs")
        expected[name]=artifact
    if not {"data.json","report.md","report.pdf","portfolio.ods","manifest.json"}.issubset(expected):
        raise WebError(409, "report_integrity", "Report bundle is incomplete")
    if len(expected)>2000 or sum(a["byte_size"] for a in artifacts)>MAX_BUNDLE:
        raise WebError(413, "export_too_large", "Report bundle exceeds export limits")
    handle = tempfile.TemporaryFile(mode="w+b", dir=contained(store.root, "cache"))
    try:
        with zipfile.ZipFile(handle,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for name, artifact in expected.items():
                raw,_,_=store.read_artifact(portfolio,artifact["id"],owner_id)
                if name=="manifest.json":
                    manifest=json.loads(raw)
                    files=manifest.get("bundle_files",{})
                    if set(files)!=set(expected)-{"manifest.json"} or any(files[p]!=expected[p]["sha256"] for p in files):
                        raise WebError(409,"report_integrity","Registered bundle differs from its frozen manifest")
                    if manifest.get("import",{}).get("operation_id")!=row["core_operation_id"]:
                        raise WebError(409,"report_integrity","Report operation linkage differs")
                archive.writestr(name,raw)
        handle.seek(0)
        return handle
    except (ValueError, TypeError, KeyError) as exc:
        handle.close()
        raise WebError(409,"report_integrity","Frozen bundle manifest needs local review") from exc
    except BaseException:
        handle.close()
        raise


def stream_file(handle):
    try:
        while chunk := handle.read(1024 * 1024):
            yield chunk
    finally:
        handle.close()


def install_export_routes(app, store, require_owner):
    @app.get("/api/v1/portfolios/{portfolio_id}/reports/{report_id}/bundle.zip",
             response_class=StreamingResponse, responses={200:{"content":{"application/zip":{}}}})
    def bundle(portfolio_id: str, report_id: str, owner=Depends(require_owner)):
        handle=report_zip(store,portfolio_id,report_id,owner["owner_id"])
        return StreamingResponse(stream_file(handle),media_type="application/zip",
            headers={"Content-Disposition":f'attachment; filename="report-{report_id}.zip"'})

    @app.get("/api/v1/portfolios/{portfolio_id}/reports/{report_id}/export",response_class=Response,
             responses={200:{"content":{"application/json":{},"text/csv":{}}}})
    def export(portfolio_id: str, report_id: str,
               dataset: Literal["holdings","accounts","history","cash_flows","btc_monthly"],
               format: Literal["csv","json"]="csv", start: date|None=None, end: date|None=None,
               owner=Depends(require_owner)):
        value=export_data(store,portfolio_id,report_id,dataset,start=start,end=end,owner_id=owner["owner_id"])
        if format=="json":
            raw=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
            media="application/json"
        else:
            output=io.StringIO(newline="")
            context={k:v for k,v in value.items() if k!="rows"}
            keys=sorted({k for row in value["rows"] for k in row})
            writer=csv.DictWriter(output,fieldnames=[*context,*keys]); writer.writeheader()
            for row in value["rows"]:
                writer.writerow({k:csv_cell(v) for k,v in {**context,**row}.items()})
            raw=output.getvalue().encode("utf-8-sig"); media="text/csv; charset=utf-8"
        if len(raw)>MAX_BUNDLE:
            raise WebError(413,"export_too_large","Export exceeds the documented size limit")
        return Response(raw,media_type=media,headers={"Content-Disposition":f'attachment; filename="{dataset}-{report_id}.{format}"'})
