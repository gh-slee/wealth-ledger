"""Quote adapter contract: listing identity, quote evidence and provider outcomes.

Every market-data provider implements :class:`QuoteProvider`. Providers return
validated :class:`Quote` and :class:`DailyBar` values or a :class:`NoData` reason
per listing, and raise :class:`ProviderError` when a whole upstream call fails.
They never return zero or a guessed price. Prices are ``Decimal`` only.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
import re
from typing import Mapping, Protocol, Sequence

_MIC = re.compile(r"^[A-Z0-9]{4}$")
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,23}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_SOURCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._\-]{0,63}$")
_CODE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
# A provider clock may run slightly ahead of ours; anything further is invalid.
FUTURE_TOLERANCE = timedelta(minutes=2)


class DelayClass(str, Enum):
    REAL_TIME = "real_time"
    DELAYED = "delayed"
    END_OF_DAY = "end_of_day"


class QuoteStatus(str, Enum):
    FRESH = "fresh"            # the latest upstream check for this listing succeeded
    STALE = "stale"            # the latest check failed; the last valid quote is returned
    UNAVAILABLE = "unavailable"  # no valid quote has ever been seen; ``reason`` says why
    NO_PROVIDER = "no_provider"  # market data is not enabled on this instance


@dataclass(frozen=True, slots=True, order=True)
class Listing:
    """A security on one exchange. ``mic`` is the ISO 10383 market identifier
    (for example ``XTSE`` for Toronto); a bare ticker is ambiguous."""
    mic: str
    symbol: str

    def __post_init__(self):
        if not isinstance(self.mic, str) or not _MIC.fullmatch(self.mic):
            raise ValueError("Listing exchange must be a four-character MIC")
        if not isinstance(self.symbol, str) or not _SYMBOL.fullmatch(self.symbol):
            raise ValueError("Listing symbol is invalid")

    @classmethod
    def of(cls, mic, symbol):
        """Normalize case and surrounding space, then validate."""
        return cls(str(mic).strip().upper(), str(symbol).strip().upper())

    def key(self):
        return f"{self.mic}:{self.symbol}"


def _utc(value, label):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{label} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _price(value):
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError("Price must be a positive finite Decimal")
    return value


def _common(currency, source, delay_class):
    if not isinstance(currency, str) or not _CURRENCY.fullmatch(currency):
        raise ValueError("Currency must be a three-letter ISO code")
    if not isinstance(source, str) or not _SOURCE.fullmatch(source):
        raise ValueError("Source name is invalid")
    if not isinstance(delay_class, DelayClass):
        raise ValueError("Delay class is invalid")


@dataclass(frozen=True, slots=True)
class Quote:
    """The latest observed price for one listing, with its evidence.

    ``evidence_sha256`` hashes the bounded upstream bytes the price was read
    from, so a stored quote can be traced to what the provider returned."""
    listing: Listing
    price: Decimal
    currency: str
    as_of: datetime
    source: str
    delay_class: DelayClass
    fetched_at: datetime
    evidence_sha256: str | None = None

    def __post_init__(self):
        if not isinstance(self.listing, Listing):
            raise ValueError("Quote listing is invalid")
        _price(self.price)
        _common(self.currency, self.source, self.delay_class)
        as_of = _utc(self.as_of, "Quote as_of")
        fetched = _utc(self.fetched_at, "Quote fetched_at")
        if as_of > fetched + FUTURE_TOLERANCE:
            raise ValueError("Quote as_of is after its fetch time")
        if self.evidence_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", self.evidence_sha256):
            raise ValueError("Evidence hash is invalid")
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "fetched_at", fetched)


@dataclass(frozen=True, slots=True)
class DailyBar:
    """One trading day's official close for a listing."""
    listing: Listing
    day: date
    close: Decimal
    currency: str
    source: str
    delay_class: DelayClass = DelayClass.END_OF_DAY

    def __post_init__(self):
        if not isinstance(self.listing, Listing):
            raise ValueError("Bar listing is invalid")
        if not isinstance(self.day, date) or isinstance(self.day, datetime):
            raise ValueError("Bar day must be a date")
        _price(self.close)
        _common(self.currency, self.source, self.delay_class)


