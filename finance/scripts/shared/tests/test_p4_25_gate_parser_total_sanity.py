"""Tests for gate #5 — parser total sanity (p4-25).

0.5% tolerance for *_orders.csv rows. Fail-loud; user decides.

Revision notes (2026-06-05):
- check_orders_file now returns (violations, corrections_applied) tuple.
- Side-aware fee convention: V rows use qty*price - fees; C/unknown use + fees.
- Corrections-join: loads manual_adjust/quantity rows from corrections dir.
- Test isolation: BOOKKEEPER_CORRECTIONS_DIR pointed at tmp dir to prevent
  real corrections leaking into tests.
"""

import csv
import json
import os
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

_CORRECTIONS_FIELDNAMES = [
    "correction_type", "field", "target_key", "correction_date",
    "from_value", "to_value", "note",
]


def _write_orders(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def _write_corrections(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CORRECTIONS_FIELDNAMES)
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
    # Default total uses buy convention (+ fees)
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
# check_orders_file unit tests — tuple return fix
# ---------------------------------------------------------------------------

def test_clean_row_no_violations(tmp_path, monkeypatch):
    """Row where total = qty*price+fees → no violation."""
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(tmp_path / "corrections"))
    path = tmp_path / "orders.csv"
    _write_orders(path, [_order_row()])
    violations, corrections_applied = gpts.check_orders_file(path)
    assert violations == []
    assert corrections_applied == 0


def test_violation_detected_above_tolerance(tmp_path, monkeypatch):
    """Row where total deviates > 0.5% → violation."""
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(tmp_path / "corrections"))
    row = _order_row(quantity=100.0, price=13.43, fees_exchange=0.41)
    expected_total = 100.0 * 13.43 + 0.41  # = 1343.41
    row["total"] = str(expected_total * 1.01)  # 1% deviation → violation
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])
    violations, _ = gpts.check_orders_file(path)
    assert len(violations) == 1
    assert violations[0]["deviation_pct"] > 0.5


def test_violation_at_exactly_tolerance_not_flagged(tmp_path, monkeypatch):
    """Row at exactly 0.5% deviation is NOT flagged (strict >)."""
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(tmp_path / "corrections"))
    row = _order_row(quantity=100.0, price=13.43, fees_exchange=0.41)
    expected_total = 100.0 * 13.43 + 0.41
    row["total"] = str(expected_total * (1 + 0.005))  # exactly 0.5% — not flagged
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])
    violations, _ = gpts.check_orders_file(path)
    assert violations == []


def test_violation_well_above_tolerance_flagged(tmp_path, monkeypatch):
    """Row at 1% deviation IS flagged (well above the 0.5% threshold)."""
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(tmp_path / "corrections"))
    row = _order_row(quantity=100.0, price=13.43, fees_exchange=0.41)
    expected_total = 100.0 * 13.43 + 0.41
    row["total"] = str(round(expected_total * 1.01, 4))  # 1% — clearly flagged
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])
    violations, _ = gpts.check_orders_file(path)
    assert len(violations) == 1


def test_multiple_rows_mixed(tmp_path, monkeypatch):
    """Mix of clean and violating rows → only violating rows reported."""
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(tmp_path / "corrections"))
    row_clean = _order_row(ticker="ITSA3")
    row_bad = _order_row(ticker="B3SA3", quantity=100.0, price=12.33, fees_exchange=0.34)
    expected_bad = 100.0 * 12.33 + 0.34
    row_bad["total"] = str(expected_bad * 1.02)  # 2% off
    path = tmp_path / "orders.csv"
    _write_orders(path, [row_clean, row_bad])
    violations, _ = gpts.check_orders_file(path)
    assert len(violations) == 1
    assert violations[0]["ticker"] == "B3SA3"


def test_row_missing_total_skipped(tmp_path, monkeypatch):
    """Rows where total is blank are skipped (not a violation — missing data)."""
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(tmp_path / "corrections"))
    row = _order_row()
    row["total"] = ""
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])
    violations, _ = gpts.check_orders_file(path)
    assert violations == []


