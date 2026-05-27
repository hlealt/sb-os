"""Regression tests for transfer_out FIFO tranche-consumption (p3-1 / D10).

Contracts tested:
  P3-1-A  D10 worked example: transfer_in 1000@5.00, transfer_in 1000@6.00,
          transfer_out 500 → weighted_avg_rate shifts to 5.667 (not 5.50).
  P3-1-B  Full-tranche consumption: transfer_out exactly the first tranche
          amount → only second tranche remains, avg = 6.00.
  P3-1-C  No-dilution regression: process_provento does NOT change
          weighted_avg_rate when dividend rate equals existing ticker rate
          (TC1 from p2-3 verification).
  P3-1-D  transfer_out with no transfer tranches (edge): balance decreases,
          rate stays 0.0, no crash.
  P3-1-E  transfer_out that fully empties balance: avg resets to 0.0.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the investimentos directory is importable.
# __file__ = shared/tests/test_p3_1_transfer_out_fifo.py
# parents[0] = shared/tests/
# parents[1] = shared/
# parents[2] = scripts/
_INVESTIMENTOS = Path(__file__).resolve().parents[2] / "investimentos"
if str(_INVESTIMENTOS) not in sys.path:
    sys.path.insert(0, str(_INVESTIMENTOS))

from fx_engine import FXState


# ---------------------------------------------------------------------------
# P3-1-A: D10 worked example — avg shifts to 5.667
# ---------------------------------------------------------------------------

def test_transfer_out_fifo_d10_worked_example():
    """D10 worked example from data-flow-map-target.md §4.3.

    transfer_in 1000 @ 5.00 → avg=5.00
    transfer_in 1000 @ 6.00 → avg=5.50
    transfer_out 500         → consumes 500 from first tranche (5.00)
    Remaining: 500@5.00 + 1000@6.00 = 1500 USD
    New avg: (500×5.00 + 1000×6.00) / 1500 = (2500 + 6000) / 1500 = 5.6̄6̄7̄
    """
    state = FXState()
    state.process_transfer_in(1000.0, 5.00)
    state.process_transfer_in(1000.0, 6.00)

    assert abs(state.weighted_avg_rate - 5.50) < 1e-9, \
        f"avg after two transfer_ins should be 5.50, got {state.weighted_avg_rate}"

    state.process_transfer_out(500.0)

    assert abs(state.usd_balance - 1500.0) < 1e-9
    expected_avg = (500.0 * 5.00 + 1000.0 * 6.00) / 1500.0  # = 5.6̄6̄7̄
    assert abs(state.weighted_avg_rate - expected_avg) < 1e-9, \
        f"expected avg={expected_avg:.6f}, got {state.weighted_avg_rate:.6f}"


# ---------------------------------------------------------------------------
# P3-1-B: full first-tranche consumption → avg = 6.00
# ---------------------------------------------------------------------------

def test_transfer_out_full_first_tranche():
    """Consuming exactly the first tranche leaves only the second."""
    state = FXState()
    state.process_transfer_in(1000.0, 5.00)
    state.process_transfer_in(1000.0, 6.00)
    state.process_transfer_out(1000.0)  # consume entire first tranche

    assert abs(state.usd_balance - 1000.0) < 1e-9
    assert abs(state.weighted_avg_rate - 6.00) < 1e-9, \
        f"only second tranche remains, avg should be 6.00, got {state.weighted_avg_rate}"


# ---------------------------------------------------------------------------
# P3-1-C: no-dilution regression (TC1 from p2-3)
# ---------------------------------------------------------------------------

def test_provento_no_dilution_regression():
    """USD dividend at existing avg rate must NOT change weighted_avg_rate.

    Verbatim TC1 from p2-3-fifo-fx.md verification.
    """
    state = FXState()
    state.process_transfer_in(100.0, 5.00)

    assert abs(state.weighted_avg_rate - 5.00) < 1e-9

    # No buy → no AAPL lots → get_ticker_fx_rate falls back to account avg (5.00)
    brl_eq = state.process_provento('AAPL', '2026-01-01', 50.0)

    assert abs(brl_eq - 250.0) < 1e-9, \
        f"BRL equivalent should be 50×5.00=250, got {brl_eq}"
    assert abs(state.weighted_avg_rate - 5.00) < 1e-9, \
        f"avg should be unchanged at 5.00 after dividend, got {state.weighted_avg_rate}"
    assert abs(state.usd_balance - 150.0) < 1e-9


# ---------------------------------------------------------------------------
# P3-1-D: transfer_out with no tranches — no crash
# ---------------------------------------------------------------------------

def test_transfer_out_no_tranches():
    """If transfer_lots is empty (edge case), transfer_out must not crash."""
    state = FXState()
    state.usd_balance = 200.0  # manually set, no transfer_in logged
    state.weighted_avg_rate = 5.50

    state.process_transfer_out(100.0)

    assert abs(state.usd_balance - 100.0) < 1e-9
    # No tranches → avg unchanged (no information to update it)
    assert abs(state.weighted_avg_rate - 5.50) < 1e-9


# ---------------------------------------------------------------------------
# P3-1-E: transfer_out empties balance → avg resets to 0.0
# ---------------------------------------------------------------------------

def test_transfer_out_empties_balance():
    """Withdrawing all USD resets weighted_avg_rate to 0.0."""
    state = FXState()
    state.process_transfer_in(1000.0, 5.00)
    state.process_transfer_in(1000.0, 6.00)
    state.process_transfer_out(2000.0)  # withdraw everything

    assert abs(state.usd_balance) < 1e-9
    assert abs(state.weighted_avg_rate) < 1e-9, \
        f"avg should be 0.0 after emptying balance, got {state.weighted_avg_rate}"
