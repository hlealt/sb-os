---
stepNumber: 4
stepId: validate
nextStepFile: step-05-portfolio.md
---

# Step 4: Validate — Sanity Check vs Documentos Fonte

**Goal:** Validar amostralmente que as linhas inseridas batem com os documentos fonte do mês — pega bugs de parser antes de regenerar `portfolio.json`.

## Mandatory Sequence

1. Para cada ledger atualizado no Step 03 com novas linhas, faça um spot-check:
   - Selecione 2-3 linhas inseridas (preferir maior valor + mais recente).
   - Compare com o documento fonte original em `{INV_RAW_DIR}/`.
   - Verifique: `date`, `quantity`, `price`, `total` (orders); `date`, `gross_value` (proventos); `date`, `amount` (balcao); `date`, `buy_quantity`, `sell_quantity` (crypto).

2. **Cobertura mínima:** B3 (orders + proventos), Safra (balcao), Avenue (orders + fx, se houver), uma exchange de crypto (se houver).

3. Apresente ao usuário:

```
Spot-check do mês {MONTH}:

  orders.csv (B3):
    [✓] 2026-04-08 PETR4 100×R$38,15 = R$3.815 → bate com b3-movimentacao.xlsx
    [✓] 2026-04-15 BRK.B 2×US$405,12 = US$810,24 → bate com avenue-notas/...

  proventos.csv (B3):
    [✓] 2026-04-12 BBAS3 dividendo R$87,50 → bate

  balcao.csv (Safra):
    [✓] 2026-04-30 SAFRA ABS aplicação R$10.000 → bate com safra-fundos.csv

  avenue_fx.csv:
    [✓] 2026-04-10 USD 500 @ 5,12 = R$2.560 → bate com recibo

Discrepâncias: nenhuma | OU lista
```

4. Se houver discrepâncias:
   - Reporte ao usuário com detalhes (esperado vs encontrado, fonte vs ledger).
   - Pergunte: "Bug de parser, dado fonte errado, ou aceitar?"
   - Se bug de parser: ledgers são append-only — remoção manual + correção do parser + re-execução do Step 02-03 para o arquivo afetado.
   - Não prossiga para Step 05 enquanto houver discrepâncias não resolvidas.

5. STOP. Aguarde confirmação.

## Step Menu

- **[C] Continue** → proceed to Step 05 (Portfolio)
- **[B] Back] → voltar para Step 02/03 para corrigir
- **[X] Exit** → halt workflow
