"""Deterministic in-memory quote provider for tests. It never opens a connection."""
from datetime import date, datetime, timezone
from decimal import Decimal

from .contract import DailyBar, DelayClass, Listing, NoData, ProviderError, Quote

TORONTO = Listing("XTSE", "VEQT")
NEW_YORK = Listing("ARCX", "VTI")
ORACLE_AS_OF = datetime(2026, 11, 6, 20, 45, tzinfo=timezone.utc)
ORACLE_FETCHED_AT = datetime(2026, 11, 6, 21, 0, tzinfo=timezone.utc)

# Synthetic oracle values. They are not market observations.
ORACLE_LATEST = {
    TORONTO: (Decimal("41.27"), "CAD"),
    NEW_YORK: (Decimal("287.15"), "USD"),
}
ORACLE_HISTORY = {
    TORONTO: ("CAD", [(date(2026, 11, 3), "40.90"), (date(2026, 11, 4), "41.05"),
                      (date(2026, 11, 5), "41.12"), (date(2026, 11, 6), "41.27")]),
    NEW_YORK: ("USD", [(date(2026, 11, 3), "284.10"), (date(2026, 11, 4), "285.62"),
                       (date(2026, 11, 5), "286.03"), (date(2026, 11, 6), "287.15")]),
}


class FakeQuoteProvider:
    """Answers from fixed oracle tables and records every call.

    ``fail_with`` makes the next calls raise ``ProviderError`` with that code;
    ``no_data`` lists listings the provider answers without a price."""
    name = "Synthetic fake"
    delay_class = DelayClass.DELAYED

    def __init__(self, latest=None, history=None, *, max_batch_size=50):
        self.latest = dict(ORACLE_LATEST if latest is None else latest)
        self.history = dict(ORACLE_HISTORY if history is None else history)
        self.max_batch_size = max_batch_size
        self.latest_calls = []
        self.history_calls = []
        self.fail_with = None
        self.no_data = set()

    def fetch_latest(self, listings):
        self.latest_calls.append(tuple(listings))
        if self.fail_with:
            raise ProviderError(self.fail_with)
        answer = {}
        for listing in listings:
            if listing in self.no_data or listing not in self.latest:
                answer[listing] = NoData("unknown_listing" if listing not in self.latest else "no_data")
                continue
            price, currency = self.latest[listing]
            answer[listing] = Quote(listing, Decimal(price), currency, ORACLE_AS_OF, self.name,
                                    self.delay_class, ORACLE_FETCHED_AT)
        return answer

    def fetch_history(self, listing, start, end):
        self.history_calls.append((listing, start, end))
        if self.fail_with:
            raise ProviderError(self.fail_with)
        if listing in self.no_data or listing not in self.history:
            return NoData("unknown_listing" if listing not in self.history else "no_data")
        currency, rows = self.history[listing]
        return [DailyBar(listing, day, Decimal(close), currency, self.name)
                for day, close in rows if start <= day <= end]
