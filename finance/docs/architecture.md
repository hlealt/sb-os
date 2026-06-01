# Finance Pipeline — Architecture

End-to-end flow from raw bank/broker statements to the financial dashboard.

## Two parallel pipelines

```
EXPENSES (gastos)                          INVESTMENTS (investimentos)

raw-data/{MONTH}/expenses/                 raw-data/{MONTH}/investment/
  └─ extrato-*.csv, fatura-*.pdf             └─ b3-*.xlsx, safra-*.csv, avenue-*.pdf
        │                                          │
        ▼ scripts/shared/normalize.py             ▼ scripts/investimentos/<parsers>
ledgers/expenses/{MONTH}/                  .user/finance/bookkeeper/investimentos/tmp-processed/
  └─ {bank}_extrato.csv, fatura_totals.json  └─ b3_orders.csv, b3_proventos.csv, ...
        │                                          │
        ▼ scripts/shared/categorize.py            ▼ scripts/investimentos/update_ledgers.py
ledgers/fechamento/{MONTH}/transactions.csv ledgers/investimentos/{orders,proventos,balcao,crypto}.csv
        │                                          │
        ▼ scripts/investimentos/calculate.py
        │                                  ledgers/investimentos/portfolio.json
        │                                          │
        └──────────────┬───────────────────────────┘
                       ▼
                 .user/finance/dashboard.html
```

## Roles by directory

| Directory | Role | Lifecycle |
|-----------|------|-----------|
| `.user/finance/bookkeeper/raw-data/{MONTH}/` | Inputs — bank/broker exports for the month | Created monthly, immutable after ingest |
| `.user/finance/bookkeeper/ledgers/expenses/{MONTH}/` | Normalized per-month expense CSVs | Output of `normalize.py`; regenerable from raw |
| `.user/finance/bookkeeper/ledgers/fechamento/{MONTH}/` | Categorized transactions for dashboard | Output of `categorize.py`; consumed by `expenses.js` |
| `.user/finance/bookkeeper/ledgers/investimentos/` | Consolidated, append-only investment ledgers | Append-only; `portfolio.json` is regenerable from CSVs |
| `sb-os/finance/dashboard/` | Browser-side rendering (JS/CSS/HTML template + dev server) | Code |
| `sb-os/finance/scripts/` | Python pipeline (shared + investimentos + migrations) | Code |
| `sb-os/finance/scripts/migrations/` | One-shot transformations (e.g., schema migrations) | Code; archive when no longer referenced |
| `.user/finance/bookkeeper/config/categories.json` | Categorization rules + reimbursement_mappings | Maintained interactively by bookkeeper; read by dashboard |
| `.user/finance/investor/` | Investor agent workspace: `research-policy.md`, `source-policy.md`, agent state | Written only by the `investor` agent or the user directly; never by bookkeeper or pipeline scripts |
| `sb-os/finance/docs/` | This file + functional/technical docs | Docs |

## What lives where

| Concern | Location | Reason |
|---------|----------|--------|
| Bookkeeper workflow definitions | `sb-os/finance/workflows/bookkeeper/*.md` | Workflow steps ship with sb-os; agent instructions, not code |
| Investor agent workflow definitions | `sb-os/finance/workflows/investor/*.md` | Read-only reasoning agent (six modes: thesis, research, review, portfolio, decision, policy); loop + capability manifest + per-mode files |
| Finance wiki scribes (`sb-fin-create-thesis`, `sb-fin-create-decision`) | `sb-os/finance/workflows/sb-fin-*/` + `sb-os/finance/skills/sb-fin-*/` | Persistence helpers invoked by the investor; never invoked directly for thesis/decision creation |
| Credentials, bank configs, asset registry | `.user/finance/bookkeeper/{config,data}/` | Operational personal data — never open-sourced |
| Investment intermediate processed CSVs | `.user/finance/bookkeeper/investimentos/tmp-processed/` | Workflow scratch — overwritten per run |
| Personal records (e.g., `pagamentos-recorrentes.md`) | `2-areas/finance/` | Vault content, not pipeline data |
| Historical archived broker exports | `4-archives/finance/investments/historical-data/` | Archived; not consumed by current pipeline |

## Path-resolution conventions

- Python scripts use `_find_vault_root()` (looks for `sb-os.json` or `.obsidian/`) and build absolute paths from `VAULT_ROOT`.
- Dashboard JS uses paths relative to the entry HTML (`.user/finance/dashboard.html`) — vault-root-absolute under `/sb-os/finance/dashboard/...` for code, `/.user/finance/bookkeeper/...` for data.
- Workflow `.md` files use `{VARIABLE}` substitution defined in `bookkeeper.md` (e.g., `{RAW_DIR}`, `{PROCESSED_DIR}`, `{INV_LEDGER_DIR}`).

## Closing reports

Monthly closing reports (`{MONTH}-fechamento-mensal.md`) are no longer generated. The dashboard supersedes them. Historical reports are archived at `4-archives/finance/monthly-closings/`.
