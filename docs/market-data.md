# Market data for stocks, ETFs and bonds

This guide is for the operator of a Kurafolio V2 instance. It covers the quote
adapter contract added by WL-P0-009A: how an instance gets prices for the
securities its users hold, what happens when a source fails, and how to turn on
the optional unofficial market-data adapter.

Market data is off by default. With the shipped configuration the instance
sends no market-data request, and every quote reports `no_provider`. Pages then
value holdings from the market values inside the imported file.

The refresh schedule, the stored price table and the Refresh route belong to
WL-P0-009B. That process is the component that reads the configuration below.
Until it is merged, the contract can be used only from code and tests.

## How quotes work

A listing is an exchange plus a symbol, for example `XTSE:VEQT` for VEQT on the
Toronto Stock Exchange or `ARCX:VTI` for VTI on NYSE Arca. The exchange is the
ISO 10383 market identifier (MIC). The Wealthsimple holdings file already
carries it in its `MIC` column. A bare ticker is never enough, because the same
ticker can trade on several exchanges.

Each quote carries:

| Field | Meaning |
|---|---|
| `price` | Exact decimal value, never a floating-point number and never zero |
| `currency` | Three-letter ISO code reported by the source |
| `as_of` | When the source says the price was observed, in UTC |
| `source` | The provider's display name |
| `delay_class` | `real_time`, `delayed` or `end_of_day` |
| `fetched_at` | When this instance received it |
| `evidence_sha256` | Hash of the bounded upstream bytes the price was read from, where the provider records one |

Daily history returns one closing price per trading day with the same currency,
source and delay fields.

Every answer has a status:

| Status | What callers get |
|---|---|
| `fresh` | The latest check succeeded; the quote is current for its delay class |
| `stale` | The latest check failed or returned nothing. The last valid quote is returned with its original `as_of` time and a reason |
| `unavailable` | No valid quote has been seen for this listing. There is no price, only a reason such as `unknown_listing` |
| `no_provider` | Market data is not enabled on this instance |

A failure never turns into a price of zero, and the instance never guesses a
price.

## One request per listing, whatever the number of users

The instance keeps one quote service. It caches each listing's latest check for
the cache window, so when several users hold the same listing, the instance
makes one upstream request for it per window. Concurrent requests wait for the
one already in flight. Requests are grouped into batches as large as the
provider accepts.

A per-instance rate limit caps upstream requests per minute. When the limit is
reached, the listings not yet checked keep their last valid quote marked stale,
or report `unavailable` with reason `rate_limited`. They are retried on the next
request.

## Configuration

The configuration is a small JSON file the operator passes to the market
refresh process. It holds no credentials. Unknown keys are rejected.

```json
{
  "provider": "none",
  "cache_seconds": 60,
  "max_requests_per_minute": 30,
  "accept_unofficial_terms": false
}
```

| Key | Default | Range | Meaning |
|---|---|---|---|
| `provider` | `none` | a registered provider name | `none` sends no request |
| `cache_seconds` | `60` | 0 to 86400 | How long one check answers every user |
| `max_requests_per_minute` | `30` | 1 to 600 | Upstream requests allowed per minute for the whole instance |
| `accept_unofficial_terms` | `false` | `true` or `false` | Must be `true` before an unofficial provider starts |

A provider that needs an API key reads it from its own private file, never from
this file or from the repository. The official keyed provider is chosen in
WL-P0-009E.

## The optional unofficial adapter

No verified free official source covers Toronto-listed securities yet, so the
first V2 release includes an optional adapter for an unofficial public
market-data endpoint. The endpoint is named and added only after the owner
approves the spike findings recorded in
[WL-P0-009A](../tickets/WL-P0-009A.md). Until then no unofficial provider is
registered, and naming one in `provider` stops the service from starting.

Before you enable it, know its limits:

- The endpoint is not a documented public API. It can change its format, start
  refusing requests or disappear without notice. When that happens, quotes go
  stale and then unavailable; values fall back to the imported market values.
- Its terms of use may not allow your use. Reading them and deciding whether
  your use is allowed is your responsibility as the operator, not the
  project's. Setting `accept_unofficial_terms` to `true` records that you made
  that decision.
- Delay and coverage are whatever the endpoint serves on the day. Every quote
  shows its `as_of` time so users can see how old it is.
- Keep `max_requests_per_minute` low. Sending many requests can get the
  instance's address blocked.

To enable it, set `provider` to the adapter's registered name and
`accept_unofficial_terms` to `true`, then restart the market refresh process.
To disable it, set `provider` back to `none`.

## What leaves the instance

A market-data request contains only the exchange and symbol of a listing and a
date range. It never contains a user, account, quantity or value.

Failures are logged at warning level under the `kurafolio.market` logger with
the provider name, the listing and a short fixed reason code such as
`http_error`, `unexpected_shape`, `no_data` or `rate_limited`. URLs, API keys,
response bodies and exception messages are never logged.

## Tests

Tests use the deterministic fake provider in `src/kurafolio/market/fake.py`
and never call the network. The market test module blocks socket connections
and DNS lookups for every test, so a test that tries to reach the network fails:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_market_quotes -v
```
