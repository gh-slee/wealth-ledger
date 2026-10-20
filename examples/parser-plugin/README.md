# Independently packaged synthetic parser

This MIT-licensed example demonstrates a third-party Python package importing the
installed Wealth Ledger contract, registering a versioned entry point and producing
validated **nonbooking** holdings evidence. It supports an invented format only;
it adds no bank, brokerage or exchange integration.

Build, isolated installation, input/config examples and installed CLI/API/worker
acceptance are in [the SDK guide](../../docs/parser-sdk.md). Build from a reviewed
checkout with `requirements-build.lock`; install the core and example wheels into
a disposable runtime with the existing locked dependencies. The core build's
private-data safeguards do not automatically apply to your own plugin package:
review its build configuration, wheel/sdist contents and provenance separately.

From the repository root, after installation:

```bash
.venv-sdk/bin/python -I -m unittest discover -s examples/parser-plugin/tests -v
```

The six parser tests are standard-library only. The seventh test needs the optional
Web test dependencies and runs the installed API and actual isolated worker. It
checks equality with a CLI plan and proves that the plan cannot book holdings.
Use the SDK acceptance script to verify the installed core outside the checkout
and three-locale report resources as well.

The parser preserves source IDs/revisions, BOM-independent record identity, Decimal
amounts, explicit timezones, unknown cost and partial source coverage. Its synthetic
fetched time is an explicitly warned source-time placeholder; real retrieval context
is a protocol-v2 requirement. No file/network/subprocess IO occurs in normalization.
Tests of common IO paths are a smoke check, not a sandbox or proof of safety.

Never add real exports, account identifiers, wallet data or credentials as fixtures.
Do not use successful structural tests to claim transactional deduplication,
verified transfers, investment contributions or financial completeness.


## Protocol-v2 report example

The same wheel has a separately enabled `synthetic_v2` entry point and
`synthetic.holdings-v2` adapter. Use the existing exact CSV columns with the distinct
`format` marker `synthetic-holdings-v2`. It supplies partial dated positions with
explicit context, original source IDs and nullable costs; it is not a real provider
or a complete holdings/cash/activity export. The current v2 demonstration accepts
original rows; correction/void reason support would require extending this invented
format rather than guessing omitted evidence. V1 remains unchanged/nonbooking.

The trusted configuration selection is:

```json
{
  "schema_version": 1,
  "enabled": [{
    "distribution": "wealth-ledger-synthetic-parser",
    "version": "0.1.0",
    "entry_point": "synthetic_v2",
    "adapter_id": "synthetic.holdings-v2"
  }],
  "bindings": []
}
```

Use the core's advanced `wealth-ledger-source-reports` preview/confirm/resume
workflow with explicit context, per-portfolio mapping and valuation JSON. See the
repository's [complete examples](../../docs/source-projections.md#frozen-source-report-publication-src-004c3c1).
The installed acceptance test generates all three report formats through the real
console, then verifies receipt recovery without original files. This does not
remove the ordinary Web/CLI cutover gate or add a real institution integration.