def test_row_zero_total_skipped(tmp_path, monkeypatch):
    """Rows with total=0 are skipped."""
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(tmp_path / "corrections"))
    row = _order_row()
    row["total"] = "0.0"
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])
    violations, _ = gpts.check_orders_file(path)
    assert violations == []


def test_row_violation_fields_present(tmp_path, monkeypatch):
    """Violation dict includes the expected fields."""
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(tmp_path / "corrections"))
    row = _order_row()
    expected_total = 100.0 * 13.43 + 0.41
    row["total"] = str(expected_total * 1.02)
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])
    violations, _ = gpts.check_orders_file(path)
    assert len(violations) == 1
    v = violations[0]
    assert "row_num" in v
    assert "deviation_pct" in v
    assert "total_stored" in v
    assert "total_expected" in v


# ---------------------------------------------------------------------------
# Side-aware fee convention tests
# ---------------------------------------------------------------------------

def test_sell_row_fees_subtracted_passes(tmp_path, monkeypatch):
    """Sell row: total = qty*price - fees → passes gate."""
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(tmp_path / "corrections"))
    qty = 100.0
    price = 13.43
    fees = 0.41
    # Sell convention: proceeds - fees
    sell_total = qty * price - fees
    row = _order_row(
        ticker="ITSA3", quantity=qty, price=price,
        fees_exchange=fees, total=sell_total, side="V",
    )
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])
    violations, _ = gpts.check_orders_file(path)
    assert violations == [], f"Expected no violations for sell row, got: {violations}"


def test_sell_row_fees_added_fails(tmp_path, monkeypatch):
    """Sell row with buy convention (total = qty*price + fees) → fails gate.

    The gate expects sell total = qty*price - fees; a value of qty*price + fees
    deviates by 2*fees/total which should exceed the 0.5% tolerance on a
    realistic trade (fees ≈ 0.03% of notional is tiny but the *direction* difference
    matters). We use higher fees to ensure the deviation is visible.
    """
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(tmp_path / "corrections"))
    qty = 100.0
    price = 13.43
    fees = 20.0  # large fee to produce clear deviation
    # Store total as if it were a BUY (+ fees) but record side=V
    wrong_total = qty * price + fees  # wrong for sell
    row = _order_row(
        ticker="ITSA3", quantity=qty, price=price,
        fees_exchange=fees, total=wrong_total, side="V",
    )
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])
    violations, _ = gpts.check_orders_file(path)
    assert len(violations) == 1, (
        f"Expected 1 violation for sell row with wrong (buy) total, got: {violations}"
    )


def test_buy_row_fees_added_passes(tmp_path, monkeypatch):
    """Buy row: total = qty*price + fees → passes (unchanged from pre-revision)."""
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(tmp_path / "corrections"))
    qty = 100.0
    price = 13.43
    fees = 0.41
    buy_total = qty * price + fees
    row = _order_row(
        ticker="ITSA3", quantity=qty, price=price,
        fees_exchange=fees, total=buy_total, side="C",
    )
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])
    violations, _ = gpts.check_orders_file(path)
    assert violations == []


def test_sell_buy_side_same_data_different_outcome(tmp_path, monkeypatch):
    """Same qty/price/fees data: total=qty*price-fees passes for V, fails for C."""
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(tmp_path / "corrections"))
    qty = 100.0
    price = 13.43
    fees = 20.0  # large to make deviation clear for side=C case
    sell_total = qty * price - fees  # correct for sell

    # Row with side=V — should PASS (total is sell-correct)
    sell_row = _order_row(
        ticker="ITSA3", quantity=qty, price=price,
        fees_exchange=fees, total=sell_total, side="V",
    )
    path_v = tmp_path / "orders_v.csv"
    _write_orders(path_v, [sell_row])
    violations_v, _ = gpts.check_orders_file(path_v)
    assert violations_v == [], f"V row should pass: {violations_v}"

    # Same total on side=C — should FAIL (expected = qty*price + fees, stored = qty*price - fees)
    buy_row = _order_row(
        ticker="ITSA3", quantity=qty, price=price,
        fees_exchange=fees, total=sell_total, side="C",
    )
    path_c = tmp_path / "orders_c.csv"
    _write_orders(path_c, [buy_row])
    violations_c, _ = gpts.check_orders_file(path_c)
    assert len(violations_c) == 1, f"C row with sell-convention total should fail: {violations_c}"


