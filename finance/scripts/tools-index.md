# Finance Tool Registry (`tools-index.md`)

> Canonical registry of the finance module's **tool layer** under `sb-os/finance/scripts/`. Sibling agents (`sb-bookkeeper`, `sb-investor`) read this index to discover available tools by class and use; companion agents (`tool-builder`, `doc-maintainer`) maintain it. This file is the single source of truth for "what tools exist, what class they are, and how to invoke them."

> **Scope — what belongs here.** A registry entry is a **registered tool**: a parser, retro-rewrite, upsert, audit-diagnostic, or validation-gate that an agent reaches for to read or mutate data on the user's behalf. The deterministic pipeline scripts (`calculate.py`, `categorize.py`, `fx_engine.py`, `normalize.py`, the per-source parser modules, and the `shared/lib/` helpers) are NOT registry tools — they are the pipeline whose ledger data is read THROUGH tools, and they already emit audit events on every ledger write. Do NOT register a pipeline script as a tool. Register the diagnostic/validation/dry-run/retro-rewrite tools that observe or correct that pipeline.

---

## Three-Class Taxonomy + Quality Bars

The architectural divide is **Write vs Read**. Sub-uses live below each class. The taxonomy and quality bars are authoritative; every entry's `class` and `use` fields MUST come from this table. (Source: `structured-problem.md` § Tool Registry; foundation `shape.md` Tool-taxonomy decision; tool-builder authority boundary 2026-05-05.)

| Class | Mutates data? | Sub-uses (the `use` field) | Quality bar |
|-------|---------------|----------------------------|-------------|
| **write** | Yes | `parser` — ingests from a source into a ledger / config. `retro-rewrite` — renames, merges, canonical corrections, code-migrations. `upsert` — asset-metadata writes via the field-ownership manifest. | Mandatory `--dry-run` mode. For `retro-rewrite`: mandatory **fix-impact preview** enumerating every affected location (rows, configs, dashboard joins, tag namespaces) BEFORE any write; rollback path. Every write tool ships a schema-validation test against the destination artifact's current schema. A registry entry AND a doc-maintainer documentation update are part of definition-of-done. |
| **read** | No | `audit-diagnostic` — interactive Q&A for an agent or user ("show all transactions over R$500"; "list every place vendor X appears"). `validation-gate` — pass/fail check consumed by the workflow / pre-commit / CI (e.g. the tag-coverage gate "R$-coverage ≥ 0.75 AND no unacknowledged untagged despesa > R$300"; "rf_balcao within 7–15%?"). | `audit-diagnostic` — human-readable output (pretty-printed tables, summaries). `validation-gate` — clean pass/fail **exit codes** (0 = pass, non-zero = fail) for machine consumption. A registry entry AND a doc-maintainer documentation update are part of definition-of-done. |

**Why Read has two sub-uses despite being one class:** they share the read primitive but have different *output contracts*. Audit-diagnostic output is read by a human or an agent in conversation, so it must be human-readable. Validation-gate output is read by a hook or workflow, so it must be a machine-parseable pass/fail exit code. The sub-use determines which contract the tool must satisfy.

**Tool-builder authority boundary (applies to every `write` entry):** the tool-builder companion NEVER writes ledgers / `portfolio.json` / dashboard directly — its output is *tools* only. Generated tools conform to the destination artifact's existing schema by default; a legitimate schema gap is surfaced to the user (a `schema_gap_finding` audit event + a user-facing prompt), never flattened away or unilaterally migrated.

---

## Per-Entry Schema (YAML front-matter per entry)

Each tool is one fenced ```yaml block below the `## Registered Tools` heading. The block is a flat map of labeled fields — NOT a row in a wide table. This format was chosen (decision S6, 2026-05-27) so that: sibling agents parse each entry reliably; the `doc-maintainer` companion (`p5-5`) updates a single field as a one-line diff; and the ~10 fields per tool stay readable.

Every entry MUST carry exactly these keys, in this order:

| Field | Meaning |
|-------|---------|
| `tool` | Invocation name (the CLI name or `python -m` target the agent calls). |
| `purpose` | One sentence: what question the tool answers or what mutation it performs. |
| `owner_script` | Repo-relative path (from `sb-os/finance/scripts/`) to the script that implements the tool. |
| `class` | `write` or `read` — from the taxonomy table. |
| `use` | One of `parser` / `retro-rewrite` / `upsert` / `audit-diagnostic` / `validation-gate` — from the taxonomy table. |
| `expected_inputs` | The arguments and the data stores / files the tool reads. |
| `outputs` | What the tool emits (report shape, or the store it writes). |
| `canonical_reader_writer` | The canonical store(s) this tool reads from or writes to. For read tools, the store(s) read; for write tools, the store(s) written. |
| `dry_run` | `available` / `not-applicable` / `default`. `write` tools MUST be `available` or `default`. Read tools are `not-applicable` (they never mutate). |
| `last_validated` | ISO date (`YYYY-MM-DD`) the tool was last confirmed working against real data, or `pending` if not yet validated post-build. |

### Discoverability conventions (machine-readable)

A sibling agent lists tools by class or use without parsing prose. To keep that reliable:

- Keys are lowercase snake_case, identical across every entry, always all ten present.
- `class` is exactly `write` or `read`. `use` is exactly one of the five literals above. No synonyms, no free text in these two fields.
- To "list every validation-gate tool," an agent scans the YAML blocks for `use: validation-gate`. To "list every write tool," it scans for `class: write`.
- One tool per block. Never combine two tools in one block.

### Append convention (binding on `p4-2`…`p4-26`)

This index is seeded below with the tools that already exist. **Every subsequent Phase-4 tool task (`p4-2` through `p4-26`) MUST append its own entry to `## Registered Tools` as part of its definition-of-done** — a tool is not "done" until its registry entry exists with all ten fields populated. The `doc-maintainer` companion (`p5-5`) maintains entries thereafter (e.g. re-stamping `last_validated`). Append new blocks; never rewrite seeded ones except to update a field.

---

## Registered Tools

```yaml
tool: audit_cli  (python -m lib.audit_cli tail [--last N] [--since DATE] [--actor A] [--run ID] [--type T])
purpose: Print a compact human-readable tail of the audit-event stream so the user/agent can review what the pipeline and bookkeeper have written.
owner_script: shared/lib/audit_cli.py
class: read
use: audit-diagnostic
expected_inputs: CLI flags (--last/--since/--actor/--run/--type); reads .user/finance/bookkeeper/audit/events-{YYYY}.jsonl
outputs: One formatted line per event (timestamp, actor, event_type, materiality, source -> destination, row/byte deltas; gate events show metric=value vs threshold). Human-readable; not JSON.
canonical_reader_writer: reads .user/finance/bookkeeper/audit/events-{YYYY}.jsonl
dry_run: not-applicable
last_validated: pending
```

```yaml
tool: detect_snapshot_contamination (python detect_snapshot_contamination.py [--snapshots-dir PATH])
purpose: Flag any dated portfolio snapshot whose api-priced positions carry a price_date different from meta.cut_date (mixed-date contamination per p2-24).
owner_script: investimentos/detect_snapshot_contamination.py
class: read
use: validation-gate
expected_inputs: optional --snapshots-dir; reads portfolio-{date}.json snapshots under .user/finance/bookkeeper/ledgers/investimentos/
outputs: Per-snapshot result (cut_date, contaminated bool, offenders list, clean/missing counts). Exit 0 = no contamination; exit 1 = one or more snapshots contaminated.
canonical_reader_writer: reads .user/finance/bookkeeper/ledgers/investimentos/portfolio-{date}.json
dry_run: not-applicable
last_validated: 2026-05-26
```

```yaml
tool: dryrun_safra_import (python dryrun_safra_import.py)
purpose: Simulate importing the 6 Safra bootstrap CSVs into balcao.csv / balance-snapshots.csv / assets.csv WITHOUT writing, reporting per-file diffs so anomalies surface before a real import.
owner_script: investimentos/dryrun_safra_import.py
class: read
use: validation-gate
expected_inputs: no args; reads .user/finance/bookkeeper/raw-data/safra-bootstrap-2024-2026/*.csv and the current ledger stores via the real upsert logic
outputs: Inserted-vs-skipped per file per bucket; inserted rows grouped by (product_id, operation); any product_id that would change its earliest-flow date (IRR risk). Writes nothing.
canonical_reader_writer: reads raw-data/safra-bootstrap-2024-2026/*.csv + ledgers/investimentos/{balcao.csv,balance-snapshots.csv,assets.csv} (no write)
dry_run: not-applicable
last_validated: pending
```

```yaml
tool: dryrun_safra_movimentacoes (python dryrun_safra_movimentacoes.py)
purpose: Dry-run the Safra movimentacoes parsers (fundos + RF) against the bootstrap CSVs, printing per-file/per-bucket summary stats and any flagged unknown lancamentos, writing nothing to ledgers.
owner_script: investimentos/dryrun_safra_movimentacoes.py
class: read
use: validation-gate
expected_inputs: no args; reads .user/finance/bookkeeper/raw-data/safra-bootstrap-2024-2026/*.csv
outputs: Summary stats per file and per output bucket; surfaced unknown-lancamento flags. Writes nothing.
canonical_reader_writer: reads raw-data/safra-bootstrap-2024-2026/*.csv (no write)
dry_run: not-applicable
last_validated: pending
```

