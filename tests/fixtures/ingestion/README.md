# Synthetic ingestion vectors

`oracle.json` contains literal invented CSV data and expected evidence, entity
bodies, financial projections, source identities, reviews and plans for the V2
ingestion contract. It contains no maintainer ledger, wallet, credentials or
private agent instructions. Placeholder installation and image hashes are test
bindings; they do not establish an installed or contained runtime.

Tests must compare implementation output with these literal expected values.
Do not calculate expected financial effects by calling the reconciliation code
being tested. Parser, database, concurrency, TLS, Linux containment and restore
tests establish different properties and must report their own evidence.

The complete/partial/empty snapshot families preserve historical observations.
An omitted holding is not a synthesized zero record. The repeated-trade examples
separate exact source identity from local row order, file hashes and equal amounts.
Unknown fees, contributions and wallet balances remain unknown.

Native expected evidence retains the exact reviewed profile policy token;
parser2 expected evidence keeps its source-supplied prose. Native policy cases
also cover rehashed wrong tokens, unchanged closed inputs and ambiguous-policy
limits. Rule-unit positives do not establish installed profiles or READY imports.
