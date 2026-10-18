"""Bounded original evidence storage; upload bytes never become executable tasks."""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import uuid

from .storage import ID, WebError, contained

CSV_BYTES = 10 * 1024 * 1024
REFERENCE_BYTES = 64 * 1024
BATCH_BYTES = 25 * 1024 * 1024
MAX_ROWS = 50000
KINDS = {"csv", "fx", "price", "opening", "cash_flows"}


def inspect_bytes(raw, kind):
    if kind not in KINDS or not raw or len(raw) > (CSV_BYTES if kind in {"csv", "cash_flows"} else REFERENCE_BYTES):
        raise WebError(422, "invalid_upload", "Upload size or kind is invalid")
    try:
        text = raw.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError("NUL is not text evidence")
        if kind not in {"csv", "cash_flows"}:
            value = json.loads(text)
            if not isinstance(value, dict):
                raise ValueError("Reference JSON must be an object")
            return None
        from ..core import REQUIRED as HOLDINGS
        from ..crypto import REQUIRED as ORDERS
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = [field.strip() for field in next(reader)]
        if len(header) > 256 or len(set(header)) != len(header):
            raise ValueError("Invalid CSV header")
        if kind == "cash_flows":
            if not {"date","account_id","flow_type","currency","amount"}.issubset(header):
                raise ValueError("Cash-flow CSV header is incomplete")
            count = 0
            for row in reader:
                count += 1
                if count > MAX_ROWS or len(row) > 256:
                    raise ValueError("CSV row/column limit exceeded")
            if count == 0: raise ValueError("Empty CSV")
            return "cash_flows"
        providers = [name for name, fields in (("wealthsimple", HOLDINGS), ("bullbitcoin", ORDERS))
                     if set(fields).issubset(header)]
        if len(providers) != 1:
            raise ValueError("Unknown or ambiguous format")
        count = 0
        for row in reader:
            count += 1
            if count > MAX_ROWS or len(row) > 256:
                raise ValueError("CSV row/column limit exceeded")
        if count == 0:
            raise ValueError("Empty CSV")
        return providers[0]
    except (UnicodeError, ValueError, csv.Error, StopIteration, RecursionError) as exc:
        raise WebError(422, "invalid_upload", "Unsupported, ambiguous or invalid evidence file") from exc


def upload_path(store, row):
    suffix = ".csv" if row["kind"] in {"csv", "cash_flows"} else ".json"
    return contained(store.root, "uploads/" + row["portfolio_id"] + "/" + row["id"] + suffix)


def get_upload(store, portfolio_id, upload_id, owner_id=1):
    store.portfolio(portfolio_id, owner_id)
    if not isinstance(upload_id, str) or not ID.fullmatch(upload_id):
        raise WebError(404, "not_found", "Upload not found")
    with store.transaction() as conn:
        row = conn.execute("SELECT * FROM uploads WHERE id=? AND portfolio_id=?", (upload_id, portfolio_id)).fetchone()
    if not row:
        raise WebError(404, "not_found", "Upload not found")
    return dict(row)


def verified_upload(store, row):
    path = upload_path(store, row)
    maximum = CSV_BYTES if row["kind"] in {"csv", "cash_flows"} else REFERENCE_BYTES
    if not path.is_file() or path.stat().st_size > maximum:
        raise WebError(409, "upload_integrity", "Upload integrity check failed")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) != row["byte_size"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
        raise WebError(409, "upload_integrity", "Upload integrity check failed")
    if inspect_bytes(raw, row["kind"]) != row["provider"]:
        raise WebError(409, "upload_integrity", "Upload provider changed")
    return path


async def receive_upload(store, portfolio_id, request, kind, filename, owner_id):
    store.portfolio(portfolio_id, owner_id)
    if (kind not in KINDS or not filename or len(filename) > 160 or
            any(ord(c) < 32 or ord(c) == 127 or c in "/\\" for c in filename)):
        raise WebError(422, "invalid_upload", "Invalid upload metadata")
    if request.headers.get("content-type", "").split(";")[0].lower() not in {
            "application/octet-stream", "text/csv", "application/json"}:
        raise WebError(415, "invalid_upload", "Send raw CSV or JSON bytes")
    maximum = CSV_BYTES if kind in {"csv", "cash_flows"} else REFERENCE_BYTES
    directory = contained(store.root, "uploads/" + portfolio_id)
    directory.mkdir(exist_ok=True, mode=0o700)
    identifier = uuid.uuid4().hex
    partial = contained(directory, identifier + ".part")
    final = contained(directory, identifier + (".csv" if kind in {"csv", "cash_flows"} else ".json"))
    size = 0
    installed = False
    try:
        descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            async for chunk in request.stream():
                size += len(chunk)
                if size > maximum:
                    raise WebError(413, "body_too_large", "Upload is too large")
                stream.write(chunk)
        raw = partial.read_bytes()
        provider = inspect_bytes(raw, kind)
        digest = hashlib.sha256(raw).hexdigest()
        with store.transaction() as conn:
            existing = conn.execute("SELECT * FROM uploads WHERE portfolio_id=? AND kind=? AND sha256=?",
                                    (portfolio_id, kind, digest)).fetchone()
            if existing:
                return dict(existing)
            total, count = conn.execute("SELECT COALESCE(SUM(byte_size),0),COUNT(*) FROM uploads WHERE portfolio_id=?", (portfolio_id,)).fetchone()
            if total + size > 512 * 1024 * 1024 or count >= 1000:
                raise WebError(409, "upload_quota", "Portfolio evidence quota needs local review")
            os.replace(partial, final); final.chmod(0o400)
            row = {"id": identifier, "portfolio_id": portfolio_id, "kind": kind, "provider": provider,
                   "original_name": filename, "sha256": digest, "byte_size": size, "created_at": store.clock()}
            conn.execute("INSERT INTO uploads VALUES(?,?,?,?,?,?,?,?)", tuple(row.values()))
        installed = True
        return row
    finally:
        partial.unlink(missing_ok=True)
        if not installed:
            final.unlink(missing_ok=True)