```yaml
tool: sample_from_ledger (python shared/sample_from_ledger.py <ledger> [--month] [--category] [--vendor] [--amount-min] [--amount-max] [--limit] [--offset])
purpose: Return a small, bounded spot-checkable row slice from a normalized per-bank extrato CSV or a fechamento transactions.csv so bookkeeper can validate by judgment without reading raw CSVs/JSONs directly (P0 tools-only access gap, p4-2).
owner_script: shared/sample_from_ledger.py
class: read
use: audit-diagnostic
expected_inputs: ledger path relative to .user/finance/bookkeeper/ledgers/ (or absolute); optional filters --month YYYY-MM, --category, --vendor PATTERN, --amount-min, --amount-max; --limit (capped at 50), --offset; reads ledgers/expenses/{YYYY-MM}/{bank}_extrato.csv or ledgers/fechamento/{YYYY-MM}/transactions.csv
outputs: Pretty-printed table of matching rows (key columns only); slice-guardrail footer showing cap. Never returns the full ledger (hard cap 50 rows per call).
canonical_reader_writer: reads .user/finance/bookkeeper/ledgers/expenses/{YYYY-MM}/*.csv and .user/finance/bookkeeper/ledgers/fechamento/{YYYY-MM}/transactions.csv (no write)
dry_run: not-applicable
last_validated: 2026-05-27
```

```yaml
tool: query_corrections (python shared/query_corrections.py [--file NAME] [--month] [--category] [--identity] [--pattern] [--limit])
purpose: Query the append-only corrections side-ledgers under .user/finance/bookkeeper/config/corrections/ and return human-readable rows answering what corrections exist for a given transaction, month, category, or identity key.
owner_script: shared/query_corrections.py
class: read
use: audit-diagnostic
expected_inputs: optional --file to target one corrections file; optional --month YYYY-MM, --category, --identity tx_date|tx_description|tx_amount, --pattern; --limit (hard cap 100); reads all *.csv under .user/finance/bookkeeper/config/corrections/ (manual-overrides.csv, competencia-overrides.csv, category-migrations.csv, code_migrations.csv, vendor-canonicals.csv, tag-renames.csv, per-asset-type files)
outputs: Per-file section with matching rows pretty-printed; total count footer. Writes nothing.
canonical_reader_writer: reads .user/finance/bookkeeper/config/corrections/*.csv (no write)
dry_run: not-applicable
last_validated: 2026-05-27
```

```yaml
tool: query_name_map (python shared/query_name_map.py [--source] [--field] [--raw] [--canonical] [--asset-type] [--limit] [--name-map-path])
purpose: Surface the ticker/instrument name-map entries from name_map.csv in human-readable form so bookkeeper can inspect canonical mappings without reading the raw ledger CSV directly.
owner_script: shared/query_name_map.py
class: read
use: audit-diagnostic
expected_inputs: optional --source (b3/safra/bipa/…), --field (fundo/produto/…), --raw PATTERN, --canonical PATTERN, --asset-type; --limit (hard cap 200); --name-map-path to override default; reads .user/finance/bookkeeper/ledgers/investimentos/name_map.csv
outputs: Pretty-printed table of matching name-map entries (source, field, raw_value, canonical_value, asset_type). Writes nothing.
canonical_reader_writer: reads .user/finance/bookkeeper/ledgers/investimentos/name_map.csv (no write)
dry_run: not-applicable
last_validated: 2026-05-27
```

```yaml
tool: position_summary (python investimentos/position_summary.py PRODUCT_ID [--ledger-dir PATH] [--assets-path PATH])
purpose: All-in-one diagnostic for a single investment position — metadata, balcão summary, balance-snapshot trajectory, and inline sub-detector results (phantom application, stale-active maturity, cross-source duplicate detection).
owner_script: investimentos/position_summary.py
class: read
use: audit-diagnostic
expected_inputs: product_id string; optional --ledger-dir PATH, --assets-path PATH; reads balcao.csv, assets.csv, balance-snapshots.csv; env overrides BOOKKEEPER_INVESTIMENTOS_DIR, BOOKKEEPER_ASSETS_PATH
outputs: Structured plain-text report with sections for metadata, balcao summary, snapshot trajectory, and per-anomaly blocks headed by === [ANOMALY TYPE] === (cross-source dup groups covered by the read-time dedup render as === [INFO] === and do not count as anomalies). Exit 0 = clean; exit 1 = anomaly found.
canonical_reader_writer: reads .user/finance/bookkeeper/ledgers/investimentos/balcao.csv + assets.csv + balance-snapshots.csv (no write)
dry_run: not-applicable
last_validated: 2026-06-05
```

```yaml
tool: validate_calculate (python investimentos/validate_calculate.py [--portfolio-path PATH] [--strict])
purpose: Re-reads portfolio.json and checks IRR sanity — per-class IRR table, irr_quality histogram, and violation detection (|irr| > 200%, missing irr_quality on valued balcão position). --strict exits non-zero on any violation.
owner_script: investimentos/validate_calculate.py
class: read
use: audit-diagnostic
expected_inputs: optional --portfolio-path PATH (default portfolio.json); optional --strict flag; env override BOOKKEEPER_PORTFOLIO_PATH; reads .user/finance/bookkeeper/ledgers/investimentos/portfolio.json
outputs: Human-readable report: total IRR + value, per-class IRR table (columns IRR all, F all, IRR cur, F cur — cur columns render n/a for legacy portfolios without summary.irr.current), irr_quality histogram, violation list (checks both all-time and current total/per_class against ±200% band), Current IRR summary line. Exit 0 always in verbose mode; exit 0/1 in --strict mode (0=clean, 1=violation).
canonical_reader_writer: reads .user/finance/bookkeeper/ledgers/investimentos/portfolio.json (no write)
dry_run: not-applicable
last_validated: 2026-06-05
```

```yaml
tool: position_table (python investimentos/position_table.py [--bucket rv_eua] [--currency USD] [--type cra] [--portfolio-path PATH])
purpose: Tabular CLI dump of all active positions from portfolio.json filtered by class bucket, currency, or type — equivalent to reading the dashboard table offline with totals row.
owner_script: investimentos/position_table.py
class: read
use: audit-diagnostic
expected_inputs: optional --bucket (rv_br|rv_eua|rf_balcao|fundos|crypto), --currency (USD|BRL), --type (acao|cra|…), --portfolio-path; env override BOOKKEEPER_PORTFOLIO_PATH; reads portfolio.json
outputs: ASCII table — one row per position (id, bucket, qty, avg_cost, price, pnl%, cost_brl, value_brl, pnl_brl, irr, quality) plus TOTAL row. Exit 0 always; exit 1 if portfolio.json not found.
canonical_reader_writer: reads .user/finance/bookkeeper/ledgers/investimentos/portfolio.json (no write)
dry_run: not-applicable
last_validated: 2026-05-27
```

```yaml
tool: bucket_sanity_check (python investimentos/bucket_sanity_check.py [--bucket rv_eua] [--threshold 0.05] [--portfolio-path PATH])
purpose: For each IRR class bucket, compare the simple average of per-asset IRRs against the stored portfolio bucket IRR and flag divergences exceeding the threshold — catches unexpected bucket-vs-per-asset mismatches.
owner_script: investimentos/bucket_sanity_check.py
class: read
use: audit-diagnostic
expected_inputs: optional --bucket (rv_br|rv_eua|rf_balcao|fundos|crypto), --threshold float (default 0.05 = 5%), --portfolio-path; env override BOOKKEEPER_PORTFOLIO_PATH; reads portfolio.json. Programmatic callers may pass informational_buckets (frozenset) to check_buckets() — buckets in this set print their section but are never counted in the return value (gate_bucket_divergence passes {'crypto'} here; standalone CLI default counts every bucket).
outputs: Per-bucket section with per-asset IRR table, simple-avg vs stored-bucket delta, and >>> DIVERGENCE <<< flag when threshold exceeded; informational-bucket divergences additionally marked "informational — not counted". Exit 0 always from CLI (informational — time-weighting divergence is expected); check_buckets() returns divergence count for programmatic callers.
canonical_reader_writer: reads .user/finance/bookkeeper/ledgers/investimentos/portfolio.json (no write)
dry_run: not-applicable
last_validated: 2026-06-05
```

```yaml
tool: task_status_check (python shared/task_status_check.py PROJECT TASK [--subtasks 3,4] [--vault-root PATH])
purpose: Given a project name and task title substring, reads the tasks file, extracts _Ref_ code-anchor references, greps those anchors in the codebase, and reports per-anchor SHIPPED/STALE/NOT_YET/UNCLEAR status — prevents redundant re-implementation of already-shipped subtasks.
owner_script: shared/task_status_check.py
class: read
use: audit-diagnostic
expected_inputs: PROJECT (folder name or direct path to tasks file), TASK (title substring, case-insensitive); optional --subtasks comma-separated indices, --vault-root PATH; reads {project}-tasks.md + greps codebase files
outputs: Markdown-style table per code anchor (status, ref, detail) + subtask summary + shipped/not-yet count. Exit 0 if all anchors SHIPPED or UNCLEAR; exit 1 if any NOT_YET or task/project not found.
canonical_reader_writer: reads {project}-tasks.md + codebase .py files (no write)
dry_run: not-applicable
last_validated: 2026-05-27
```

