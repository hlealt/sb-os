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
   - Header is correct (10 expected columns)
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

4. STOP. Wait for user confirmation.

## Step Menu

- **[C] Continue** → proceed to Step 04 (Categorize)
- **[X] Exit** → halt workflow
