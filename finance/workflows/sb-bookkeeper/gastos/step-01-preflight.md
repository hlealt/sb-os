---
stepNumber: 1
stepId: preflight
nextStepFile: step-02-normalize.md
---

# Step 1: Pre-flight Check and Filename Normalization

**Goal:** Identify each downloaded file, map it to the correct bank, and rename to the standard filename expected by `normalize.py`.

## Help — Where to download and where to save

BEFORE any scan, read `{CONFIG_DIR}/banks.json` and render a table with one row per bank and three columns:

| Column | Value |
|--------|-------|
| Source | bank `name` |
| What to download | bank `download_hint` |
| Where to save | `{RAW_DIR}/{standard_filename}` |

Example of what the user should see (for `{MONTH}=2026-04`):

```
| Source                                 | What to download                             | Where to save                                                        |
|----------------------------------------|----------------------------------------------|----------------------------------------------------------------------|
| Bradesco — Extrato Conta Corrente      | Bradesco app > Extrato > Export CSV          | .user/finance/bookkeeper/raw-data/2026-04/expenses/extrato-bradesco.csv |
| Santander — Extrato Conta Corrente     | Santander Internet Banking > Extrato > PDF   | .user/finance/bookkeeper/raw-data/2026-04/expenses/extrato-santander.pdf|
| Santander — Fatura Cartão Visa         | Santander email or app > Fatura > Download PDF | .user/finance/bookkeeper/raw-data/2026-04/expenses/fatura-santander.pdf |
| Mercado Pago — Extrato Conta           | Mercado Pago app > Extrato > Export CSV      | .user/finance/bookkeeper/raw-data/2026-04/expenses/extrato-mercado-pago.csv |
| Wise — Extrato Multi-Moeda             | Wise > Statements > Export CSV (per currency)| .user/finance/bookkeeper/raw-data/2026-04/expenses/wise/extrato-wise-{MOEDA}.csv |
| Mercado Pago — Fatura Cartão           | Mercado Pago email > Fatura attached as PDF  | .user/finance/bookkeeper/raw-data/2026-04/expenses/fatura-mercado-pago.pdf |
| Nubank — Fatura Cartão                 | Nubank app > Fatura > Download PDF or email  | .user/finance/bookkeeper/raw-data/2026-04/expenses/fatura-nubank.pdf    |
| XP — Fatura Cartão                     | XP app > Cartão > Fatura > Export CSV        | .user/finance/bookkeeper/raw-data/2026-04/expenses/fatura-xp.csv        |
```

After rendering the table, ask: "Have you downloaded all the files to `{RAW_DIR}/`? [S/N]".

- If **N** → use the table as a guide, wait for the user to download, and only then proceed.
- If **S** or if files already exist in `{RAW_DIR}/` → proceed. The agent handles identification and renaming automatically — the user does NOT need to rename manually.

## Naming Convention

Standard: `{tipo}-{banco}.{ext}` — defined in the `standard_filename` field of each bank in `banks.json`.

## Mandatory Sequence

1. Read `{CONFIG_DIR}/banks.json` to list all configured banks and their `standard_filename`.
2. Scan `{RAW_DIR}/` and subfolders to find files (PDF, CSV). Create `{RAW_DIR}/` if it does not exist.
3. For each file, attempt automatic identification:
   - If the name already matches `standard_filename` → direct match.
   - For CSVs: read the first 5 lines and compare known headers (e.g., `Data;Hist` = Bradesco, `RELEASE_DATE;TRANSACTION_TYPE` = Mercado Pago bank statement, `Data;Estabelecimento;Portador` = XP credit card invoice).
   - For PDFs: use name heuristics (e.g., `extrato_conta` = Santander bank statement, `Fatura_*_VISA_*` = Santander credit card invoice, `Nubank_*` = Nubank credit card invoice).
   - **Same-issuer multi-file disambiguation:** when two or more files come from the SAME issuer but map to DIFFERENT sources (e.g., two Santander faturas from different cards), filename and page-1 visual heuristics are NOT sufficient and file display/image order MUST NEVER be trusted to assign identity. Bind each physical file to its source by a deterministic parser signal: parse each candidate file and match its `extract_total` and transaction count to the card/source identity, and confirm that parsed total equals the file's OWN page-1 total before assigning a `standard_filename`.
4. Present to the user:

```
Files found vs. configured banks:

  Identified:
  [✓] Bradesco Bank Statement — 1fbc0c58-...csv → extrato-bradesco.csv
  [✓] Santander Bank Statement — extrato_conta (1).pdf → extrato-santander.pdf
  [✓] Mercado Pago Bank Statement — account_statement-...csv → extrato-mercado-pago.csv

  Not identified (assign manually):
  [?] credit-card-mp-statement.pdf — which bank?
  [?] fatura.pdf — which bank?

  Missing:
  [ ] Wise — no file found
  [ ] Nubank — no file found

Confirm mapping?
```

5. STOP. Wait for user confirmation.
6. After confirmation, rename all files in `{RAW_DIR}/` to their corresponding `standard_filename`.
7. Verify that all files were renamed correctly. For same-issuer multi-file sources, re-verify AFTER renaming that each file's parser signal (`extract_total` + transaction count) matches the source its name now claims — a swap is silent-wrong. Halt and correct if the post-rename parser signal contradicts the page-1 identity.

## Completion Gate — Expected-Source Coverage (auto-halt)

Before advancing, confirm every source expected for a close is actually present. Read `{CONFIG_DIR}/sources.yaml` and collect every entry with `enabled_for_close: true`. For the gastos flow, the expected SET is the bank/card sources among them (the entries whose `id` matches a bank in `banks.json`: e.g. `bradesco_extrato`, `santander_extrato`, `santander_fatura`, `mp_extrato`, `mp_fatura`, `wise_extrato`, `manual_cash`). An entry with `enabled_for_close: false` (e.g. `nubank_fatura`, `xp_fatura` — historical only) is NOT expected and its absence is fine.

Compare the expected set against the files identified in step 4. If an expected source has NO file:

- This is a Rule C **blocking** issue (`../gatekeeper-loop.md`). The close cannot proceed with a silently-missing expected source — a missing month of bank data would understate spending without any signal (silent-wrong is the worst outcome).
- Surface it inline: name the missing source(s), propose the fix (download the missing file into `{RAW_DIR}/`, or — if the source is genuinely not expected this month — set `enabled_for_close: false` for it in `sources.yaml`), and offer `[S]` approve / `[N]` reject.
- **STOP. Do NOT advance to step-02 while an expected source is missing and unresolved.** `manual_cash` is satisfied if the user confirms there were no cash expenses (it is reconciled in step-05 Section 2, not a file in `{RAW_DIR}/`).

## Step Menu

- **Gatekeeper checkpoint** → before advancing, run § Per-Step Checkpoint in `../gatekeeper-loop.md` (out-of-structure → Rule A; detected issue → Rule C blocking/deferrable; direct data read → re-route through a `tools-index.md` tool). The expected-source coverage gate above is this step's Rule C blocking check.
- **[C] Continue** → proceed to Step 02 (Normalize)
- **[X] Exit** → halt workflow
