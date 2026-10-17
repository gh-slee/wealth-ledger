# Security and privacy

Wealth Ledger stores investment and transaction data locally. SQLite is unencrypted
by default. Ignore rules and publication checks reduce accidental commits; they do
not encrypt files or guarantee complete detection of personal information.

## User data

Keep databases, raw exports, reports, backups, private configuration and local agent
state in ignored locations. Never attach real CSVs, wallet addresses, account IDs,
credentials or personal financial values to public issues, PRs, Actions artifacts
or examples. Ignored files already tracked or present in Git history still need a
separate review.

Normal reporting queries public FX, BTC prices and official ETF sources; it should
not upload portfolios or broker exports. Offline previews and synthetic demos need
no network. GitHub publication is separate from daily imports.

## Optional Web foundation

The API uses a dedicated instance outside the code checkout. Trusted host commands
initialize/reset the sole owner; there is no public registration or owner claim.
Argon2id password hashes, hashed opaque sessions, bounded lifetimes, CSRF/Origin/Host
validation and persistent login budgets protect the implemented routes. The owner
can access all instance portfolios; this is not multitenant or family-member RBAC.
Private artifacts require session/ownership and bounded path/hash checks, and are
never mounted as public static files. These controls do not encrypt SQLite/backups.

Use the exact configured origin; non-loopback origins require HTTPS. Forwarded
headers are ignored by the supported host CLI. Keep the complete data directory,
secrets and backups private. Docker context generation uses reviewed source-only
inputs, a deny-by-default ignore file and explicit COPY paths; never include a real
workspace or publish an unreviewed image. The upload/job API uses bounded raw files, immutable hashes, offline previews and
fixed internal JSON queue notifications, never browser-supplied pickle or callables.
Unproven commit states require local review. React/full backup workflows and wider
platform/release acceptance remain pending. See [Web operations](docs/web-operations.md)
for implemented commands, security limits and remaining gates.

## Reporting a vulnerability

If GitHub private vulnerability reporting is enabled, submit a private report from
the repository's Security page. Otherwise, contact the maintainer through GitHub to
arrange a private channel before sharing details. Do not open a public issue with
sensitive information.

Provide a minimal synthetic reproduction, version, platform, and expected/actual
behavior. If financial data or credentials are exposed, stop related publication,
revoke exposed credentials and coordinate remediation. Deleting the latest file
does not erase Git history or copies others have downloaded.

The project is an early `0.1.x` release. Security fixes target the latest version;
there is no commitment to maintaining historical release branches yet.
