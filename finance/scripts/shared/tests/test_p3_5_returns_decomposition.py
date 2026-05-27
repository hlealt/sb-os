"""Regression tests for returns decomposition (p3-5 / D11).

Contracts tested:
  P3-5-A  BRK.B worked example: return_usd, return_fx_brl, return_total_brl
          match expected values (within float tolerance).
  P3-5-B  Reconciliation identity: return_total_brl ≈ pnl_absolute_brl
          (within R$0.02 float tolerance).
  P3-5-C  BRL position: return_usd / return_fx_brl / return_total_brl /
          funding_fx are NOT emitted (omit, not zero).
  P3-5-D  Price-missing USD position: all four fields are null.
  P3-5-E  Multiple lots: funding_fx is the quantity-weighted avg of active lots.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Ensure the investimentos directory is importable.
_INVESTIMENTOS = Path(__file__).resolve().parents[2] / "investimentos"
if str(_INVESTIMENTOS) not in sys.path:
    sys.path.insert(0, str(_INVESTIMENTOS))

from calculate import _build_position_entry
from fx_engine import FXState
from position_calculator import Position


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_position(id, currency, cost_basis, quantity):
    """Minimal Position with only the fields _build_position_entry uses."""
    pos = Position(id=id, name='', asset_class='variable_income', type='stock_us',
                   broker='avenue', currency=currency)
    pos.quantity = quantity
    pos.cost_basis = cost_basis
    pos.total_dividends = 0.0
    pos.total_dividends_ttm = 0.0
    pos.sector = ''
    return pos


def _make_price_data(id, price, source='api'):
    return {id: {'current_price': price, 'price_source': source,
                 'price_date': '2026-05-27', 'price_changes': {}}}


def _make_fx_state(ticker, buy_qty, buy_price, funding_rate):
    """FXState with a single buy lot at the given funding_rate."""
    state = FXState()
    state.process_transfer_in(buy_qty * buy_price, funding_rate)
    state.process_buy(ticker, '2025-01-01', buy_qty, buy_price)
    return state


# ---------------------------------------------------------------------------
# P3-5-A + P3-5-B: BRK.B worked example + reconciliation identity
# ---------------------------------------------------------------------------

def test_brk_b_worked_example_and_reconciliation():
    """BRK.B worked example — cost-basis FX lens (Decision 2026-05-27 in shape.md).

    Formula:
        return_usd      = native_value − native_cost
        return_fx_brl   = native_cost × current_fx − cost_basis_brl
        return_total_brl = return_usd × current_fx + return_fx_brl
                        = native_value × current_fx − cost_basis_brl
                        = pnl_absolute_brl  (identity holds exactly)

    Self-consistent setup (single transfer_in → single buy):
        quantity       = 14.0 shares
        cost_per_share = 320.00 USD
        funding_fx     = 5.40 BRL/USD  (single transfer_in rate)
        current_price  = 473.00 USD
        current_fx     = 4.957 BRL/USD (spot)
        cost_basis_brl = 14 × 320 × 5.40 = 24192.0  (from FX engine)
    """
    quantity = 14.0
    cost_per_share = 320.0
    cost_basis = cost_per_share * quantity   # = 4480.0
    current_price = 473.0
    current_fx = 4.957
    funding_fx = 5.40  # exact — single transfer_in

    pos = _make_position('BRK.B', 'USD', cost_basis, quantity)
    price_data = _make_price_data('BRK.B', current_price)

    # FXState with a single buy lot at funding_fx
    state = _make_fx_state('BRK.B', quantity, cost_per_share, funding_fx)

    entry = _build_position_entry(
        pos=pos,
        price_data=price_data,
        fx_state=state,
        usd_brl_rate=current_fx,
        assets={},
        position_flows={},
        terminal_date='2026-05-27',
    )

    assert 'return_usd' in entry, "return_usd must be emitted for USD position"
    assert 'return_fx_brl' in entry
    assert 'return_total_brl' in entry
    assert 'funding_fx' in entry

    native_value = quantity * current_price    # 14 × 473 = 6622.0
    native_cost = cost_basis                   # 4480.0
    # cost_basis_brl from FX engine: quantity × cost_per_share × funding_fx
    cost_basis_brl = state.get_ticker_cost_brl('BRK.B')   # = 24192.0

    # Expected values — cost-basis FX lens (shape.md Decision 2026-05-27)
    expected_return_usd = round(native_value - native_cost, 2)
    expected_return_fx_brl = round(native_cost * current_fx - cost_basis_brl, 2)
    expected_return_total_brl = round(
        expected_return_usd * current_fx + expected_return_fx_brl, 2
    )

    assert abs(entry['return_usd'] - expected_return_usd) < 0.01, \
        f"return_usd: expected {expected_return_usd}, got {entry['return_usd']}"
    assert abs(entry['return_fx_brl'] - expected_return_fx_brl) < 0.01, \
        f"return_fx_brl: expected {expected_return_fx_brl}, got {entry['return_fx_brl']}"
    assert abs(entry['return_total_brl'] - expected_return_total_brl) < 0.01, \
        f"return_total_brl: expected {expected_return_total_brl}, got {entry['return_total_brl']}"

    # P3-5-B: reconciliation identity — return_total_brl == pnl_absolute_brl
    # Algebraically exact: return_total_brl = native_value × current_fx − cost_basis_brl
    #                                       = current_value_brl − cost_basis_brl
    #                                       = pnl_absolute_brl
    pnl_absolute_brl = entry['pnl_absolute_brl']
    diff = abs(entry['return_total_brl'] - pnl_absolute_brl)
    assert diff < 0.02, (
        f"Reconciliation identity VIOLATED: return_total_brl={entry['return_total_brl']}, "
        f"pnl_absolute_brl={pnl_absolute_brl}, diff={diff:.6f}"
    )


# ---------------------------------------------------------------------------
# P3-5-C: BRL position — decomposition fields are absent
# ---------------------------------------------------------------------------

def test_brl_position_omits_decomposition_fields():
    """BRL positions must NOT have return_usd / return_fx_brl / return_total_brl / funding_fx."""
    pos = _make_position('PETR4', 'BRL', 10000.0, 100.0)
    price_data = _make_price_data('PETR4', 35.50)

    entry = _build_position_entry(
        pos=pos,
        price_data=price_data,
        fx_state=FXState(),
        usd_brl_rate=4.957,
        assets={},
        position_flows={},
        terminal_date='2026-05-27',
    )

    assert 'return_usd' not in entry, "BRL position must NOT emit return_usd"
    assert 'return_fx_brl' not in entry, "BRL position must NOT emit return_fx_brl"
    assert 'return_total_brl' not in entry, "BRL position must NOT emit return_total_brl"
    assert 'funding_fx' not in entry, "BRL position must NOT emit funding_fx"


# ---------------------------------------------------------------------------
# P3-5-D: price-missing USD position → all four fields are null
# ---------------------------------------------------------------------------

def test_price_missing_usd_position_emits_null():
    """When price_source='missing', all four decomposition fields must be null."""
    pos = _make_position('AAPL', 'USD', 5000.0, 10.0)
    price_data = _make_price_data('AAPL', 0.0, source='missing')

    state = FXState()
    state.process_transfer_in(5000.0, 5.00)
    state.process_buy('AAPL', '2025-01-01', 10.0, 500.0)

    entry = _build_position_entry(
        pos=pos,
        price_data=price_data,
        fx_state=state,
        usd_brl_rate=4.957,
        assets={},
        position_flows={},
        terminal_date='2026-05-27',
    )

    assert entry['return_usd'] is None, "price_source=missing must emit null for return_usd"
    assert entry['return_fx_brl'] is None
    assert entry['return_total_brl'] is None
    assert entry['funding_fx'] is None


# ---------------------------------------------------------------------------
# P3-5-E: multiple lots → funding_fx is quantity-weighted avg
# ---------------------------------------------------------------------------

def test_multiple_lots_funding_fx_weighted_avg():
    """funding_fx must be the quantity-weighted avg of active lots.

    To get predictable lot fx_rates, each transfer_in fully funds a single buy
    (so the account avg at each buy equals that transfer_in's rate exactly).

    Transfer 1: 500 USD @ 5.00, buy 5 shares @ 100 → lot1 fx=5.00, balance=0
    Transfer 2: 1000 USD @ 6.00 (rescue path resets avg to 6.00), buy 10 @ 100
                → lot2 fx=6.00, balance=0

    Expected funding_fx = (5×5.00 + 10×6.00) / 15 = 5.6667
    """
    state = FXState()
    state.process_transfer_in(500.0, 5.00)   # balance=500, avg=5.00
    state.process_buy('MSFT', '2025-01-01', 5.0, 100.0)   # balance=0, lot1 fx=5.00
    state.process_transfer_in(1000.0, 6.00)  # balance<= 0 rescue → avg=6.00
    state.process_buy('MSFT', '2025-06-01', 10.0, 100.0)  # balance=0, lot2 fx=6.00

    # Verify lot fx_rates directly on state before building entry
    actual_funding_fx = state.get_ticker_fx_rate('MSFT')
    expected_funding_fx = (5.0 * 5.00 + 10.0 * 6.00) / 15.0  # = 5.6667
    assert abs(actual_funding_fx - expected_funding_fx) < 1e-9, \
        f"FX engine: expected {expected_funding_fx:.4f}, got {actual_funding_fx:.4f}"

    pos = _make_position('MSFT', 'USD', 15 * 100.0, 15.0)
    price_data = _make_price_data('MSFT', 110.0)

    entry = _build_position_entry(
        pos=pos,
        price_data=price_data,
        fx_state=state,
        usd_brl_rate=5.00,
        assets={},
        position_flows={},
        terminal_date='2026-05-27',
    )

    assert abs(entry['funding_fx'] - round(expected_funding_fx, 4)) < 1e-9, \
        f"funding_fx in entry: expected {expected_funding_fx:.4f}, got {entry['funding_fx']}"


# ---------------------------------------------------------------------------
# P3-5-F: multi-lot reconciliation — return_total_brl == pnl_absolute_brl
# exactly for a position with heterogeneous lot FX rates.
# ---------------------------------------------------------------------------

def test_multi_lot_reconciliation_exact():
    """return_total_brl must equal pnl_absolute_brl exactly (within R$0.02) for
    a multi-lot position where each lot was funded at a different FX rate.

    This confirms the cost-basis lens identity holds for any lot structure.

    Setup: MSFT with two lots at different funding rates.
        Lot 1: 5 shares @ 100 USD, funded @ 5.00 → cost_brl1 = 2500.0
        Lot 2: 10 shares @ 100 USD, funded @ 6.00 → cost_brl2 = 6000.0
        total cost_basis_brl = 8500.0
        current_price = 110 USD, current_fx = 5.50
    """
    state = FXState()
    state.process_transfer_in(500.0, 5.00)
    state.process_buy('MSFT', '2025-01-01', 5.0, 100.0)
    state.process_transfer_in(1000.0, 6.00)
    state.process_buy('MSFT', '2025-06-01', 10.0, 100.0)

    cost_basis = 15.0 * 100.0   # = 1500.0
    current_price = 110.0
    current_fx = 5.50
    quantity = 15.0

    pos = _make_position('MSFT', 'USD', cost_basis, quantity)
    price_data = _make_price_data('MSFT', current_price)

    entry = _build_position_entry(
        pos=pos,
        price_data=price_data,
        fx_state=state,
        usd_brl_rate=current_fx,
        assets={},
        position_flows={},
        terminal_date='2026-05-27',
    )

    pnl_absolute_brl = entry['pnl_absolute_brl']
    return_total_brl = entry['return_total_brl']
    diff = abs(return_total_brl - pnl_absolute_brl)
    assert diff < 0.02, (
        f"Multi-lot reconciliation VIOLATED: return_total_brl={return_total_brl}, "
        f"pnl_absolute_brl={pnl_absolute_brl}, diff={diff:.6f}"
    )
