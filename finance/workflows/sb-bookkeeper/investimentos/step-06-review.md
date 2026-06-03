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

5. **Completion gates — pré-snapshot (auto-halt).** Antes de criar o snapshot (Step 07), rode os três gates de portfolio. Todos leem `portfolio.json` recém-gerado; nenhum auto-loopa (o usuário decide a próxima ação). Cada falha é Rule C **blocking** — NÃO avance ao Step 07 enquanto não resolver ou o usuário aceitar explicitamente.

   a. **Anomalia de delta de portfolio (`gate_portfolio_delta.py`, gate #8):**

      ```bash
      python "{SCRIPTS_DIR}/gate_portfolio_delta.py" --portfolio "{INV_LEDGER_DIR}/portfolio.json" --flagged-ids "{IDS_ACEITOS}"
      ```

      Mecaniza a lista "Anomalias detectadas" do passo 2: variação por posição >20%, posição zerada inesperadamente, ticker novo vs snapshot anterior. Passe em `{IDS_ACEITOS}` (vírgula-separado) os `id`s que o usuário classificou como "aceitar (movimento real)" no passo 3 — assim o gate só falha em anomalias NÃO reconhecidas. Exit 0 = nenhuma anomalia não-flagada; exit 1 = anomalias não-flagadas restam; exit 2 = arquivos ausentes. Sem snapshot anterior → pass vácuo.

   b. **Sanidade de IRR + banda rf_balcao (`gate_irr_sanity.py`, gate #9):**

      ```bash
      python "{SCRIPTS_DIR}/gate_irr_sanity.py"
      ```

      Falha (exit 1) se `|irr| > 200%` em qualquer posição/classe, se `irr_quality` faltar numa posição balcão com valor, ou se uma posição `rf_balcao` tiver retorno anualizado fora da banda `[7%, 15%]` (lida de `investment_rules.sanity_bands.rf_balcao` em `standing-rules.yaml`). Exit 0 = sem violações; exit 2 = `portfolio.json` ausente.

   c. **Divergência de bucket IRR (`gate_bucket_divergence.py`, gate #10):**

      ```bash
      python "{SCRIPTS_DIR}/gate_bucket_divergence.py"
      ```

      Falha (exit 1) se, em qualquer bucket (rv_br/rv_eua/rf_balcao/fundos/crypto), `|média-simples-por-ativo − IRR-do-bucket-armazenado| > 5%`. Exit 0 = todos dentro da tolerância; exit 2 = `portfolio.json` ausente.

   Para CADA gate com exit 1: Rule C **blocking** (`../gatekeeper-loop.md`). Surface as violações inline (pt-BR), proponha o fix (investigar bug de dados/parser → corrigir e re-rodar Step 02-05; ou aceitar explicitamente a anomalia — para o #8, re-rodar com o `id` adicionado a `--flagged-ids`), e ofereça `[S]`/`[N]`. Exit 2 em qualquer gate → `portfolio.json` não foi gerado; volte ao Step 05.

6. STOP. Aguarde confirmação do usuário ("OK, snapshot pode ser criado").

## Step Menu

- **Gatekeeper checkpoint** → before advancing, run § Per-Step Checkpoint in `../gatekeeper-loop.md`. This step is the canonical Rule C surface for investimentos: an anomaly classified "investigar" (variação >20%, posição zerada, novo ticker) is BLOCKING — surface inline with a proposed fix and do not advance until resolved; a low-materiality quality flag (`seed_only`, `short_window`) is DEFERRABLE — record it and route to review-mode. Three completion gates auto-halt here before the snapshot: `gate_portfolio_delta.py` (#8), `gate_irr_sanity.py` (#9), `gate_bucket_divergence.py` (#10).
- **[C] Continue** → proceed to Step 07 (Snapshot)
- **[B] Back] → voltar para investigar
- **[X] Exit** → halt workflow
