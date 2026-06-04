---
stepNumber: 1
stepId: preflight
nextStepFile: step-02-parse.md
---

# Step 1: Pre-flight — Investment File Identification and Renaming

**Goal:** Check which investment sources have files for the month, identify each file in `{INV_RAW_DIR}/`, and rename to the pattern expected by the parsers.

## Help — Where to download and where to save

Present this table to the user BEFORE any scan:

| Source | What to download | Where to save |
|--------|------------------|---------------|
| B3 | Área do Investidor (investidor.b3.com.br) → Extrato de Movimentação → xlsx | `{INV_RAW_DIR}/b3-movimentacao.xlsx` |
| Safra (movements — all assets) | Log into Internet Banking PF → Meus Investimentos → **Histórico Mensal** tab. Paste the prompt `3-resources/tools/prompts/safra-extrair-movimentacoes.md` into the Claude Chrome extension and provide the year. The agent generates **two CSVs** per year: one for funds (with quota and quantity) and one for RF (CRA/Deb/LCA/CDB/Tesouro). Both consumed by the `safra_fundos_movimentacoes` and `safra_rf_movimentacoes` parsers in step-02 | `{INV_RAW_DIR}/safra-fundos-{ANO}.csv` and `{INV_RAW_DIR}/safra-rf-{ANO}.csv` |
| Avenue (trades) | Avenue app/site → Notas de corretagem (PDFs) — only if there was a trade | `{INV_RAW_DIR}/avenue-notas/*.pdf` |
| Avenue (FX) | Avenue app/site → Recibos de câmbio (PDFs) — only if there was FX this month | `{INV_RAW_DIR}/avenue-cambio/*.pdf` |
| Bipa | Bipa app → Extrato (CSV) | `{INV_RAW_DIR}/bipa-extrato.csv` |
| Mercado Bitcoin | Mercado Bitcoin site → Extrato (CSV) | `{INV_RAW_DIR}/mb-extrato.csv` |
| Mercado Pago (investments) | Automatic — comes from the gastos flow at `.user/finance/bookkeeper/ledgers/expenses/{MONTH}/mp_extrato.csv` | (do not download) |

Then ask: "Have you downloaded the available files to `{INV_RAW_DIR}/`? [S/N]". If N, wait. If S or if the folder already has content, proceed — the agent handles identification + renaming. The user does NOT need to rename manually.

Note on Safra: the Safra site has known download issues. If the user cannot download, proceed without that source and log a pending item at the end.

## Mandatory Sequence

1. Read `{CONFIG_DIR}/investment-sources.json` to list active sources.
2. Scan `{INV_RAW_DIR}/` (including the `avenue-notas/` and `avenue-cambio/` subfolders). Create the folder if it does not exist.
3. For each file found, attempt automatic identification:
   - If the name already follows the pattern (`b3-movimentacao.xlsx`, `safra-fundos-{ANO}.csv`, `safra-rf-{ANO}.csv`, `bipa-extrato.csv`, `mb-extrato.csv`) → direct match.
   - If the name differs but is identifiable by heuristic (extension + name heuristic, e.g.: `movimentacao-2026-04.xlsx` → b3, `bipa_*.csv` → bipa, `extrato-mb*.csv` → mercado_bitcoin) → map automatically.
   - PDFs in `avenue-notas/` or names with an Avenue nota pattern → route to `avenue-notas/`. PDFs with `cambio` or `fx` in the name → `avenue-cambio/`.
   - Ambiguous names → ask the user before renaming. Do NOT open the file to try to identify it.
4. Check completeness: for each source in the table, if the user indicated there was activity this month, the corresponding file must exist.
5. Check MP: if Mercado Pago activity is expected, confirm that `.user/finance/bookkeeper/ledgers/expenses/{MONTH}/mp_extrato.csv` exists. If not, instruct: "The gastos close for month `{MONTH}` must run first to generate `mp_extrato.csv`. Run `/sb-bookkeeper` with path=Gastos first."
6. Present to the user:

```
Files found in {INV_RAW_DIR}/:

  Identified:
  [✓] B3 — movimentacao-2026-04.xlsx → b3-movimentacao.xlsx
  [✓] Safra Fundos — fundos-2026.csv → safra-fundos-2026.csv
  [✓] Safra RF — rf-2026.csv → safra-rf-2026.csv
  [✓] Avenue Notas — 3 PDFs in avenue-notas/

  Not identified (assign manually):
  [?] outro_arquivo.csv — which source?

  Missing (confirm):
  [ ] Bipa — no file found. Was there activity?
  [ ] Mercado Bitcoin — no file found. Was there activity?

  MP investments: ✓ found in .user/finance/bookkeeper/ledgers/expenses/2026-04/

Confirm mapping?
```

7. STOP. Wait for the user's confirmation (mapping + confirmation of missing sources).
8. After confirmation, rename all files to the standard names. For Avenue, ensure the PDFs are in `avenue-notas/` or `avenue-cambio/`.
9. Verify that the renaming completed without errors.

## Completion Gate — Expected-Source Coverage (auto-halt)

Read `{CONFIG_DIR}/sources.yaml` and collect every entry with `enabled_for_close: true`. For the investimentos flow, split the enabled sources into two groups:

- **Always-expected** (a file/feed every close): `b3` and `safra` (plus `funds` if the user maintains a funds feed). A missing always-expected source is a Rule C **blocking** issue — surface it inline, propose the fix (download the file into `{INV_RAW_DIR}/`, or — if genuinely not expected this month — set `enabled_for_close: false` in `sources.yaml`), offer `[S]`/`[N]`, and **STOP**. Do NOT advance to step-02 while an always-expected source is missing and unresolved. (`safra` is exempt only when the user confirms the known Safra download outage — record the pendency instead of halting, per the Safra note above.)
- **Intermittent** (only when there was activity): `avenue`, `mercado_bitcoin`, `bipa`. Their absence is NOT a halt — it is the "Missing (confirm)" prompt in step 6. When such a source IS present, its rows are gated downstream by `gate_spot_check_coverage.py` (#7) in step-04.

This is the investimentos counterpart of the gastos step-01 expected-source gate; it respects that broker/exchange activity is intermittent while still halting on a silently-missing always-expected source.

## Step Menu

- **Gatekeeper checkpoint** → before advancing, run § Per-Step Checkpoint in `../gatekeeper-loop.md` (out-of-structure, e.g. an unrecognized source file → Rule A; detected issue → Rule C blocking/deferrable; direct data read → re-route through a `tools-index.md` tool). The expected-source coverage gate above is this step's Rule C blocking check.
- **[C] Continue** → proceed to Step 02 (Parse)
- **[X] Exit** → halt workflow
