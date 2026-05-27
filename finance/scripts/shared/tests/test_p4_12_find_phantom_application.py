"""Regression tests for p4-12: find_phantom_application read tool.

Verifies:
  1. Position with juros_amort>0 and aplicado=0 is flagged as phantom.
  2. Position with aplicado>0 is NOT flagged.
  3. Position with both juros_amort=0 and aplicado=0 is NOT flagged.
  4. compute_per_product_totals aggregates multiple rows correctly.
  5. detect_phantoms enriches with asset metadata when available.
  6. detect_phantoms handles product_id not in assets gracefully.
  7. audit() returns 0 for clean data and 1 for phantoms.
  8. audit() returns 1 when balcao.csv is missing.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
_INVESTIMENTOS_DIR = _SCRIPTS_DIR / "investimentos"
for _p in (_SCRIPTS_DIR, _INVESTIMENTOS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from find_phantom_application import (  # noqa: E402
    compute_per_product_totals,
    detect_phantoms,
    audit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _balcao_row(pid: str, op: str, amount: str) -> dict:
    return {"product_id": pid, "operation": op, "amount": amount, "date": "2024-01-15"}


def _write_balcao(path: Path, rows: list[dict]) -> None:
    fieldnames = ["product_id", "operation", "amount", "date",
                  "product_type", "quantity", "irrf", "iof", "broker", "source"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _write_assets(path: Path, rows: list[dict]) -> None:
    fieldnames = ["id", "name", "type", "active", "application_date", "maturity_date"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


# ---------------------------------------------------------------------------
# Unit tests: compute_per_product_totals
# ---------------------------------------------------------------------------

def test_phantom_totals_detected():
    rows = [
        _balcao_row("cra_ghost", "juros", "1500.0"),
        _balcao_row("cra_ghost", "amortizacao", "500.0"),
    ]
    totals = compute_per_product_totals(rows)
    assert totals["cra_ghost"]["aplicado_total"] == 0.0
    assert totals["cra_ghost"]["juros_amort_total"] == 2000.0


def test_normal_position_not_phantom():
    rows = [
        _balcao_row("cra_normal", "aplicacao", "-10000.0"),
        _balcao_row("cra_normal", "juros", "800.0"),
    ]
    totals = compute_per_product_totals(rows)
    assert totals["cra_normal"]["aplicado_total"] == 10000.0
    assert totals["cra_normal"]["juros_amort_total"] == 800.0


def test_zero_income_not_flagged():
    """Position with no juros/amort AND no aplicacao is not phantom."""
    rows = [_balcao_row("cra_empty", "resgate", "-5000.0")]
    totals = compute_per_product_totals(rows)
    phantoms = detect_phantoms(totals, {})
    assert not any(p["product_id"] == "cra_empty" for p in phantoms)


# ---------------------------------------------------------------------------
# Unit tests: detect_phantoms
# ---------------------------------------------------------------------------

def test_detect_phantoms_flags_correctly():
    totals = {
        "cra_ghost": {"aplicado_total": 0.0, "juros_amort_total": 2000.0,
                      "first_date": "2024-01-15", "row_count": 2},
        "cra_normal": {"aplicado_total": 10000.0, "juros_amort_total": 800.0,
                       "first_date": "2022-01-01", "row_count": 5},
    }
    assets = {"cra_ghost": {"name": "Ghost CRA", "application_date": "2021-01-01"}}
    phantoms = detect_phantoms(totals, assets)
    assert len(phantoms) == 1
    assert phantoms[0]["product_id"] == "cra_ghost"
    assert phantoms[0]["asset_name"] == "Ghost CRA"


def test_detect_phantoms_handles_missing_asset():
    """Phantom not in assets.csv → shows '(not in assets.csv)' note."""
    totals = {
        "unknown_asset": {"aplicado_total": 0.0, "juros_amort_total": 500.0,
                          "first_date": "2024-01-01", "row_count": 1},
    }
    phantoms = detect_phantoms(totals, {})
    assert len(phantoms) == 1
    assert "not in assets.csv" in phantoms[0]["application_date"]


# ---------------------------------------------------------------------------
# Integration: audit()
# ---------------------------------------------------------------------------

def test_audit_missing_balcao_exits_1(tmp_path):
    assets_path = tmp_path / "assets.csv"
    _write_assets(assets_path, [])
    exit_code = audit(tmp_path, assets_path)
    assert exit_code == 1


def test_audit_clean_data_exits_0(tmp_path):
    _write_balcao(tmp_path / "balcao.csv", [
        _balcao_row("cra_ok", "aplicacao", "-10000.0"),
        _balcao_row("cra_ok", "juros", "500.0"),
    ])
    assets_path = tmp_path / "assets.csv"
    _write_assets(assets_path, [{"id": "cra_ok", "name": "OK", "type": "cra",
                                  "active": "true", "application_date": "2022-01-01",
                                  "maturity_date": "2030-01-01"}])
    exit_code = audit(tmp_path, assets_path)
    assert exit_code == 0


def test_audit_phantom_exits_1(tmp_path, capsys):
    _write_balcao(tmp_path / "balcao.csv", [
        _balcao_row("cra_ghost", "juros", "1500.0"),
    ])
    assets_path = tmp_path / "assets.csv"
    _write_assets(assets_path, [{"id": "cra_ghost", "name": "Ghost",
                                  "type": "cra", "active": "true",
                                  "application_date": "", "maturity_date": ""}])
    exit_code = audit(tmp_path, assets_path)
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "cra_ghost" in out
