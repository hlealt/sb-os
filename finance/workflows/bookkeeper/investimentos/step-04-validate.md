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

5. **Completion gate — cobertura de spot-check (`gate_spot_check_coverage.py`, gate #7 — auto-halt).** Mecaniza a "Cobertura mínima" do passo 2: garante que toda classe mandatória foi de fato spot-checada antes do Step 05.

   a. Escreva o coverage-record JSON em `{INV_PROCESSED}/.spot-check-coverage.json` com EXATAMENTE estas chaves (o gate #7 lê apenas estas):

      ```json
      {
        "checked": ["b3_orders", "b3_proventos", "safra_balcao", "avenue_orders", "avenue_fx", "crypto_exchange"],
        "present_sources": ["b3", "safra_balcao", "avenue", "crypto"]
      }
      ```

      - `checked`: os tokens de classe que VOCÊ de fato spot-checou no passo 1 (use os literais que o gate reconhece: `b3_orders`, `b3_proventos`, `safra_balcao`, `avenue_orders`, `avenue_fx`, `crypto_exchange`).
      - `present_sources`: quais fontes existem neste mês — determina quais classes condicionais são exigidas. Inclua `avenue` se houver arquivos Avenue; `crypto` se houver exchange de crypto. `b3` e `safra_balcao` são sempre exigidos.

   b. Rode o gate:

      ```bash
      python "{SCRIPTS_DIR}/gate_spot_check_coverage.py" --coverage-record "{INV_PROCESSED}/.spot-check-coverage.json"
      ```

      Classes sempre exigidas: `b3_orders`, `b3_proventos`, `safra_balcao`. Condicionais: `avenue_orders`/`avenue_fx` (se `avenue` presente), `crypto_exchange` (se `crypto` presente). Exit 0 = todas cobertas; exit 1 = uma ou mais classes mandatórias não checadas; exit 2 = record ausente/malformado.

   - **Exit 0** → registre o pass e prossiga.
   - **Exit 1 (FAIL)** → Rule C **blocking** (`../gatekeeper-loop.md`). NÃO avance ao Step 05. Faça o spot-check das classes faltantes, reescreva o coverage-record e rode o gate de novo. O step não avança até exit 0.

6. STOP. Aguarde confirmação.

## Step Menu

- **Gatekeeper checkpoint** → before advancing, run § Per-Step Checkpoint in `../gatekeeper-loop.md`. A spot-check discrepancy (source vs ledger) is a Rule C blocking issue — surface inline with a proposed fix (parser bug → fix + re-parse; source error; accept). Do the spot-check by reading sample rows through a `tools-index.md` tool (`sample_from_ledger` / `position_summary`), not by opening ledger CSVs directly. The spot-check coverage gate (#7) above auto-halts before Step 05 if any mandatory class was skipped.
- **[C] Continue** → proceed to Step 05 (Portfolio)
- **[B] Back] → voltar para Step 02/03 para corrigir
- **[X] Exit** → halt workflow
