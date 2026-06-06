---
stepNumber: 4
stepId: categorize
nextStepFile: step-05-review.md
---

# Step 4: Categorize

**Goal:** Run `categorize.py` to auto-classify transactions, then read its structured stdout to surface unknowns by item type (categories, suppliers) — priming Pass 1 of the review queue in step-05. Tag unknowns are built from the `tags` column by `queue.py`, not emitted by `categorize.py`.

## Mandatory Sequence

1. Run:
   ```bash
   python "{SCRIPTS_DIR}/categorize.py" "{PROCESSED_DIR}" "{CONFIG_DIR}" "{DASHBOARD_DATA}/{MONTH}"
   ```

2. Parse the script stdout for the two structured sections emitted by `categorize.py`:
   - `UNKNOWN CATEGORIES` — transactions with `category = a_identificar` (description, bank, amount, date).
   - `UNKNOWN SUPPLIERS` — distinct descriptions where alias detection produced no canonical supplier (grouped by description, count per group).

   Each section starts with `Count:`. Read the counts and the sample rows.

3. Report the counts to the user in a single line:

   ```
   Unknown categories: {N1} · Unknown suppliers: {N2}
   ```

   If any count is zero, still report it (`0`) — the review queue in step-05 silently skips empty item-type batches per the queue ordering invariant.

4. Confirm to the user that the CSV was written to `{DASHBOARD_DATA}/{MONTH}/transactions.csv` with the new schema (`data_caixa`, `data_competencia`, `supplier_canonical`, `tags`).

5. Hand off to step-05 carrying the parsed unknowns, batched by item type (categories → suppliers → tags) — this ordering is mandatory for the two-pass queue (Pass 1 must close before Pass 2 boundary prompts can fire in step-05).

6. STOP. Wait for confirmation.

## Step Menu

- **Gatekeeper checkpoint** → before advancing, run § Per-Step Checkpoint in `../gatekeeper-loop.md` (out-of-structure → Rule A; detected issue → Rule C blocking/deferrable; direct data read → re-route through a `tools-index.md` tool). The unknowns surfaced here (categories/suppliers) plus tag unknowns from the queue are the deviation-to-structure protocol's input — Step 05 resolves them per Rule B.
- **[C] Continue** → proceed to Step 05 (Pass 1 — Resolve unknowns)
- **[X] Exit** → halt workflow
