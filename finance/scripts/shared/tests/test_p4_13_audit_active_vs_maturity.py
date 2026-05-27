"""Regression tests for p4-13: audit_active_vs_maturity read tool.

Verifies:
  1. Asset with active=true and maturity_date in the past → stale-active.
  2. Asset with active=true and future maturity_date → NOT stale-active.
  3. Asset with active=false and no maturity_date → NOT stale-active.
  4. Stale-inactive detected when active=false but recent balcao rows exist.
  5. Stale-inactive NOT triggered when last balcao row is beyond activity_days.
  6. Assets with no maturity_date are skipped for stale-active (e.g. equities).
  7. audit() returns 0 when no anomalies, 1 when anomalies found.
  8. audit() returns 1 when assets.csv is missing.
"""
from __future__ import annotations

import csv
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
_INVESTIMENTOS_DIR = _SCRIPTS_DIR / "investimentos"
for _p in (_SCRIPTS_DIR, _INVESTIMENTOS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from audit_active_vs_maturity import (  # noqa: E402
    detect_stale_active,
    detect_stale_inactive,
    audit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TODAY = date.today()
_PAST = (_TODAY - timedelta(days=30)).strftime("%Y-%m-%d")
_FUTURE = (_TODAY + timedelta(days=365)).strftime("%Y-%m-%d")
_RECENT = (_TODAY - timedelta(days=10)).strftime("%Y-%m-%d")
_OLD = (_TODAY - timedelta(days=200)).strftime("%Y-%m-%d")


def _asset(pid: str, active: str, maturity_date: str = "") -> dict:
    return {"id": pid, "name": f"Test {pid}", "active": active,
            "maturity_date": maturity_date}


def _balcao_row(pid: str, date_str: str) -> dict:
    return {"product_id": pid, "date": date_str, "operation": "juros",
            "amount": "100.0", "source": "safra_movimentacoes"}


def _write_assets(path: Path, rows: list[dict]) -> None:
    fieldnames = ["id", "name", "active", "maturity_date"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _write_balcao(path: Path, rows: list[dict]) -> None:
    fieldnames = ["product_id", "date", "operation", "amount", "source"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


# ---------------------------------------------------------------------------
# Unit tests: detect_stale_active
# ---------------------------------------------------------------------------

def test_stale_active_past_maturity_detected():
    """active=true, maturity in past → stale-active."""
    assets = [_asset("cra_a", "true", _PAST)]
    result = detect_stale_active(assets, _TODAY)
    assert len(result) == 1
    assert result[0]["product_id"] == "cra_a"
    assert result[0]["days_past_maturity"] >= 30


def test_active_future_maturity_clean():
    """active=true, maturity in future → not stale."""
    assets = [_asset("cra_b", "true", _FUTURE)]
    result = detect_stale_active(assets, _TODAY)
    assert result == []


def test_inactive_asset_not_stale_active():
    """active=false → skip stale-active check."""
    assets = [_asset("cra_c", "false", _PAST)]
    result = detect_stale_active(assets, _TODAY)
    assert result == []


def test_no_maturity_date_skipped():
    """Asset with no maturity_date is skipped (e.g. equities)."""
    assets = [_asset("acao_d", "true", "")]
    result = detect_stale_active(assets, _TODAY)
    assert result == []


# ---------------------------------------------------------------------------
# Unit tests: detect_stale_inactive
# ---------------------------------------------------------------------------

def test_stale_inactive_detected_recent_activity():
    """active=false but recent balcao row → stale-inactive."""
    assets = [_asset("cra_e", "false")]
    balcao = [_balcao_row("cra_e", _RECENT)]
    result = detect_stale_inactive(assets, balcao, _TODAY, activity_days=90)
    assert len(result) == 1
    assert result[0]["product_id"] == "cra_e"


def test_stale_inactive_not_triggered_old_activity():
    """active=false and last row beyond activity_days → not stale-inactive."""
    assets = [_asset("cra_f", "false")]
    balcao = [_balcao_row("cra_f", _OLD)]
    result = detect_stale_inactive(assets, balcao, _TODAY, activity_days=90)
    assert result == []


def test_stale_inactive_requires_balcao():
    """With no balcao rows, stale-inactive check returns empty."""
    assets = [_asset("cra_g", "false")]
    result = detect_stale_inactive(assets, [], _TODAY, activity_days=90)
    assert result == []


# ---------------------------------------------------------------------------
# Integration: audit()
# ---------------------------------------------------------------------------

def test_audit_missing_assets_exits_1(tmp_path):
    exit_code = audit(tmp_path / "assets.csv", tmp_path, activity_days=90)
    assert exit_code == 1


def test_audit_clean_data_exits_0(tmp_path):
    assets_path = tmp_path / "assets.csv"
    _write_assets(assets_path, [
        _asset("cra_ok", "true", _FUTURE)
    ])
    _write_balcao(tmp_path / "balcao.csv", [])
    exit_code = audit(assets_path, tmp_path, activity_days=90)
    assert exit_code == 0


def test_audit_stale_active_exits_1(tmp_path, capsys):
    assets_path = tmp_path / "assets.csv"
    _write_assets(assets_path, [_asset("cra_stale", "true", _PAST)])
    _write_balcao(tmp_path / "balcao.csv", [])
    exit_code = audit(assets_path, tmp_path, activity_days=90)
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "cra_stale" in out
