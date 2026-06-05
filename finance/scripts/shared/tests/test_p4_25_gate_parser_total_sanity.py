"""Tests for gate #5 — parser total sanity (p4-25).

0.5% tolerance for *_orders.csv rows. Fail-loud; user decides.
"""

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_parser_total_sanity as gpts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIELDNAMES = ["date", "side", "ticker", "quantity", "price", "currency",
               "total", "fees_exchange", "fees_brokerage", "fees_irrf",
               "broker", "asset_type", "market", "source"]


def _write_orders(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def _order_row(
    ticker: str = "ITSA3",
    quantity: float = 100.0,
    price: float = 13.43,
    fees_exchange: float = 0.41,
    fees_brokerage: float = 0.0,
    fees_irrf: float = 0.0,
    total: float | None = None,
    side: str = "C",
    date: str = "2019-06-26",
) -> dict:
    computed_total = quantity * price + fees_exchange + fees_brokerage + fees_irrf
    return {
        "date": date,
        "side": side,
        "ticker": ticker,
        "quantity": str(quantity),
        "price": str(price),
        "currency": "BRL",
        "total": str(total if total is not None else computed_total),
        "fees_exchange": str(fees_exchange),
        "fees_brokerage": str(fees_brokerage),
        "fees_irrf": str(fees_irrf),
        "broker": "clear",
        "asset_type": "acao",
        "market": "vista",
        "source": "spreadsheet",
    }


# ---------------------------------------------------------------------------
# check_orders_file unit tests
# ---------------------------------------------------------------------------

def test_clean_row_no_violations(tmp_path):
    """Row where total = qty*price+fees → no violation."""
    path = tmp_path / "orders.csv"
    _write_orders(path, [_order_row()])
    violations = gpts.check_orders_file(path)
    assert violations == []


def test_violation_detected_above_tolerance(tmp_path):
    """Row where total deviates > 0.5% → violation."""
    row = _order_row(quantity=100.0, price=13.43, fees_exchange=0.41)
    expected_total = 100.0 * 13.43 + 0.41  # = 1343.41
    row["total"] = str(expected_total * 1.01)  # 1% deviation → violation
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])
    violations = gpts.check_orders_file(path)
    assert len(violations) == 1
    assert violations[0]["deviation_pct"] > 0.5


def test_violation_at_exactly_tolerance_not_flagged(tmp_path):
    """Row at exactly 0.5% deviation is NOT flagged (strict >)."""
    row = _order_row(quantity=100.0, price=13.43, fees_exchange=0.41)
    expected_total = 100.0 * 13.43 + 0.41
    row["total"] = str(expected_total * (1 + 0.005))  # exactly 0.5% — not flagged
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])
    violations = gpts.check_orders_file(path)
    assert violations == []


def test_violation_well_above_tolerance_flagged(tmp_path):
    """Row at 1% deviation IS flagged (well above the 0.5% threshold)."""
    row = _order_row(quantity=100.0, price=13.43, fees_exchange=0.41)
    expected_total = 100.0 * 13.43 + 0.41
    row["total"] = str(round(expected_total * 1.01, 4))  # 1% — clearly flagged
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])
    violations = gpts.check_orders_file(path)
    assert len(violations) == 1


def test_multiple_rows_mixed(tmp_path):
    """Mix of clean and violating rows → only violating rows reported."""
    row_clean = _order_row(ticker="ITSA3")
    row_bad = _order_row(ticker="B3SA3", quantity=100.0, price=12.33, fees_exchange=0.34)
    expected_bad = 100.0 * 12.33 + 0.34
    row_bad["total"] = str(expected_bad * 1.02)  # 2% off
    path = tmp_path / "orders.csv"
    _write_orders(path, [row_clean, row_bad])
    violations = gpts.check_orders_file(path)
    assert len(violations) == 1
    assert violations[0]["ticker"] == "B3SA3"


def test_row_missing_total_skipped(tmp_path):
    """Rows where total is blank are skipped (not a violation — missing data)."""
    row = _order_row()
    row["total"] = ""
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])
    violations = gpts.check_orders_file(path)
    assert violations == []


def test_row_zero_total_skipped(tmp_path):
    """Rows with total=0 are skipped."""
    row = _order_row()
    row["total"] = "0.0"
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])
    violations = gpts.check_orders_file(path)
    assert violations == []


def test_row_violation_fields_present(tmp_path):
    """Violation dict includes the expected fields."""
    row = _order_row()
    expected_total = 100.0 * 13.43 + 0.41
    row["total"] = str(expected_total * 1.02)
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])
    violations = gpts.check_orders_file(path)
    assert len(violations) == 1
    v = violations[0]
    assert "row_num" in v
    assert "deviation_pct" in v
    assert "total_stored" in v
    assert "total_expected" in v


# ---------------------------------------------------------------------------
# main() exit codes + event emission
# ---------------------------------------------------------------------------

def test_main_pass_exit_0(tmp_path, monkeypatch):
    """All rows clean → exit 0."""
    path = tmp_path / "orders.csv"
    _write_orders(path, [_order_row()])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_parser_total_sanity.py",
        "--orders-path", str(path),
    ])
    assert gpts.main() == 0


def test_main_fail_exit_1_on_violation(tmp_path, monkeypatch):
    """Violating row → exit 1."""
    row = _order_row()
    expected_total = 100.0 * 13.43 + 0.41
    row["total"] = str(expected_total * 1.02)
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_parser_total_sanity.py",
        "--orders-path", str(path),
    ])
    assert gpts.main() == 1


def test_main_error_exit_2_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_parser_total_sanity.py",
        "--orders-path", str(tmp_path / "nope.csv"),
    ])
    assert gpts.main() == 2


def test_main_gate_event_emitted_on_fail(tmp_path, monkeypatch):
    """gate_fail event emitted when violation found."""
    import lib.audit as audit_mod
    audit_mod._reset_cache_for_tests()

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()

    row = _order_row()
    expected_total = 100.0 * 13.43 + 0.41
    row["total"] = str(expected_total * 1.02)
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])

    monkeypatch.setenv("BOOKKEEPER_AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "0")
    monkeypatch.setattr(sys, "argv", [
        "gate_parser_total_sanity.py",
        "--orders-path", str(path),
    ])

    result = gpts.main()
    assert result == 1

    event_files = list(audit_dir.glob("events-*.jsonl"))
    assert event_files
    events = [json.loads(line) for line in event_files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    gate_events = [e for e in events if e.get("event_type") == "gate_fail"]
    assert gate_events
    assert gate_events[0]["gate"]["name"] == "gate_5_parser_total_sanity"

    audit_mod._reset_cache_for_tests()


def test_main_gate_pass_event_emitted(tmp_path, monkeypatch):
    """gate_pass event emitted when all rows clean."""
    import lib.audit as audit_mod
    audit_mod._reset_cache_for_tests()

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    path = tmp_path / "orders.csv"
    _write_orders(path, [_order_row()])

    monkeypatch.setenv("BOOKKEEPER_AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "0")
    monkeypatch.setattr(sys, "argv", [
        "gate_parser_total_sanity.py",
        "--orders-path", str(path),
    ])

    result = gpts.main()
    assert result == 0

    event_files = list(audit_dir.glob("events-*.jsonl"))
    assert event_files
    events = [json.loads(line) for line in event_files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    gate_events = [e for e in events if e.get("event_type") == "gate_pass"]
    assert gate_events
    assert gate_events[0]["gate"]["name"] == "gate_5_parser_total_sanity"

    audit_mod._reset_cache_for_tests()
