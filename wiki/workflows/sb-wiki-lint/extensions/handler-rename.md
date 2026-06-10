# Lint Step 9 handler — RENAME PROPOSAL (PDF title-conformance)

> **Loaded by** `sb-wiki-lint.md` Step 9 ONLY when the `rename-proposals` set is non-empty. Paths below are relative to THIS file's location (`wiki/workflows/sb-wiki-lint/extensions/`).

User response handling for RENAME PROPOSAL:

| Response | Behavior |
|----------|----------|
| `accept all` | Execute every proposed rename per step 7.6 § "PDF title-conformance execution" — rename raw + source page and rewrite the full referrer set. No log entry. |
| `accept N` (e.g. `accept 1,2`) | Execute the listed renames only. Others defer. |
| `reject` | All renames defer; re-surface next run. |
| `defer` (default) | Same as `reject` for this run; proposals re-detect next run while the mismatch persists. |
