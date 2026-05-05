# Accountant scripts — test suite

Pytest-based tests for the gastos pipeline primitives (`lib/`) and the
end-to-end `categorize.py` runner. Stdlib + pytest only — no pandas, no
external deps.

## How to run

From the vault root:

```bash
pytest 3-resources/tools/finance/scripts/accountant/shared/tests/ -v
```

Or, from this `tests/` directory:

```bash
pytest -v
```

`conftest.py` adds the parent `scripts/` directory to `sys.path` so
`from lib.accrual import ...` and `from utils import NORMALIZED_COLUMNS`
resolve regardless of cwd.

## Files

| File | Covers |
|------|--------|
| `test_accrual.py` | Four behavior-matrix scenarios from spec §R3; invariants 1–5 (data_caixa immutability, CC installment competência collapse, per-invoice caixa, reimbursement caixa-never-moves, skip-default). |
| `test_suppliers.py` | Alias longest-first + first-match-wins; movable cascade (explicit / hint / mixed-raises); R$200 rollup boundaries (R$199 → Outros, R$201 → canonical, exact threshold = canonical, 92-day window inclusivity). |
| `test_boundary.py` | `is_boundary_day` for 28-day Feb (Feb 23 NOT boundary, Feb 24 IS), 30-day April, 31-day Jan; `needs_boundary_prompt` truth table (movable T/F × boundary T/F + fatura-excluded); tag token validation (invariant 7); Pass 2 ordering (invariant 8). |
| `test_categorize_integration.py` | End-to-end `categorize.py` against the synthetic month fixture. Asserts 19-column schema, no `subcategory` column, all four behavior-matrix per-row dates, invariant 6 (no `Outros` in storage). |

## Fixtures

`fixtures/` contains hand-authored synthetic data — never copies of real
bank statements.

| Fixture | Purpose |
|---------|---------|
| `suppliers.json` | Eight suppliers covering: short alias (`IFD*`), longer specific alias (`IFD*ARCOS DOURADOS`), explicit `movable=true` (`Claro`, `Dr. XYZ`), explicit `movable=false`, R$200-rollup test pair. |
| `categories.json` | Minimal categories with `movable_hint` covering `movable`, `non-movable`, `mixed`; vendor_mappings + reimbursement_mappings sufficient for the integration test. |
| `tags.json` | One accepted tag (`tennis`); two rejected entries (`return_count=2` and `=3`) for re-surface threshold testing. |
| `month-2026-04/processed/transactions-normalized.csv` | Four rows — one per behavior-matrix scenario (CC single, CC installment 1/3, non-CC utility, reimbursement). |
| `month-2026-04/processed/fatura_totals.json` | `payment_date: 2026-05-10` for the fixture's CC bank (`visa_fatura`). |

## Behavior-matrix coverage

| Scenario | data_caixa expected | data_competencia expected | Verified in |
|----------|---------------------|---------------------------|-------------|
| (a) Apr 12 single CC, paid May 10 | 2026-05-10 | 2026-04-12 | `test_accrual.py::test_scenario_a_*`, integration |
| (b) Mar 10 3× installments | per-invoice payment | 2026-03-10 (collapsed) | `test_accrual.py::test_scenario_b_*`, integration (parcela 1/3) |
| (c) Apr 5 utility bill (non-CC) | 2026-04-05 | 2026-04-05 (skip-default) | `test_accrual.py::test_scenario_c_*`, integration |
| (d) Apr 30 reimbursement (manual override) | 2026-04-30 | 2026-03-15 with override | `test_accrual.py::test_scenario_d_*` |

The integration test exercises the categorize.py emission of (d) WITHOUT
the manual override (no override is applied at categorize.py time — it is
a Pass 2 review-queue concern). The unit test in `test_accrual.py`
covers the override path.
