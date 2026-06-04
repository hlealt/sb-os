---
stepNumber: 5
stepId: portfolio
nextStepFile: step-06-review.md
---

# Step 5: Portfolio — Recompute `portfolio.json` and Snapshots

**Goal:** Regenerate `portfolio.json` from the updated ledgers and update `balance-snapshots.csv` with end-of-month balances for RF/fundos.

## Mandatory Sequence

1. **Import balance snapshots** (RF + fundos) — for sources that provide a balance in a statement (not derivable from the ledgers):

   ```
   python {INV_SCRIPTS_DIR}/import_balance_snapshots.py --month {MONTH}
   ```

   If the script asks for source-specific input (Safra títulos, etc.), follow the script's instructions. If there are no balance statements, skip this step and proceed.

2. **Regenerate `portfolio.json`:**

   ```
   python {INV_SCRIPTS_DIR}/calculate.py --cut-date {MONTH}-LAST_DAY
   ```

   - `{MONTH}-LAST_DAY` = last day of the month (e.g.: `2026-04-30`).
   - The script orchestrates: position_calculator → fx_engine → price_fetcher → irr_calculator → writes `portfolio.json` to `{INV_LEDGER_DIR}/portfolio.json`.
   - If the user has no internet or wants to skip price fetching, use `--no-prices`.

3. Report to the user:

```
portfolio.json regenerated for cut-date {MONTH}-LAST_DAY:
  - Positions: 78 (variable: 24, RF: 42, crypto: 6, fundos: 6)
  - Total: R$ X.XXX.XXX
  - Prices: 22 fetched, 56 from snapshots, 0 missing
  - IRR computed: ✓
balance-snapshots.csv: +N rows
```

4. **Price pending items** — if `price_source: "missing"` on any relevant position, list them and ask the user whether to proceed anyway or wait.

5. STOP. Wait for confirmation.

## Step Menu

- **Gatekeeper checkpoint** → before advancing, run § Per-Step Checkpoint in `../gatekeeper-loop.md`. Missing prices (`price_source: "missing"`) on relevant positions are a Rule C issue — surface and let the user decide proceed vs wait; a rate shape `calculate.py` cannot classify is a deviation (Rule A → Rule B).
- **[C] Continue** → proceed to Step 06 (Review)
- **[R] Re-run** → re-run calculate.py
- **[X] Exit** → halt workflow
