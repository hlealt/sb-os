---
stepNumber: 4
stepId: validate
nextStepFile: step-05-portfolio.md
---

# Step 4: Validate — Sanity Check vs Source Documents

**Goal:** Sample-validate that the inserted rows match the month's source documents — catches parser bugs before regenerating `portfolio.json`.

## Mandatory Sequence

1. For each ledger updated in Step 03 with new rows, do a spot-check:
   - Select 2-3 inserted rows (prefer highest value + most recent).
   - Compare with the original source document in `{INV_RAW_DIR}/`.
   - Verify: `date`, `quantity`, `price`, `total` (orders); `date`, `gross_value` (proventos); `date`, `amount` (balcao); `date`, `buy_quantity`, `sell_quantity` (crypto).

2. **Minimum coverage:** B3 (orders + proventos), Safra (balcao), Avenue (orders + fx, if present), one crypto exchange (if present).

3. Present to the user:

```
Spot-check for month {MONTH}:

  orders.csv (B3):
    [✓] 2026-04-08 PETR4 100×R$38,15 = R$3.815 → matches b3-movimentacao.xlsx
    [✓] 2026-04-15 BRK.B 2×US$405,12 = US$810,24 → matches avenue-notas/...

  proventos.csv (B3):
    [✓] 2026-04-12 BBAS3 dividend R$87,50 → matches

  balcao.csv (Safra):
    [✓] 2026-04-30 SAFRA ABS aplicação R$10.000 → matches safra-fundos.csv

  avenue_fx.csv:
    [✓] 2026-04-10 USD 500 @ 5,12 = R$2.560 → matches receipt

Discrepancies: none | OR list
```

4. If there are discrepancies:
   - Report to the user with details (expected vs found, source vs ledger).
   - Ask: "Parser bug, wrong source data, or accept?"
   - If a parser bug: ledgers are append-only — manual removal + parser fix + re-run of Step 02-03 for the affected file.
   - Do not proceed to Step 05 while discrepancies remain unresolved.

5. **Completion gate — spot-check coverage (`gate_spot_check_coverage.py`, gate #7 — auto-halt).** Mechanizes the "Minimum coverage" of step 2: ensures every mandatory class was in fact spot-checked before Step 05.

   a. Write the coverage-record JSON to `{INV_PROCESSED}/.spot-check-coverage.json` with EXACTLY these keys (gate #7 reads only these):

      ```json
      {
        "checked": ["b3_orders", "b3_proventos", "safra_balcao", "avenue_orders", "avenue_fx", "crypto_exchange"],
        "present_sources": ["b3", "safra_balcao", "avenue", "crypto"]
      }
      ```

      - `checked`: the class tokens YOU in fact spot-checked in step 1 (use the literals the gate recognizes: `b3_orders`, `b3_proventos`, `safra_balcao`, `avenue_orders`, `avenue_fx`, `crypto_exchange`).
      - `present_sources`: which sources exist this month — determines which conditional classes are required. Include `avenue` if there are Avenue files; `crypto` if there is a crypto exchange. `b3` and `safra_balcao` are always required.

   b. Run the gate:

      ```bash
      python "{SCRIPTS_DIR}/gate_spot_check_coverage.py" --coverage-record "{INV_PROCESSED}/.spot-check-coverage.json"
      ```

      Always-required classes: `b3_orders`, `b3_proventos`, `safra_balcao`. Conditional: `avenue_orders`/`avenue_fx` (if `avenue` present), `crypto_exchange` (if `crypto` present). Exit 0 = all covered; exit 1 = one or more mandatory classes not checked; exit 2 = record missing/malformed.

   - **Exit 0** → record the pass and proceed.
   - **Exit 1 (FAIL)** → Rule C **blocking** (`../gatekeeper-loop.md`). Do NOT advance to Step 05. Spot-check the missing classes, rewrite the coverage-record, and run the gate again. The step does not advance until exit 0.

6. STOP. Wait for confirmation.

## Step Menu

- **Gatekeeper checkpoint** → before advancing, run § Per-Step Checkpoint in `../gatekeeper-loop.md`. A spot-check discrepancy (source vs ledger) is a Rule C blocking issue — surface inline with a proposed fix (parser bug → fix + re-parse; source error; accept). Do the spot-check by reading sample rows through a `tools-index.md` tool (`sample_from_ledger` / `position_summary`), not by opening ledger CSVs directly. The spot-check coverage gate (#7) above auto-halts before Step 05 if any mandatory class was skipped.
- **[C] Continue** → proceed to Step 05 (Portfolio)
- **[B] Back** → go back to Step 02/03 to correct
- **[X] Exit** → halt workflow
