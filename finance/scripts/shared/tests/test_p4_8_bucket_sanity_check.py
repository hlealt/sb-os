"""Regression tests for p4-8: bucket_sanity_check read tool.

Verifies:
  1. No divergence when per-asset IRRs average close to stored bucket IRR.
  2. Divergence flagged when |simple_avg - stored_bucket_irr| > threshold.
  3. Targeting a single bucket with --bucket narrows the check.
  4. Bucket with no positions reports gracefully.
  5. Bucket with stored_irr=None skips the comparison gracefully.
  6. _irr_bucket classification matches calculate.py conventions.
  7. Custom threshold is respected.
  8. check_buckets returns 0 (informational) even when divergences found.
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

from bucket_sanity_check import check_buckets, _irr_bucket  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_portfolio(per_class_irrs: dict, positions: list[dict]) -> dict:
    per_class_section = {
        cls: {"irr": irr, "terminal_value": 100000.0, "flow_count": 5}
        for cls, irr in per_class_irrs.items()
    }
    return {
        "meta": {"cut_date": "2026-01-01"},
        "summary": {
            "total_value": 200000.0, "total_cost": 180000.0, "total_pnl": 20000.0,
            "allocation_by_class": {}, "allocation_by_broker": {}, "allocation_by_currency": {},
            "irr": {"total": 0.12, "per_class": per_class_section}
        },
        "positions": positions,
        "income": {}
    }


def _make_position(pid: str, typ: str, currency: str, irr: float,
                   asset_class: str = "variable_income") -> dict:
    return {
        "id": pid, "type": typ, "currency": currency, "asset_class": asset_class,
        "irr": irr, "current_value_brl": 50000.0, "irr_quality": "complete",
        "valuation_method": "price"
    }


# ---------------------------------------------------------------------------
# Tests: _irr_bucket
# ---------------------------------------------------------------------------

def test_bucket_acao_is_rv_br():
    pos = {"type": "acao", "currency": "BRL", "asset_class": "variable_income"}
    assert _irr_bucket(pos) == "rv_br"


def test_bucket_stock_us_is_rv_eua():
    pos = {"type": "stock_us", "currency": "USD", "asset_class": "variable_income"}
    assert _irr_bucket(pos) == "rv_eua"


def test_bucket_cra_is_rf_balcao():
    pos = {"type": "cra", "currency": "BRL", "asset_class": "fixed_income"}
    assert _irr_bucket(pos) == "rf_balcao"


def test_bucket_fia_br_is_fundos():
    pos = {"type": "fia_br", "currency": "BRL", "asset_class": "funds"}
    assert _irr_bucket(pos) == "fundos"


def test_bucket_crypto_is_crypto():
    pos = {"type": "crypto", "currency": "BRL", "asset_class": "crypto"}
    assert _irr_bucket(pos) == "crypto"


# ---------------------------------------------------------------------------
# Tests: check_buckets
# ---------------------------------------------------------------------------

def test_no_divergence_within_threshold(capsys):
    """Simple avg ≈ stored IRR → 0 divergences."""
    # Two positions with irr 0.10 and 0.12 → avg = 0.11 = stored
    positions = [
        _make_position("SIMH3", "acao", "BRL", 0.10),
        _make_position("PRIO3", "acao", "BRL", 0.12),
    ]
    portfolio = _make_portfolio({"rv_br": 0.11}, positions)
    divergences = check_buckets(portfolio, target_bucket="rv_br", threshold=0.05)
    assert divergences == 0


def test_divergence_detected_exceeds_threshold(capsys):
    """Simple avg much higher than stored → divergence."""
    positions = [
        _make_position("BAD1", "acao", "BRL", 1.00),  # 100% IRR
        _make_position("BAD2", "acao", "BRL", 1.00),  # 100% IRR
    ]
    portfolio = _make_portfolio({"rv_br": 0.10}, positions)  # stored = 10%
    divergences = check_buckets(portfolio, target_bucket="rv_br", threshold=0.05)
    assert divergences == 1


def test_custom_threshold_respected(capsys):
    """With tight threshold of 0.01 even a 3pp gap triggers divergence."""
    positions = [_make_position("A1", "acao", "BRL", 0.12)]
    portfolio = _make_portfolio({"rv_br": 0.15}, positions)  # delta = 3pp
    divs_tight = check_buckets(portfolio, target_bucket="rv_br", threshold=0.01)
    divs_loose = check_buckets(portfolio, target_bucket="rv_br", threshold=0.10)
    assert divs_tight == 1
    assert divs_loose == 0


def test_empty_bucket_no_crash(capsys):
    """Bucket with no positions is handled gracefully."""
    portfolio = _make_portfolio(
        {"rv_eua": 0.15},
        [_make_position("SIMH3", "acao", "BRL", 0.10)]  # only rv_br positions
    )
    divergences = check_buckets(portfolio, target_bucket="rv_eua", threshold=0.05)
    assert divergences == 0


def test_stored_irr_none_skips_comparison(capsys):
    """When stored_irr is None the comparison is skipped without crash."""
    positions = [_make_position("X1", "acao", "BRL", 0.10)]
    portfolio = _make_portfolio({}, positions)  # no rv_br in per_class
    # rv_br exists in positions but not in per_class → stored_irr = None
    divergences = check_buckets(portfolio, target_bucket="rv_br", threshold=0.05)
    assert divergences == 0


def test_all_buckets_checked_when_no_target(capsys):
    """No --bucket: all 5 standard buckets are processed without crash."""
    positions = [
        _make_position("SIMH3", "acao", "BRL", 0.08),
    ]
    per_class = {
        "rv_br": 0.08, "rv_eua": 0.15, "rf_balcao": 0.11, "fundos": 0.14, "crypto": 0.35
    }
    portfolio = _make_portfolio(per_class, positions)
    # Should not raise; returns divergence count
    result = check_buckets(portfolio, target_bucket=None, threshold=0.05)
    assert isinstance(result, int)


def test_informational_bucket_reported_but_not_counted(capsys):
    """A bucket in informational_buckets prints its divergence but returns 0."""
    positions = [_make_position("BAD1", "acao", "BRL", 1.00)]  # 100% vs stored 10%
    portfolio = _make_portfolio({"rv_br": 0.10}, positions)
    divergences = check_buckets(portfolio, target_bucket="rv_br", threshold=0.05,
                                informational_buckets={"rv_br"})
    assert divergences == 0
    out = capsys.readouterr().out
    assert "DIVERGENCE (informational — not counted)" in out


def test_informational_default_is_none_and_counts(capsys):
    """Without informational_buckets the same divergence counts (default unchanged)."""
    positions = [_make_position("BAD1", "acao", "BRL", 1.00)]
    portfolio = _make_portfolio({"rv_br": 0.10}, positions)
    divergences = check_buckets(portfolio, target_bucket="rv_br", threshold=0.05)
    assert divergences == 1