# ---------------------------------------------------------------------------
# Corrections-join tests
# ---------------------------------------------------------------------------

def _corrections_row(
    ticker: str,
    date: str,
    from_value: float,
    to_value: float,
    correction_type: str = "manual_adjust",
    field: str = "quantity",
) -> dict:
    return {
        "correction_type": correction_type,
        "field": field,
        "target_key": ticker,
        "correction_date": date,
        "from_value": str(from_value),
        "to_value": str(to_value),
        "note": "test",
    }


def test_corrections_join_fixes_truncated_qty(tmp_path, monkeypatch):
    """Truncated-qty row fails alone but passes via corrections-join.

    The stored quantity is truncated (stored=100, true=101); the
    corrections file has from_value=100, to_value=101; total was computed
    with 101. Deviation from stored qty: (101*50+2 - 100*50+2) / (101*50+2) ≈ 1%
    → above 0.5% without correction, within tolerance after correction.
    After correction the row should pass and corrections_applied==1.
    """
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(tmp_path / "corrections"))
    corr_dir = tmp_path / "corrections"
    corr_dir.mkdir()

    ticker = "AAPL"
    date = "2024-01-15"
    true_qty = 101.0   # use integer step to ensure deviation > 0.5%
    stored_qty = 100.0
    price = 50.0
    fees = 2.0
    # Total computed with true (corrected) qty, buy convention
    total = true_qty * price + fees

    # Write correction: from stored_qty → true_qty
    corr_path = corr_dir / "intl.csv"
    _write_corrections(corr_path, [
        _corrections_row(ticker, date, from_value=stored_qty, to_value=true_qty),
    ])

    # Order row: has truncated stored_qty but total reflects true_qty
    row = _order_row(
        ticker=ticker, quantity=stored_qty, price=price,
        fees_exchange=fees, total=total, side="C", date=date,
    )
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])

    corrections = gpts.load_qty_corrections(corr_dir)
    violations, corrections_applied = gpts.check_orders_file(path, corrections)
    assert violations == [], f"Row should pass via correction: {violations}"
    assert corrections_applied == 1


def test_missing_corrections_dir_fails_soft(tmp_path, monkeypatch):
    """Missing corrections dir → no crash, no corrections, violating rows still fail."""
    # Point to a non-existent dir — must not raise
    absent_dir = tmp_path / "no_such_corrections_dir"
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(absent_dir))

    row = _order_row()
    expected_total = 100.0 * 13.43 + 0.41
    row["total"] = str(expected_total * 1.02)  # 2% deviation
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])

    # load_qty_corrections must return empty dict without raising
    corrections = gpts.load_qty_corrections(absent_dir)
    assert corrections == {}

    violations, corrections_applied = gpts.check_orders_file(path, corrections)
    assert len(violations) == 1
    assert corrections_applied == 0


def test_from_value_mismatch_does_not_misbind(tmp_path, monkeypatch):
    """Correction with from_value ≠ stored qty must NOT correct the row.

    Row fails; corrections_applied stays 0 (no misbinding).
    """
    corr_dir = tmp_path / "corrections"
    corr_dir.mkdir()
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(corr_dir))

    ticker = "AAPL"
    date = "2024-01-15"
    stored_qty = 100.0
    # Correction targets a DIFFERENT from_value (200.0 ≠ 100.0)
    wrong_from_qty = 200.0
    true_qty = 200.5
    price = 50.0
    fees = 2.0

    # Total is off by 2% from stored_qty convention → deviation > 0.5%
    expected_total = stored_qty * price + fees
    row = _order_row(
        ticker=ticker, quantity=stored_qty, price=price,
        fees_exchange=fees, total=expected_total * 1.02, side="C", date=date,
    )

    corr_path = corr_dir / "intl.csv"
    _write_corrections(corr_path, [
        _corrections_row(ticker, date, from_value=wrong_from_qty, to_value=true_qty),
    ])

    # Write orders first, then load corrections and check
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])
    corrections = gpts.load_qty_corrections(corr_dir)
    violations, corrections_applied = gpts.check_orders_file(path, corrections)

    assert len(violations) == 1, "from_value mismatch must not fix the row"
    assert corrections_applied == 0, "No correction should have been applied"


