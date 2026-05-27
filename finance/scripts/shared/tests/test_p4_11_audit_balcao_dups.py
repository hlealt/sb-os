"""Regression tests for p4-11: audit_balcao_dups read tool.

Verifies:
  1. Cross-source duplicates are detected (same date/op/amount, different source).
  2. Same-source rows with identical key are NOT flagged as duplicates.
  3. --product-id filter narrows to that asset only.
  4. No duplicates returns empty dict.
  5. Multiple assets each with duplicates are reported independently.
  6. Missing balcao.csv exits 1 gracefully.
  7. Amount rounding (2 decimal places) correctly groups rows.
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

from audit_balcao_dups import find_duplicate_groups, audit  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(pid: str, date: str, op: str, amount: str, source: str) -> dict:
    return {
        "product_id": pid,
        "date": date,
        "operation": op,
        "amount": amount,
        "source": source,
    }


def _write_balcao(path: Path, rows: list[dict]) -> None:
    fieldnames = ["product_id", "date", "operation", "amount", "source",
                  "product_type", "quantity", "irrf", "iof", "broker"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


# ---------------------------------------------------------------------------
# Tests: find_duplicate_groups
# ---------------------------------------------------------------------------

def test_cross_source_dup_detected():
    """Same (date, op, amount) across two different sources → 1 group."""
    rows = [
        _row("cra_test", "2024-01-15", "juros", "500.00", "b3"),
        _row("cra_test", "2024-01-15", "juros", "500.00", "safra_movimentacoes"),
    ]
    result = find_duplicate_groups(rows, product_id=None)
    assert "cra_test" in result
    assert len(result["cra_test"]) == 1


def test_same_source_not_flagged():
    """Two identical rows from same source are NOT cross-source dups."""
    rows = [
        _row("cra_test", "2024-01-15", "juros", "500.00", "safra_movimentacoes"),
        _row("cra_test", "2024-01-15", "juros", "500.00", "safra_movimentacoes"),
    ]
    result = find_duplicate_groups(rows, product_id=None)
    assert "cra_test" not in result


def test_product_id_filter():
    """--product-id narrows to that asset; other assets not included."""
    rows = [
        _row("asset_a", "2024-01-15", "juros", "100.00", "b3"),
        _row("asset_a", "2024-01-15", "juros", "100.00", "safra_movimentacoes"),
        _row("asset_b", "2024-01-15", "amortizacao", "200.00", "b3"),
        _row("asset_b", "2024-01-15", "amortizacao", "200.00", "safra_movimentacoes"),
    ]
    result = find_duplicate_groups(rows, product_id="asset_a")
    assert "asset_a" in result
    assert "asset_b" not in result


def test_no_duplicates_returns_empty():
    """Clean data: no cross-source dups → empty dict."""
    rows = [
        _row("cra_test", "2024-01-15", "juros", "500.00", "safra_movimentacoes"),
        _row("cra_test", "2024-02-15", "juros", "500.00", "safra_movimentacoes"),
    ]
    result = find_duplicate_groups(rows, product_id=None)
    assert result == {}


def test_amount_rounding_groups_correctly():
    """500.001 and 500.00 round to same key → treated as dup."""
    rows = [
        _row("cra_test", "2024-01-15", "juros", "500.001", "b3"),
        _row("cra_test", "2024-01-15", "juros", "500.00", "safra_movimentacoes"),
    ]
    result = find_duplicate_groups(rows, product_id=None)
    assert "cra_test" in result


def test_multiple_assets_independent():
    """Multiple assets can each have separate dup groups."""
    rows = [
        _row("asset_a", "2024-01-01", "juros", "100.00", "b3"),
        _row("asset_a", "2024-01-01", "juros", "100.00", "safra_movimentacoes"),
        _row("asset_b", "2024-01-01", "amortizacao", "300.00", "b3_manual"),
        _row("asset_b", "2024-01-01", "amortizacao", "300.00", "safra_movimentacoes"),
    ]
    result = find_duplicate_groups(rows, product_id=None)
    assert "asset_a" in result
    assert "asset_b" in result


# ---------------------------------------------------------------------------
# Integration: audit() with real files
# ---------------------------------------------------------------------------

def test_missing_balcao_exits_1(tmp_path):
    """audit() returns exit code 1 when balcao.csv is missing."""
    exit_code = audit(tmp_path, product_id=None)
    assert exit_code == 1


def test_audit_clean_exits_0(tmp_path):
    """audit() returns 0 when no duplicates found."""
    _write_balcao(tmp_path / "balcao.csv", [
        _row("cra_test", "2024-01-15", "juros", "500.00", "safra_movimentacoes"),
    ])
    exit_code = audit(tmp_path, product_id=None)
    assert exit_code == 0


def test_audit_with_dups_exits_1(tmp_path, capsys):
    """audit() returns 1 when duplicates are found."""
    _write_balcao(tmp_path / "balcao.csv", [
        _row("cra_test", "2024-01-15", "juros", "500.00", "b3"),
        _row("cra_test", "2024-01-15", "juros", "500.00", "safra_movimentacoes"),
    ])
    exit_code = audit(tmp_path, product_id=None)
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "cra_test" in out
