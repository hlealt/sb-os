---
stepNumber: 7
stepId: snapshot
nextStepFile: step-08-report.md
---

# Step 7: Snapshot — Persist the Month's Snapshot

**Goal:** Copy `portfolio.json` to `portfolio-{MONTH}-LAST_DAY.json` and update `snapshots.json` for the dashboard's date selector.

## Mandatory Sequence

1. Set `{SNAPSHOT_DATE}` = last day of month `{MONTH}` (e.g.: `2026-04-30`).

2. Copy `{INV_LEDGER_DIR}/portfolio.json` → `{INV_LEDGER_DIR}/portfolio-{SNAPSHOT_DATE}.json`. If the file already exists (re-run), overwrite and report.

3. Update `{INV_LEDGER_DIR}/snapshots.json`:
   - Add an entry with `date: {SNAPSHOT_DATE}` pointing to the freshly-created file.
   - Include a summary: `total_brl`, `total_by_class`, `position_count`.
   - Keep the array sorted chronologically.
   - If an entry for `{SNAPSHOT_DATE}` already exists, overwrite it.

4. Report:

```
Snapshot persisted:
  portfolio-{SNAPSHOT_DATE}.json (R$ X.XXX.XXX, 78 positions)
  snapshots.json: +1 entry (or updated)
```

5. STOP. Wait for confirmation.

## Step Menu

- **Gatekeeper checkpoint** → before advancing, run § Per-Step Checkpoint in `../gatekeeper-loop.md` (out-of-structure → Rule A; detected issue, e.g. snapshot-triplet drift → Rule C blocking; direct data read → re-route through a `tools-index.md` tool).
- **[C] Continue** → proceed to Step 08 (Report)
- **[X] Exit** → halt workflow
