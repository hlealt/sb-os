# Lint Step 9 handler — SUBDIVISION PROPOSAL

> **Loaded by** `sb-wiki-lint.md` Step 9 ONLY when the `subdivision-proposals` set is non-empty. Paths below are relative to THIS file's location (`wiki/workflows/sb-wiki-lint/extensions/`).

User response handling for SUBDIVISION PROPOSAL:

| Response | Behavior |
|----------|----------|
| `accept all` | Execute every proposed subdivision per the procedure in step 7.5 § "Subdivision execution". No log entry — the new folder structure and indexes are the record. |
| `accept N` (e.g. `accept 1,2`) | Execute the listed proposals only. Other proposals defer. |
| `reject` | All proposals defer; surface as warnings in the next lint run. |
| `defer` (default) | Same as `reject` for this run; proposals re-surface in subsequent runs as long as the kind remains ≥10 pages (threshold: `../../shared/folder-structure.md` § "Stability Rules"). |
