# README artwork

- `wealth-ledger-mark.svg` is original project artwork, distributed under the project's MIT license.
- `report-preview.png` is generated exclusively from the repository's invented offline demonstration. It contains no real user's accounts, balances, reference prices, or broker export.
- The public preview path is explicitly allowlisted; arbitrary images are not approved for publication.

Rebuild from a source checkout with its locked Python dependencies:

```bash
python scripts/render_readme_preview.py
```

The command creates its own temporary synthetic demo, refuses external portfolio inputs, and performs no market/reference downloads. It does not read or modify a real `data/`, `reports/`, SQLite database, or latest pointer. Regenerate when the example/report design changes, then inspect the image and rerun the publication check before staging.

README badges are external static Shields.io images. Their labels describe implemented capabilities, not remote CI, coverage, popularity, downloads, or a published package. They are optional documentation images, not runtime dependencies.