@dataclass(frozen=True, slots=True)
class NoData:
    """The provider answered but has no price for this listing."""
    reason: str

    def __post_init__(self):
        if not isinstance(self.reason, str) or not _CODE.fullmatch(self.reason):
            raise ValueError("Reason must be a short code")


class ProviderError(Exception):
    """A whole upstream call failed. ``code`` is a short fixed code that is safe to
    log; providers never put URLs, keys or response bodies into it."""

    def __init__(self, code):
        if not isinstance(code, str) or not _CODE.fullmatch(code):
            code = "provider_error"
        super().__init__(code)
        self.code = code


class QuoteProvider(Protocol):
    name: str
    delay_class: DelayClass
    max_batch_size: int  # listings one upstream request can answer

    def fetch_latest(self, listings: Sequence[Listing]) -> Mapping[Listing, "Quote | NoData"]:
        """Return one entry per requested listing or raise ProviderError."""

    def fetch_history(self, listing: Listing, start: date, end: date) -> "Sequence[DailyBar] | NoData":
        """Return closes for ``start <= day <= end`` in date order or raise ProviderError."""


@dataclass(frozen=True, slots=True)
class QuoteResult:
    """What callers receive. ``quote`` is set for fresh and stale results only;
    ``reason`` is set for every result that is not fresh. Never a zero price."""
    listing: Listing
    status: QuoteStatus
    checked_at: datetime | None
    quote: Quote | None = None
    reason: str | None = None

    def __post_init__(self):
        has_quote = self.status in (QuoteStatus.FRESH, QuoteStatus.STALE)
        if has_quote != (self.quote is not None):
            raise ValueError("Only fresh and stale results carry a quote")
        if (self.status != QuoteStatus.FRESH) != (self.reason is not None):
            raise ValueError("Every result that is not fresh carries a reason")
        if self.quote is not None and self.quote.listing != self.listing:
            raise ValueError("Result quote belongs to another listing")


@dataclass(frozen=True, slots=True)
class HistoryResult:
    listing: Listing
    start: date
    end: date
    status: QuoteStatus
    checked_at: datetime | None
    bars: tuple = field(default=())
    reason: str | None = None

    def __post_init__(self):
        if (self.status != QuoteStatus.FRESH) != (self.reason is not None):
            raise ValueError("Every result that is not fresh carries a reason")
        if self.status in (QuoteStatus.UNAVAILABLE, QuoteStatus.NO_PROVIDER) and self.bars:
            raise ValueError("Unavailable history carries no bars")


def validate_latest(listings, answer, now):
    """Check a provider's answer covers exactly the request with valid values."""
    if not isinstance(answer, Mapping) or set(answer) != set(listings):
        raise ProviderError("unexpected_shape")
    for listing, item in answer.items():
        if isinstance(item, Quote):
            if item.listing != listing or item.as_of > now + FUTURE_TOLERANCE:
                raise ProviderError("unexpected_shape")
        elif not isinstance(item, NoData):
            raise ProviderError("unexpected_shape")
    return answer


def validate_history(listing, start, end, answer):
    if isinstance(answer, NoData):
        return answer
    try:
        bars = tuple(answer)
    except TypeError:
        raise ProviderError("unexpected_shape") from None
    days = [bar.day for bar in bars if isinstance(bar, DailyBar)]
    if (len(days) != len(bars) or any(bar.listing != listing for bar in bars)
            or days != sorted(set(days)) or any(not start <= day <= end for day in days)):
        raise ProviderError("unexpected_shape")
    if not bars:
        return NoData("no_data")
    return bars
