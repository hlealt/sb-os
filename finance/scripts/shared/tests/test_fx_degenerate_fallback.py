"""Regression tests for the degenerate FX 1.0 fallback on closed-ticker
USD flows (per-class IRR).

Latent bug: `_compute_portfolio_irr`'s flow conversion fell back to
`weighted_avg_rate or 1.0`. `process_transfer_out` zeroes
`weighted_avg_rate` when the transfer tranches are exhausted and the USD
balance reaches 0 (full repatriation), so every closed-ticker USD flow
(no active lots) would silently convert at FX 1.0 — ~5× undervalued —
while the bucket terminal stayed in real BRL.

Contracts tested:
  FX-A  Full repatriation persists the pre-zeroing account average in
        FXState.last_nonzero_avg_rate; weighted_avg_rate still resets to
        0.0 (P3-1-E behavior preserved).
  FX-B  get_ticker_fx_rate for a ticker with no active lots falls back
        to last_nonzero_avg_rate after a full repatriation (never 0).
  FX-C  Re-entry after a repatriation: a new transfer_in governs again;
        a second full repatriation captures the NEW average.
  FX-D  A trailing USD provento after full repatriation converts at the
        persisted rate, not 0.
  FX-E  calculate._to_brl converts closed-ticker flows at the persisted
        rate after full repatriation — no warning emitted.
  FX-F  calculate._to_brl with NO FX history anywhere converts at 1.0
        but warns LOUD on stderr (never silent), once per ticker.
  FX-G  calculate._to_brl passes BRL flows through untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the investimentos directory is importable.
_INVESTIMENTOS = Path(__file__).resolve().parents[2] / "investimentos"
if str(_INVESTIMENTOS) not in sys.path:
    sys.path.insert(0, str(_INVESTIMENTOS))

from fx_engine import FXState
from calculate import _to_brl


def _repatriated_state() -> FXState:
    """A state with real FX history fully repatriated: avg captured 5.50."""
    state = FXState()
    state.process_transfer_in(1000.0, 5.00)
    state.process_transfer_in(1000.0, 6.00)
    state.process_transfer_out(2000.0)  # withdraw everything
    return state


# ---------------------------------------------------------------------------
# FX-A: full repatriation persists last non-zero average
# ---------------------------------------------------------------------------

def test_full_repatriation_persists_last_nonzero_rate():
    state = _repatriated_state()
    assert abs(state.usd_balance) < 1e-9
    # P3-1-E contract preserved: the live average still zeroes.
    assert abs(state.weighted_avg_rate) < 1e-9
    # New contract: the pre-zeroing average survives.
    assert abs(state.last_nonzero_avg_rate - 5.50) < 1e-9, \
        f"expected persisted avg 5.50, got {state.last_nonzero_avg_rate}"


# ---------------------------------------------------------------------------
# FX-B: closed-ticker rate lookup falls back to the persisted average
# ---------------------------------------------------------------------------

def test_get_ticker_fx_rate_falls_back_after_repatriation():
    state = _repatriated_state()
    # No lots for MTCH (closed ticker) → account avg is 0 → persisted avg.
    rate = state.get_ticker_fx_rate('MTCH')
    assert abs(rate - 5.50) < 1e-9, \
        f"closed-ticker rate should fall back to 5.50, got {rate}"


# ---------------------------------------------------------------------------
# FX-C: re-entry then second repatriation captures the NEW average
# ---------------------------------------------------------------------------

def test_reentry_then_second_repatriation_updates_persisted_rate():
    state = _repatriated_state()
    state.process_transfer_in(500.0, 5.20)
    # Live average governs while non-zero.
    assert abs(state.get_ticker_fx_rate('MTCH') - 5.20) < 1e-9
    state.process_transfer_out(500.0)
    assert abs(state.weighted_avg_rate) < 1e-9
    assert abs(state.last_nonzero_avg_rate - 5.20) < 1e-9, \
        f"second repatriation should capture 5.20, got {state.last_nonzero_avg_rate}"


# ---------------------------------------------------------------------------
# FX-D: trailing provento after repatriation converts at persisted rate
# ---------------------------------------------------------------------------

def test_trailing_provento_after_repatriation():
    state = _repatriated_state()
    brl = state.process_provento('AAPL', '2026-06-01', 10.0)
    assert abs(brl - 55.0) < 1e-9, \
        f"trailing provento should convert at 5.50 → 55.0 BRL, got {brl}"


# ---------------------------------------------------------------------------
# FX-E: _to_brl uses persisted rate after repatriation — silent, correct
# ---------------------------------------------------------------------------

def test_to_brl_closed_ticker_after_full_repatriation(capsys):
    state = _repatriated_state()
    warned: set = set()
    brl = _to_brl(state, 'MTCH', 'USD', -100.0, warned)
    assert abs(brl - (-550.0)) < 1e-9, \
        f"closed-ticker USD flow should convert at 5.50, got {brl}"
    assert capsys.readouterr().err == ''
    assert not warned


# ---------------------------------------------------------------------------
# FX-F: _to_brl with no FX history at all → 1.0 but LOUD, once per ticker
# ---------------------------------------------------------------------------

def test_to_brl_degenerate_warns_loud_once(capsys):
    state = FXState()  # no FX history anywhere
    warned: set = set()
    brl = _to_brl(state, 'XYZ', 'USD', -100.0, warned)
    assert abs(brl - (-100.0)) < 1e-9
    err = capsys.readouterr().err
    assert 'XYZ' in err and '1.0' in err, \
        f"degenerate 1.0 conversion must warn on stderr, got: {err!r}"
    assert 'XYZ' in warned
    # Second flow for the same ticker: no duplicate warning.
    _to_brl(state, 'XYZ', 'USD', -50.0, warned)
    assert capsys.readouterr().err == ''


# ---------------------------------------------------------------------------
# FX-G: BRL flows pass through untouched
# ---------------------------------------------------------------------------

def test_to_brl_brl_passthrough(capsys):
    state = FXState()
    brl = _to_brl(state, 'VALE3', 'BRL', -123.45, set())
    assert abs(brl - (-123.45)) < 1e-9
    assert capsys.readouterr().err == ''
