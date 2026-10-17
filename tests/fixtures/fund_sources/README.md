# Synthetic source-format fixtures

These are independently authored minimal parser fixtures, not copies of official
website responses or downloaded workbooks. Companies, positions, weights, dates,
identifiers and classifications are invented. Parser-required public fund IDs,
field names and specific labels are retained for format/source detection.

Fixtures contain no website code, tracking parameters, session metadata, complete
holdings tables or original workbook properties. The XLSX is an independently
generated minimal OOXML ZIP. These synthetic fixtures use the project's MIT license.

## Format references

These URLs identify the supported formats, not the source of fixture financial data:

- Vanguard GraphQL: `https://www.vanguard.ca/gpx/graphql`; `delayeredHoldings`, pagination and `portIds`.
- BlackRock CSV: `https://www.blackrock.com/ca/investors/en/products/332756/fund/1464253357814.ajax?fileType=csv&fileName=XCHP_holdings&dataType=fund`.
- VanEck XLSX: `https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/downloads/holdings/`.
- BMO GraphQL: `https://df.bmogam.com/api/graphql/etf-funds-production`; public profile `ZNQ-a`.
- Fidelity JSON: `https://fidcaproductsapi.fidelity.ca/FidcaProductsAPI/api/fundPage/fund/EN/FBTC`.
- CI HTML: `https://funds.cifinancial.com/en/create-html-for-pdf.html?series_id=49756`.
- Invesco JSON: `https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/46138G649/holdings/fund?idType=cusip&productType=ETF`.

## Coverage

Fixtures cover percentage/fractional weights, negative cash, missing weights, cash,
crypto, ADRs, underlying funds, distinct effective/NAV dates and pagination total/
cursor completeness. Classification tests use explicit GICS and ICB fields; an
arbitrary industry label cannot establish its taxonomy.

Tests are offline. Fixtures are not production fallbacks, latest official holdings
or price evidence. Normal updates still obtain published data through official adapters.
