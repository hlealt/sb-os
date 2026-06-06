---
stepNumber: 3
stepId: validate
nextStepFile: step-04-categorize.md
---

# Step 3: Validation Checkpoint

**Goal:** Verify that all normalized CSVs are structurally correct before categorization.

## Mandatory Sequence

1. Read each CSV in `{PROCESSED_DIR}/`.
2. For each file, verify:
   - Header matches `NORMALIZED_COLUMNS` (12 columns: date, description, amount, balance, bank, source_type, currency, original_ref, installment_current, installment_total, original_amount, exchange_rate)
   - Dates are within the expected month (±5 day tolerance for boundary transactions)
   - `amount` values are numeric (no NaN, no text)
   - Transaction count is reasonable (not zero for banks with a file present)
3. Report to the user:

```
Normalized CSV validation:
  bradesco_extrato.csv — 8 transactions, dates 02/27 to 03/27 ✓
  xp_extrato.csv — 114 transactions, dates 03/02 to 03/31 ✓
  santander_extrato.csv — 17 transactions ✓
  nubank_fatura.csv — 6 transactions ✓
  wise_extrato_USD.csv — 2 transactions ✓

Any issues? If not, I'll proceed to categorization.
```

4. Run the transaction-count completion gate (`gate_transaction_count.py`, gate #4 — auto-halt) over the normalized CSVs:

   ```bash
   python "{SCRIPTS_DIR}/gate_transaction_count.py" --expenses-dir "{PROCESSED_DIR}" --month {MONTH}
   ```

   The gate fail-loud halts when any present CSV has zero rows or when >10% of its rows fall outside the expected month ±5 days — the machine-checkable form of the manual checks in step 2. Exit 0 = pass; exit 1 = fail; exit 2 = directory error.

   - **Exit 0** → record the pass and continue to step 5.
   - **Exit 1 (FAIL)** → Rule C **blocking** (`../gatekeeper-loop.md`). Do NOT advance. Surface the failing file(s) inline, propose the fix (re-export the empty/short file, or correct a parser/date issue, then re-run step-02 and this gate), and offer `[S]`/`[N]`. The step does not advance until the gate returns exit 0.
   - **Exit 2** → report the directory error and ask how to proceed.

5. STOP. Wait for user confirmation.

## Step Menu

- **Gatekeeper checkpoint** → before advancing, run § Per-Step Checkpoint in `../gatekeeper-loop.md` (out-of-structure → Rule A; detected issue → Rule C blocking/deferrable; direct data read → re-route through a `tools-index.md` tool). The transaction-count gate above is this step's Rule C blocking gate — a non-zero exit halts the close.
- **[C] Continue** → proceed to Step 04 (Categorize)
- **[X] Exit** → halt workflow
