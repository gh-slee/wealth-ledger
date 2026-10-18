# Adopt recognized legacy reports without rewriting history

Some older CLI publications contain the original ODS, Markdown, PDF, charts and
`data.json`, but their `manifest.json` predates `bundle_files` and `data_sha256`.
The default [adoption workflow](web-adoption.md) refuses these reports. Missing old
checksums do not by themselves prove loss or corruption; they also cannot establish
that current bytes are identical to the original historical publication.

## Explicit trusted-host acceptance

Stop source writers, retain the original workspace and protected backup, and initialize
a separate Web instance first. The source and destination must match the supported
financial schema and all ordinary evidence/lock/size checks still apply. Preview with
one additional option:

```bash
python scripts/web.py --data-root "$HOME/.local/share/wealth-ledger/web-instance" adopt-preview \
  --workspace "$HOME/.local/share/wealth-ledger/cli-workspace" \
  --name "Investment ledger" \
  --allow-legacy-reports \
  --output "$HOME/.local/state/wealth-ledger/adoption/legacy.adoption.json"
```

Create the private output directory first, as in [the adoption guide](web-adoption.md).
The response gives the number of legacy reports and states the evidence limitation.
Review the private plan's source/destination, exact inventory, original manifest and
artifact hashes, report cutoffs/snapshot IDs, and the `migration_capture` basis.
Only then confirm its exact canonical digest:

```bash
python scripts/web.py --data-root "$HOME/.local/share/wealth-ledger/web-instance" adopt-confirm \
  --plan "$HOME/.local/state/wealth-ledger/adoption/legacy.adoption.json" \
  --plan-sha256 '<plan_sha256 returned by adopt-preview>'
```

Confirmation rechecks the source and copied bytes against that reviewed plan. The
flag is recorded in the plan; it is not a global setting or an automatic fallback.
Source changes, engine changes, unknown locks or unsupported files require a new
preview/review. Confirmation never generates a new report or financial observation.

## Accepted format and preserved evidence

The recognized pre-checksum profile requires `snapshot_id`, `snapshot_as_of`,
`report_generated_at`, `import`, `workbook_validation`, `reporting` and `database_backup`.
Known optional fields cover combined observations, source/quantity status, official
look-through/classification and presentation validation. Unknown fields are rejected.
Cutoffs must have offsets; the payload must retain matching cutoff/snapshot identity
and supported accounts/positions/totals. Declared report/chart/supplement paths must
refer to retained members. This is not a generic loader for arbitrary older schemas.

Any modern marker (`bundle_files`, `data_sha256`, `financial_fingerprint`,
`previous_latest`, `localization`) selects the existing strict modern validation.
A partial, corrupt or mixed modern manifest never falls back to legacy acceptance.
As the old format is unsigned and unversioned, this is bounded format recognition,
not proof that a trusted operator's input was never deliberately changed before preview.

All original files stay byte-identical, including the old manifest. The migration
receipt separately captures the exact relative member set, sizes and SHA-256 values,
original manifest hash, source operation/snapshot/cutoff, original report-generation
time and migration capture time. It is stored privately under `admin/adoptions/`;
the report's Web registration pins that evidence digest and capture time. Existing
financial rows, identifiers, append-only revisions, language and cost settings are
preserved. Do not add checksums to the original manifest or backdate new evidence.

The report summary preserves the legacy manifest's report-generation time in its
published-time display, rather than showing adoption time as historical publication.
The API exposes `verification_basis: "migration_capture"`; modern reports use
`"publication_manifest"`. The browser shows the migration-time limitation in all
three product locales in both report analysis and the report library. Changing the
interface language only changes presentation; unknown historical fields remain unknown.

## Downloads, exports and backups

Single-file downloads and frozen payload/data exports require the same receipt,
registration/member scope, original manifest and requested-file hash checks. They do
not silently recreate a missing receipt or accept a new file as an old member.
Changing even a same-size requested artifact fails its hash check. ZIP/full backups
check every included artifact. CSV/JSON exports carry the verification basis alongside their frozen scope and cutoff.
No live quote, source import, report generation or LLM is involved in reading/exporting these reports.

A legacy report ZIP contains the untouched original report files and an additional
`migration-verification.json` with the separate evidence, capture time and limitation.
That reserved filename cannot already exist in an accepted source bundle. This
additional export member does not rewrite the original manifest. The separate
receipt is also retained in full private instance backups; empty-target restore
checks registrations, receipt binding, member scope and file hashes before serving.
Missing/changed/cross-portfolio evidence fails closed after restore too.

The usual [export and backup bounds](web-backups.md) apply: supported artifact types,
64 MiB per artifact, 256 MiB/2,000 members per report, bounded private receipts and
validated paths. Symlinks, traversal, missing required outputs, unsupported payloads,
unknown format fields and duplicate JSON keys are rejected. The only workspace-level
report link supported remains the validated relative `reports/latest` link.

Private plans, receipts and exported verification JSON contain portfolio metadata;
keep them private. A hash inventory is damage/change detection, not a signature,
independent audit, historical authenticity proof, tax basis or permission to publish
financial data.

## Acceptance and recovery

`tests/test_web_legacy_adoption.py` uses independently authored synthetic old-format
manifests with invented ledger/report data. It verifies explicit acceptance, modern
rejection boundaries, three locales, original dates/bytes/financial IDs, mixed editions,
ZIP/CSV/JSON/single downloads, evidence/registry tampering, repeat confirmation,
interrupted copies and full backup/empty-root restore. The browser fixture additionally
adopts an invented CLI ledger through the real service and exercises three-locale
notices, accessibility and downloads. Opt-in Docker acceptance adopts an invented old
publication and verifies its evidence/analysis/ZIP after restoration to a new volume.
Never substitute a real portfolio for these tests.

Recovery follows [ordinary adoption](web-adoption.md): reuse the same reviewed plan
and digest for an interrupted exact copy. Unexpected local changes are retained for
host review. A missing proof or changed artifact is not repaired by rerunning adoption,
reimporting CSVs, recalculating history or weakening modern validation.
