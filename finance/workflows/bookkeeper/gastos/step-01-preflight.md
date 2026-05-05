---
stepNumber: 1
stepId: preflight
nextStepFile: step-02-normalize.md
---

# Step 1: Pre-flight Check and Filename Normalization

**Goal:** Identify each downloaded file, map it to the correct bank, and rename to the standard filename expected by `normalize.py`.

## Help — Onde baixar e onde salvar

ANTES de qualquer scan, leia `{CONFIG_DIR}/banks.json` e renderize uma tabela com uma linha por banco e três colunas:

| Coluna | Valor |
|--------|-------|
| Fonte | `name` do banco |
| O que baixar | `download_hint` do banco |
| Onde salvar | `{RAW_DIR}/{standard_filename}` |

Exemplo do que o usuário deve ver (para `{MONTH}=2026-04`):

```
| Fonte                                  | O que baixar                                 | Onde salvar                                                          |
|----------------------------------------|----------------------------------------------|----------------------------------------------------------------------|
| Bradesco — Extrato Conta Corrente      | App Bradesco > Extrato > Exportar CSV        | 3-resources/tools/finance/raw/2026-04/expenses/extrato-bradesco.csv |
| Santander — Extrato Conta Corrente     | Internet Banking Santander > Extrato > PDF   | 3-resources/tools/finance/raw/2026-04/expenses/extrato-santander.pdf|
| Santander — Fatura Cartão Visa         | Email ou app Santander > Fatura > Baixar PDF | 3-resources/tools/finance/raw/2026-04/expenses/fatura-santander.pdf |
| Mercado Pago — Extrato Conta           | App Mercado Pago > Extrato > Exportar CSV    | 3-resources/tools/finance/raw/2026-04/expenses/extrato-mercado-pago.csv |
| Wise — Extrato Multi-Moeda             | Wise > Statements > Export CSV (por moeda)   | 3-resources/tools/finance/raw/2026-04/expenses/wise/extrato-wise-{MOEDA}.csv |
| Mercado Pago — Fatura Cartão           | Email Mercado Pago > Fatura anexa em PDF     | 3-resources/tools/finance/raw/2026-04/expenses/fatura-mercado-pago.pdf |
| Nubank — Fatura Cartão                 | App Nubank > Fatura > Baixar PDF ou email    | 3-resources/tools/finance/raw/2026-04/expenses/fatura-nubank.pdf    |
| XP — Fatura Cartão                     | App XP > Cartão > Fatura > Exportar CSV      | 3-resources/tools/finance/raw/2026-04/expenses/fatura-xp.csv        |
```

Após renderizar a tabela, pergunte: "Já baixou todos os arquivos para `{RAW_DIR}/`? [S/N]".

- Se **N** → use a tabela como guia, aguarde o usuário baixar, e só então prossiga.
- Se **S** ou se já houver arquivos em `{RAW_DIR}/` → prossiga. O agente cuida de identificação e renomeação automaticamente — o usuário NÃO precisa renomear manualmente.

## Naming Convention

Standard: `{tipo}-{banco}.{ext}` — defined in the `standard_filename` field of each bank in `banks.json`.

## Mandatory Sequence

1. Read `{CONFIG_DIR}/banks.json` to list all configured banks and their `standard_filename`.
2. Scan `{RAW_DIR}/` and subfolders to find files (PDF, CSV). Create `{RAW_DIR}/` if it does not exist.
3. For each file, attempt automatic identification:
   - If the name already matches `standard_filename` → direct match.
   - For CSVs: read the first 5 lines and compare known headers (e.g., `Data;Hist` = Bradesco, `RELEASE_DATE;TRANSACTION_TYPE` = Mercado Pago bank statement, `Data;Estabelecimento;Portador` = XP credit card invoice).
   - For PDFs: use name heuristics (e.g., `extrato_conta` = Santander bank statement, `Fatura_*_VISA_*` = Santander credit card invoice, `Nubank_*` = Nubank credit card invoice).
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
7. Verify that all files were renamed correctly.

## Step Menu

- **[C] Continue** → proceed to Step 02 (Normalize)
- **[X] Exit** → halt workflow
