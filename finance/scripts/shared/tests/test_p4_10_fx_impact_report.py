"""Regression tests for p4-10: fx_impact_report read tool.

Verifies:
  1. Decomposition produces non-None native_pnl_brl and fx_gain_brl when FX rate given.
  2. native_pnl_brl + fx_gain_brl == total_pnl_brl (accounting identity).
  3. Non-USD positions are excluded from decomposed results.
  4. Positions with zero cost_brl produce a 'note' entry (not a crash).
  5. print_report handles empty rows gracefully (no USD positions case).
  6. Positions with zero FX rate produce a 'note' entry (not a crash).
  7. Total aggregates are correct for a multi-position portfolio.
"""
from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
_INVESTIMENTOS_DIR = _SCRIPTS_DIR / "investimentos"
for _p in (_SCRIPTS_DIR, _INVESTIMENTOS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fx_impact_report import decompose_positions, print_report  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pos(pid: str, currency: str = "USD", cost_brl: float = 10000.0,
          value_brl: float = 12000.0, qty: float = 100.0, price: float = 50.0) -> dict:
    return {
        "id": pid,
        "currency": currency,
        "cost_brl": cost_brl,
        "current_value_brl": value_brl,
        "quantity": qty,
        "price": price,
    }


# ---------------------------------------------------------------------------
# Tests: decompose_positions
# ---------------------------------------------------------------------------

def test_usd_decomposition_identity():
    """native_pnl_brl + fx_gain_brl == total_pnl_brl."""
    positions = [_pos("AAPL", "USD", cost_brl=10000.0, value_brl=12000.0,
                       qty=100.0, price=60.0)]
    fx_rates = {"AAPL": 5.0}  # BRL/USD at cost = 5.0
    rows = decompose_positions(positions, fx_rates)
    assert len(rows) == 1
    r = rows[0]
    assert r["native_pnl_brl"] is not None
    assert r["fx_gain_brl"] is not None
    # Accounting identity: total = native + fx
    identity = r["native_pnl_brl"] + r["fx_gain_brl"]
    assert abs(identity - r["total_pnl_brl"]) < 0.01


def test_non_usd_positions_excluded():
    """BRL positions must not appear in results."""
    positions = [
        _pos("SIMH3", "BRL", cost_brl=5000.0, value_brl=6000.0),
        _pos("AAPL", "USD", cost_brl=10000.0, value_brl=11000.0),
    ]
    fx_rates = {"AAPL": 5.2}
    rows = decompose_positions(positions, fx_rates)
    assert all(r["id"] != "SIMH3" for r in rows)
    assert len(rows) == 1


def test_zero_cost_brl_produces_note():
    """Position with zero cost_brl gets a note, not a crash."""
    positions = [_pos("MSFT", "USD", cost_brl=0.0, value_brl=5000.0)]
    fx_rates = {"MSFT": 5.0}
    rows = decompose_positions(positions, fx_rates)
    assert len(rows) == 1
    assert rows[0]["native_pnl_brl"] is None
    assert rows[0].get("note")


def test_zero_fx_rate_produces_note():
    """Position with zero FX rate gets a note, not a crash."""
    positions = [_pos("TSLA", "USD", cost_brl=8000.0, value_brl=9000.0)]
    fx_rates = {"TSLA": 0.0}
    rows = decompose_positions(positions, fx_rates)
    assert len(rows) == 1
    assert rows[0].get("note")


def test_multi_position_totals(capsys):
    """Total P&L sums across positions correctly."""
    positions = [
        _pos("AAPL", "USD", cost_brl=10000.0, value_brl=12000.0, qty=100.0, price=60.0),
        _pos("MSFT", "USD", cost_brl=8000.0, value_brl=9500.0, qty=50.0, price=95.0),
    ]
    fx_rates = {"AAPL": 5.0, "MSFT": 5.1}
    rows = decompose_positions(positions, fx_rates)
    assert len(rows) == 2
    total_pnl = sum(r["total_pnl_brl"] for r in rows)
    assert abs(total_pnl - 3500.0) < 0.01  # (12000-10000) + (9500-8000)


def test_print_report_empty_no_crash(capsys):
    """print_report with no rows must not crash and states no USD positions."""
    print_report([], {"cut_date": "2026-01-01"})
    out = capsys.readouterr().out
    assert "no usd positions found" in out.lower()


def test_print_report_single_position(capsys):
    """print_report with one position produces readable output."""
    positions = [_pos("AAPL", "USD", cost_brl=10000.0, value_brl=12000.0,
                       qty=100.0, price=60.0)]
    rows = decompose_positions(positions, {"AAPL": 5.0})
    print_report(rows, {"cut_date": "2026-05-01"})
    out = capsys.readouterr().out
    assert "AAPL" in out
    assert "TOTAL" in out
