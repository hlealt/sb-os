---
stepNumber: 1
stepId: preflight
nextStepFile: step-02-parse.md
---

# Step 1: Pre-flight — Identificação e Renomeação de Arquivos de Investimentos

**Goal:** Verificar quais fontes de investimentos têm arquivos para o mês, identificar cada arquivo em `{INV_RAW_DIR}/`, e renomear para o padrão esperado pelos parsers.

## Help — Onde baixar e onde salvar

Apresente esta tabela ao usuário ANTES de qualquer scan:

| Fonte | O que baixar | Onde salvar |
|-------|--------------|-------------|
| B3 | Área do Investidor (investidor.b3.com.br) → Extrato de Movimentação → xlsx | `{INV_RAW_DIR}/b3-movimentacao.xlsx` |
| Safra (movimentações — todos os ativos) | Logue no Internet Banking PF → Meus Investimentos → aba **Histórico Mensal**. Cole o prompt `3-resources/tools/prompts/safra-extrair-movimentacoes-v2.md` na extensão Claude do Chrome e informe o ano. O agente gera **dois CSVs** por ano: um de fundos (com cota e quantidade) e um de RF (CRA/Deb/LCA/CDB/Tesouro). Ambos consumidos pelos parsers `safra_fundos_movimentacoes` e `safra_rf_movimentacoes` no step-02 | `{INV_RAW_DIR}/safra-fundos-{ANO}.csv` e `{INV_RAW_DIR}/safra-rf-{ANO}.csv` |
| Avenue (operações) | App/site Avenue → Notas de corretagem (PDFs) — apenas se houve operação | `{INV_RAW_DIR}/avenue-notas/*.pdf` |
| Avenue (câmbio) | App/site Avenue → Recibos de câmbio (PDFs) — apenas se houve câmbio no mês | `{INV_RAW_DIR}/avenue-cambio/*.pdf` |
| Bipa | App Bipa → Extrato (CSV) | `{INV_RAW_DIR}/bipa-extrato.csv` |
| Mercado Bitcoin | Site Mercado Bitcoin → Extrato (CSV) | `{INV_RAW_DIR}/mb-extrato.csv` |
| Mercado Pago (investimentos) | Automático — vem do fluxo de gastos em `3-resources/tools/finance/ledgers/expenses/{MONTH}/mp_extrato.csv` | (não baixar) |

Em seguida pergunte: "Já baixou os arquivos disponíveis para `{INV_RAW_DIR}/`? [S/N]". Se N, aguarde. Se S ou se a pasta já tiver conteúdo, prossiga — o agente cuida de identificação + renomeação. O usuário NÃO precisa renomear manualmente.

Nota sobre Safra: o site Safra tem problemas conhecidos de download. Se o usuário não conseguir baixar, prosseguir sem essa fonte e registrar pendência ao final.

## Mandatory Sequence

1. Read `{CONFIG_DIR}/investment-sources.json` para listar fontes ativas.
2. Scan `{INV_RAW_DIR}/` (incluindo subpastas `avenue-notas/` e `avenue-cambio/`). Crie a pasta se não existir.
3. Para cada arquivo encontrado, tente identificação automática:
   - Se o nome já segue o padrão (`b3-movimentacao.xlsx`, `safra-fundos-{ANO}.csv`, `safra-rf-{ANO}.csv`, `bipa-extrato.csv`, `mb-extrato.csv`) → match direto.
   - Se o nome difere mas é identificável por heurística (extensão + heurística de nome, ex.: `movimentacao-2026-04.xlsx` → b3, `bipa_*.csv` → bipa, `extrato-mb*.csv` → mercado_bitcoin) → mapear automaticamente.
   - PDFs em `avenue-notas/` ou nomes com padrão de nota Avenue → roteia para `avenue-notas/`. PDFs com `cambio` ou `fx` no nome → `avenue-cambio/`.
   - Nomes ambíguos → perguntar ao usuário antes de renomear. NÃO abrir o arquivo para tentar identificar.
4. Verifique completude: para cada fonte da tabela, se o usuário indicou que houve movimentação no mês, o arquivo correspondente deve existir.
5. Verifique MP: se houver expectativa de movimentação no Mercado Pago, confirmar que `3-resources/tools/finance/ledgers/expenses/{MONTH}/mp_extrato.csv` existe. Se não, instruir: "O fechamento de gastos do mês `{MONTH}` precisa rodar antes para gerar `mp_extrato.csv`. Rode `/accountant` com path=Gastos primeiro."
6. Apresente ao usuário:

```
Arquivos encontrados em {INV_RAW_DIR}/:

  Identificados:
  [✓] B3 — movimentacao-2026-04.xlsx → b3-movimentacao.xlsx
  [✓] Safra Fundos — fundos-2026.csv → safra-fundos-2026.csv
  [✓] Safra RF — rf-2026.csv → safra-rf-2026.csv
  [✓] Avenue Notas — 3 PDFs em avenue-notas/

  Não identificados (atribuir manualmente):
  [?] outro_arquivo.csv — qual fonte?

  Ausentes (confirmar):
  [ ] Bipa — não encontrei arquivo. Houve movimentação?
  [ ] Mercado Bitcoin — não encontrei arquivo. Houve movimentação?

  MP investimentos: ✓ encontrado em 3-resources/tools/finance/ledgers/expenses/2026-04/

Confirmar mapeamento?
```

7. STOP. Aguarde confirmação do usuário (mapeamento + confirmação de ausentes).
8. Após confirmação, renomeie todos os arquivos para os nomes-padrão. Para Avenue, garanta que os PDFs estejam em `avenue-notas/` ou `avenue-cambio/`.
9. Verifique que a renomeação completou sem erros.

## Step Menu

- **[C] Continue** → proceed to Step 02 (Parse)
- **[X] Exit** → halt workflow