```yaml
tool: fx_impact_report (python investimentos/fx_impact_report.py [--portfolio-path PATH])
purpose: For all USD (rv_eua) positions, decomposes total BRL P&L into native asset gain (price appreciation in USD) and FX gain (USD/BRL rate change on cost basis) — answers "how much of rv_eua performance is the company vs the dollar appreciating?"
owner_script: investimentos/fx_impact_report.py
class: read
use: audit-diagnostic
expected_inputs: optional --portfolio-path PATH; env override BOOKKEEPER_PORTFOLIO_PATH; reads portfolio.json and fx_engine.py FX state (per-ticker weighted rates)
outputs: Per-position table (id, cost_brl, value_brl, native_pnl_brl, fx_gain_brl, total_pnl_brl, fx_rate_at_cost) with TOTAL row; footer with portfolio-level FX attribution (e.g. "FX added R$X of the R$Y total rv_eua gain"). Exit 0 always; exit 1 if portfolio.json not found.
canonical_reader_writer: reads .user/finance/bookkeeper/ledgers/investimentos/portfolio.json + avenue_fx.csv/orders.csv/proventos.csv via fx_engine (no write)
dry_run: not-applicable
last_validated: 2026-05-27
```

```yaml
tool: audit_balcao_dups (python investimentos/audit_balcao_dups.py [--product-id ID] [--ledger-dir PATH])
purpose: Scan balcao.csv for rows sharing the same (date, operation, |amount|) triple across different source values, flagging cross-source duplication (e.g. b3_manual and safra_movimentacoes both recorded the same amortization event).
owner_script: investimentos/audit_balcao_dups.py
class: read
use: audit-diagnostic
expected_inputs: optional --product-id to narrow to one asset; optional --ledger-dir PATH; env override BOOKKEEPER_INVESTIMENTOS_DIR; reads balcao.csv
outputs: Per-asset duplicate groups (date, operation, amount, source list), each annotated covered / NOT-covered by the read-time dedup (`_dedup_cross_source_balcao`, precedence safra_movimentacoes > b3 > b3_manual); convention-compliant action text (corrections entry — never delete ledger rows). Exit 0 = clean or all groups covered; exit 1 = uncovered duplicates or balcao.csv missing.
canonical_reader_writer: reads .user/finance/bookkeeper/ledgers/investimentos/balcao.csv (no write)
dry_run: not-applicable
last_validated: 2026-06-05
```

```yaml
tool: find_phantom_application (python investimentos/find_phantom_application.py [--ledger-dir PATH] [--assets-path PATH])
purpose: Scan balcao.csv for positions where juros_amort_total > 0 but aplicado_total = 0, indicating a phantom income stream with no recorded principal investment (common when parser data window starts after the actual investment date).
owner_script: investimentos/find_phantom_application.py
class: read
use: audit-diagnostic
expected_inputs: optional --ledger-dir PATH, --assets-path PATH; env overrides BOOKKEEPER_INVESTIMENTOS_DIR, BOOKKEEPER_ASSETS_PATH; reads balcao.csv + assets.csv
outputs: Table of flagged product_ids (juros_amort_total, first_balcao_date, application_date, active); total phantom income summary. Exit 0 = clean; exit 1 = phantoms found or balcao.csv missing.
canonical_reader_writer: reads .user/finance/bookkeeper/ledgers/investimentos/balcao.csv + .user/finance/bookkeeper/data/assets.csv (no write)
dry_run: not-applicable
last_validated: 2026-05-27
```

```yaml
tool: audit_active_vs_maturity (python investimentos/audit_active_vs_maturity.py [--assets-path PATH] [--ledger-dir PATH] [--activity-days N])
purpose: Scan assets.csv for STALE-ACTIVE assets (active=true but maturity_date < today, inflating portfolio value) and STALE-INACTIVE assets (active=false but recent balcao activity within N days — converse anomaly).
owner_script: investimentos/audit_active_vs_maturity.py
class: read
use: audit-diagnostic
expected_inputs: optional --assets-path PATH, --ledger-dir PATH, --activity-days N (default 90); env overrides BOOKKEEPER_ASSETS_PATH, BOOKKEEPER_INVESTIMENTOS_DIR; reads assets.csv + optionally balcao.csv
outputs: Two sections: stale-active table (product_id, maturity_date, days_past_maturity, last_balcao_date) and stale-inactive table (product_id, last_balcao_date, days_since_activity). Exit 0 = clean; exit 1 = anomalies found or assets.csv missing.
canonical_reader_writer: reads .user/finance/bookkeeper/data/assets.csv + .user/finance/bookkeeper/ledgers/investimentos/balcao.csv (no write)
dry_run: not-applicable
last_validated: 2026-05-27
```

```yaml
tool: audit-aliases (python shared/audit-aliases.py [--suppliers-path PATH] [--duplicates-only])
purpose: Scan suppliers.json for alias strings that appear under more than one supplier entry — duplicate aliases are a silent ambiguity because categorize.py's first-match-wins lookup resolves to different suppliers depending on iteration order.
owner_script: shared/audit-aliases.py
class: read
use: validation-gate
expected_inputs: optional --suppliers-path PATH; optional --duplicates-only flag (omit stats header); env override BOOKKEEPER_SUPPLIERS_PATH; reads suppliers.json
outputs: Table of duplicate aliases with the supplier slugs they appear under; count of affected aliases and suppliers; recommended action. Exit 0 = clean; exit 1 = duplicates found or suppliers.json missing (suitable as pre-commit hook).
canonical_reader_writer: reads .user/finance/bookkeeper/config/suppliers.json (no write)
dry_run: not-applicable
last_validated: 2026-05-27
```

```yaml
tool: gate_pass_1_queue (python shared/gate_pass_1_queue.py [--queue-state PATH])
purpose: Gate #11 (P0) — verify Pass-1 review queue is fully resolved (zero items) before Pass 2 is dispatched; raises QueueOrderingError condition as a pass/fail exit code.
owner_script: shared/gate_pass_1_queue.py
class: read
use: validation-gate
expected_inputs: optional --queue-state PATH to queue state JSON {pass_1_items: [...], pass_2_items: [...]} written by bookkeeper step-05; no-arg call = vacuous pass
outputs: PASS (exit 0) when pass_1_items is empty or pass_2 is not yet queued; FAIL (exit 1) when pass_1 items remain while pass_2 is pending; emits gate_pass/gate_fail event.
canonical_reader_writer: reads queue state JSON (no ledger write)
dry_run: not-applicable
last_validated: 2026-05-27
```

```yaml
tool: gate_ledger_tolerance (python shared/gate_ledger_tolerance.py --report PATH)
purpose: Gate #6 (P0) — verify the ledger upsert used tolerance=0 (exact-match dedup only); fail-loud if any fuzzy match appears in the update_ledgers report.
owner_script: shared/gate_ledger_tolerance.py
class: read
use: validation-gate
expected_inputs: --report PATH to upsert report JSON {ledger_name: {inserted, skipped_exact, skipped_fuzzy, ...}} from update_ledgers.py; env override BOOKKEEPER_AUDIT_DISABLED
outputs: PASS (exit 0) when skipped_fuzzy is empty across all ledgers; FAIL (exit 1) when any fuzzy match found; emits gate_pass/gate_fail event.
canonical_reader_writer: reads update_ledgers report JSON (no ledger write)
dry_run: not-applicable
last_validated: 2026-05-27
```

```yaml
tool: gate_transaction_count (python shared/gate_transaction_count.py [--expenses-dir PATH] [--month YYYY-MM])
purpose: Gate #4 (P1) — transaction-count sanity per bank file; fail-loud if any present file has zero rows or if >10% of rows fall outside the expected month ±5 days.
owner_script: shared/gate_transaction_count.py
class: read
use: validation-gate
expected_inputs: optional --expenses-dir PATH to normalized expenses/{YYYY-MM}/ directory; optional --month YYYY-MM; defaults to most-recent month under .user/finance/bookkeeper/ledgers/expenses/; reads *.csv files
outputs: Per-file PASS/FAIL table; PASS (exit 0) all files have rows and within tolerance; FAIL (exit 1) any file fails; exit 2 on missing directory; emits gate_pass/gate_fail event.
canonical_reader_writer: reads .user/finance/bookkeeper/ledgers/expenses/{YYYY-MM}/*.csv (no write)
dry_run: not-applicable
last_validated: 2026-05-27
```

```yaml
tool: gate_spot_check_coverage (python shared/gate_spot_check_coverage.py --coverage-record PATH)
purpose: Gate #7 (P1) — mandatory spot-check source classes (B3 orders+proventos, Safra balcao, Avenue orders+fx if present, 1 crypto if present) must all be covered; auto-halt before step-05 if any mandatory class was skipped.
owner_script: shared/gate_spot_check_coverage.py
class: read
use: validation-gate
expected_inputs: --coverage-record PATH to JSON {checked: [...], present_sources: [...]} written by bookkeeper step-04 after spot-checking
outputs: PASS (exit 0) all mandatory classes for present sources are covered; FAIL (exit 1) any mandatory class missing; exit 2 on missing record; emits gate_pass/gate_fail event.
canonical_reader_writer: reads coverage record JSON (no ledger write)
dry_run: not-applicable
last_validated: 2026-05-27
```

