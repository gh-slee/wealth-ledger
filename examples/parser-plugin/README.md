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
