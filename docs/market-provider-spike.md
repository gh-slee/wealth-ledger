# Official quote provider spike (WL-P0-009E)

This report compares keyed market-data providers that could become the
official quote source next to the optional unofficial adapter from
WL-P0-009A. The owner picks one provider from it; only then is its adapter
written. Status: documented terms collected on 2026-11-12; the tests with real
keys have not run yet (see [Measured results](#measured-results)).

## What was compared

The question for this project is narrow: can an instance operator with their
own key get a latest quote and daily closes for Toronto-listed and US-listed
ETFs, stocks and bond ETFs, within a free or personal-plan budget, under terms
that allow it?

Candidates: Alpha Vantage, Twelve Data and Finnhub (named in the ticket), plus
EODHD and Tiingo, which also sell keyed end-of-day and delayed data to
individuals.

## Documented terms, read 2026-11-12

Every fact below comes from the provider's own pages, read on 2026-11-12.
Quotes are short and verbatim. "Not stated" means the pages read did not say.

### Alpha Vantage

- Limit: "25 API requests per day" on the free key
  ([support](https://www.alphavantage.co/support/)). Free per-minute limit not
  stated. Paid plans start at 75 requests a minute with no daily limit
  ([premium](https://www.alphavantage.co/premium/)).
- Delay: the quote endpoint is "updated at the end of each trading day for all
  users"; real-time and 15-minute delayed US data are premium
  ([documentation](https://www.alphavantage.co/documentation/)).
- Toronto: documented, with symbols such as `SHOP.TRT` (TSX) and `GPV.TRV`
  (TSX Venture) in the daily-series examples.
- History: `TIME_SERIES_DAILY` with "compact" output (about 100 days) is free;
  "full" output is premium. The adjusted series is premium.
- Licence: the free licence is "for personal, non-commercial use". Use counts as
  commercial when it "allows individuals or entities other than User to access
  information directly or indirectly"
  ([terms of service, PDF](https://www.alphavantage.co/terms_of_service/), section 2).
- Error format: not stated on the pages read.

### Twelve Data

- Limit: Basic (free) plan, "8 (800 a day)" credits; quote and time series cost
  one credit per symbol ([pricing](https://twelvedata.com/pricing),
  [credits](https://support.twelvedata.com/en/articles/5615854-credits)).
- Toronto: not on the free plan. The free exchange list holds only US, forex and
  crypto; the [XTSE page](https://twelvedata.com/exchanges/xtse) is tagged
  Grow and shows "Delay EOD". Grow is listed at $79 a month.
- Request format: separate `symbol` and `mic_code` parameters (ISO 10383), which
  match the listing identity the contract already uses.
- Licence: access is "solely for Internal Use", and the terms prohibit using
  "Free Tier data for commercial purposes". Display to third parties needs a
  tier, an add-on or a separate agreement ([terms](https://twelvedata.com/terms),
  sections 2.1 to 2.4).
- Errors: JSON with `code`, `message` and `status`; 429 means "API request limit
  reached for your key"; headers `api-credits-used` and `api-credits-left`
  ([errors](https://twelvedata.com/docs/introduction/errors)).
- Bonds: bond and bond-fund types exist; free-plan coverage not stated.

### Finnhub

- Limit: free plan "60 API calls/minute"; licence column "Personal Use"
  ([pricing](https://finnhub.io/pricing), read in a browser because the page is
  rendered by script).
- Coverage: free market data is US only. The free column is empty for daily
  OHLC history and for "TSX, LSE, Euronext, Deutsche Börse", and the page notes
  that international markets other than LSE are end of day only on the paid plan.
- Licence: plans are "strictly for personal use unless explicitly stated
  otherwise"; sharing data or derived results with any third party needs written
  approval ([terms](https://finnhub.io/terms-of-service)).
- Error format: the documentation pages did not render; not stated.

### EODHD

- Limit: free plan 20 API calls a day and one year of history
  ([pricing](https://eodhd.com/pricing),
  [API limits](https://eodhd.com/financial-apis/api-limits/)). The two pages
  disagree on the per-minute cap (20 versus 1,000).
- Delay: live prices are "delayed: 15-20 minutes for stocks"; end-of-day data
  arrives two to three hours after the close
  ([live](https://eodhd.com/financial-apis/live-realtime-stocks-api)).
- Toronto: not stated on the pages read. Symbols use EODHD's own exchange code
  (`SYMBOL.EXCHANGE`), not a MIC; the Toronto code is unconfirmed.
- Licence: the plans on the pricing page "are intended for personal use only";
  personal users may not display or grant access to the data
  ([terms](https://eodhd.com/financial-apis/terms-conditions),
  [commercial use](https://eodhd.com/financial-apis/commercial-vs-personal-license-use)).
- Errors: 402 when the daily limit is spent, 429 with `Retry-After` for the
  minute limit, 404 "Ticker Not Found" (still billed).

### Tiingo

- Limit: free Starter plan 50 requests an hour and 1,000 a day
  ([pricing](https://www.tiingo.com/about/pricing)).
- Coverage: "Equity, Mutual Fund, and ETF prices for US markets" and Chinese
  equities ([symbology](https://www.tiingo.com/documentation/appendix/symbology)).
  Toronto is not covered.
- Licence: personal or internal use only, and on the Starter plan you "may not
  write, save, archive, back up, or otherwise retain Tiingo Data"
  ([terms](https://www.tiingo.com/tos), section 1.6(a)). That rules out the
  price store from WL-P0-009B.

## What the documents already decide

- Finnhub (free) and Tiingo cannot serve Toronto listings. Tiingo's free terms
  also forbid storing prices. Neither is tested further.
- No candidate offers Toronto quotes on a free plan except Alpha Vantage, and
  its free Toronto data is end of day with 25 requests a day.
- Every free or personal plan read here forbids showing the data to other
  people without a commercial agreement. An instance that serves anyone beyond
  its operator needs a commercial licence from whichever provider is chosen.

## Request budget at the default intervals

WL-P0-009B refreshes a security every 15 minutes while its exchange is open
(6.5 hours) and once after the close: 27 requests per listing per trading day
when every refresh costs one request. An end-of-day source needs only the one
fetch after the close. History backfill is a one-time cost and is left out.

| Plan | Limit | 10 listings | 30 listings | 100 listings |
|---|---|---|---|---|
| Delayed source, 27 a day each | | 270 | 810 | 2,700 |
| End-of-day source, 1 a day each | | 10 | 30 | 100 |
| Alpha Vantage free | 25 a day | EOD only: fits | EOD: over | over |
| Twelve Data Basic | 800 a day, 8 a minute | delayed fits (US only) | 810: just over | over |
| EODHD free | 20 a day | EOD only: fits | over | over |
| Finnhub free | 60 a minute | fits (US only) | fits (US only) | fits (US only) |
| Tiingo Starter | 50 an hour, 1,000 a day | fits (US only) | 120 an hour: over | over |

Per-minute limits also matter for a refresh round: 30 listings fetched at once
exceed Twelve Data's 8 credits a minute, so a round has to be spread over about
four minutes.

## Test plan with real keys

Run by the owner or an operator with keys created on the providers' sites.
Keys stay outside the repository.

1. Create free keys for Alpha Vantage, Twelve Data and EODHD (and Finnhub if a
   US-only comparison is wanted). Save each as one line in
   `~/.config/kurafolio-spike/<provider>.key` with mode 600:
   `alphavantage.key`, `twelvedata.key`, `eodhd.key`, `finnhub.key`.
2. Run, preferably during Toronto trading hours:

   ```bash
   PYTHONPATH=src .venv/bin/python scripts/market_provider_spike.py \
       --key-dir ~/.config/kurafolio-spike --output work/market-spike.json
   ```

   The probe asks each provider for the latest quote and about 30 days of daily
   closes for `XTSE:VEQT`, `XTSE:XIC`, `ARCX:VTI`, `ARCX:SPY`, `XTSE:RY`,
   `XNAS:AAPL`, `XTSE:ZAG` and `XNAS:BND`: 16 requests per provider, within
   every free daily limit except EODHD's 20 (one run only).
3. The output holds only status codes, rate-limit headers, prices, currencies,
   times, bar counts and short refusal messages, with any key replaced by
   `[redacted]`. Check it before sharing, then paste it or attach it to the
   ticket. The observed delay is the fetch time minus the provider's `as_of`.

## Measured results

Not run yet: no provider key was available to the agent on 2026-11-12. This
section will hold one table per provider with the result for each listing.

## Recommendation

Pending the measured results. On the documents alone, Alpha Vantage is the only
candidate whose free key reaches Toronto, at end of day and for at most 25 listings
with one fetch each a day. Twelve Data's `mic_code` matches the contract well, but Toronto needs its
Grow plan. The test run should confirm Alpha Vantage's Toronto bars and
currency, and show what Twelve Data and EODHD return for Toronto on a free key.
