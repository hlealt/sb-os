# Finance Pipeline — Architecture

End-to-end flow from raw bank/broker statements to the financial dashboard.

## Two parallel pipelines

```
EXPENSES (gastos)                          INVESTMENTS (investimentos)

raw/{MONTH}/expenses/                      raw/{MONTH}/investment/
  └─ extrato-*.csv, fatura-*.pdf             └─ b3-*.xlsx, safra-*.csv, avenue-*.pdf
        │                                          │
        ▼ scripts/accountant/shared/normalize.py   ▼ scripts/accountant/investimentos/<parsers>
ledgers/expenses/{MONTH}/                  .user/workflows/accountant/investimentos/tmp-processed/
  └─ {bank}_extrato.csv, fatura_totals.json  └─ b3_orders.csv, b3_proventos.csv, ...
        │                                          │
        ▼ scripts/accountant/shared/categorize.py  ▼ scripts/accountant/investimentos/update_ledgers.py
ledgers/fechamento/{MONTH}/transactions.csv ledgers/investimentos/{orders,proventos,balcao,crypto}.csv
        │                                          │
        ▼ scripts/accountant/investimentos/calculate.py
        │                                  ledgers/investimentos/portfolio.json
        │                                          │
        └──────────────┬───────────────────────────┘
                       ▼
                 dashboard.html
```

## Roles by directory

| Directory | Role | Lifecycle |
|-----------|------|-----------|
| `raw/{MONTH}/` | Inputs — bank/broker exports for the month | Created monthly, immutable after ingest |
| `ledgers/expenses/{MONTH}/` | Normalized per-month expense CSVs | Output of `normalize.py`; regenerable from raw |
| `ledgers/fechamento/{MONTH}/` | Categorized transactions for dashboard | Output of `categorize.py`; consumed by `expenses.js` |
| `ledgers/investimentos/` | Consolidated, append-only investment ledgers | Append-only; `portfolio.json` is regenerable from CSVs |
| `scripts/dashboard/` | Browser-side rendering | Code |
| `scripts/accountant/` | Python pipeline | Code |
| `scripts/migrations/` | One-shot transformations (e.g., schema migrations) | Code; archive when no longer referenced |
| `config/categories.json` | Categorization rules + reimbursement_mappings | Maintained interactively by accountant; read by dashboard |
| `docs/` | This file + functional/technical docs | Docs |

## What lives outside `3-resources/tools/finance/`

| Concern | Location | Reason |
|---------|----------|--------|
| Workflow definitions | `.user/workflows/accountant/*.md` | Workflow steps are agent instructions, not code; sb-os convention |
| Credentials, bank configs, asset registry | `.user/workflows/accountant/{config,data}/` | Operational personal data — never open-sourced |
| Investment intermediate processed CSVs | `.user/workflows/accountant/investimentos/tmp-processed/` | Workflow scratch — overwritten per run |
| Personal records (e.g., `pagamentos-recorrentes.md`) | `2-areas/finance/` | Vault content, not pipeline data |
| Historical archived broker exports | `4-archives/finance/investments/historical-data/` | Archived; not consumed by current pipeline |

## Path-resolution conventions

- Python scripts use `_find_vault_root()` (looks for `sb-os.json` or `.obsidian/`) and build absolute paths from `VAULT_ROOT`.
- Dashboard JS uses paths relative to `dashboard.html` location (e.g., `./ledgers/...`, `./config/...`).
- Workflow `.md` files use `{VARIABLE}` substitution defined in `accountant.md` (e.g., `{RAW_DIR}`, `{PROCESSED_DIR}`, `{INV_LEDGER_DIR}`).

## Closing reports

Monthly closing reports (`{MONTH}-fechamento-mensal.md`) are no longer generated. The dashboard supersedes them. Historical reports are archived at `4-archives/finance/monthly-closings/`.
