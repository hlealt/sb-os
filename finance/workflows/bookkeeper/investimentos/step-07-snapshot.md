---
stepNumber: 7
stepId: snapshot
nextStepFile: step-08-report.md
---

# Step 7: Snapshot — Persistir Snapshot do Mês

**Goal:** Copiar `portfolio.json` para `portfolio-{MONTH}-LAST_DAY.json` e atualizar `snapshots.json` para o seletor de datas do dashboard.

## Mandatory Sequence

1. Defina `{SNAPSHOT_DATE}` = último dia do mês `{MONTH}` (ex.: `2026-04-30`).

2. Copie `{INV_LEDGER_DIR}/portfolio.json` → `{INV_LEDGER_DIR}/portfolio-{SNAPSHOT_DATE}.json`. Se o arquivo já existir (re-execução), sobrescreva e reporte.

3. Atualize `{INV_LEDGER_DIR}/snapshots.json`:
   - Adicione entry com `date: {SNAPSHOT_DATE}` apontando para o arquivo recém-criado.
   - Inclua resumo: `total_brl`, `total_by_class`, `position_count`.
   - Mantenha o array ordenado cronologicamente.
   - Se já existir entry para `{SNAPSHOT_DATE}`, sobrescreva.

4. Reporte:

```
Snapshot persistido:
  portfolio-{SNAPSHOT_DATE}.json (R$ X.XXX.XXX, 78 posições)
  snapshots.json: +1 entry (ou atualizada)
```

5. STOP. Aguarde confirmação.

## Step Menu

- **[C] Continue** → proceed to Step 08 (Report)
- **[X] Exit] → halt workflow
