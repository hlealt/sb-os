---
stepNumber: 6
stepId: review
nextStepFile: step-07-snapshot.md
---

# Step 6: Review — Apresentar Mudanças e Anomalias

**Goal:** Apresentar ao usuário um resumo das mudanças do mês (deltas) e anomalias detectadas, para confirmação antes de criar o snapshot.

## Mandatory Sequence

1. Compare `portfolio.json` recém-gerado com o snapshot anterior em `{INV_LEDGER_DIR}/snapshots.json` (último entry). Calcule:
   - Δ valor total (BRL e %)
   - Δ por classe (variable_income, fixed_income, crypto, funds)
   - Δ por broker
   - Top movers (maiores variações absolutas e percentuais por posição)

2. Apresente:

```
Revisão {MONTH}:

  Total: R$ X.XXX.XXX → R$ X.XXX.XXX (+R$ XX.XXX, +X.X%)
  
  Por classe:
    Variável: +R$ XX (+X.X%)
    RF:       +R$ XX (+X.X%)
    Crypto:   −R$ XX (−X.X%)
    Fundos:   +R$ XX (+X.X%)

  Top movers:
    +R$ X.XXX  PETR4 (preço ↑ + compras)
    −R$ X.XXX  BTC (preço ↓)
    +R$ X.XXX  SAFRA ABS (aplicação)

  Anomalias detectadas:
    - <vazia> | OU lista (variação >20%, posição zerada inesperadamente, novo ticker, etc.)
```

3. Para cada anomalia, peça classificação ao usuário: aceitar (movimento real) ou investigar (provável bug).

4. Se houver anomalias para investigar, NÃO prossiga — volte ao Step 02-03-04 conforme o caso.

5. STOP. Aguarde confirmação do usuário ("OK, snapshot pode ser criado").

## Step Menu

- **[C] Continue** → proceed to Step 07 (Snapshot)
- **[B] Back] → voltar para investigar
- **[X] Exit** → halt workflow
