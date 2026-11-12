"""Deterministic financial display formats, independent of the host OS locale."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext
from zoneinfo import ZoneInfo

from .i18n import tr, current_context, registry


def money(value, digits=2):
    if value is None:
        return tr('message.756762e293f2')
    with localcontext() as context:
        context.prec = 80
        amount = Decimal(str(value)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    profile = registry()["locales"][current_context().locale]
    whole, _, fraction = f"{amount:,.{digits}f}".partition(".")
    whole = whole.replace(",", profile["group_separator"])
    return whole + (profile["decimal_separator"] + fraction if digits else "")


def quantity(value):
    if value is None:
        return money(None)
    text = format(Decimal(str(value)), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def percent(value):
    if value is None:
        return tr('message.190b16ffcdce')
    number = Decimal(str(value)) * 100
    digits = 6 if number and abs(number) < Decimal("0.01") else 2
    rounded = number.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    if number and rounded == 0:
        return "<0.000001%" if number > 0 else ">-0.000001%"
    return money(number, digits) + "%"


def display_time(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo:
        stamp = stamp.astimezone(ZoneInfo("America/Toronto"))
    return stamp.strftime("%Y-%m-%d %H:%M %Z").strip()
