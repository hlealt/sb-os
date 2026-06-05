"""Tests for gate #4 — Transaction count sanity per bank (p4-17)."""

import csv
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gate_transaction_count import check_file, main


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None):
    if not rows:
        path.write_text("date,description,amount,bank\n", encoding="utf-8")
        return
    fn = fieldnames or list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fn)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# check_file unit tests
# ---------------------------------------------------------------------------


def test_pass_for_rows_within_window(tmp_path):
    """All dates within ±5 days of expected month → pass."""
    csv_path = tmp_path / "bradesco_extrato.csv"
    rows = [
        {"date": "2026-03-10", "description": "A", "amount": "-100"},
        {"date": "2026-03-20", "description": "B", "amount": "-50"},
    ]
    _write_csv(csv_path, rows)
    expected = date(2026, 3, 1)
    result = check_file(csv_path, expected)
    assert result["passed"] is True
    assert result["row_count"] == 2
    assert result["outside_window"] == 0


def test_fail_for_zero_rows(tmp_path):
    """Empty file → zero transactions → gate fails."""
    csv_path = tmp_path / "bradesco_extrato.csv"
    _write_csv(csv_path, [])
    result = check_file(csv_path, date(2026, 3, 1))
    assert result["passed"] is False
    assert result["row_count"] == 0
    assert "Zero transactions" in result["issues"][0]


def test_fail_when_more_than_10pct_outside_window(tmp_path):
    """11% outside window → gate fails."""
    csv_path = tmp_path / "test.csv"
    # 9 in-window + 1 way-out-of-window = 10 rows, 10% outside.
    # Use 10 in-window + 2 out = 12 rows, 16.7% outside → should fail.
    rows = [{"date": f"2026-03-{d:02d}", "description": "X", "amount": "-10"} for d in range(1, 11)]
    rows += [
        {"date": "2026-01-01", "description": "old", "amount": "-10"},
        {"date": "2025-12-01", "description": "older", "amount": "-10"},
    ]
    _write_csv(csv_path, rows)
    result = check_file(csv_path, date(2026, 3, 1))
    assert result["passed"] is False
    assert result["outside_window"] == 2
    assert result["outside_pct"] > 0.10


def test_pass_when_exactly_10pct_outside_window(tmp_path):
    """Exactly 10% outside window → borderline → passes (threshold is >10%)."""
    csv_path = tmp_path / "test.csv"
    # 9 in-window + 1 boundary = 10 rows, exactly 10% → should pass (threshold is STRICTLY >10%).
    rows = [{"date": f"2026-03-{d:02d}", "description": "X", "amount": "-10"} for d in range(1, 10)]
    rows += [{"date": "2026-01-01", "description": "old", "amount": "-10"}]
    _write_csv(csv_path, rows)
    result = check_file(csv_path, date(2026, 3, 1))
    # 10% is NOT > 10%, so it passes.
    assert result["passed"] is True


def test_boundary_dates_within_5_days(tmp_path):
    """Dates ±5 days of month boundary are within tolerance."""
    csv_path = tmp_path / "test.csv"
    rows = [
        {"date": "2026-02-24", "description": "before", "amount": "-10"},  # 5 days before March
        {"date": "2026-04-05", "description": "after", "amount": "-10"},   # 5 days after March
    ]
    _write_csv(csv_path, rows)
    result = check_file(csv_path, date(2026, 3, 1))
    assert result["outside_window"] == 0
    assert result["passed"] is True


def test_derives_month_from_file_when_not_given(tmp_path):
    """When expected_month is None, derives it from file contents."""
    csv_path = tmp_path / "test.csv"
    rows = [{"date": f"2026-03-{d:02d}", "description": "X", "amount": "-10"} for d in range(1, 6)]
    _write_csv(csv_path, rows)
    result = check_file(csv_path, None)
    assert result["passed"] is True


# ---------------------------------------------------------------------------
# main() exit-code integration tests
# ---------------------------------------------------------------------------


def test_main_pass_exit_0(tmp_path, monkeypatch):
    expenses_dir = tmp_path / "expenses" / "2026-03"
    expenses_dir.mkdir(parents=True)
    csv_path = expenses_dir / "bradesco_extrato.csv"
    rows = [{"date": "2026-03-15", "description": "X", "amount": "-100"}]
    _write_csv(csv_path, rows)
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_transaction_count.py",
        "--expenses-dir", str(expenses_dir),
        "--month", "2026-03",
    ])
    assert main() == 0


def test_main_fail_exit_1_empty_file(tmp_path, monkeypatch):
    expenses_dir = tmp_path / "expenses" / "2026-03"
    expenses_dir.mkdir(parents=True)
    csv_path = expenses_dir / "empty_extrato.csv"
    _write_csv(csv_path, [])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_transaction_count.py",
        "--expenses-dir", str(expenses_dir),
        "--month", "2026-03",
    ])
    assert main() == 1


def test_main_missing_dir_exit_2(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_transaction_count.py",
        "--expenses-dir", str(tmp_path / "nonexistent"),
    ])
    assert main() == 2


def test_gate_event_emitted(tmp_path, monkeypatch):
    """gate_pass/gate_fail event is emitted."""
    import lib.audit as audit_mod
    audit_mod._reset_cache_for_tests()

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    expenses_dir = tmp_path / "expenses" / "2026-03"
    expenses_dir.mkdir(parents=True)
    csv_path = expenses_dir / "bradesco_extrato.csv"
    rows = [{"date": "2026-03-15", "description": "X", "amount": "-100"}]
    _write_csv(csv_path, rows)

    monkeypatch.setenv("BOOKKEEPER_AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "0")
    monkeypatch.setattr(sys, "argv", [
        "gate_transaction_count.py",
        "--expenses-dir", str(expenses_dir),
        "--month", "2026-03",
    ])

    result = main()
    assert result == 0

    import json
    event_files = list(audit_dir.glob("events-*.jsonl"))
    assert event_files
    events = [json.loads(line) for line in event_files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    gate_events = [e for e in events if e.get("event_type") in ("gate_pass", "gate_fail")]
    assert gate_events
    assert gate_events[0]["gate"]["name"] == "gate_4_transaction_count"

    audit_mod._reset_cache_for_tests()