```yaml
tool: gate_portfolio_delta (python shared/gate_portfolio_delta.py [--portfolio PATH] [--prior-snapshot PATH] [--flagged-ids IDS] [--flagged FILE])
purpose: Gate #8 (P1) — portfolio delta anomaly detector; auto-halt if any UNFLAGGED anomaly exists (per-position variacao >20%, position zeroed unexpectedly, or new unknown ticker vs prior snapshot).
owner_script: shared/gate_portfolio_delta.py
class: read
use: validation-gate
expected_inputs: optional --portfolio PATH (default portfolio.json); optional --prior-snapshot PATH (default latest dated snapshot); optional --flagged-ids comma-separated IDs or --flagged FILE with JSON list of user-acknowledged anomaly IDs; reads portfolio.json + prior portfolio-{date}.json
outputs: Anomaly table with FLAGGED/UNFLAGGED markers; PASS (exit 0) when all anomalies are flagged or none exist; FAIL (exit 1) when unflagged anomalies remain; exit 2 on missing files; emits gate_pass/gate_fail event.
canonical_reader_writer: reads .user/finance/bookkeeper/ledgers/investimentos/portfolio*.json (no write)
dry_run: not-applicable
last_validated: 2026-05-27
```

```yaml
tool: gate_coverage (python shared/gate_coverage.py [--transactions PATH] [--loop-count N] [--config-dir PATH] [--ack-file PATH])
purpose: Gates #1/#3 (ANDed, P2, S7) — R$-coverage >= config threshold (0.75) AND no unacknowledged untagged despesa > config floor (R$300); gate 2 row-coverage is informational only (printed + audit event, never fails); auto-loops up to 3 times then surfaces the "Proceed anyway? [S/N]" user prompt. THRESHOLD PROVENANCE (compound cp-sb-bookkeeper-gates-measure-meaning, change 3): each config threshold MUST carry a sibling `*_provenance` block naming the metric it was decided for (step_5_5_coverage.threshold → despesas_tagged_brl_pct; tag_coverage.gate.untagged_amount_threshold_brl → untagged_despesa_floor_brl); a missing or metric-mismatched (inherited) block makes the gate refuse to run (exit 2) rather than silently enforce a borrowed number.
owner_script: shared/gate_coverage.py
class: read
use: validation-gate
expected_inputs: optional --transactions PATH to transactions.csv (default: latest fechamento month); optional --loop-count N (current auto-loop iteration, default 0); optional --config-dir PATH; optional --ack-file PATH to tag-review-acks.csv (default: .user/finance/bookkeeper/config/corrections/tag-review-acks.csv); reads standing-rules.yaml for R$ threshold (gates.step_5_5_coverage.threshold, 0.75) and floor (tag_coverage.gate.untagged_amount_threshold_brl, 300); reads tag-review-acks.csv (identity-keyed ack side-ledger; missing file treated as empty set; malformed file — missing identity columns — exits 2); excludes receitas/intercontas/ignorar/venda
outputs: R$ coverage % + row coverage % (informational) + a `Provenance:` line per config threshold naming the metric it was decided for + ACK/VIOLATION lines per large-untagged row (ACK = row acked in tag-review-acks.csv, VIOLATION = unacked); PASS (exit 0) gate 1 R$ >= threshold AND gate 3 zero VIOLATION lines; FAIL (exit 1) gate 1 below threshold OR any VIOLATION line; exit 2 on missing transactions.csv, malformed ack file, OR a config threshold whose `*_provenance` block is absent or names a different metric (threshold-provenance check, compound change 3); emits coverage_progress (x2) + gate_pass/gate_fail events (trigger_context.gate3_acked_skips = count of acked rows above floor; gate1_threshold_metric / gate3_floor_metric = the provenance metric per threshold). Max-loop guard at 3 iterations.
canonical_reader_writer: reads .user/finance/bookkeeper/ledgers/fechamento/{YYYY-MM}/transactions.csv; reads .user/finance/bookkeeper/config/corrections/tag-review-acks.csv (no write); reads gates.step_5_5_coverage.threshold(+_provenance) and tag_coverage.gate.untagged_amount_threshold_brl(+_provenance) from standing-rules.yaml
dry_run: not-applicable
last_validated: 2026-06-08
```

```yaml
tool: gate_irr_sanity (python shared/gate_irr_sanity.py [--portfolio-path PATH] [--config-dir PATH])
purpose: Gate #9 (P3, S7-2) — IRR strict sanity: |irr|>200% → fail; irr_quality missing on valued balcão → fail; rf_balcao annualized return outside [7%,15%] band (config-driven) → fail unless position is band-exempt. Fail-loud; auto-halt before snapshot.
owner_script: shared/gate_irr_sanity.py
class: read
use: validation-gate
expected_inputs: optional --portfolio-path PATH (default portfolio.json); optional --config-dir PATH; reads portfolio.json + standing-rules.yaml (investment_rules.sanity_bands.rf_balcao.expected_return_pct_min/max for the 7–15% band AND investment_rules.sanity_bands.rf_balcao.band_exempt_ids for positions that skip the band check); env override BOOKKEEPER_PORTFOLIO_PATH
outputs: Violation list on stderr; visible EXEMPT notes (stdout) for band-exempt positions outside the band — never silent skips; PASS (exit 0) no violations; FAIL (exit 1) one or more violations; exit 2 if portfolio.json missing; emits gate_pass/gate_fail event (trigger_context.band_exempt_skips records exempt-position count). Strict checks (|irr|>200%, irr_quality) apply to exempt positions regardless.
canonical_reader_writer: reads .user/finance/bookkeeper/ledgers/investimentos/portfolio.json (no write)
dry_run: not-applicable
last_validated: 2026-06-05
```

```yaml
tool: gate_bucket_divergence (python shared/gate_bucket_divergence.py [--portfolio-path PATH] [--bucket BUCKET] [--threshold FLOAT])
purpose: Gate #10 (P3) — per-class IRR vs simple avg of per-asset IRRs; |delta|>5% across any non-informational bucket → fail-loud and auto-halt; surfaces per-asset breakdown. The crypto bucket is informational (module constant _INFORMATIONAL_BUCKETS): its section and divergence always print but never trigger gate failure. User decides next action on real failures.
owner_script: shared/gate_bucket_divergence.py
class: read
use: validation-gate
expected_inputs: optional --portfolio-path PATH (default portfolio.json); optional --bucket (rv_br|rv_eua|rf_balcao|fundos|crypto) to narrow check; optional --threshold float (default 0.05 = 5%); env override BOOKKEEPER_PORTFOLIO_PATH; reads portfolio.json
outputs: Per-bucket section with per-asset IRR table, simple-avg vs stored-bucket delta, DIVERGENCE flag; informational-bucket divergence marked "informational — not counted"; PASS (exit 0) all non-informational buckets within threshold; FAIL (exit 1) any non-informational bucket diverges; exit 2 if portfolio.json missing; emits gate_pass/gate_fail event (trigger_context.informational_buckets lists exempt buckets).
canonical_reader_writer: reads .user/finance/bookkeeper/ledgers/investimentos/portfolio.json (no write)
dry_run: not-applicable
last_validated: 2026-06-05
```

```yaml
tool: gate_parser_total_sanity (python shared/gate_parser_total_sanity.py [--orders-path PATH | --orders-dir PATH])
purpose: Gate #5 (P4) — parser total sanity for *_orders.csv rows; side-aware total check (V: qty×price−fees; C/unknown: qty×price+fees) with 0.5% tolerance; corrections-join applies manual_adjust/quantity rows from per-asset-type corrections files before flagging; fail-loud listing all violating rows; user decides halt vs accept; no auto-loop.
owner_script: shared/gate_parser_total_sanity.py
class: read
use: validation-gate
expected_inputs: optional --orders-path PATH to one orders.csv, OR --orders-dir PATH to scan *orders*.csv; default: .user/finance/bookkeeper/ledgers/investimentos/orders.csv; env override BOOKKEEPER_ORDERS_PATH; reads CSV columns quantity/price/total/fees_exchange/fees_brokerage/fees_irrf/side; also reads .user/finance/bookkeeper/config/corrections/{intl,stocks,fii,rf,crypto,funds}.csv for manual_adjust/quantity rows (fail-soft if absent); env override BOOKKEEPER_CORRECTIONS_DIR
outputs: Violation table (row_num, date, ticker, side, stored vs expected total, deviation%); PASS (exit 0) all within 0.5% with message noting corrections_applied count; FAIL (exit 1) any row exceeds tolerance after corrections; exit 2 on missing file; emits gate_pass/gate_fail event (trigger_context.corrections_applied reports rows rescued by corrections-join).
canonical_reader_writer: reads .user/finance/bookkeeper/ledgers/investimentos/orders.csv and .user/finance/bookkeeper/config/corrections/*.csv (no write)
dry_run: not-applicable
last_validated: 2026-06-05
```

```yaml
tool: me_gate (python shared/me_gate.py --concept "DESC" [--target PATH] [--keys k1,k2] [--store-name NAME] | --manifest PATH)
purpose: Structural non-overlap (ME) semantic gate — fires on any data-store/config/dashboard-script edit and refuses a SECOND store for a concept the 23 p2-7 sources-of-truth domains already own (e.g. a new vendor->category dict when suppliers.json::default_category exists). Detects overlap at the semantic level, not by filesystem existence; surfaces reuse/justify-new/consolidate options on overlap.
owner_script: shared/me_gate.py
class: read
use: validation-gate
expected_inputs: --concept "plain description of the data" (required unless --manifest); optional --target PATH (store/config/script being edited; only basename used as a signal), --keys comma-separated config keys/columns, --store-name NAME; OR --manifest PATH to a JSON list of {concept,target,keys,store_name} for pre-commit/quarterly sweep; reads shared/lib/source_of_truth_registry.py (the 23 p2-7 domains); composes optional shared/audit_data_duplication.py (deferred, plan p5-12) as a tertiary net when present
outputs: PASS (exit 0) when the concept is genuinely new (no overlap); REFUSE (exit 1) with the matching canonical store(s) + p2-7 section number(s) + the three options (Reuse/Justify new/Consolidate); exit 2 on bad args or unreadable manifest; emits gate_pass/gate_fail event (gate.name me_non_overlap). Never blocks on the missing tertiary net.
canonical_reader_writer: reads shared/lib/source_of_truth_registry.py (the p2-7 inventory transcription); no store write
dry_run: not-applicable
last_validated: 2026-06-04
```

