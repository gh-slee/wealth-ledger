<!-- Start with the problem and resulting behavior. Use a concrete example when
helpful. Keep small changes short; explain significant risks and migration needs.
Follow AGENTS.md writing guidance. Remove unused prose prompts. -->

## What and why

Explain what a reviewer or user can do after this change and why it is needed.
State whether this is backend-only or has a visible effect in the app.

## Review and validation

Point reviewers to the important behavior, material risks and relevant checks.
Link detailed CI evidence instead of pasting logs or exhaustive test inventories.
State meaningful gaps. Use synthetic data; exclude financial inputs and private paths.

- [ ] Final committed HEAD passed `python scripts/check_pr_image.py` (including docs-only changes).
- Candidate commit / immutable image ID and smoke result:

<!-- Link changed manuals or contracts if they help the reviewer. -->
