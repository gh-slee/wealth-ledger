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
one already in flight for that listing, while requests for cached listings
answer at once. Requests are grouped into batches as large as the
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
first V2 release includes an optional adapter for the unofficial Yahoo Finance
chart endpoint (`query1.finance.yahoo.com/v8/finance/chart/`). The owner
approved it on 2026-11-12 after the spike recorded in
[WL-P0-009A](../tickets/WL-P0-009A.md). Its registered name is
`unofficial-yahoo-chart`.

What it does:

- It supports the Toronto Stock Exchange (`XTSE`), the TSX Venture Exchange
  (`XTSX`) and the US exchanges `XNYS`, `XNAS`, `ARCX`, `BATS` and `XASE`. A
  listing on any other exchange is reported `unavailable` with reason
  `unsupported_exchange`, and no request is sent for it.
- It sends one request per listing, because the endpoint's multi-symbol quote
  call needs a browser session. It identifies itself as `Kurafolio/0.1` and
  does not imitate a browser.
- Quotes are reported as `delayed`. In the spike the latest price was one to
  five minutes old, but the endpoint does not state its delay, so it can be
  older.
- Daily history uses the endpoint's closing prices, which include split
  adjustments but not dividend adjustments. Days the endpoint leaves empty are
  skipped, never filled. Today's bar is left out until the exchange's day has
  ended, because during trading the endpoint fills it with the live price.
- Prices are read as exact decimals and rounded to the precision the endpoint
  reports for the listing, which removes floating-point noise in its history.
- Bond coverage was not tested. A bond with no listing on a supported exchange
  stays `unavailable`.

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

To enable it, set `provider` and `accept_unofficial_terms` and restart the
market refresh process:

```json
{
  "provider": "unofficial-yahoo-chart",
  "accept_unofficial_terms": true,
  "cache_seconds": 300,
  "max_requests_per_minute": 20
}
```

Without `accept_unofficial_terms: true` the service refuses to start.
To disable it, set `provider` back to `none`.

## What leaves the instance

A market-data request contains only the provider's symbol for a listing (for
the unofficial adapter, for example `VEQT.TO`) and a date range. It never
contains a user, account, quantity or value. Like any HTTP request, it also
shows the provider the instance's IP address and the client name
`Kurafolio/0.1`. The adapter does not follow redirects, so a request never
moves to another host.

Failures are logged at warning level under the `kurafolio.market` logger with
the provider's registered name, the listing and a short fixed reason code such as
`http_error`, `upstream_rate_limited`, `network_error`, `unexpected_shape`,
`no_data` or `rate_limited`. URLs, API keys,
response bodies and exception messages are never logged.

## Tests

Tests use the deterministic fake provider in `src/kurafolio/market/fake.py`
and recorded synthetic responses for the unofficial adapter. They never call
the network. Every test in the market test modules blocks socket connections
and DNS lookups and records each attempt. A test that tries to connect fails,
even when the code under test catches the error. The guard covers these two
modules only, not the whole test suite.

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_market_*.py' -v
```