```yaml
tool: rename_tags (python migrations/rename_tags.py --from OLD --to NEW [--apply] [--merge-into-existing] [--rollback TOKEN])
purpose: Retro-rewrite a tag across the tag namespace — renames a tag in tags.json (and records the old name in `rejected`), updates suppliers.json default_tags and categories.json reimbursement_mappings.*.tag, and appends the durable record to the append-only corrections/tag-renames.csv. NEVER edits historical ledger rows (transactions.csv tags regenerate via categorize.py).
owner_script: migrations/rename_tags.py
class: write
use: retro-rewrite
expected_inputs: --from OLD --to NEW (required); --apply to execute (DRY-RUN is the DEFAULT); --merge-into-existing to fold into an existing tag; --rollback TOKEN to undo a prior apply; env overrides BOOKKEEPER_CONFIG_DIR/BOOKKEEPER_LEDGER_DIR/BOOKKEEPER_ROOT; reads tags.json, suppliers.json, categories.json, all fechamento transactions.csv (enumeration only)
outputs: Fix-impact preview enumerating every affected location (correction-ledger row, config edits, transactions.csv rows affected, tag-namespace rejected entry) BEFORE any write; under --apply writes tag-renames.csv + tags.json (+ suppliers.json/categories.json if affected), backs up each file to a timestamped .bak, persists a rollback manifest, and emits one config_write audit event per destination. Dry-run writes NOTHING.
canonical_reader_writer: appends .user/finance/bookkeeper/config/corrections/tag-renames.csv; rewrites .user/finance/bookkeeper/config/tags.json (+ suppliers.json/categories.json when default_tags/reimbursement tags reference the tag)
dry_run: default
last_validated: 2026-05-27
```

```yaml
tool: rename_canonical (python migrations/rename_canonical.py [--from "Old"|--slug SLUG] --to "New" [--apply] [--rollback TOKEN])
purpose: Retro-rewrite a vendor's canonical display name — rewrites the matched supplier's `canonical` field in suppliers.json (the classifier's live source for the supplier_canonical output column) and appends the durable record to the append-only corrections/vendor-canonicals.csv. NEVER edits historical ledger rows (transactions.csv supplier_canonical regenerates via categorize.py); flags the 2-areas/finance/pagamentos-recorrentes.md cross-tree mention for manual reconcile.
owner_script: migrations/rename_canonical.py
class: write
use: retro-rewrite
expected_inputs: --to "New" (required); one of --from "Old canonical" or --slug SLUG (required to target); --apply to execute (DRY-RUN is the DEFAULT); --rollback TOKEN to undo; env overrides BOOKKEEPER_CONFIG_DIR/BOOKKEEPER_LEDGER_DIR/BOOKKEEPER_RECURRING_PATH/BOOKKEEPER_ROOT; reads suppliers.json, all fechamento transactions.csv (enumeration only), pagamentos-recorrentes.md (mention check)
outputs: Fix-impact preview enumerating every affected location (correction-ledger row, suppliers.json canonical edit, transactions.csv rows affected, pagamentos-recorrentes.md cross-tree dep) BEFORE any write; composes audit-aliases.py to surface current alias ambiguities; under --apply writes vendor-canonicals.csv + suppliers.json, backs up each to a timestamped .bak, persists a rollback manifest, and emits one config_write audit event per destination. Dry-run writes NOTHING.
canonical_reader_writer: appends .user/finance/bookkeeper/config/corrections/vendor-canonicals.csv; rewrites .user/finance/bookkeeper/config/suppliers.json
dry_run: default
last_validated: 2026-05-27
```

```yaml
tool: merge_categories (python migrations/merge_categories.py --from OLD --to KEEP [--apply] [--rollback TOKEN])
purpose: Retro-rewrite that merges one category into another (highest blast radius) — drops the OLD key from categories.json and rewrites OLD->KEEP across value_based_mappings.category, reimbursement_mappings.*.category, recurrence_rules.default_by_category, plus suppliers.json default_category; appends the durable record to the append-only corrections/category-migrations.csv. NEVER edits historical ledger rows (transactions.csv category regenerates via categorize.py); enumerates the dashboard/expenses.js live-read join and the pagamentos-recorrentes.md cross-tree dep.
owner_script: migrations/merge_categories.py
class: write
use: retro-rewrite
expected_inputs: --from OLD --to KEEP (required; both must be existing categories, OLD != KEEP); --apply to execute (DRY-RUN is the DEFAULT); --rollback TOKEN to undo; env overrides BOOKKEEPER_CONFIG_DIR/BOOKKEEPER_LEDGER_DIR/BOOKKEEPER_RECURRING_PATH/BOOKKEEPER_ROOT; reads categories.json, suppliers.json, all fechamento transactions.csv (enumeration only), pagamentos-recorrentes.md (mention check)
outputs: Fix-impact preview enumerating every affected location (correction-ledger row, categories.json 4 sub-surfaces, suppliers.json default_category, transactions.csv rows affected, dashboard-join, cross-tree dep) BEFORE any write; under --apply writes category-migrations.csv + categories.json + suppliers.json, backs up each to a timestamped .bak, persists a rollback manifest, and emits one config_write audit event per destination. Refuses (exit 1) if OLD or KEEP is not a valid category or OLD==KEEP. Dry-run writes NOTHING.
canonical_reader_writer: appends .user/finance/bookkeeper/config/corrections/category-migrations.csv; rewrites .user/finance/bookkeeper/config/categories.json + suppliers.json
dry_run: default
last_validated: 2026-05-27
```

```yaml
tool: audit_data_duplication (python shared/audit_data_duplication.py [--config-dir PATH])
purpose: Scan bookkeeper config stores for cross-config data duplicates — vendor→category mappings present in both suppliers.json::default_category and categories.json::value_based_mappings (OC-1), and self-transfer patterns also present as supplier aliases (OC-3) — the class of duplication the ME gate's registry keyword check cannot see.
owner_script: shared/audit_data_duplication.py
class: read
use: audit-diagnostic
expected_inputs: optional --config-dir PATH (default: auto-resolved from vault root via sb-os.json/vault heuristic); env override BOOKKEEPER_CONFIG_DIR; reads .user/finance/bookkeeper/config/suppliers.json and .user/finance/bookkeeper/config/categories.json
outputs: Human-readable report grouped by overlap class (OC-1, OC-3) with per-hit vendor/store details and resolution guidance. Exit 0 = no duplicates; exit 1 = duplicates found; exit 2 = config directory missing. Also exposes find_cross_config_duplicates(concept, target) -> list[str] for composition by me_gate.py as the tertiary safety net (plan p5-12).
canonical_reader_writer: reads .user/finance/bookkeeper/config/suppliers.json + .user/finance/bookkeeper/config/categories.json (no write)
dry_run: not-applicable
last_validated: 2026-05-27
```

