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
| Investor agent workflow definitions | `sb-os/finance/workflows/investor/*.md` | Read-only reasoning agent (six modes: thesis, research, review, portfolio, decision, policy); loop + capability manifest + per-mode files. Research-rigor primitives (Decompose, Disconfirm, Assumption Audit) and their placement: see Investor reasoning layer below |
| Finance wiki scribes (`sb-fin-create-thesis`, `sb-fin-create-decision`) | `sb-os/finance/workflows/sb-fin-*/` + `sb-os/finance/skills/sb-fin-*/` | Persistence helpers invoked by the investor; never invoked directly for thesis/decision creation |
| Credentials, bank configs, asset registry | `.user/finance/bookkeeper/{config,data}/` | Operational personal data — never open-sourced |
| Investment intermediate processed CSVs | `.user/finance/bookkeeper/investimentos/tmp-processed/` | Workflow scratch — overwritten per run |
| Personal records (e.g., `pagamentos-recorrentes.md`) | `2-areas/finance/` | Vault content, not pipeline data |
| Historical archived broker exports | `4-archives/finance/investments/historical-data/` | Archived; not consumed by current pipeline |

## Investor reasoning layer

The `investor` agent (read-only; six modes — thesis, research, review, portfolio, decision, policy) carries three deep-research reasoning primitives. This section specs WHERE each primitive lives and HOW consumers reach it; the step-by-step mechanics live in the workflow files (`workflows/investor/*.md`) and are not duplicated here.

**Primitives:**

- **Decompose** — split a research question / thesis claim into atomic sub-questions + a coverage matrix (pre-discovery scoping).
- **Disconfirm** — an adversarial discovery wave that asks "what source would OVERTURN this?" and hunts for it, surfacing disconfirming evidence.
- **Assumption Audit** — a first-principles reasoning lens that surfaces a thesis's hidden assumptions, classifies each, and rewrites them as testable questions.

**Placement (single evidence engine + reasoning-at-the-consumer):** the two discovery primitives live inside the `research` mode — the one evidence engine — and the reasoning lens lives inline at the two reasoning modes. The engine/lens boundary is "does it fetch the web?".

| Primitive | Nature | Home | Reached by |
|-----------|--------|------|------------|
| Decompose | Pre-discovery scoping | `research.md` Step 2.5 (before Discover) | Native to `research`; `thesis`/`review` get it transitively when they dispatch `research` |
| Width sweep (Discover) | Breadth discovery — fan-out web-search sub-agents | `research.md` Step 3 (Discover, rewritten single-sub-agent → capped parallel waves) | Inside `research`; consumed by dispatch |
| Disconfirm | Adversarial discovery wave | `research.md` Step 7a | `thesis`/`review` DISPATCH `research` (the existing `review`→`research` sub-agent precedent); never re-implemented |
| Assumption Audit | Reasoning lens (not discovery) | INLINE — `thesis.md` Step 2 + `review.md` Step 3/4 (standing assumptions) | Inline lens; its output (testable questions) becomes Disconfirm targets fed to the dispatched `research` |

**Dispatch / implementation model:** Disconfirm and the width sweep are implemented as **native sub-agent dispatch** (NOT the `deep-research` skill) — the same mechanism `research` Step 3 Discover already uses. Each sub-agent is directed to invoke `rbtv-web-searching` and follow it exactly, keeping discovery plugin-agnostic so the finance module stays portable. Sub-agents run **single-pass** (never loop), on the **Haiku** model, with **≤ 5 fetches per wave** (the cheap, capped cost model that preserves the agent's interactive present-and-confirm rhythm). Results return as **ranked candidates + metadata only** (title, url, source, trust class, why-it-matters, relation-to-thesis) into `research` Step 4 Propose; full source text stays inside each sub-agent so the parent context stays clean (anti-context-rot). The user approves the candidate subset at the existing Step 4 present-and-confirm checkpoint before anything is captured. This adds no new data-access path, no ledger mutation, and no change to the read-only / tools-only model — capture still happens only via `investment_source_capture`; the Assumption Audit writes nothing.

## Path-resolution conventions

- Python scripts use `_find_vault_root()` (looks for `sb-os.json` or `.obsidian/`) and build absolute paths from `VAULT_ROOT`.
- Dashboard JS uses paths relative to the entry HTML (`.user/finance/dashboard.html`) — vault-root-absolute under `/sb-os/finance/dashboard/...` for code, `/.user/finance/bookkeeper/...` for data.
- Workflow `.md` files use `{VARIABLE}` substitution defined in `bookkeeper.md` (e.g., `{RAW_DIR}`, `{PROCESSED_DIR}`, `{INV_LEDGER_DIR}`).

## Closing reports

Monthly closing reports (`{MONTH}-fechamento-mensal.md`) are no longer generated. The dashboard supersedes them. Historical reports are archived at `4-archives/finance/monthly-closings/`.
