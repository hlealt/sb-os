---
stepNumber: 2
stepId: parse
nextStepFile: step-03-update.md
---

# Step 2: Parse — Normalização por Fonte

**Goal:** Executar os parsers para cada fonte presente em `{INV_RAW_DIR}/` e gerar CSVs normalizados em `{INV_PROCESSED}/`. Resolver pendências de `name_map.csv` e ratios de ações corporativas.

## Mandatory Sequence

1. **Limpar `{INV_PROCESSED}/`** — apague todos os arquivos `*.csv` existentes ANTES de qualquer parser rodar. Esta pasta é scratch (overwrite per month); resíduos de meses anteriores corrompem `update_ledgers.py` (reimportaria dados antigos). Crie a pasta se não existir.
2. Para cada arquivo presente em `raw/`, invoque o parser correspondente:

| Fonte | Parser (módulo) | Entrada | Saída(s) em `processed/` |
|-------|-----------------|---------|-------------------------|
| B3 | `parsers.b3_parser` | `raw/b3-movimentacao.xlsx` | `b3_orders.csv`, `b3_proventos.csv`, `b3_balcao.csv`, `b3_corporate.csv` |
| Safra fundos (movimentações) | `parsers.safra_fundos_movimentacoes` | `raw/safra-fundos-{ANO}.csv` | `safra_fundos_balcao.csv`, `safra_fundos_seeds.csv`, `safra_fundos_snapshots.csv`, `assets.csv` (upsert) |
| Safra RF (movimentações) | `parsers.safra_rf_movimentacoes` | `raw/safra-rf-{ANO}.csv` | `safra_rf_balcao.csv`, `safra_rf_seeds.csv`, `safra_rf_snapshots.csv`, `assets.csv` (upsert) |
| Avenue (notas) | `parsers.avenue` | `raw/avenue-notas/*.pdf` | `avenue_orders.csv` |
| Avenue FX | `parsers.avenue_fx` | `raw/avenue-cambio/*.pdf` | `avenue_fx.csv` |
| Bipa | `parsers.bipa` | `raw/bipa-extrato.csv` | `bipa_crypto.csv` |
| Mercado Bitcoin | `parsers.mercado_bitcoin` | `raw/mb-extrato.csv` | `mb_crypto.csv` |
| Mercado Pago (inv) | `parsers.mp_investimentos` | `.user/finance/bookkeeper/ledgers/expenses/{MONTH}/mp_extrato.csv` | `mp_balcao.csv` |

Os parsers são independentes — podem rodar em qualquer ordem. Se um parser falhar com erro de formato, reporte o erro completo ao usuário e pergunte como proceder. Não bloqueie a execução dos demais.

3. **Resolução de name_map** — se um parser retornar valores não mapeados (`name_map.csv` em `{INV_LEDGER_DIR}/name_map.csv`):
   - O parser não processa as linhas com valores desconhecidos (mas processa o restante).
   - Apresente ao usuário a lista: `source / field / raw_value`.
   - Pergunte: "O que são estes itens?"
   - Insira os mapeamentos canônicos em `name_map.csv` (append).
   - Re-execute apenas os parsers afetados.
   - Repita até zerar pendências.

4. **Ações corporativas sem ratio** — o B3 parser pode gerar entradas em `b3_corporate.csv` sem `ratio_from`/`ratio_to` (Grupamento, Cisão, Bonificação):
   - Para cada flag, pesquise o ratio em fontes oficiais (CVM, fato relevante, site da empresa) usando ticker + data.
   - Se encontrar, preencha `ratio_from`/`ratio_to` no CSV normalizado ANTES de prosseguir.
   - Se não encontrar, pergunte ao usuário. Se o usuário não souber, prossiga com ratio vazio e registre pendência ao final.

5. **Operações flaggadas** — se o B3 parser retornar operações marcadas como "flag" na tabela de classificação (não classificáveis automaticamente):
   - Apresente ao usuário: data, movimentação, produto, valores.
   - Usuário indica tratamento (ignorar, ordem, provento, etc.).
   - Se for padrão recorrente, sugerir adicionar à tabela de classificação do parser.

6. **Completion gate — parser total sanity (`gate_parser_total_sanity.py`, gate #5 — auto-halt).** Rode o gate sobre os `*orders*.csv` recém-parseados. `{INV_PROCESSED}/` contém SOMENTE os arquivos parseados nesta sessão (o passo 1 limpa a pasta antes) — então `--orders-dir {INV_PROCESSED}` é exatamente o slice "linhas novas" deste mês (não dados históricos):

   ```bash
   python "{SCRIPTS_DIR}/gate_parser_total_sanity.py" --orders-dir "{INV_PROCESSED}"
   ```

   O gate verifica `total ≈ quantity × price + fees` (tolerância 0.5%) em cada linha; `fees = fees_exchange + fees_brokerage + fees_irrf`. Exit 0 = todas dentro da tolerância; exit 1 = uma ou mais violam (listadas no stderr); exit 2 = nenhum arquivo `*orders*.csv` em `{INV_PROCESSED}` (caso normal quando o mês não tem ordens — trate como pass: não há ordens a validar).

   - **Exit 0** → registre o pass e prossiga.
   - **Exit 1 (FAIL)** → Rule C **blocking** (`../gatekeeper-loop.md`). Surface as linhas violantes inline (pt-BR), proponha o fix (bug de parser ou dado fonte errado → corrigir e re-parsear o arquivo afetado), e ofereça `[S]`/`[N]`. NÃO prossiga ao Step 03 enquanto houver violação não resolvida; o gate não auto-loopa (a causa-raiz está no arquivo fonte ou no parser).
   - **Exit 2 sem arquivos de ordens** → não há ordens neste mês; siga (pass vácuo). Se ESPERAVA ordens e elas faltam, trate como o gate de fonte-esperada (step-01).

7. STOP. Apresente resumo:

```
Parsers executados: B3 ✓, Safra ✓, Avenue ✓, Bipa ✓, MB ✓, MP ✓
Saídas em {INV_PROCESSED}/:
  - b3_orders.csv (12 linhas)
  - b3_proventos.csv (8 linhas)
  - b3_balcao.csv (3 linhas)
  - safra_balcao.csv (2 linhas)
  - avenue_orders.csv (4 linhas)
  ...
Pendências: nenhuma | OU lista de pendências (ratios, MP ausente, etc.)
```

## Step Menu

- **Gatekeeper checkpoint** → before advancing, run § Per-Step Checkpoint in `../gatekeeper-loop.md`. Unmapped `name_map` values, missing corporate-action ratios, and flagged operations here are deviations — surface them via Rule A and route the resolution to durable structure (Rule B; a new parser case routes to Seam 1 `tool-builder`). A parser sanity-check failure (total ≈ qty×price+fees) is a Rule C issue.
- **[C] Continue** → proceed to Step 03 (Update Ledgers)
- **[R] Re-run] → re-executar parser específico
- **[X] Exit** → halt workflow