```yaml
tool: investment_source_capture (python investimentos/investment_source_capture.py --url URL --origin ORIGIN [--mode markdown|html-archive|both|browser|manual] [--ext md|html|json] [--title TITLE] [--thesis SLUG] [--vault-root PATH] [--user-agent UA] [--manual-file PATH|-] [--no-curl-fallback] [--pdf-text] [--dry-run] [--gated] [--gated-why TEXT])
purpose: |
  Save an approved open-web URL to {wiki_root}/raw/{origin}/ and return a metadata summary only
  (title, url, origin, related thesis, saved path, lifecycle state, byte count, fetch method).

  Content-validation (A1): before returning captured_to_raw, every fetched body is validated:
  (1) byte floor — 0-byte / near-0-byte bodies fail; (2) CAPTCHA/bot-wall fingerprint scan —
  known interstitials (Cloudflare, Imperva, captcha markers) in a 200 body fail;
  (3) article-body density — prose extracted after stripping scripts/nav/boilerplate must
  meet a minimum; pure JS shells (emarketer, Next.js self.__next_f.push() soup) fail this
  even if they pass the byte floor. On fail: state=blocked, source-queue row written via the
  same blocked path as transport failures (failure_reason recorded). Manual-file and PDF paths
  are EXEMPT from density checks (user already vetted); only byte floor applies.

  Article-body extraction (A2): for markdown and both modes, a two-tier extractor produces
  the primary .md written to raw/. PRIMARY: trafilatura (lazy optional dep) — purpose-built
  readability, handles diverse site layouts. FALLBACK (trafilatura unavailable OR near-empty):
  BeautifulSoup4 (lazy optional dep) richest-container logic — strips scripts/styles/nav/header/
  footer, evaluates every content-selector container plus <body>, keeps the richest-prose result.
  The full original HTML is preserved as a .full.html sidecar (listed under sidecar_paths in the
  result, NOT in saved_paths) so the full dump is never lost. Multi-MB single-line HTML (CNN
  5.5 MB, SEC EDGAR 1.9 MB, ELC 8-K 258K tokens on one line) is split into readable prose.
  extraction_note in the result JSON records the extraction regime when not primary-trafilatura.

  Transport fallback: on httpx failure (403/bot-fingerprint rejection/connection reset) retries
  once via subprocess curl with the same UA (fetch_method: curl-fallback) — state=blocked only
  after BOTH fail. Gated sources register gated_pending_access without fetching. Transport-level
  and content-validation blocked outcomes both register a source-queue entry (dedup by state+url;
  usage-error blocked and dry-run register nothing).

  Manual/browser: saves user-fetched local content via --manual-file without HTTP. PDF --manual-file
  is BINARY-COPIED to {title-slug}.pdf per Raw PDF Title-Conformance (--title required, no date
  prefix, never overwritten on collision); --pdf-text writes a pypdf companion .md.

  --manual-file path contract (A3): paths with Unicode characters (curly quotes, accented letters,
  spaces) MUST be literal-quoted in the shell. PowerShell: --manual-file '"Weird Title".html'
  (single-quote the whole argument). bash: --manual-file $'"Weird Title".html'. Pass '-' to
  read content from stdin (--title MUST be supplied for slug derivation).

  Preservation rules (tool contract): user originals are NEVER deleted. Binaries are filed
  raw/{origin}/{title-slug}.{ext} + a raw-index row. ONLY byte-identical agent-created temp
  files are removable. Obsidian-clipper " 1.md" copies of a verbatim-captured text original
  are byte-identical temps → removable under the same rule.
owner_script: investimentos/investment_source_capture.py
class: write
use: parser
expected_inputs: |
  --url (required); --origin folder name (required); --mode (markdown|html-archive|both|browser|manual,
  default markdown); --ext (md|html|json — overrides the saved-file extension for markdown-mode and
  manual/browser-mode saves; XBRL companyfacts data artifacts use --ext json; html-archive/both
  unaffected; does NOT apply to PDF saves); optional --title, --thesis slug, --vault-root, --dry-run;
  --gated (declare source gated — no fetch, registers gated_pending_access in source-queue.md);
  --gated-why TEXT (reason recorded in the queue entry, shown to user for context); --user-agent
  (fetch modes send it as User-Agent on BOTH httpx and the curl fallback; default = descriptive
  tool UA; fair-access endpoints like SEC EDGAR require a contact-bearing UA per source-policy.md);
  --manual-file PATH or '-' (required by browser/manual modes; PDF detection by .pdf extension or
  %PDF- magic bytes; --title REQUIRED for PDF captures — filename is the title-slug; '-' reads from
  stdin, --title required; paths with Unicode characters MUST be literal-quoted — see A3 contract
  above); --pdf-text (PDF manual captures only: write a {title-slug}.md companion via pypdf, a lazy
  optional dep; extraction failure or near-empty scanned-PDF surfaced as transform_error/warning,
  never fatal); --no-curl-fallback (disable subprocess-curl retry; fallback ON by default, binary
  resolved via shutil.which — never a shell alias; missing binary → state=blocked)

  Worked examples:
    # Gated paywall source — register without fetching
    python investimentos/investment_source_capture.py \
      --url "https://www.mckinsey.com/report" --origin mckinsey \
      --gated --gated-why "Key aging-consumer market share data"

    # Manual capture of a user-fetched HTML clip (Unicode filename — PowerShell)
    python investimentos/investment_source_capture.py \
      --url "https://ft.com/article" --origin ft \
      --mode manual --manual-file '"FT Article 2026".html' --title "FT Article 2026"

    # PDF binary capture with optional pypdf text companion
    python investimentos/investment_source_capture.py \
      --url "https://www.cms.gov/files/report.pdf" --origin cms \
      --mode manual --manual-file report.pdf \
      --title "CMS Health Spending Highlights 2020" --pdf-text
outputs: |
  JSON metadata summary to stdout (state, url, title, origin, related_thesis, saved_paths, bytes,
  fetch_method, dry_run; manual path adds manual_source; PDF manual path adds format: pdf and lists
  companion in saved_paths when --pdf-text elected; markdown/both modes add sidecar_paths for the
  .full.html full-dump sidecar; extraction_note added when trafilatura unavailable/near-empty or bs4 fallback runs;
  content-validation blocked adds failure_reason).
  For gated: state=gated_pending_access + queue_path + queue (registered|already-registered|dry-run).
  For blocked (transport or content-validation): state=blocked + error + failure_reason + queue_path + queue.

  Writes to {wiki_root}/raw/{origin}/:
  - markdown/both: YYYY-MM-DD-{slug}.{ext} (extracted article prose) + YYYY-MM-DD-{slug}.full.html sidecar
  - html-archive/both: YYYY-MM-DD-{slug}.html (full body)
  - manual non-PDF: YYYY-MM-DD-{slug}.{ext} (default .md, honors --ext)
  - manual PDF: {title-slug}.pdf (binary copy, no date prefix, collision → blocked)
  - manual PDF --pdf-text: {title-slug}.md companion (pypdf text extraction)
  - .json data artifacts (--ext json): YYYY-MM-DD-{slug}.json

  Creates {wiki_root}/source-queue.md with type: source-queue frontmatter when absent.
  Dry-run writes nothing.
canonical_reader_writer: writes {wiki_root}/raw/{origin}/<YYYY-MM-DD-slug>.{md,html,json} and <YYYY-MM-DD-slug>.full.html (sidecar) and {wiki_root}/raw/{origin}/<title-slug>.pdf (+ companion .md); appends {wiki_root}/source-queue.md (gated + transport-blocked + content-validation-blocked registrations)
dry_run: available
last_validated: 2026-06-08
```

```yaml
tool: trace_fx_balance (python investimentos/trace_fx_balance.py [--strict] [--eps EPS])
purpose: Replay the Avenue FX engine event stream (fx_engine.load_events/apply_event) with a per-event USD balance trace, reporting every negative-balance period and the final engine state; --strict exits non-zero if the balance ever drops below -EPS (the "usd_balance >= 0 across full history" verification gate).
owner_script: investimentos/trace_fx_balance.py
class: read
use: audit-diagnostic
expected_inputs: optional --strict flag; optional --eps tolerance (default 0.005); reads .user/finance/bookkeeper/ledgers/investimentos/avenue_fx.csv + orders.csv (currency=USD) + proventos.csv (currency=USD) via fx_engine
outputs: Human-readable report: event counts by type, per-period negative-balance detail (entry/min/recovery + events while negative), final state (usd_balance, weighted_avg_rate, per-ticker qty/cost_brl/avg_fx). Exit 0 always in verbose mode; exit 0/1 in --strict mode (0 = never negative, 1 = negative period found).
canonical_reader_writer: reads .user/finance/bookkeeper/ledgers/investimentos/avenue_fx.csv + orders.csv + proventos.csv (no write)
dry_run: not-applicable
last_validated: 2026-06-03
```

```yaml
tool: market_price (python investimentos/market_price.py TICKER [TICKER ...] [--as-of YYYY-MM-DD] [--market us|br|crypto|index])
purpose: Quote live or historical market prices for arbitrary tickers (US equities, B3 stocks, crypto, market indices, BR↔ADR cross-listings) to resolve disputed market figures per thesis.md's Market-figure range rule — the tools-only invariant for all numeric evidence.
owner_script: investimentos/market_price.py
class: read
use: audit-diagnostic
expected_inputs: |
  one or more TICKER symbols (e.g. TEAM PETR4 BTC DXY ELET3); optional --as-of YYYY-MM-DD for historical end-of-day price; optional --market us|br|crypto|index to override per-ticker market inference (B3 pattern → br, known CoinGecko symbol → crypto, known index token → index, all others → us); reads live market APIs via price_fetcher (yfinance for US/B3/index, brapi.dev fallback for B3 with optional BRAPI_TOKEN auth, CoinGecko simple/price for crypto live-spot + market_chart for period windows).
  Index token map (auto-detected or via --market index): DXY→DX-Y.NYB, SPX/SP500→^GSPC, NDX/NASDAQ→^NDX, DJIA/DOW→^DJI, VIX→^VIX, IBOV/IBOVESPA→^BVSP, RUT→^RUT.
  BR↔ADR auto-expansion (no flag needed): when a B3 ticker with a known ADR mapping (e.g. PETR4↔PBR, VALE3↔VALE, ITUB4↔ITUB, CPLE6↔ELP, ELET3↔EBR, ABEV3↔ABEV, BBDC4↔BBD, BRAP4↔EB) is requested without its paired leg, both legs are auto-expanded and surfaced in the output table.
  BRAPI_TOKEN (optional): when set as OS env var or in .user/config/env/.env, authenticates brapi.dev requests via ?token= param; degrades gracefully if absent.
outputs: Human-readable table — one row per ticker with columns ticker, market, currency, price, price_date, source, 1d/30d/90d/180d/365d/ytd change percentages (absent windows render as n/a), status (OK|MISSING|DELISTED); summary footer "{N} ticker(s) queried — {ok} OK[, {d} DELISTED][, {m} MISSING]"; DELISTED tickers listed separately from MISSING; auto-expanded ADR/BR legs noted in footer. Writes nothing.
  DELISTED status: set ONLY for US (bare) tickers — when yfinance returns no recent price data but its metadata (share count) indicates the ticker existed — distinct from MISSING. B3 (.SA) tickers with no yfinance data fall through to brapi.dev and end as MISSING (not DELISTED) if brapi also cannot price them. The stale-last-trade delisted path (had data, last trade >90 days ago) fires for any market. price_source stays 'missing' so the dashboard contract is unchanged; DELISTED is an additive field.
  Crypto current_price: live spot from CoinGecko simple/price (price_date = today). Period windows (30d/90d/180d/365d/ytd) sourced from market_chart series via _compute_changes. 365d may be n/a on free tier. Falls back to market_chart last value if simple/price is unavailable.
canonical_reader_writer: reads live market APIs (yfinance / brapi.dev / CoinGecko) via price_fetcher — no local store read, no write
dry_run: not-applicable
last_validated: 2026-06-08
```

