"""Per-instance quote service: one cache, one rate limit and one upstream call
per listing per cache window, whatever the number of users asking.

A failed, malformed or empty answer never becomes zero: the last valid quote is
returned marked stale, or the listing is reported unavailable with a reason.
Failures are logged with fixed codes only, never URLs, keys or bodies.
"""
from collections import deque
from datetime import datetime, timedelta, timezone
import logging
import threading

from .contract import (HistoryResult, NoData, ProviderError, Quote, QuoteResult, QuoteStatus,
                       validate_history, validate_latest)

LOGGER = logging.getLogger("kurafolio.market")


def utc_now():
    return datetime.now(timezone.utc)


class RateLimiter:
    """Sliding window: at most ``max_requests`` upstream calls per ``per_seconds``."""

    def __init__(self, max_requests, per_seconds):
        if max_requests < 1 or per_seconds <= 0:
            raise ValueError("Rate limit must allow at least one request")
        self.max_requests = max_requests
        self.window = timedelta(seconds=per_seconds)
        self._sent = deque()

    def try_acquire(self, now):
        while self._sent and now - self._sent[0] >= self.window:
            self._sent.popleft()
        if len(self._sent) >= self.max_requests:
            return False
        self._sent.append(now)
        return True


class _Bounded(dict):
    """Insertion-ordered map that forgets its oldest entries past ``limit``."""

    def __init__(self, limit):
        super().__init__()
        self.limit = limit

    def put(self, key, value):
        self.pop(key, None)
        self[key] = value
        while len(self) > self.limit:
            self.pop(next(iter(self)))


class QuoteService:
    def __init__(self, provider=None, *, cache_seconds=60, max_requests=30, per_seconds=60,
                 clock=utc_now, max_entries=10000, logger=LOGGER):
        if cache_seconds < 0:
            raise ValueError("Cache window cannot be negative")
        self.provider = provider
        self.cache_window = timedelta(seconds=cache_seconds)
        self.limiter = RateLimiter(max_requests, per_seconds)
        self.clock = clock
        self.logger = logger
        self._lock = threading.Lock()
        self._checks = _Bounded(max_entries)      # Listing -> QuoteResult
        self._last_valid = _Bounded(max_entries)  # Listing -> Quote
        self._history = _Bounded(max_entries)     # (Listing, start, end) -> HistoryResult
        self._last_history = _Bounded(max_entries)

    @property
    def enabled(self):
        return self.provider is not None

    def latest(self, listings):
        """Return ``{listing: QuoteResult}`` for the distinct listings requested."""
        unique = list(dict.fromkeys(listings))
        if self.provider is None:
            return {item: QuoteResult(item, QuoteStatus.NO_PROVIDER, None, reason="no_provider")
                    for item in unique}
        with self._lock:
            now = self.clock()
            due = [item for item in unique if not self._cached(self._checks.get(item), now)]
            size = max(1, int(self.provider.max_batch_size))
            for offset in range(0, len(due), size):
                self._refresh(due[offset:offset + size], now)
            return {item: self._checks.get(item) or self._fallback(item, now, "rate_limited")
                    for item in unique}

    def history(self, listing, start, end):
        """Return a ``HistoryResult`` of daily closes for ``start <= day <= end``."""
        if start > end:
            raise ValueError("History start is after its end")
        if self.provider is None:
            return HistoryResult(listing, start, end, QuoteStatus.NO_PROVIDER, None, reason="no_provider")
        key = (listing, start, end)
        with self._lock:
            now = self.clock()
            cached = self._history.get(key)
            if self._cached(cached, now):
                return cached
            if not self.limiter.try_acquire(now):
                return self._history_fallback(key, now, "rate_limited")
            try:
                answer = validate_history(listing, start, end, self.provider.fetch_history(listing, start, end))
            except Exception as error:
                answer = NoData(self._failure_code(error))
            if isinstance(answer, NoData):
                self._log(listing, answer.reason)
                result = self._history_fallback(key, now, answer.reason)
            else:
                result = HistoryResult(listing, start, end, QuoteStatus.FRESH, now, answer)
                self._last_history.put(key, result)
            self._history.put(key, result)
            return result

    def _cached(self, result, now):
        return result is not None and result.checked_at is not None and now - result.checked_at < self.cache_window

    def _refresh(self, batch, now):
        if not self.limiter.try_acquire(now):
            for item in batch:  # not cached, so the next request retries
                self._log(item, "rate_limited")
            return
        try:
            answer = validate_latest(batch, self.provider.fetch_latest(batch), now)
        except Exception as error:
            code = self._failure_code(error)
            answer = {item: NoData(code) for item in batch}
        for item in batch:
            outcome = answer[item]
            if isinstance(outcome, Quote):
                previous = self._last_valid.get(item)
                if previous is None or outcome.as_of >= previous.as_of:
                    self._last_valid.put(item, outcome)
                result = QuoteResult(item, QuoteStatus.FRESH, now, self._last_valid[item])
            else:
                self._log(item, outcome.reason)
                result = self._fallback(item, now, outcome.reason)
            self._checks.put(item, result)

    def _fallback(self, listing, now, reason):
        last = self._last_valid.get(listing)
        if last is not None:
            return QuoteResult(listing, QuoteStatus.STALE, now, last, reason)
        return QuoteResult(listing, QuoteStatus.UNAVAILABLE, now, reason=reason)

    def _history_fallback(self, key, now, reason):
        listing, start, end = key
        last = self._last_history.get(key)
        if last is not None:
            return HistoryResult(listing, start, end, QuoteStatus.STALE, now, last.bars, reason)
        return HistoryResult(listing, start, end, QuoteStatus.UNAVAILABLE, now, reason=reason)

    @staticmethod
    def _failure_code(error):
        if isinstance(error, ProviderError):
            return error.code
        if isinstance(error, (ValueError, TypeError, KeyError)):
            return "unexpected_shape"
        return "provider_error"

    def _log(self, listing, reason):
        name = getattr(self.provider, "name", "unknown")
        self.logger.warning("market quote check failed provider=%s listing=%s reason=%s",
                            name, listing.key(), reason)
