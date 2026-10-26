"""Lossless domain token adapters; no SQL rounding or ambient decimal arithmetic."""
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from wealth_ledger.domain.canonical_v1 import DateOnlyV1, DecimalTokenV1
from wealth_ledger.domain.validation_v1 import decimal_parts_v1


def decimal_value(value):
    if value is None:
        return None, None
    decimal_parts_v1(value)
    return value.token, Decimal(value.token)


def source_time(value):
    if value is None:
        return {"time_tag": None, "time_token": None, "time_zone": None,
                "time_utc": None, "time_index": "unknown", "time_detail": None}
    status, derived = "date_only", None
    if not isinstance(value, DateOnlyV1):
        try:
            derived = datetime.fromisoformat(value.token).astimezone(timezone.utc)
            status = "indexed"
        except (ValueError, OverflowError):
            status = "unindexable"
    return {"time_tag": value.tag, "time_token": value.token,
            "time_zone": getattr(value, "zone", None), "time_utc": derived,
            "time_index": status, "time_detail": asdict(value)}
