"""Bounded, text-only reading of an edition's verified, already published report.

Markdown and PDF originate in the same Python presentation model. Reading the
saved Markdown preserves historical wording instead of rerunning today's model.
Only the small grammar emitted by that model is interpreted; HTML and links are
never executed. Chart references resolve through the same report's registry.
"""
from contextlib import closing
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Literal

from pydantic import Field

from .reports import Artifact, Locale, ReportSummary, ViewModel
from .storage import WebError

MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_CELLS = 200_000
MAX_BLOCKS = 4096
MAX_SECTIONS = 128
MAX_COLUMNS = 512
IMAGE = re.compile(r"!\[(.*)\]\(charts/([A-Za-z0-9_-]+\.png)\)")

def separator(line):
    parts = line.strip().strip("|").split("|")
    return len(parts) <= MAX_COLUMNS and all(re.fullmatch(r":?-{3,}:?", value.strip()) for value in parts)

class DocumentBlock(ViewModel):
    kind: Literal["paragraph", "subheading", "table", "chart"]
    text: str = ""
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    artifact_id: str | None = None
    filename: str | None = None


class DocumentSection(ViewModel):
    id: str
    title: str
    blocks: list[DocumentBlock]


class ReportDocument(ViewModel):
    schema_version: Literal[1] = 1
    report: ReportSummary
    basis: Literal["saved_markdown"] = "saved_markdown"
    locale: Locale | None
    source: Artifact
    title: str
    sections: list[DocumentSection]


def edition_metadata(data, payload_path):
    """Financial scope is distinct from a date, filename or report revision."""
    meta = data["meta"]
    scope = meta.get("scope_id")
    if not scope:
        accounts = sorted(str(row["account_id"]) for row in data.get("accounts", []))
        scope = json.dumps({"model": meta.get("report_model", "native"), "accounts": accounts}, sort_keys=True) if accounts else None
    locale = meta.get("report_locale") or data.get("reporting", {}).get("locale") or data.get("localization", {}).get("locale")
    parent = PurePosixPath(payload_path).parent.name
    return {"scope_key": hashlib.sha256(scope.encode()).hexdigest() if isinstance(scope, str) else None,
            "scope_labels": sorted({str(row.get("account_type", row.get("label", ""))) for row in data.get("accounts", [])}),
            "report_locale": locale if locale in ("en-CA", "zh-TW", "zh-CN") else None,
            "edition_label": parent if re.fullmatch(r"r\d{1,6}", parent) else None}


def cells(line):
    return [value.strip().replace(r"\|", "|").replace("<br>", "\n")
            for value in re.split(r"(?<!\\)\|", line.strip()[1:-1])]


def parse_document(text, chart_ids):
    """Return escaped-by-consumer text blocks, never arbitrary HTML or URLs."""
    sections, title = [], ""
    count = cell_count = 0
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        index += 1
        if not line:
            continue
        if line.startswith("# ") and not sections:
            title = line[2:]
            continue
        if line.startswith("## "):
            sections.append({"id": f"section-{len(sections)+1}", "title": line[3:], "blocks": []})
            if len(sections) > MAX_SECTIONS:
                raise ValueError("Too many report sections")
            continue
        # The report header's cutoff is already exposed in the evidence rail.
        if not sections:
            continue
        image = IMAGE.fullmatch(line)
        if image:
            alt, filename = image.groups()
            block = {"kind": "chart", "text": alt, "filename": filename, "artifact_id": chart_ids.get(filename)}
        elif line.startswith("### "):
            block = {"kind": "subheading", "text": line[4:]}
        elif line.startswith("|") and line.endswith("|") and index < len(lines) and separator(lines[index]):
            headers, rows = cells(line), []
            index += 1
            if len(headers) > MAX_COLUMNS:
                raise ValueError("Too many report columns")
            while index < len(lines) and lines[index].strip().startswith("|") and lines[index].strip().endswith("|"):
                row = cells(lines[index])
                if len(row) != len(headers):
                    raise ValueError("Report table shape differs")
                rows.append(row)
                if cell_count + len(headers)*(len(rows)+1) > MAX_CELLS:
                    raise ValueError("Too many report cells")
                index += 1
            cell_count += len(headers)*(len(rows)+1)
            block = {"kind": "table", "headers": headers, "rows": rows}
        else:
            block = {"kind": "paragraph", "text": line}
        count += 1
        if count > MAX_BLOCKS or cell_count > MAX_CELLS:
            raise ValueError("Report document exceeds reading limits")
        sections[-1]["blocks"].append(block)
    if not sections:
        raise ValueError("Report sections are missing")
    return title, sections


def read_document(publications, portfolio_id, report_id, owner_id=1):
    row = publications.row(portfolio_id, report_id, owner_id)
    summary = publications.summary(row)
    candidates = [item for item in summary["artifacts"] if item["filename"] == "report.md"]
    if len(candidates) != 1:
        raise WebError(409, "report_document_unavailable", "This edition has no unique saved Markdown report")
    source = candidates[0]
    if source["byte_size"] > MAX_DOCUMENT_BYTES:
        raise WebError(409, "report_document_unavailable", "Saved report exceeds browser reading limits")
    raw, _, _ = publications.store.read_artifact(portfolio_id, source["id"], owner_id)
    with closing(publications.store.connect()) as conn:
        files = conn.execute("SELECT id,relative_path,media_type FROM artifacts WHERE portfolio_id=? AND report_id=?",
                             (portfolio_id, report_id)).fetchall()
    base = PurePosixPath(next(item["relative_path"] for item in files if item["id"] == source["id"])).parent
    charts = {PurePosixPath(item["relative_path"]).name: item["id"] for item in files
              if PurePosixPath(item["relative_path"]).parent == base/"charts"
              and item["media_type"] == "image/png"}
    try:
        title, sections = parse_document(raw.decode("utf-8"), charts)
        return ReportDocument.model_validate({"report": summary, "locale": summary.get("report_locale"),
            "source": source, "title": title, "sections": sections}).model_dump()
    except (ValueError, UnicodeError, TypeError) as exc:
        raise WebError(409, "report_document_unavailable", "Saved report needs local document review") from exc
