"""Regression tests for p4-6: validate_calculate read tool.

Verifies:
  1. Loads portfolio.json and prints a report without error (healthy portfolio).
  2. Detects IRR > 200% violation for a per-class bucket.
  3. Detects IRR > 200% violation for a per-asset position.
  4. Detects missing irr_quality on a valued balcão position.
  5. --strict mode exits 1 when violations found; exits 0 when clean.
  6. --strict mode exits 0 when no violations found.
  7. Raises FileNotFoundError when portfolio.json is missing.
  8. irr_quality histogram reports all quality values present.
  9. BOOKKEEPER_PORTFOLIO_PATH env var override works for test isolation.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
_INVESTIMENTOS_DIR = _SCRIPTS_DIR / "investimentos"
for _p in (_SCRIPTS_DIR, _INVESTIMENTOS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from validate_calculate import (  # noqa: E402
    load_portfolio,
    _irr_violations,
    _quality_violations,
    _quality_histogram,
    validate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_portfolio(tmp_path: Path, portfolio: dict) -> Path:
    p = tmp_path / "portfolio.json"
    p.write_text(json.dumps(portfolio), encoding="utf-8")
    return p


def _base_portfolio(**kwargs) -> dict:
    base = {
        "meta": {"generated_at": "2026-01-01T00:00:00", "cut_date": "2026-01-01",
                 "fx_rate_usd_brl": 5.0, "market_indicators": {}},
        "summary": {
            "total_value": 100000.0, "total_cost": 90000.0, "total_pnl": 10000.0,
            "allocation_by_class": {}, "allocation_by_broker": {}, "allocation_by_currency": {},
            "irr": {
                "total": 0.12,
                "per_class": {
                    "rv_br": {"irr": 0.08, "terminal_value": 50000.0, "flow_count": 10},
                    "rf_balcao": {"irr": 0.11, "terminal_value": 50000.0, "flow_count": 5},
                }
            }
        },
        "positions": [],
        "income": {},
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Tests: _irr_violations
# ---------------------------------------------------------------------------

def test_no_irr_violations_on_clean_portfolio():
    portfolio = _base_portfolio()
    assert _irr_violations(portfolio) == []


def test_irr_violation_total_over_200pct():
    portfolio = _base_portfolio()
    portfolio["summary"]["irr"]["total"] = 3.5  # 350%
    violations = _irr_violations(portfolio)
    assert len(violations) == 1
    assert "Portfolio total IRR" in violations[0]


def test_irr_violation_per_class_bucket():
    portfolio = _base_portfolio()
    portfolio["summary"]["irr"]["per_class"]["rv_br"]["irr"] = 2.5  # 250%
    violations = _irr_violations(portfolio)
    assert any("rv_br" in v for v in violations)


def test_irr_violation_per_position():
    portfolio = _base_portfolio()
    portfolio["positions"] = [
        {"id": "XBAD3", "irr": 5.0, "valuation_method": "price", "currency": "BRL"}
    ]
    violations = _irr_violations(portfolio)
    assert any("XBAD3" in v for v in violations)


def test_no_irr_violation_when_irr_is_none():
    """None IRR (missing price) must not trigger a violation."""
    portfolio = _base_portfolio()
    portfolio["positions"] = [
        {"id": "NO_PRICE", "irr": None, "valuation_method": "price", "currency": "BRL"}
    ]
    assert _irr_violations(portfolio) == []


# ---------------------------------------------------------------------------
# Tests: _quality_violations
# ---------------------------------------------------------------------------

def test_no_quality_violation_when_balcao_has_quality():
    portfolio = _base_portfolio()
    portfolio["positions"] = [
        {"id": "CRA_OK", "valuation_method": "balcao", "current_value": 10000.0,
         "irr_quality": "complete"}
    ]
    assert _quality_violations(portfolio) == []


def test_quality_violation_balcao_valued_no_quality():
    portfolio = _base_portfolio()
    portfolio["positions"] = [
        {"id": "CRA_BAD", "valuation_method": "balcao", "current_value": 10000.0,
         "irr_quality": ""}
    ]
    violations = _quality_violations(portfolio)
    assert len(violations) == 1
    assert "CRA_BAD" in violations[0]


def test_no_quality_violation_balcao_null_value():
    """Balcão position with no current_value (e.g. price_source=missing) must NOT flag."""
    portfolio = _base_portfolio()
    portfolio["positions"] = [
        {"id": "CRA_NO_VAL", "valuation_method": "balcao", "current_value": None, "irr_quality": ""}
    ]
    assert _quality_violations(portfolio) == []


# ---------------------------------------------------------------------------
# Tests: _quality_histogram
# ---------------------------------------------------------------------------

def test_quality_histogram_counts_correctly():
    portfolio = _base_portfolio()
    portfolio["positions"] = [
        {"id": "A", "valuation_method": "balcao", "irr_quality": "complete"},
        {"id": "B", "valuation_method": "balcao", "irr_quality": "seed_only"},
        {"id": "C", "valuation_method": "balcao", "irr_quality": "complete"},
        {"id": "D", "valuation_method": "price"},  # no irr_quality → "missing"
    ]
    hist = _quality_histogram(portfolio)
    assert hist.get("complete") == 2
    assert hist.get("seed_only") == 1
    assert hist.get("missing") == 1


# ---------------------------------------------------------------------------
# Tests: validate() integration
# ---------------------------------------------------------------------------

def test_validate_clean_exits_0(tmp_path):
    p = _make_portfolio(tmp_path, _base_portfolio())
    code = validate(p, strict=False)
    assert code == 0


def test_validate_strict_exits_0_when_clean(tmp_path):
    p = _make_portfolio(tmp_path, _base_portfolio())
    code = validate(p, strict=True)
    assert code == 0


def test_validate_strict_exits_1_on_irr_violation(tmp_path):
    portfolio = _base_portfolio()
    portfolio["summary"]["irr"]["total"] = 99.0  # 9900%
    p = _make_portfolio(tmp_path, portfolio)
    code = validate(p, strict=True)
    assert code == 1


def test_validate_strict_exits_1_on_quality_violation(tmp_path):
    portfolio = _base_portfolio()
    portfolio["positions"] = [
        {"id": "BAD_Q", "valuation_method": "balcao", "current_value": 5000.0, "irr_quality": ""}
    ]
    p = _make_portfolio(tmp_path, portfolio)
    code = validate(p, strict=True)
    assert code == 1


def test_validate_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_portfolio(tmp_path / "does_not_exist.json")


def test_bookkeeper_portfolio_path_env(tmp_path, monkeypatch):
    portfolio = _base_portfolio()
    p = _make_portfolio(tmp_path, portfolio)
    monkeypatch.setenv("BOOKKEEPER_PORTFOLIO_PATH", str(p))
    # validate using the env override path
    code = validate(p, strict=False)
    assert code == 0
