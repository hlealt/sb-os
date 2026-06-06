---
stepNumber: 7
stepId: recurring
nextStepFile: step-08-manifest.md
---

# Step 7: Update Recurring Payments with Invoice Totals

**Goal:** Write credit card invoice totals into `pagamentos-recorrentes.md` for the payment month.

**Skip this step if `{MONTH}` is not the month immediately before the current one.** Retroactive closings do not update recurring payments — the amounts have already been paid.

## Invoice Total Source

Invoice totals are extracted directly from PDFs by `normalize.py` ("Total a pagar" / "Pagamento total da fatura" field) and saved to `{PROCESSED_DIR}/fatura_totals.json`. Deterministic — no transaction summing.

## Mandatory Sequence

1. Read `{PROCESSED_DIR}/fatura_totals.json`.
2. Calculate the payment month: if `{MONTH}` = `2026-03`, payment = day 10 of `2026-04`.
3. Present to the user:

```
Invoice totals extracted from PDFs for payment in April/2026:

  Cartão Santander (ativo): R$ 18,734.75
  Cartão Mercado Pago:      R$ 9,727.55
  Cartão Nubank:             R$ 257.54
  Cartão XP:                 no invoice processed

Update pagamentos-recorrentes.md? (Y/N)
```

4. STOP. Wait for confirmation.
5. Read `2-areas/finance/pagamentos-recorrentes.md`.
6. Find the section `### {YYYY-MM of payment}`, subsection `#### Dia 10`.
7. Replace `___` with the formatted value (pt-BR with period as thousands separator):
   - Before: `- [ ] Cartão Mercado Pago — ___`
   - After: `- [ ] Cartão Mercado Pago — 9.727,55`
8. Save.

## Bank ID Mapping

| bank_id | Name in pagamentos-recorrentes.md |
|---|---|
| `santander_fatura` | Cartão Santander (bloqueado) — Visa final 4011, old card, residual subscriptions only |
| `santander_fatura_infinite` | Cartão Santander (ativo) — Unique Cashback Visa Infinite final 8667 |
| `mp_fatura` | Cartão Mercado Pago |
| `nubank_fatura` | Cartão Nubank |

## Step Menu

- **Gatekeeper checkpoint** → before advancing, run § Per-Step Checkpoint in `../gatekeeper-loop.md` (out-of-structure → Rule A; detected issue → Rule C blocking/deferrable; direct data read → re-route through a `tools-index.md` tool).
- **[C] Continue** → proceed to Step 08 (Update Manifest)
- **[X] Exit** → halt workflow
