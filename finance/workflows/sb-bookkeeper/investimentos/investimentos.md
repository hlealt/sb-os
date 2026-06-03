# Investimentos

> **RETIRED — este índice de passos está desatualizado.** Lista 3 passos com nomes pré-restruturação; existem 8 passos em disco (`step-01-preflight.md` … `step-08-report.md`). A descrição canônica de "o que o workflow `sb-bookkeeper` faz" — incluindo o modo investimentos — é a seção `## What This Workflow Does` em [`../bookkeeper.md`](../bookkeeper.md). Para os passos individuais, ler diretamente os arquivos `step-NN-*.md` nesta pasta. O conteúdo abaixo é mantido apenas como registro histórico.

Investment tracking workflow — import historical data, ingest new source files, compute positions, validate against brokerage statements.

## Path Variables

```
WORKFLOW_DIR     = 3-resources/tools/sb-os/finance/workflows/sb-bookkeeper/investimentos
SCRIPTS_DIR      = 3-resources/tools/sb-os/finance/scripts/investimentos
CONFIG_DIR       = .user/finance/bookkeeper/config
ASSETS_FILE      = .user/finance/bookkeeper/data/assets.csv
LEDGER_DIR       = .user/finance/bookkeeper/ledgers/investimentos
INV_RAW_ROOT     = .user/finance/bookkeeper/raw-data                # per-month investment raw under {INV_RAW_ROOT}/{MONTH}/investment
INV_PROCESSED    = .user/finance/bookkeeper/investimentos/tmp-processed  # intermediate parsed CSVs (overwritten per run)
```

## Config Files

| File | Location | Purpose |
|------|----------|---------|
| `assets.csv` | `{ASSETS_FILE}` | Master asset registry (variable income, fixed income, funds, crypto) |
| `investment-sources.json` | `{CONFIG_DIR}` | Broker/exchange config with status and migration metadata |

## Ledger Files

| File | Location | Content |
|------|----------|---------|
| `orders.csv` | `{LEDGER_DIR}` | Stock/ETF/FII/FIAGRO/option buy/sell orders |
| `proventos.csv` | `{LEDGER_DIR}` | Dividends, JCP, FII rendimentos, frações |
| `balcao.csv` | `{LEDGER_DIR}` | Fixed income + fund transactions (apply, redeem, interest, tax) |
| `crypto.csv` | `{LEDGER_DIR}` | Crypto trades (fiat↔crypto and crypto↔crypto) |

## Steps

| Step | File | Purpose |
|------|------|---------|
| 1 | `step-01-import-spreadsheet.md` | Import historical spreadsheet CSVs into ledgers |
| 2 | `step-02-import-sources.md` | Parse source files (Safra, Bipa, XP, etc.) and append to ledgers |
| 3 | `step-03-validate.md` | Compute positions and validate against brokerage statements |

## Rules

- Communicate in Brazilian Portuguese
- Ledgers are append-only — never delete or modify existing rows
- Every row has a `source` column identifying data origin
- Never skip steps. Each step ends with STOP for user confirmation
- On error: report complete error, ask user how to proceed