```yaml
tool: investment_financials_extract (python investimentos/investment_financials_extract.py --entity PATH [--xbrl PATH] [--targets PATH] [--cik N] [--since YYYY-MM-DD] [--vault-root PATH] [--vocab PATH] [--dry-run])
purpose: SOLE agent-side writer of entity ## Financials sections — verifies agent-pointed anchors verbatim against the captured raw and re-parses the number itself (lane 2, method structured), parses captured XBRL companyfacts artifacts fully OFFLINE via the us-gaap→vocab map (lane 1, method xbrl; corroborate-only by default, --since DATE opens extraction to new periods), accepts scan-flagged unverifiable rows (lane 3, method llm), and hard-rejects any metric/unit/period_type/method outside metric-vocab.md (incl. suffix families) at write time.
owner_script: investimentos/investment_financials_extract.py
class: write
use: parser
expected_inputs: --entity wiki entity page path (must exist; kind company|asset|country|sector; optional cik frontmatter cross-checked against the artifact, --cik overrides); --xbrl captured companyfacts JSON path (lane 1) and/or --targets scan-output JSON path (lanes 2/3 — path-transported from .user/finance/investor/, rows carry metric, period_type, period_end, value_as_printed, unit_as_printed, anchor, unverifiable+reason); --since YYYY-MM-DD lane-1 open-extraction window; --vocab PATH override (tests); reads {wiki_root}/raw/** (anchor verification + source resolution), finance/wiki-ext/metric-vocab.md (hard gate), investimentos/us_gaap_vocab_map.json (us-gaap concept map)
outputs: Metadata JSON only to stdout (entity, kind, dry_run, written {xbrl/structured/llm}, upgraded, skipped, rejected + reasons, conflicts, vocab_proposals, lane1_mode) — never page or raw content. Writes ONLY the ## Financials table block of the target entity page (creates the section at the deterministic position when absent; canonical row sort; upsert key metric+period_type+period_end+source; same key+value with stronger method upgrades in place xbrl>structured>llm>manual; value conflicts surfaced, NEVER written; values re-parsed from the cited raw with scale/sign resolution, ROUND_HALF_UP). Exit 0 = success (rejects/conflicts are surfaced state); exit 1 = usage/validation error.
canonical_reader_writer: writes the ## Financials section of {wiki_root}/wiki/entities/** pages; reads {wiki_root}/raw/{origin}/** (incl. *-xbrl-companyfacts.json data artifacts)
dry_run: available
last_validated: 2026-06-04
```

```yaml
tool: upsert_assets (python investimentos/upsert_assets.py <input_csv> [--apply] [--actor ACTOR_ID])
purpose: Upsert rows into assets.csv via the field-ownership manifest — inserts new asset rows and updates existing ones, respecting curated/source_bound/derived field classes so that user-curated fields (name, issuer, active, sector) are never overwritten on update by actors without ownership.
owner_script: investimentos/upsert_assets.py
class: write
use: upsert
expected_inputs: positional input_csv (must match assets.csv schema: id,asset_class,name,type,sector,currency,current_broker,active,issuer,indexer,rate,indexer_pct,application_date,maturity_date,cnpj,manager); optional --apply flag (dry-run is the DEFAULT); optional --actor ACTOR_ID (default: agent_manual; use a parser's source_id such as safra_titulos to write source_bound fields; use --actor user to authorize curated-field updates — curated fields are implicitly user-owned so actor=user may overwrite them on update, e.g. to correct an asset name; source_bound fields remain parser-owned regardless of actor and are NOT unlocked by actor=user); reads .user/finance/bookkeeper/data/assets.csv and .user/finance/bookkeeper/config/_field_ownership.yaml
outputs: Per-row diff on stdout (INSERT/UPDATE/NOOP + ownership-blocked fields); summary line (X inserts, Y updates, Z noops, W ownership-blocked fields). Under --apply writes .user/finance/bookkeeper/data/assets.csv (existing rows preserved in their original order; new rows inserted at byte/ASCII sort position by id — uppercase sorts before lowercase, e.g. XRP before aplicacoes_renda_fixa), emits one ledger_write audit event via audit.track_write, and emits docs_potentially_stale. Dry-run writes NOTHING. Unknown input columns trigger a field_ownership_unknown audit event and exit 1 (no write). Schema gaps (input column absent from destination schema) are dual-surfaced (schema_gap_finding event + user prompt) and exit 1.
canonical_reader_writer: reads and writes .user/finance/bookkeeper/data/assets.csv; reads .user/finance/bookkeeper/config/_field_ownership.yaml
dry_run: default
last_validated: 2026-06-05
```

```yaml
tool: irr_flows (python investimentos/irr_flows.py ID [ID ...] [--portfolio-path PATH] [--ledger-dir PATH])
purpose: Per-asset IRR flow decomposition reader — prints the synthetic XIRR cash-flow ladder that calculate.py builds, the terminal anchoring, and the recomputed XIRR vs the stored portfolio.json value for each requested asset id, closing the tools-only gap that previously forced direct ledger reads during IRR-divergence diagnosis.
owner_script: investimentos/irr_flows.py
class: read
use: audit-diagnostic
expected_inputs: one or more asset ids (product_id / ticker); optional --portfolio-path PATH (default portfolio.json); optional --ledger-dir PATH (default investimentos ledger dir); env overrides BOOKKEEPER_PORTFOLIO_PATH, BOOKKEEPER_INVESTIMENTOS_DIR; reads portfolio.json + orders.csv + proventos.csv + balcao.csv + crypto.csv + corporate_actions.csv via _build_position_flows (mirrors calculate.py exactly)
outputs: Human-readable report per asset: FLOW LADDER section (per-row date/amount/cumulative table per flow key), TERMINAL ANCHORING AND XIRR section (recomputed_xirr, stored_irr, drift columns), optional [COMBINED] row for split-id crypto positions (per-exchange flow partitions merged + combined terminal), POSITION METADATA section. Header shows cut_date and portfolio filename. Footer shows total ids requested vs not-found count. Exit 0 always; exit 1 if portfolio.json is missing. Writes nothing.
canonical_reader_writer: reads .user/finance/bookkeeper/ledgers/investimentos/portfolio.json + orders.csv + proventos.csv + balcao.csv + crypto.csv + corporate_actions.csv (no write)
dry_run: not-applicable
last_validated: 2026-06-05
```

```yaml
tool: ack_tag_review (python shared/ack_tag_review.py --month YYYY-MM --source LABEL [--date D --description TEXT --amount AMT [--note TEXT] | --input FILE.json] [--apply] [--ack-file PATH] [--fechamento-dir PATH])
purpose: Append tag-review acknowledgement rows to the append-only side-ledger tag-review-acks.csv — marks a large untagged despesa as reviewed-and-intentionally-untagged so gate_coverage.py renders it ACK instead of VIOLATION; replaces the improvised hand-edits used across the April/May/June review-and-close sessions with one validated, deduped, audited writer.
owner_script: shared/ack_tag_review.py
class: write
use: upsert
expected_inputs: --month YYYY-MM (required; its fechamento transactions.csv validates every row) and --source LABEL (required provenance, e.g. review-mode-2026-03); single row via --date YYYY-MM-DD --description TEXT --amount AMT [--note TEXT], OR batch via --input FILE.json (a list of {tx_date,tx_description,tx_amount,note}); --apply to write (DRY-RUN is the DEFAULT); --ack-file PATH and --fechamento-dir PATH isolation overrides (test/non-default tree); reads ledgers/fechamento/{month}/transactions.csv (identity validation) and the ack side-ledger (dedup); identity helpers (_ack_identity/_tx_identity/_tx_amount_key) are IMPORTED from gate_coverage.py — no second implementation, so the ack key is exactly the key the gate joins on.
outputs: Per-request preview (would-append / SKIP duplicate / REFUSED with near-miss candidates; multi-match surfaced as "matches N transactions") + a summary line (requests / would-append / skip-duplicate / refusals). All three identity fields (tx_date+tx_description+tx_amount) MUST JOINTLY match a transactions.csv row — a partial match is a named refusal that writes NOTHING; batch runs validate every row first and ANY refusal refuses the entire run (atomic), exit 1. tx_date may lie OUTSIDE {month} (cc-invoice rows) — membership check only, never a date-range check. Duplicates (by identity triple, vs the existing ack set) are visible SKIP duplicate, exit 0 even when all rows are duplicates (no-op apply is success). Under --apply appends rows to tag-review-acks.csv preserving its CRLF/UTF-8/QUOTE_MINIMAL convention byte-compatibly (existing bytes never modified) and emits one config_write audit event for the run via audit.track_write (fail-soft; respects BOOKKEEPER_AUDIT_DISABLED/BOOKKEEPER_AUDIT_LOG_DIR). Dry-run writes NOTHING. Exit 0 success/no-op; exit 1 validation refusal; exit 2 usage error / missing transactions.csv or --input / malformed ack header.
canonical_reader_writer: appends .user/finance/bookkeeper/config/corrections/tag-review-acks.csv; reads .user/finance/bookkeeper/ledgers/fechamento/{YYYY-MM}/transactions.csv (validation only)
dry_run: default
last_validated: 2026-06-06
```

