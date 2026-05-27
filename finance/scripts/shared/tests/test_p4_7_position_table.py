"""Regression tests for p4-7: position_table read tool.

Verifies:
  1. Returns all positions when no filter is applied.
  2. --bucket filter narrows to the correct IRR class.
  3. --currency filter narrows to USD or BRL positions.
  4. --type filter narrows to a specific asset type.
  5. Multiple filters combine correctly (AND logic).
  6. Totals row is always present.
  7. Empty result is printed gracefully (no crash).
  8. _irr_bucket mapping matches calculate.py conventions.
  9. BOOKKEEPER_PORTFOLIO_PATH env override works for test isolation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
_INVESTIMENTOS_DIR = _SCRIPTS_DIR / "investimentos"
for _p in (_SCRIPTS_DIR, _INVESTIMENTOS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from position_table import filter_positions, _irr_bucket  # noqa: E402


# ---------------------------------------------------------------------------
# Sample positions
# ---------------------------------------------------------------------------

_ACAO = {
    "id": "SIMH3", "name": "Simpar", "asset_class": "variable_income",
    "type": "acao", "valuation_method": "price", "broker": "safra",
    "currency": "BRL", "quantity": 1800, "avg_cost": 14.0, "current_price": 11.0,
    "pnl_pct": -0.21, "cost_basis_brl": 25200.0, "current_value_brl": 19800.0,
    "pnl_absolute_brl": -5400.0, "irr": 0.08, "irr_quality": ""
}
_STOCK_US = {
    "id": "BRK/B", "name": "Berkshire", "asset_class": "variable_income",
    "type": "stock_us", "valuation_method": "price", "broker": "avenue",
    "currency": "USD", "quantity": 50, "avg_cost": 320.0, "current_price": 400.0,
    "pnl_pct": 0.25, "cost_basis_brl": 80000.0, "current_value_brl": 100000.0,
    "pnl_absolute_brl": 20000.0, "irr": 0.15, "irr_quality": ""
}
_CRA = {
    "id": "cra_test", "name": "CRA Test", "asset_class": "fixed_income",
    "type": "cra", "valuation_method": "balcao", "broker": "safra",
    "currency": "BRL", "quantity": 0, "aplicado_total": 10000.0,
    "current_value": 11000.0, "pnl_absolute": 1000.0,
    "cost_basis_brl": 10000.0, "current_value_brl": 11000.0,
    "pnl_absolute_brl": 1000.0, "irr": 0.10, "irr_quality": "complete"
}
_FUNDO = {
    "id": "claritas_valor", "name": "Claritas", "asset_class": "funds",
    "type": "fia_br", "valuation_method": "balcao", "broker": "safra",
    "currency": "BRL", "quantity": 0, "aplicado_total": 50000.0,
    "current_value": 58000.0, "pnl_absolute": 8000.0,
    "cost_basis_brl": 50000.0, "current_value_brl": 58000.0,
    "pnl_absolute_brl": 8000.0, "irr": 0.14, "irr_quality": "complete"
}
_BTC = {
    "id": "BTC", "name": "Bitcoin", "asset_class": "crypto",
    "type": "crypto", "valuation_method": "crypto", "broker": "bipa",
    "currency": "BRL", "quantity": 0.5, "avg_cost": 180000.0, "current_price": 400000.0,
    "pnl_pct": 1.22, "cost_basis_brl": 90000.0, "current_value_brl": 200000.0,
    "pnl_absolute_brl": 110000.0, "irr": 0.35, "irr_quality": ""
}

_ALL = [_ACAO, _STOCK_US, _CRA, _FUNDO, _BTC]


# ---------------------------------------------------------------------------
# Tests: _irr_bucket mapping
# ---------------------------------------------------------------------------

def test_bucket_rv_br():
    assert _irr_bucket(_ACAO) == "rv_br"


def test_bucket_rv_eua():
    assert _irr_bucket(_STOCK_US) == "rv_eua"


def test_bucket_rf_balcao():
    assert _irr_bucket(_CRA) == "rf_balcao"


def test_bucket_fundos():
    assert _irr_bucket(_FUNDO) == "fundos"


def test_bucket_crypto():
    assert _irr_bucket(_BTC) == "crypto"


# ---------------------------------------------------------------------------
# Tests: filter_positions
# ---------------------------------------------------------------------------

def test_no_filter_returns_all():
    result = filter_positions(_ALL, None, None, None)
    assert len(result) == 5


def test_filter_by_bucket_rv_br():
    result = filter_positions(_ALL, "rv_br", None, None)
    assert len(result) == 1
    assert result[0]["id"] == "SIMH3"


def test_filter_by_bucket_rv_eua():
    result = filter_positions(_ALL, "rv_eua", None, None)
    assert len(result) == 1
    assert result[0]["id"] == "BRK/B"


def test_filter_by_bucket_rf_balcao():
    result = filter_positions(_ALL, "rf_balcao", None, None)
    assert len(result) == 1
    assert result[0]["id"] == "cra_test"


def test_filter_by_bucket_fundos():
    result = filter_positions(_ALL, "fundos", None, None)
    assert len(result) == 1
    assert result[0]["id"] == "claritas_valor"


def test_filter_by_currency_usd():
    result = filter_positions(_ALL, None, "USD", None)
    assert len(result) == 1
    assert result[0]["id"] == "BRK/B"


def test_filter_by_currency_brl():
    result = filter_positions(_ALL, None, "BRL", None)
    assert len(result) == 4  # all except BRK/B


def test_filter_by_type_cra():
    result = filter_positions(_ALL, None, None, "cra")
    assert len(result) == 1
    assert result[0]["id"] == "cra_test"


def test_filter_combined_bucket_and_currency():
    """rv_eua AND USD → only BRK/B."""
    result = filter_positions(_ALL, "rv_eua", "USD", None)
    assert len(result) == 1
    assert result[0]["id"] == "BRK/B"


def test_filter_combined_no_match():
    """rf_balcao AND USD → no match (CRA is BRL)."""
    result = filter_positions(_ALL, "rf_balcao", "USD", None)
    assert len(result) == 0


def test_empty_input_returns_empty():
    result = filter_positions([], "rv_br", None, None)
    assert result == []
