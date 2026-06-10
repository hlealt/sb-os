# Lint Step 9 handler — LINK-FIX PROPOSAL (broken-link bucket A)

> **Loaded by** `sb-wiki-lint.md` Step 9 ONLY when the broken-link bucket-A proposal set is non-empty. Paths below are relative to THIS file's location (`wiki/workflows/sb-wiki-lint/extensions/`).

User response handling for LINK-FIX PROPOSAL (broken-link bucket A, step 5):

| Response | Behavior |
|----------|----------|
| `accept all` | Build a plan of all bucket-A rows (`{file, old, new}` where `old` = broken target, `new` = `suggestion`) and run `python {sb_os_path}/wiki/scripts/sb-wiki-lint-deterministic.py --execute-link-fixes <plan.json>` from the vault root. Then re-read `detected.link_fixes` and resolve every `skipped`/`errors` entry. No log entry. |
| `accept N` (e.g. `accept 1,2`) | Plan + execute the listed rows only. Others defer. |
| `reject` | All fixes defer; broken links persist and re-surface next lint run. |
| `defer` (default) | Same as `reject` for this run; re-detected next run while the link stays broken. |
