"""Contract tests for supplier_spend_spikes.py (read/audit-diagnostic).

Contracts tested:
  A  aggregate_spend nets refunds, excludes non-expense categories, groups by
     the axis date column (not the folder name), buckets empty supplier as "(unmapped)".
  B  find_spikes flags suppliers strictly above the threshold, sorted by pct desc.
  C  --min-base suppresses tiny-base percentage blowups.
  D  Suppliers with no prior-month spend are reported under "appeared", never
     counted in the spike list (no prior = no percentage).
  E  Comparison is against the immediately preceding CALENDAR month (year boundary),
     and --month restricts to one comparison.
  F  CLI output contract: human-readable header + columns + a flagged row (audit-diagnostic).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Make the shared scripts dir importable (mirror conftest's path insert).
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from supplier_spend_spikes import aggregate_spend, find_spikes

_OWNER_SCRIPT = _SCRIPTS_DIR / "supplier_spend_spikes.py"
_HEADER = ("date,description,amount,balance,bank,source_type,currency,original_ref,"
           "installment_current,installment_total,original_amount,exchange_rate,"
           "category,match_confidence,recurrence,data_caixa,data_competencia,"
           "supplier_canonical,tags,manual_override")


def _row(amount, category, supplier, caixa, competencia):
    cells = [""] * 20
    cells[2] = str(amount)          # amount
    cells[12] = category            # category
    cells[15] = caixa               # data_caixa
    cells[16] = competencia         # data_competencia
    cells[17] = supplier            # supplier_canonical
    return ",".join(cells)


def _write_month(fechamento: Path, folder: str, rows: list[str]) -> None:
    d = fechamento / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / "transactions.csv").write_text("\n".join([_HEADER, *rows]) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- A
def test_aggregate_nets_excludes_and_groups_by_axis(tmp_path):
    f = tmp_path / "fechamento"
    _write_month(f, "2026-02", [
        _row(-100.0, "alimentacao", "Uber", "2026-02-03", "2026-02-03"),
        _row(-50.0, "alimentacao", "Uber", "2026-02-10", "2026-02-10"),   # same supplier same month
        _row(20.0, "alimentacao", "Uber", "2026-02-12", "2026-02-12"),    # refund nets down
        _row(-999.0, "receitas", "Salary", "2026-02-01", "2026-02-01"),   # excluded category
        _row(-30.0, "transporte", "", "2026-02-05", "2026-02-05"),        # empty supplier -> (unmapped)
        # competencia in a DIFFERENT month than the folder (installment collapse)
        _row(-200.0, "compras", "Loja", "2026-02-10", "2026-01-15"),
    ])
    totals = aggregate_spend(f, axis="competencia")
    assert round(totals["2026-02"]["Uber"], 2) == 130.0   # 100 + 50 - 20
    assert "Salary" not in totals["2026-02"]              # excluded category
    assert totals["2026-02"]["(unmapped)"] == 30.0
    assert totals["2026-01"]["Loja"] == 200.0            # grouped by competencia, not folder


# --------------------------------------------------------------------------- B
def test_find_spikes_flags_above_threshold_sorted(tmp_path):
    totals = {
        "2026-01": {"A": 100.0, "B": 200.0, "C": 500.0},
        "2026-02": {"A": 130.0, "B": 230.0, "C": 1000.0},  # A +30%, B +15%, C +100%
    }
    out = find_spikes(totals, threshold=0.20, min_base=0.0, only_month="2026-02")
    flagged = [s["supplier"] for s in out["2026-02"]["spikes"]]
    assert flagged == ["C", "A"]                # B below 20%; sorted by pct desc
    assert out["2026-02"]["prior"] == "2026-01"


# --------------------------------------------------------------------------- C
def test_min_base_suppresses_tiny_base(tmp_path):
    totals = {"2026-01": {"Tiny": 1.0}, "2026-02": {"Tiny": 5.0}}  # +400% but base R$1
    with_floor = find_spikes(totals, threshold=0.20, min_base=100.0, only_month="2026-02")
    no_floor = find_spikes(totals, threshold=0.20, min_base=0.0, only_month="2026-02")
    assert with_floor["2026-02"]["spikes"] == []
    assert [s["supplier"] for s in no_floor["2026-02"]["spikes"]] == ["Tiny"]


# --------------------------------------------------------------------------- D
def test_no_prior_listed_as_appeared_not_spike(tmp_path):
    totals = {"2026-01": {"Old": 100.0}, "2026-02": {"Old": 200.0, "New": 300.0}}
    out = find_spikes(totals, threshold=0.20, min_base=0.0, only_month="2026-02")
    flagged = [s["supplier"] for s in out["2026-02"]["spikes"]]
    appeared = [a["supplier"] for a in out["2026-02"]["appeared"]]
    assert "New" in appeared and "New" not in flagged
    assert "Old" in flagged


# --------------------------------------------------------------------------- E
def test_prior_is_calendar_month_year_boundary(tmp_path):
    totals = {"2025-12": {"A": 100.0}, "2026-01": {"A": 200.0}}
    out = find_spikes(totals, threshold=0.20, min_base=0.0)
    assert out["2026-01"]["prior"] == "2025-12"
    assert [s["supplier"] for s in out["2026-01"]["spikes"]] == ["A"]


def test_missing_prior_month_skips_pair(tmp_path):
    totals = {"2026-01": {"A": 100.0}, "2026-03": {"A": 500.0}}  # no 2026-02
    out = find_spikes(totals, threshold=0.20, min_base=0.0)
    assert "2026-03" not in out  # prior calendar month (2026-02) absent -> not comparable


# --------------------------------------------------------------------------- F
def test_cli_human_readable_output_contract(tmp_path):
    f = tmp_path / "fechamento"
    _write_month(f, "2026-01", [_row(-100.0, "alimentacao", "Uber", "2026-01-03", "2026-01-03")])
    _write_month(f, "2026-02", [_row(-500.0, "alimentacao", "Uber", "2026-02-03", "2026-02-03")])
    result = subprocess.run(
        [sys.executable, str(_OWNER_SCRIPT), "--ledger-dir", str(f), "--month", "2026-02"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    out = result.stdout
    assert "Supplier spend spikes" in out          # header
    assert "2026-02 vs 2026-01" in out             # pair label
    assert "supplier" in out and "pct" in out      # column headers
    assert "Uber" in out and "+400.0%" in out      # the flagged row


def test_cli_no_data_exits_1(tmp_path):
    empty = tmp_path / "fechamento"
    empty.mkdir()
    result = subprocess.run(
        [sys.executable, str(_OWNER_SCRIPT), "--ledger-dir", str(empty)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "No fechamento transactions.csv data found" in result.stderr
