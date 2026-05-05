---
stepNumber: 5
stepId: portfolio
nextStepFile: step-06-review.md
---

# Step 5: Portfolio — Recalcular `portfolio.json` e Snapshots

**Goal:** Regenerar `portfolio.json` a partir dos ledgers atualizados e atualizar `balance-snapshots.csv` com saldos de fim de mês para RF/fundos.

## Mandatory Sequence

1. **Importar balance snapshots** (RF + fundos) — para fontes que fornecem saldo em statement (não derivável dos ledgers):

   ```
   python {INV_SCRIPTS_DIR}/import_balance_snapshots.py --month {MONTH}
   ```

   Se o script pedir input de fonte específica (Safra títulos, etc.), siga as instruções do script. Se não houver statements de saldo, pule este passo e prossiga.

2. **Regenerar `portfolio.json`:**

   ```
   python {INV_SCRIPTS_DIR}/calculate.py --cut-date {MONTH}-LAST_DAY
   ```

   - `{MONTH}-LAST_DAY` = último dia do mês (ex.: `2026-04-30`).
   - O script orquestra: position_calculator → fx_engine → price_fetcher → irr_calculator → escreve `portfolio.json` em `{INV_LEDGER_DIR}/portfolio.json`.
   - Se o usuário não tiver internet ou quiser pular fetch de preços, use `--no-prices`.

3. Reporte ao usuário:

```
portfolio.json regenerado para cut-date {MONTH}-LAST_DAY:
  - Posições: 78 (variável: 24, RF: 42, crypto: 6, fundos: 6)
  - Total: R$ X.XXX.XXX
  - Preços: 22 fetched, 56 from snapshots, 0 missing
  - IRR computado: ✓
balance-snapshots.csv: +N linhas
```

4. **Pendências de preço** — se `price_source: "missing"` em qualquer posição relevante, liste e pergunte ao usuário se quer prosseguir mesmo assim ou aguardar.

5. STOP. Aguarde confirmação.

## Step Menu

- **[C] Continue** → proceed to Step 06 (Review)
- **[R] Re-run] → re-executar calculate.py
- **[X] Exit** → halt workflow
