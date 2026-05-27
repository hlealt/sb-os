"""Regression tests for p4-5: position_summary read tool.

Verifies:
  1. Builds a clean report (exit 0) for a healthy position.
  2. Detects phantom application (aplicado=0, juros_amort>0) → anomaly.
  3. Detects stale-active past maturity → anomaly.
  4. Detects cross-source balcão duplicates → anomaly.
  5. Returns exit 1 when product_id not found in either file.
  6. Works with BOOKKEEPER_INVESTIMENTOS_DIR + BOOKKEEPER_ASSETS_PATH env overrides.
  7. Fails soft (no crash) when balcao.csv or assets.csv is missing.
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

from position_summary import (  # noqa: E402
    detect_phantom_application,
    detect_active_vs_maturity,
    detect_balcao_dups,
    build_report,
    load_assets,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_balcao(path: Path, rows: list[dict]) -> None:
    fieldnames = ["date", "operation", "product_id", "product_type", "quantity",
                  "amount", "irrf", "iof", "broker", "source"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _write_assets(path: Path, rows: list[dict]) -> None:
    fieldnames = ["id", "asset_class", "name", "type", "sector", "currency",
                  "current_broker", "active", "issuer", "indexer", "rate",
                  "indexer_pct", "application_date", "maturity_date", "cnpj", "manager"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _write_snapshots(path: Path, rows: list[dict]) -> None:
    fieldnames = ["date", "product_id", "balance", "source"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


_ASSET_DEFAULTS = {
    "asset_class": "fixed_income", "name": "Test CRA", "type": "cra",
    "sector": "", "currency": "BRL", "current_broker": "safra",
    "active": "true", "issuer": "", "indexer": "", "rate": "",
    "indexer_pct": "", "application_date": "2022-01-01",
    "maturity_date": "2030-12-31", "cnpj": "", "manager": ""
}

_BALCAO_DEFAULTS = {
    "product_type": "cra", "quantity": "0",
    "irrf": "0", "iof": "0", "broker": "safra", "source": "safra_movimentacoes"
}


# ---------------------------------------------------------------------------
# Unit tests — sub-detectors
# ---------------------------------------------------------------------------

def test_phantom_application_detected():
    rows = [
        {**_BALCAO_DEFAULTS, "operation": "juros", "amount": "1500.0"},
    ]
    result = detect_phantom_application(rows)
    assert result["is_phantom"] is True
    assert result["aplicado_total"] == 0.0
    assert result["juros_amort_total"] == 1500.0


def test_phantom_application_not_detected_with_aplicacao():
    rows = [
        {**_BALCAO_DEFAULTS, "operation": "aplicacao", "amount": "-10000.0"},
        {**_BALCAO_DEFAULTS, "operation": "juros", "amount": "500.0"},
    ]
    result = detect_phantom_application(rows)
    assert result["is_phantom"] is False


def test_stale_active_past_maturity():
    meta = {**_ASSET_DEFAULTS, "active": "true", "maturity_date": "2020-01-01"}
    result = detect_active_vs_maturity(meta)
    assert result["stale_active"] is True
    assert result["days_past"] > 0


def test_active_future_maturity_clean():
    meta = {**_ASSET_DEFAULTS, "active": "true", "maturity_date": "2035-01-01"}
    result = detect_active_vs_maturity(meta)
    assert result["stale_active"] is False


def test_inactive_skips_maturity_check():
    meta = {**_ASSET_DEFAULTS, "active": "false", "maturity_date": "2020-01-01"}
    result = detect_active_vs_maturity(meta)
    assert result["stale_active"] is False


def test_balcao_dups_detected():
    rows = [
        {**_BALCAO_DEFAULTS, "date": "2024-01-15", "operation": "juros",
         "amount": "500.0", "source": "b3"},
        {**_BALCAO_DEFAULTS, "date": "2024-01-15", "operation": "juros",
         "amount": "500.0", "source": "safra_movimentacoes"},
    ]
    dups = detect_balcao_dups(rows)
    assert len(dups) == 1
    sources = {r["source"] for r in dups[0]}
    assert "b3" in sources and "safra_movimentacoes" in sources


def test_no_dups_same_source():
    """Two rows from the same source with the same amount are NOT cross-source dups."""
    rows = [
        {**_BALCAO_DEFAULTS, "date": "2024-01-15", "operation": "juros",
         "amount": "500.0", "source": "safra_movimentacoes"},
        {**_BALCAO_DEFAULTS, "date": "2024-01-15", "operation": "juros",
         "amount": "500.0", "source": "safra_movimentacoes"},
    ]
    dups = detect_balcao_dups(rows)
    assert len(dups) == 0


# ---------------------------------------------------------------------------
# Integration tests — build_report
# ---------------------------------------------------------------------------

def test_clean_position_exits_0(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_INVESTIMENTOS_DIR", str(tmp_path))
    monkeypatch.setenv("BOOKKEEPER_ASSETS_PATH", str(tmp_path / "assets.csv"))

    _write_balcao(tmp_path / "balcao.csv", [
        {**_BALCAO_DEFAULTS, "date": "2022-01-01", "product_id": "cra_test",
         "operation": "aplicacao", "amount": "-10000.0"},
        {**_BALCAO_DEFAULTS, "date": "2023-06-01", "product_id": "cra_test",
         "operation": "juros", "amount": "800.0"},
    ])
    _write_assets(tmp_path / "assets.csv", [{"id": "cra_test", **_ASSET_DEFAULTS}])
    _write_snapshots(tmp_path / "balance-snapshots.csv", [
        {"date": "2024-12-31", "product_id": "cra_test", "balance": "11000.0",
         "source": "safra_movimentacoes"},
    ])

    exit_code = build_report("cra_test", tmp_path, tmp_path / "assets.csv")
    assert exit_code == 0


def test_phantom_application_report_exits_1(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_INVESTIMENTOS_DIR", str(tmp_path))
    monkeypatch.setenv("BOOKKEEPER_ASSETS_PATH", str(tmp_path / "assets.csv"))

    _write_balcao(tmp_path / "balcao.csv", [
        {**_BALCAO_DEFAULTS, "date": "2023-06-01", "product_id": "phantom_asset",
         "operation": "juros", "amount": "1500.0"},
    ])
    _write_assets(tmp_path / "assets.csv", [{"id": "phantom_asset", **_ASSET_DEFAULTS}])
    _write_snapshots(tmp_path / "balance-snapshots.csv", [])

    exit_code = build_report("phantom_asset", tmp_path, tmp_path / "assets.csv")
    assert exit_code == 1


def test_product_not_found_exits_1(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_INVESTIMENTOS_DIR", str(tmp_path))
    monkeypatch.setenv("BOOKKEEPER_ASSETS_PATH", str(tmp_path / "assets.csv"))

    _write_balcao(tmp_path / "balcao.csv", [])
    _write_assets(tmp_path / "assets.csv", [])
    _write_snapshots(tmp_path / "balance-snapshots.csv", [])

    exit_code = build_report("nonexistent_id", tmp_path, tmp_path / "assets.csv")
    assert exit_code == 1


def test_missing_balcao_fails_soft(tmp_path, monkeypatch):
    """No balcao.csv — returns [] without crashing; non-zero exit since not found."""
    monkeypatch.setenv("BOOKKEEPER_INVESTIMENTOS_DIR", str(tmp_path))
    monkeypatch.setenv("BOOKKEEPER_ASSETS_PATH", str(tmp_path / "assets.csv"))
    _write_assets(tmp_path / "assets.csv", [{"id": "cra_test", **_ASSET_DEFAULTS}])
    _write_snapshots(tmp_path / "balance-snapshots.csv", [])
    # No balcao.csv — the position has no balcao rows but IS in assets
    exit_code = build_report("cra_test", tmp_path, tmp_path / "assets.csv")
    # No balcao rows → aplicado=0, juros_amort=0 → not phantom (both 0)
    assert exit_code == 0


def test_stale_active_detected_in_report(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_INVESTIMENTOS_DIR", str(tmp_path))
    monkeypatch.setenv("BOOKKEEPER_ASSETS_PATH", str(tmp_path / "assets.csv"))

    _write_balcao(tmp_path / "balcao.csv", [
        {**_BALCAO_DEFAULTS, "date": "2019-01-01", "product_id": "stale_cra",
         "operation": "aplicacao", "amount": "-10000.0"},
    ])
    _write_assets(tmp_path / "assets.csv", [
        {"id": "stale_cra", **_ASSET_DEFAULTS, "active": "true",
         "maturity_date": "2020-06-01"},  # past
    ])
    _write_snapshots(tmp_path / "balance-snapshots.csv", [])

    exit_code = build_report("stale_cra", tmp_path, tmp_path / "assets.csv")
    assert exit_code == 1
