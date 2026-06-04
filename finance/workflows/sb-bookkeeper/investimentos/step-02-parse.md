---
stepNumber: 2
stepId: parse
nextStepFile: step-03-update.md
---

# Step 2: Parse — Per-Source Normalization

**Goal:** Run the parsers for each source present in `{INV_RAW_DIR}/` and generate normalized CSVs in `{INV_PROCESSED}/`. Resolve `name_map.csv` pending items and corporate-action ratios.

## Mandatory Sequence

1. **Clear `{INV_PROCESSED}/`** — delete all existing `*.csv` files BEFORE any parser runs. This folder is scratch (overwrite per month); leftovers from previous months corrupt `update_ledgers.py` (it would re-import old data). Create the folder if it does not exist.
2. For each file present in `raw/`, invoke the corresponding parser:

| Source | Parser (module) | Input | Output(s) in `processed/` |
|--------|-----------------|-------|---------------------------|
| B3 | `parsers.b3_parser` | `raw/b3-movimentacao.xlsx` | `b3_orders.csv`, `b3_proventos.csv`, `b3_balcao.csv`, `b3_corporate.csv` |
| Safra fundos (movements) | `parsers.safra_fundos_movimentacoes` | `raw/safra-fundos-{ANO}.csv` | `safra_fundos_balcao.csv`, `safra_fundos_seeds.csv`, `safra_fundos_snapshots.csv`, `assets.csv` (upsert) |
| Safra RF (movements) | `parsers.safra_rf_movimentacoes` | `raw/safra-rf-{ANO}.csv` | `safra_rf_balcao.csv`, `safra_rf_seeds.csv`, `safra_rf_snapshots.csv`, `assets.csv` (upsert) |
| Avenue (notas) | `parsers.avenue` | `raw/avenue-notas/*.pdf` | `avenue_orders.csv` |
| Avenue FX | `parsers.avenue_fx` | `raw/avenue-cambio/*.pdf` | `avenue_fx.csv` |
| Bipa | `parsers.bipa` | `raw/bipa-extrato.csv` | `bipa_crypto.csv` |
| Mercado Bitcoin | `parsers.mercado_bitcoin` | `raw/mb-extrato.csv` | `mb_crypto.csv` |
| Mercado Pago (inv) | `parsers.mp_investimentos` | `.user/finance/bookkeeper/ledgers/expenses/{MONTH}/mp_extrato.csv` | `mp_balcao.csv` |

The parsers are independent — they can run in any order. If a parser fails with a format error, report the complete error to the user and ask how to proceed. Do not block the execution of the others.

3. **name_map resolution** — if a parser returns unmapped values (`name_map.csv` at `{INV_LEDGER_DIR}/name_map.csv`):
   - The parser does not process the rows with unknown values (but processes the rest).
   - Present the list to the user: `source / field / raw_value`.
   - Ask: "What are these items?"
   - Insert the canonical mappings into `name_map.csv` (append).
   - Re-run only the affected parsers.
   - Repeat until no pending items remain.

4. **Corporate actions without ratio** — the B3 parser may generate entries in `b3_corporate.csv` without `ratio_from`/`ratio_to` (Grupamento, Cisão, Bonificação):
   - For each flag, research the ratio in official sources (CVM, fato relevante, company site) using ticker + date.
   - If found, fill `ratio_from`/`ratio_to` in the normalized CSV BEFORE proceeding.
   - If not found, ask the user. If the user does not know, proceed with an empty ratio and log a pending item at the end.

5. **Flagged operations** — if the B3 parser returns operations marked as "flag" in the classification table (not automatically classifiable):
   - Present to the user: date, movement, product, amounts.
   - The user indicates the treatment (ignore, order, dividend, etc.).
   - If it is a recurring pattern, suggest adding it to the parser's classification table.

6. **Completion gate — parser total sanity (`gate_parser_total_sanity.py`, gate #5 — auto-halt).** Run the gate over the freshly-parsed `*orders*.csv`. `{INV_PROCESSED}/` contains ONLY the files parsed this session (step 1 clears the folder first) — so `--orders-dir {INV_PROCESSED}` is exactly the "new rows" slice for this month (not historical data):

   ```bash
   python "{SCRIPTS_DIR}/gate_parser_total_sanity.py" --orders-dir "{INV_PROCESSED}"
   ```

   The gate verifies `total ≈ quantity × price + fees` (0.5% tolerance) on each row; `fees = fees_exchange + fees_brokerage + fees_irrf`. Exit 0 = all within tolerance; exit 1 = one or more violate (listed in stderr); exit 2 = no `*orders*.csv` file in `{INV_PROCESSED}` (the normal case when the month has no orders — treat as pass: there are no orders to validate).

   - **Exit 0** → record the pass and proceed.
   - **Exit 1 (FAIL)** → Rule C **blocking** (`../gatekeeper-loop.md`). Surface the violating rows inline, propose the fix (parser bug or wrong source data → correct and re-parse the affected file), and offer `[S]`/`[N]`. Do NOT proceed to Step 03 while a violation remains unresolved; the gate does not auto-loop (the root cause is in the source file or the parser).
   - **Exit 2 with no order files** → there are no orders this month; continue (vacuous pass). If you EXPECTED orders and they are missing, treat as the expected-source gate (step-01).

7. STOP. Present a summary:

```
Parsers run: B3 ✓, Safra ✓, Avenue ✓, Bipa ✓, MB ✓, MP ✓
Outputs in {INV_PROCESSED}/:
  - b3_orders.csv (12 rows)
  - b3_proventos.csv (8 rows)
  - b3_balcao.csv (3 rows)
  - safra_balcao.csv (2 rows)
  - avenue_orders.csv (4 rows)
  ...
Pending items: none | OR list of pending items (ratios, MP missing, etc.)
```

## Step Menu

- **Gatekeeper checkpoint** → before advancing, run § Per-Step Checkpoint in `../gatekeeper-loop.md`. Unmapped `name_map` values, missing corporate-action ratios, and flagged operations here are deviations — surface them via Rule A and route the resolution to durable structure (Rule B; a new parser case routes to Seam 1 `tool-builder`). A parser sanity-check failure (total ≈ qty×price+fees) is a Rule C issue.
- **[C] Continue** → proceed to Step 03 (Update Ledgers)
- **[R] Re-run** → re-run a specific parser
- **[X] Exit** → halt workflow
