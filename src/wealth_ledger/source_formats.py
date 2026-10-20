"""Pure byte-only CSV grammars shared by legacy importers and versioned adapters.

No filesystem, clock, database, process, network or workspace access belongs here.
Return source numbers/times and coded findings without filling missing history.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, localcontext

D = Decimal
ZERO = D(0)
TOLERANCE = D("0.01")
PROVIDER = "bullbitcoin"

WS_REQUIRED = ("Account Type", "Account Number", "Symbol", "MIC", "Name",
            "Security Type", "Quantity", "Market Price", "Market Price Currency",
            "Book Value (CAD)", "Book Value (Market)", "Book Value Currency (Market)",
            "Market Value", "Market Value Currency", "Market Unrealized Returns",
            "Market Unrealized Returns Currency")

BULL_REQUIRED = (
    "ORDER_ID", "ORDER_TYPE", "PAYIN_AMOUNT", "PAYIN_CURRENCY",
    "PAYOUT_AMOUNT", "PAYOUT_CURRENCY", "PAYIN_METHOD", "PAYOUT_METHOD",
    "ORDER_STATUS", "PAYIN_STATUS", "PAYOUT_STATUS", "CREATED_AT (UTC)",
    "COMPLETED_AT (UTC)", "SENT_AT (UTC)",
)

NETWORKS = {"BTC": "bitcoin", "LBTC": "liquid"}

METHODS = {"BTC": "Bitcoin On-Chain", "LBTC": "Liquid Network"}


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _text(number):
    value = format(number, "f")
    return value.rstrip("0").rstrip(".") if "." in value else value


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _number(value, *, optional=False):
    if optional and not str(value).strip():
        return None
    try:
        number = Decimal(str(value).strip())
    except Exception as exc:
        raise ValueError("Invalid numeric order amount") from exc
    if not number.is_finite() or number < ZERO:
        raise ValueError("Order amounts must be finite and nonnegative")
    return _text(number)


def _time(value, *, optional=False):
    text = str(value).strip()
    if optional and not text:
        return None
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid order timestamp") from exc
    if result.tzinfo is None:
        raise ValueError("Order and valuation timestamps require a time zone")
    return result.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _complete(order):
    return all(order[key].casefold() == "completed" for key in (
        "order_status", "payin_status", "payout_status"))


def _account_id(source_account):
    return "crypto_" + _hash((PROVIDER + "\0" + source_account).encode())[:20]


def _order_key(source_account, order_id):
    return "co_" + _hash((PROVIDER + "\0" + source_account + "\0" + order_id).encode())


def _decimal(value):
    number = D(str(value))
    if not number.is_finite():
        raise ValueError("Amounts and rates must be finite")
    return number


def _finding(code, **context):
    return {"code": code, "severity": "warning", **context}


def _parse_wealthsimple(raw):
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig")))
    rows = list(reader)
    if not rows:
        raise ValueError("Empty holdings CSV")
    headers = [item.strip() for item in rows[0]]
    if len(headers) != len(set(headers)) or any(item not in headers for item in WS_REQUIRED):
        raise ValueError("Missing or duplicate holdings CSV columns")
    footer, records, accounts, issues, seen = None, [], {}, [], set()
    for line, values in enumerate(rows[1:], 2):
        if not values or not any(item.strip() for item in values):
            continue
        if len(values) == 1 and values[0].strip().startswith("As of "):
            if footer is not None:
                raise ValueError("Multiple as-of footers")
            footer = values[0].strip()
            continue
        if footer is not None or len(values) != len(headers):
            raise ValueError(f"Malformed holdings row {line}")
        row = dict(zip(headers, (item.strip() for item in values)))
        number = row["Account Number"]
        if not number or not row["Symbol"]:
            raise ValueError(f"Missing account or symbol at row {line}")
        aid = "a_" + _hash(number.encode())[:16]
        currency = row["Market Value Currency"].upper()
        if currency not in ("CAD", "USD"):
            raise ValueError(f"Unsupported market currency: {currency}")
        for field in ("Market Price Currency", "Book Value Currency (Market)",
                      "Market Unrealized Returns Currency"):
            if row[field].upper() != currency:
                raise ValueError(f"Currency mismatch at row {line}: {field}")
        if row.get("Book Value Currency (CAD)", "CAD").upper() != "CAD":
            raise ValueError(f"CAD book value currency mismatch at row {line}")
        if row.get("Position Direction", "LONG") != "LONG":
            raise ValueError("Only long positions are supported in this version")
        security_type = row["Security Type"]
        sid = ("cash:" + currency if security_type == "CURRENCY" else
               ":".join((row["MIC"], row["Symbol"], currency)))
        if (aid, sid) in seen:
            raise ValueError(f"Duplicate account/security key at row {line}")
        seen.add((aid, sid))
        account = {"account_id": aid, "account_type": row["Account Type"],
                   "label": row["Account Type"], "masked_number": "****" + number[-4:]}
        if aid in accounts and accounts[aid] != account:
            raise ValueError("Conflicting metadata for one account")
        accounts[aid] = account
        record = {"account_id": aid, "account_type": account["account_type"],
                  "security_id": sid, "symbol": row["Symbol"], "currency": currency,
                  "security_type": security_type, "mic": row["MIC"],
                  "exchange": row.get("Exchange", ""), "name": row["Name"],
                  "quantity": _decimal(row["Quantity"]), "price": _decimal(row["Market Price"]),
                  "book_native": _decimal(row["Book Value (Market)"]),
                  "book_cad": _decimal(row["Book Value (CAD)"]),
                  "market_native": _decimal(row["Market Value"]),
                  "unrealized_native": _decimal(row["Market Unrealized Returns"])}
        context = {"account_id": aid, "symbol": record["symbol"]}
        if abs(record["quantity"] * record["price"] - record["market_native"]) > TOLERANCE:
            issues.append(_finding('market_math', **context))
        if abs(record["market_native"] - record["book_native"] - record["unrealized_native"]) > TOLERANCE:
            issues.append(_finding('unrealized_math', **context))
        if record["quantity"] < 0 or record["market_native"] < 0:
            raise ValueError("Negative long position quantity/value is unsupported")
        if security_type != "CURRENCY" and (record["quantity"] <= 0 or record["book_native"] <= 0):
            issues.append(_finding('nonpositive_cost_quantity', **context))
        records.append(record)
    if not records or not footer:
        raise ValueError("Holdings CSV needs holdings rows and an as-of footer")
    match = re.fullmatch(r"As of (\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?) GMT([+-]\d{2}:\d{2})", footer)
    if not match:
        raise ValueError("Unrecognized holdings as-of footer")
    as_of = datetime.fromisoformat(match[1] + match[2])
    return raw, as_of, records, accounts, issues


def parse_wealthsimple(raw):
    """Use the established arithmetic precision without changing global context."""
    with localcontext() as context:
        context.prec = 60
        return _parse_wealthsimple(raw)


def parse_bull(raw, source_account):
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    fields = reader.fieldnames or []
    if len(fields) != len(set(fields)) or any(key not in fields for key in BULL_REQUIRED):
        raise ValueError("Missing or duplicate Bull order CSV columns")
    orders, row_count, duplicate_rows = {}, 0, 0
    for line, original in enumerate(reader, 2):
        if None in original or any(value is None for value in original.values()):
            raise ValueError(f"Malformed Bull order row {line}")
        row = {key: value.strip() for key, value in original.items()}
        if not any(row.values()):
            continue
        row_count += 1
        if not row["ORDER_ID"] or any(not row[key] for key in (
                "ORDER_STATUS", "PAYIN_STATUS", "PAYOUT_STATUS")):
            raise ValueError(f"Missing order ID or status at row {line}")
        order_type = row["ORDER_TYPE"]
        if order_type not in ("Funding", "Buy Bitcoin"):
            raise ValueError(f"Unsupported Bull order type at row {line}: {order_type}")
        order = {
            "order_key": _order_key(source_account, row["ORDER_ID"]),
            "order_id": row["ORDER_ID"], "order_type": order_type,
            "order_subtype": row.get("ORDER_SUBTYPE", ""),
            "payin_amount": _number(row["PAYIN_AMOUNT"]),
            "payin_currency": row["PAYIN_CURRENCY"].upper(),
            "payout_amount": _number(row["PAYOUT_AMOUNT"]),
            "payout_currency": row["PAYOUT_CURRENCY"].upper(),
            "payin_method": row["PAYIN_METHOD"], "payout_method": row["PAYOUT_METHOD"],
            "order_status": row["ORDER_STATUS"], "payin_status": row["PAYIN_STATUS"],
            "payout_status": row["PAYOUT_STATUS"],
            "created_at": _time(row["CREATED_AT (UTC)"]),
            "completed_at": _time(row["COMPLETED_AT (UTC)"], optional=True),
            "sent_at": _time(row["SENT_AT (UTC)"], optional=True),
            "exchange_rate_amount": _number(row.get("EXCHANGE_RATE_AMOUNT", ""), optional=True),
            "exchange_rate_currency": row.get("EXCHANGE_RATE_CURRENCY", ""),
            "index_rate_amount": _number(row.get("INDEX_RATE_AMOUNT", ""), optional=True),
            "index_rate_currency": row.get("INDEX_RATE_CURRENCY", ""),
        }
        if order["payin_currency"] != "CAD":
            raise ValueError("Only CAD-funded Bull orders are supported")
        if order_type == "Funding":
            if order["payout_currency"] != "CAD" or order["payout_method"] != "CAD Balance":
                raise ValueError("Funding must credit the CAD balance")
            if Decimal(order["payin_amount"]) != Decimal(order["payout_amount"]):
                raise ValueError("Funding payin and payout differ; fee treatment requires explicit support")
            order["network"] = None
        else:
            asset = order["payout_currency"]
            if asset not in NETWORKS or order["payout_method"] != METHODS[asset]:
                raise ValueError("Unsupported Bitcoin payout currency/network combination")
            if order["payin_method"] != "CAD Balance":
                raise ValueError("Buy Bitcoin must debit the CAD balance")
            order["network"] = NETWORKS[asset]
            with localcontext() as context:
                context.prec = 80
                quantity = Decimal(order["payout_amount"])
                if quantity != quantity.quantize(Decimal("0.00000001")):
                    raise ValueError("BTC/LBTC quantities cannot exceed eight decimal places")
        if _complete(order):
            if order["completed_at"] is None:
                raise ValueError("Completed orders require a completion timestamp")
            if order["completed_at"] < order["created_at"]:
                raise ValueError("Order completion precedes creation")
            if Decimal(order["payin_amount"]) <= ZERO or Decimal(order["payout_amount"]) <= ZERO:
                raise ValueError("Completed order amounts must be positive")
        key = order["order_key"]
        if key in orders and orders[key] != order:
            raise ValueError("Conflicting duplicate order ID within the same CSV")
        if key in orders:
            duplicate_rows += 1
        orders[key] = order
    if not orders:
        raise ValueError("Bull order CSV contains no orders")
    semantic = _hash(_json(sorted(orders.values(), key=lambda item: item["order_key"])).encode())
    return raw, list(orders.values()), row_count, duplicate_rows, semantic
