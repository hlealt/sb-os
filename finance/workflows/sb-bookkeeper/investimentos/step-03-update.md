---
stepNumber: 3
stepId: update
nextStepFile: step-04-validate.md
---

# Step 3: Update — Ledger Update

**Goal:** Apply the normalized CSVs from `{INV_PROCESSED}/` to the permanent ledgers in `{INV_LEDGER_DIR}` via `update_ledgers.py`. Exact match (tolerance 0) — recurring monthly flow.

## Pre-Script Action — Lot Splits

**Source.** `{CONFIG_DIR}/lot-splits.yaml` (formerly inlined into a YAML companion file at `.user/context/accountant/investimentos/step-03-update.yaml` before the rename; consolidated here on 2026-05-05 per p1-15).

**MANDATORY pre-script action.** Execute BEFORE the `python update_ledgers.py` command below. The splits modify the processed CSVs in `{INV_PROCESSED}/` so that the script picks up already-split rows and dedup behaves naturally on re-runs.

For each entry under `splits:` in `lot-splits.yaml`:

1. Determine which processed CSV(s) to scan. The `primary_id` lives in `balcao.csv` ledger, so check `{INV_PROCESSED}/b3_balcao.csv` (and any other `*_balcao.csv` for the same month). If none of the processed files contains rows with `product_id == primary_id`, skip this split entry silently.

2. For each matching row in the processed CSV:
   a. Validate `quantity == total_units`. If not, STOP and ask the user — a buy/sell since last close changed the lot ratio, and the config needs to be updated before continuing.
   b. Replace the matching row with one row per lot in `lots`:
      - `quantity` = `lot.units`
      - `amount`   = `round(original_amount × lot.units / total_units, 2)`
      - the LAST lot absorbs rounding so the sum equals `original_amount` exactly (compute as `original_amount` minus sum of prior lots)
      - keep `date`, `operation`, `product_type`, `irrf`, `iof`, `broker`, `source` identical to the original row

3. Before saving the modified processed CSV, show the user a table of the proposed splits (original row → split rows) and ask for confirmation. Do NOT auto-apply.

4. After confirmation, save the modified processed CSV in place. Then proceed with the normal Step 03 sequence (`update_ledgers.py`).

5. Mention the splits in the Step 03 report shown to the user (e.g., `balcao.csv +7 (includes +1 row from TAEB15 lot split)`).

If `splits:` is empty or no processed file contains matching rows, skip silently — no user prompt needed.

## Mandatory Sequence

1. Run the script (with `--report-out` to feed gate #6 in step 7):

```
python {INV_SCRIPTS_DIR}/update_ledgers.py "{INV_PROCESSED}" --tolerance 0 --report-out "{INV_PROCESSED}/.upsert-report.json"
```

2. The script:
   - Identifies the destination ledger by the normalized file's prefix (`b3_orders.csv → orders.csv`, `safra_balcao.csv → balcao.csv`, etc.).
   - Applies an exact match on identity + numeric fields.
   - Inserts only new rows (dedup guarantees idempotency — safe to re-run).
   - Returns a report with: tolerance used, inserted per ledger, skipped (exact match), skipped (fuzzy match — must not occur with tolerance 0), forced duplicates.

3. If the script fails mid-execution, ledgers may be partially updated. Re-running is safe — dedup prevents duplication. Report the complete error and ask how to proceed.

4. Present the report to the user in summary form:

```
Ledgers updated (tolerance 0):
  orders.csv      +12 (3 already existing skipped)
  proventos.csv   +8
  balcao.csv      +5
  crypto.csv      +6
  corporate_actions.csv  +1
  avenue_fx.csv   +2

Special cases: none | OR detailed list
```

5. **Fuzzy matches or forced duplicates** — if they appear (they must not with tolerance 0), list them individually. The user must confirm they are real duplicates or flag them as a bug.

6. **Fee update from authoritative source** (`--update-fees`) — do NOT use in the monthly flow by default. Reserved for historical reconciliation when a more authoritative source (B3) corrects imprecise fees from an earlier source (spreadsheet). Mention the option only if the user asks.

7. **Completion gate — match tolerance = 0 (`gate_ledger_tolerance.py`, gate #6 — auto-halt).** Run the gate over the upsert report written in step 1:

   ```bash
   python "{SCRIPTS_DIR}/gate_ledger_tolerance.py" --report "{INV_PROCESSED}/.upsert-report.json"
   ```

   The gate fails (exit 1) if ANY ledger has a non-empty `skipped_fuzzy` — with `--tolerance 0` a fuzzy match indicates a parser or data bug. Exit 0 = no fuzzy match; exit 2 = report missing/malformed.

   - **Exit 0** → record the pass and proceed.
   - **Exit 1 (FAIL)** → Rule C **blocking** (`../gatekeeper-loop.md`). Mechanizes step 5 above as an exit-code gate. Surface the fuzzy matches inline, propose the fix (confirm a real duplicate → record it; or flag as a bug → fix the parser and re-run Step 02-03), and offer `[S]`/`[N]`. Do NOT proceed to Step 04 while a fuzzy match remains unresolved.
   - **Exit 2** → report missing; re-run step 1 with `--report-out` and try again.

8. STOP. Wait for the user's confirmation before proceeding.

## Step Menu

- **Gatekeeper checkpoint** → before advancing, run § Per-Step Checkpoint in `../gatekeeper-loop.md`. A fuzzy match or forced duplicate (should not occur at tolerance 0) is a Rule C blocking issue — surface inline with a proposed fix; a lot-split ratio mismatch is a deviation (Rule A). The ledger-tolerance gate (#6) above is the exit-code form of this blocking check.
- **[C] Continue** → proceed to Step 04 (Validate)
- **[R] Re-run** → re-run update_ledgers.py
- **[X] Exit** → halt workflow