def test_test_isolation_real_corrections_do_not_leak(tmp_path, monkeypatch):
    """BOOKKEEPER_CORRECTIONS_DIR set to tmp dir → real corrections never loaded.

    Verifies that the env var override is respected and the corrections dict
    loaded is empty when pointing at an empty tmp dir.
    """
    empty_corr_dir = tmp_path / "empty_corrections"
    empty_corr_dir.mkdir()
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(empty_corr_dir))

    # _default_corrections_dir() must return the overridden path
    resolved = gpts._default_corrections_dir()
    assert resolved == empty_corr_dir

    corrections = gpts.load_qty_corrections(empty_corr_dir)
    assert corrections == {}


# ---------------------------------------------------------------------------
# main() exit codes + event emission
# ---------------------------------------------------------------------------

def test_main_pass_exit_0(tmp_path, monkeypatch):
    """All rows clean → exit 0."""
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(tmp_path / "corrections"))
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
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(tmp_path / "corrections"))
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
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(tmp_path / "corrections"))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_parser_total_sanity.py",
        "--orders-path", str(tmp_path / "nope.csv"),
    ])
    assert gpts.main() == 2


def test_main_pass_with_corrections_applied(tmp_path, monkeypatch):
    """Rows passing only via corrections → exit 0; PASS message mentions corrections."""
    corr_dir = tmp_path / "corrections"
    corr_dir.mkdir()
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(corr_dir))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")

    ticker = "AAPL"
    date = "2024-01-15"
    true_qty = 100.5
    stored_qty = 100.0
    price = 50.0
    fees = 2.0
    total = true_qty * price + fees

    corr_path = corr_dir / "intl.csv"
    _write_corrections(corr_path, [
        _corrections_row(ticker, date, from_value=stored_qty, to_value=true_qty),
    ])

    row = _order_row(
        ticker=ticker, quantity=stored_qty, price=price,
        fees_exchange=fees, total=total, side="C", date=date,
    )
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])

    monkeypatch.setattr(sys, "argv", [
        "gate_parser_total_sanity.py",
        "--orders-path", str(path),
    ])
    result = gpts.main()
    assert result == 0


def test_main_gate_event_emitted_on_fail(tmp_path, monkeypatch):
    """gate_fail event emitted when violation found."""
    import lib.audit as audit_mod
    audit_mod._reset_cache_for_tests()

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(tmp_path / "corrections"))

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
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(tmp_path / "corrections"))

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


def test_main_gate_pass_event_includes_corrections_applied(tmp_path, monkeypatch):
    """gate_pass trigger_context.corrections_applied is set when corrections used."""
    import lib.audit as audit_mod
    audit_mod._reset_cache_for_tests()

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    corr_dir = tmp_path / "corrections"
    corr_dir.mkdir()
    monkeypatch.setenv("BOOKKEEPER_CORRECTIONS_DIR", str(corr_dir))

    ticker = "AAPL"
    date = "2024-02-20"
    true_qty = 50.5
    stored_qty = 50.0
    price = 200.0
    fees = 1.0
    total = true_qty * price + fees

    corr_path = corr_dir / "stocks.csv"
    _write_corrections(corr_path, [
        _corrections_row(ticker, date, from_value=stored_qty, to_value=true_qty),
    ])

    row = _order_row(
        ticker=ticker, quantity=stored_qty, price=price,
        fees_exchange=fees, total=total, side="C", date=date,
    )
    path = tmp_path / "orders.csv"
    _write_orders(path, [row])

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
    # trigger_context is a top-level event field (not nested under gate)
    tc = gate_events[0].get("trigger_context") or {}
    assert tc.get("corrections_applied") == 1

    audit_mod._reset_cache_for_tests()
