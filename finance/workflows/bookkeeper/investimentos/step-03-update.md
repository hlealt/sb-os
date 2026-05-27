---
stepNumber: 3
stepId: update
nextStepFile: step-04-validate.md
---

# Step 3: Update — Atualização dos Ledgers

**Goal:** Aplicar os CSVs normalizados de `{INV_PROCESSED}/` aos ledgers permanentes em `{INV_LEDGER_DIR}` via `update_ledgers.py`. Match exato (tolerância 0) — fluxo mensal recorrente.

## Pre-Script Action — Lot Splits

**Source.** `{CONFIG_DIR}/lot-splits.yaml` (formerly inlined into a YAML companion file at `.user/context/accountant/investimentos/step-03-update.yaml` before the rename; consolidated here on 2026-05-05 per p1-15).

**MANDATORY pre-script action.** Execute BEFORE the `python update_ledgers.py` command below. The splits modify the processed CSVs in `{INV_PROCESSED}/` so that the script picks up already-split rows and dedup behaves naturally on re-runs.

For each entry under `splits:` in `lot-splits.yaml`:

1. Determine which processed CSV(s) to scan. The `primary_id` lives in `balcao.csv` ledger, so check `{INV_PROCESSED}/b3_balcao.csv` (and any other `*_balcao.csv` for the same month). If none of the processed files contains rows with `product_id == primary_id`, skip this split entry silently.

2. For each matching row in the processed CSV:
   a. Validate `quantity == total_units`. If not, STOP and ask the user — a buy/sell since last close changed the lot ratio, and the config needs to be updated before continuing.
   b. Replace the matching row with one row per lot in `lots`:
      - `quantity` = `lot.units`
      - `amount`   = `round(original_amount × lot.units / total_units, 2)`
      - the LAST lot absorbs rounding so the sum equals `original_amount` exactly (compute as `original_amount` minus sum of prior lots)
      - keep `date`, `operation`, `product_type`, `irrf`, `iof`, `broker`, `source` identical to the original row

3. Before saving the modified processed CSV, show the user a table of the proposed splits (original row → split rows) and ask for confirmation. Do NOT auto-apply.

4. After confirmation, save the modified processed CSV in place. Then proceed with the normal Step 03 sequence (`update_ledgers.py`).

5. Mention the splits in the Step 03 report shown to the user (e.g., `balcao.csv +7 (includes +1 row from TAEB15 lot split)`).

If `splits:` is empty or no processed file contains matching rows, skip silently — no user prompt needed.

## Mandatory Sequence

1. Execute o script (com `--report-out` para alimentar o gate #6 no passo 7):

```
python {INV_SCRIPTS_DIR}/update_ledgers.py "{INV_PROCESSED}" --tolerance 0 --report-out "{INV_PROCESSED}/.upsert-report.json"
```

2. O script:
   - Identifica o ledger destino pelo prefixo do arquivo normalizado (`b3_orders.csv → orders.csv`, `safra_balcao.csv → balcao.csv`, etc.).
   - Aplica match exato em campos de identidade + numéricos.
   - Insere apenas linhas novas (dedup garante idempotência — seguro re-executar).
   - Retorna relatório com: tolerância usada, inseridas por ledger, ignoradas (match exato), ignoradas (match fuzzy — não deve ocorrer com tolerance 0), duplicadas forçadas.

3. Se o script falhar no meio da execução, ledgers podem estar parcialmente atualizados. Re-executar é seguro — dedup previne duplicação. Reporte o erro completo e pergunte como proceder.

4. Apresente o relatório ao usuário em formato resumido:

```
Ledgers atualizados (tolerance 0):
  orders.csv      +12 (3 já existentes ignoradas)
  proventos.csv   +8
  balcao.csv      +5
  crypto.csv      +6
  corporate_actions.csv  +1
  avenue_fx.csv   +2

Casos especiais: nenhum | OU lista detalhada
```

5. **Matches fuzzy ou duplicatas forçadas** — se aparecerem (não devem com tolerance 0), liste individualmente. O usuário deve confirmar que são duplicatas reais ou flagar como bug.

6. **Atualização de fees por fonte autoritativa** (`--update-fees`) — NÃO usar no fluxo mensal por padrão. Reservado para reconciliação histórica quando uma fonte mais autoritativa (B3) corrige fees imprecisos de fonte anterior (planilha). Mencione a opção apenas se o usuário pedir.

7. **Completion gate — tolerância de match = 0 (`gate_ledger_tolerance.py`, gate #6 — auto-halt).** Rode o gate sobre o relatório de upsert escrito no passo 1:

   ```bash
   python "{SCRIPTS_DIR}/gate_ledger_tolerance.py" --report "{INV_PROCESSED}/.upsert-report.json"
   ```

   O gate falha (exit 1) se QUALQUER ledger tiver `skipped_fuzzy` não-vazio — com `--tolerance 0` um match fuzzy indica bug de parser ou de dados. Exit 0 = nenhum match fuzzy; exit 2 = relatório ausente/malformado.

   - **Exit 0** → registre o pass e prossiga.
   - **Exit 1 (FAIL)** → Rule C **blocking** (`../gatekeeper-loop.md`). Mecaniza o passo 5 acima como gate de exit-code. Surface os matches fuzzy inline (pt-BR), proponha o fix (confirmar duplicata real → registrar; ou flag como bug → corrigir parser e re-rodar Step 02-03), e ofereça `[S]`/`[N]`. NÃO prossiga ao Step 04 enquanto houver match fuzzy não resolvido.
   - **Exit 2** → relatório ausente; re-rode o passo 1 com `--report-out` e tente de novo.

8. STOP. Aguarde confirmação do usuário antes de prosseguir.

## Step Menu

- **Gatekeeper checkpoint** → before advancing, run § Per-Step Checkpoint in `../gatekeeper-loop.md`. A fuzzy match or forced duplicate (should not occur at tolerance 0) is a Rule C blocking issue — surface inline with a proposed fix; a lot-split ratio mismatch is a deviation (Rule A). The ledger-tolerance gate (#6) above is the exit-code form of this blocking check.
- **[C] Continue** → proceed to Step 04 (Validate)
- **[R] Re-run] → re-executar update_ledgers.py
- **[X] Exit** → halt workflow