```yaml
tool: apply_review_resolution (python migrations/apply_review_resolution.py --month YYYY-MM --date YYYY-MM-DD --description TEXT --amount FLOAT --set field=value [--corrections-file FILENAME] [--reason TEXT] [--source LABEL] [--note TEXT] [--apply])
purpose: Apply a row-level review resolution on a closed fechamento month — re-stamps one or more mutable fields (category, tags, recurrence, supplier_canonical, data_competencia, manual_override) on the unique matching row of transactions.csv, and optionally appends the canonical correction row to manual-overrides.csv or competencia-overrides.csv so categorize.py re-applies the override on the next regeneration.
owner_script: migrations/apply_review_resolution.py
class: write
use: retro-rewrite
expected_inputs: --month YYYY-MM (required); --date YYYY-MM-DD, --description TEXT, --amount FLOAT (required identity triple); --set field=value (repeatable; mutable-field whitelist: category, tags, recurrence, supplier_canonical, data_competencia, manual_override; data_caixa is NEVER mutable — hardcoded reject); --corrections-file FILENAME (optional; manual-overrides.csv or competencia-overrides.csv); --reason, --source, --note (optional provenance); --apply to execute (DRY-RUN is the DEFAULT); env overrides BOOKKEEPER_ROOT / BOOKKEEPER_CONFIG_DIR / BOOKKEEPER_LEDGER_DIR
outputs: Fix-impact preview enumerating every affected location (transactions.csv row re-stamp + corrections side-ledger append) BEFORE any write; exact-one-match enforcement (0 or >1 matches = hard error, rc=1); under --apply re-stamps the matched row (atomic write via safe_write) + appends the corrections row + emits one ledger_write + one config_write audit event; rollback manifest written to corrections/.rollback/. Dry-run writes NOTHING.
canonical_reader_writer: overwrites .user/finance/bookkeeper/ledgers/fechamento/{YYYY-MM}/transactions.csv (single-row re-stamp); appends .user/finance/bookkeeper/config/corrections/manual-overrides.csv or competencia-overrides.csv
dry_run: default
last_validated: 2026-06-06
```

```yaml
tool: supplier_spend_spikes (python shared/supplier_spend_spikes.py [--axis competencia|caixa] [--threshold FLOAT] [--min-base FLOAT] [--month YYYY-MM] [--ledger-dir PATH])
purpose: List every supplier whose monthly spending total increased by more than a threshold (default >20%) versus the immediately preceding calendar month, across the fechamento transactions.csv ledgers — month-over-month supplier spend-spike diagnostic.
owner_script: shared/supplier_spend_spikes.py
class: read
use: audit-diagnostic
expected_inputs: optional --axis competencia|caixa (date column defining the spend month, default competencia), --threshold fraction (default 0.20 = 20%), --min-base FLOAT (minimum prior-month total to flag, default 100.0; 0 disables the floor), --month YYYY-MM (restrict to that month vs its calendar prior), --ledger-dir PATH override; env override BOOKKEEPER_LEDGER_DIR; reads .user/finance/bookkeeper/ledgers/fechamento/{YYYY-MM}/transactions.csv. Spend = sum of (-amount) per supplier_canonical (expenses positive, refunds net down); rows in categories receitas/intercontas/ignorar/venda excluded; empty supplier_canonical bucketed as "(unmapped)".
outputs: Per month-pair section ("{month} vs {prior}") with a pretty-printed table of flagged suppliers (supplier, prior, current, delta, pct) sorted by pct descending, plus an "appeared (no prior month spend)" line listing suppliers with no comparable prior total (surfaced, never counted in the >threshold list). Human-readable; writes nothing. Exit 0 always when data exists; exit 1 when no fechamento transactions.csv data is found.
canonical_reader_writer: reads .user/finance/bookkeeper/ledgers/fechamento/{YYYY-MM}/transactions.csv (no write)
dry_run: not-applicable
last_validated: 2026-06-06
```

```yaml
tool: restamp_supplier_canonical (python migrations/restamp_supplier_canonical.py --from "Old" --to "New" [--months YYYY-MM,YYYY-MM] [--apply] [--rollback TOKEN])
purpose: Bulk re-stamp of the supplier_canonical column across closed fechamento months — rewrites every transactions.csv row whose supplier_canonical exactly equals --from to --to, for casing-duplicate canonical merges where a config-side fix (rename_canonical / standing-rules name_canonicalization exceptions) corrects future closes but leaves already-stamped derived rows split across two spend buckets. Refuses any --to the live name-canonicalization pipeline would not itself stamp (convergence guard: a later categorize.py regeneration produces the same value). Touches ONLY supplier_canonical; data_caixa and every other column preserved.
owner_script: migrations/restamp_supplier_canonical.py
class: write
use: retro-rewrite
expected_inputs: --from "Old value" and --to "New value" (required; exact match, --to must resolve from a suppliers.json canonical through the live name_canonicalization standing rule); optional --months comma-separated scope (default all fechamento months); --apply to execute (DRY-RUN is the DEFAULT); --rollback TOKEN to undo; env overrides BOOKKEEPER_ROOT / BOOKKEEPER_CONFIG_DIR / BOOKKEEPER_LEDGER_DIR; reads suppliers.json + standing-rules.yaml (live-canonical validation) and the scoped transactions.csv files
outputs: Fix-impact preview with per-month matched-row counts BEFORE any write; blocking refusal (exit 1) when --from == --to or --to is not a live canonical form; advisory warning when --from is itself still a live form; under --apply rewrites each affected transactions.csv atomically (safe_write), backs each up to a microsecond-timestamped .bak (back-to-back runs never share tokens), persists a rollback manifest to corrections/.rollback/, and emits one ledger_write audit event per written file (fail-soft). Dry-run writes NOTHING.
canonical_reader_writer: overwrites .user/finance/bookkeeper/ledgers/fechamento/{YYYY-MM}/transactions.csv (supplier_canonical column only)
dry_run: default
last_validated: 2026-06-07
```

```yaml
tool: sec_filing_finder (python investimentos/sec_filing_finder.py --ticker TICKER --form FORM --latest [--market us|br] [--cvm-code N] [--cnpj "NN.NNN.NNN/NNNN-NN"] [--company "Name fragment"] [--count N] [--json] [--user-agent UA])
purpose: Resolve a company + filing type to the exhibit-direct document URL(s) + metadata for US (SEC EDGAR) and BR (CVM dados-abertos) — returns URLs and filing metadata only; NEVER fetches or writes the document body. Enables the resolve→capture chain: feed the resolved primary_url to investment_source_capture.
owner_script: investimentos/sec_filing_finder.py
class: read
use: audit-diagnostic
expected_inputs: |
  US arm (--market us or --ticker present):
    --ticker TICKER (e.g. AMZN, MSFT); --form FORM (10-K, 10-Q, 8-K, 6-K, etc.); --latest (default on); --count N (number of filings, overridden to 1 by --latest); --cik N (override ticker→CIK lookup); --json (machine-readable output); --user-agent UA (default: contact-bearing UA from source-policy.md — SEC 403s non-contact UAs).
  BR arm (--market br or --cvm-code/--cnpj/--company present):
    one of --cvm-code N (CD_CVM numeric), --cnpj "NN.NNN.NNN/NNNN-NN", --company "fragment" (case-insensitive partial match against DENOM_SOCIAL); --form FORM: DFP (annual), ITR (quarterly), IPE (periodic/eventual, direct PDF links); --latest; --count N; --json.
  Resolution path:
    US: ticker→CIK via https://www.sec.gov/files/company_tickers.json; submissions JSON via https://data.sec.gov/submissions/CIK{cik:010d}.json; primary_url = filing folder + primaryDocument; 8-K exhibit list parsed from index for EX-99.1 targeting.
    BR: company→CD_CVM via https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv; filing index ZIP via https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{TYPE}/DADOS/{type}_cia_aberta_{year}.zip (DFP/ITR base CSV or IPE CSV); Link_Download / LINK_DOC field is the document URL. IPE Link_Download URLs are direct PDFs on rad.cvm.gov.br/ENET/. DFP/ITR LINK_DOC URLs are ENETCONSULTA download-trigger pages (ZIP packages — see concerns).
outputs: |
  Human-readable metadata table (or JSON with --json) per resolved filing. US fields: market, company_name, ticker, cik, form, filing_date, accession_number, primary_document, primary_url (exhibit-direct), filing_folder_url, index_url, exhibit_list (8-K only: [{doc, type, description, url}]). BR fields: market, company_name, cd_cvm, form, doc_type_used (DFP|ITR|IPE), categoria, tipo, reference_date, filing_date, protocol, version, primary_url (= link_download), assunto (IPE only).
  Exit 0 = at least one filing resolved; exit 1 = not found / resolution failed; exit 2 = usage error.
  Writes nothing.
canonical_reader_writer: reads SEC EDGAR APIs (company_tickers.json, data.sec.gov submissions) and CVM open-data APIs (cad_cia_aberta.csv, IPE/DFP/ITR ZIP CSVs) — no local store read, no write
dry_run: not-applicable
last_validated: 2026-06-08
```
