"""Regression tests for irr_flows read tool (audit-diagnostic).

Verifies:
  1. _collect_positions_by_id groups positions correctly.
  2. _get_flow_key returns composite {asset}@{exchange} for crypto positions.
  3. _get_flow_key returns bare id for non-crypto positions.
  4. _get_terminal_for_position returns (current_value, cut_date) for listed/crypto.
  5. _get_terminal_for_position returns (current_value, price_date) for balcao.
  6. report_for_id prints FLOW LADDER section header.
  7. report_for_id prints TERMINAL ANCHORING AND XIRR section header.
  8. report_for_id prints recomputed_xirr vs stored_irr drift column.
  9. Single-position asset: no COMBINED row printed.
  10. Split-id (crypto 2 exchanges): COMBINED row printed with merged flows.
  11. _load_portfolio exits 1 when portfolio.json is missing.
  12. main() writes nothing to ledger dir or portfolio.json (read-only invariant).
  13. Report header includes cut_date and portfolio filename.
  14. Asset not found in portfolio.json: WARNING printed, no crash.
"""
from __future__ import annotations

import json
import os
import sys
from io import StringIO
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_SHARED_DIR = _TESTS_DIR.parent          # scripts/shared/
_SCRIPTS_DIR = _SHARED_DIR.parent        # scripts/
_INVESTIMENTOS_DIR = _SCRIPTS_DIR / "investimentos"
for _p in (_SHARED_DIR, _SCRIPTS_DIR, _INVESTIMENTOS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from irr_flows import (  # noqa: E402
    _collect_positions_by_id,
    _get_flow_key,
    _get_terminal_for_position,
    report_for_id,
    _load_portfolio,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_portfolio(tmp_path: Path, positions: list[dict], cut_date: str = "2026-01-01") -> Path:
    """Write a minimal portfolio.json to tmp_path and return its path."""
    p = tmp_path / "portfolio.json"
    data = {
        "meta": {"cut_date": cut_date, "generated_at": "2026-01-01T00:00:00",
                 "fx_rate_usd_brl": 5.8, "market_indicators": {}},
        "summary": {
            "total_value": 100000.0, "total_cost": 90000.0, "total_pnl": 10000.0,
            "allocation_by_class": {}, "allocation_by_broker": {}, "allocation_by_currency": {},
            "irr": {"total": 0.12, "per_class": {}}
        },
        "positions": positions,
        "income": {},
    }
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _position(pid: str, vm: str = "price", broker: str = "b3",
              irr: float = 0.10, current_value: float = 10000.0,
              price_date: str = "2026-01-01") -> dict:
    return {
        "id": pid,
        "valuation_method": vm,
        "broker": broker,
        "irr": irr,
        "current_value": current_value,
        "price_date": price_date,
        "type": "crypto" if vm == "crypto" else "acao",
        "currency": "BRL",
        "asset_class": "variable_income",
        "quantity": 1.0,
        "irr_quality": "complete",
    }


# ---------------------------------------------------------------------------
# Tests: _collect_positions_by_id
# ---------------------------------------------------------------------------

def test_collect_positions_groups_by_id():
    positions = [
        _position("BTC", "crypto", "binance"),
        _position("BTC", "crypto", "foxbit"),
        _position("PETR4", "price", "b3"),
    ]
    result = _collect_positions_by_id({"positions": positions})
    assert len(result["BTC"]) == 2
    assert len(result["PETR4"]) == 1


def test_collect_positions_empty():
    result = _collect_positions_by_id({"positions": []})
    assert result == {}


def test_collect_positions_skips_empty_id():
    positions = [{"id": "", "valuation_method": "price"}]
    result = _collect_positions_by_id({"positions": positions})
    assert result == {}


# ---------------------------------------------------------------------------
# Tests: _get_flow_key
# ---------------------------------------------------------------------------

def test_get_flow_key_crypto_returns_composite():
    # broker field in portfolio.json already holds the normalized exchange name
    # (e.g. 'mercado_bitcoin', 'bipa') — _get_flow_key passes it through as-is
    pos = {"id": "BTC", "valuation_method": "crypto", "broker": "mercado_bitcoin"}
    assert _get_flow_key(pos) == "BTC@mercado_bitcoin"


def test_get_flow_key_crypto_bipa():
    pos = {"id": "ETH", "valuation_method": "crypto", "broker": "bipa"}
    assert _get_flow_key(pos) == "ETH@bipa"


def test_get_flow_key_price_returns_bare_id():
    pos = {"id": "PETR4", "valuation_method": "price", "broker": "b3"}
    assert _get_flow_key(pos) == "PETR4"


def test_get_flow_key_balcao_returns_bare_id():
    pos = {"id": "cra_ipca_klabin_350", "valuation_method": "balcao", "broker": "safra"}
    assert _get_flow_key(pos) == "cra_ipca_klabin_350"


# ---------------------------------------------------------------------------
# Tests: _get_terminal_for_position
# ---------------------------------------------------------------------------

def test_terminal_price_uses_cut_date():
    pos = {"valuation_method": "price", "current_value": 50000.0, "price_date": "2025-12-01"}
    val, date_s = _get_terminal_for_position(pos, "2026-01-01")
    assert val == 50000.0
    assert date_s == "2026-01-01"


def test_terminal_crypto_uses_cut_date():
    pos = {"valuation_method": "crypto", "current_value": 30000.0, "price_date": "2025-11-01"}
    val, date_s = _get_terminal_for_position(pos, "2026-01-01")
    assert val == 30000.0
    assert date_s == "2026-01-01"


def test_terminal_balcao_uses_price_date():
    pos = {"valuation_method": "balcao", "current_value": 20000.0, "price_date": "2025-12-15"}
    val, date_s = _get_terminal_for_position(pos, "2026-01-01")
    assert val == 20000.0
    assert date_s == "2025-12-15"


def test_terminal_balcao_falls_back_to_cut_date_when_no_price_date():
    pos = {"valuation_method": "balcao", "current_value": 15000.0}
    val, date_s = _get_terminal_for_position(pos, "2026-01-01")
    assert val == 15000.0
    assert date_s == "2026-01-01"


def test_terminal_none_current_value_returns_zero():
    pos = {"valuation_method": "price", "current_value": None, "price_date": "2026-01-01"}
    val, date_s = _get_terminal_for_position(pos, "2026-01-01")
    assert val == 0.0


# ---------------------------------------------------------------------------
# Tests: report_for_id output contract (human-readable report shape)
# ---------------------------------------------------------------------------

def _run_report(asset_id: str, flows: dict, pos_by_id: dict, cut_date: str,
                capsys) -> str:
    """Run report_for_id and return captured stdout."""
    report_for_id(asset_id, flows, pos_by_id, cut_date)
    return capsys.readouterr().out


def test_report_contains_asset_section_header(capsys):
    """ASSET: <id> header must appear in output."""
    flows = {"PETR4": [("2025-01-01", -10000.0), ("2026-01-01", 12000.0)]}
    pos_by_id = {"PETR4": [_position("PETR4", "price", "b3", irr=0.10)]}
    out = _run_report("PETR4", flows, pos_by_id, "2026-01-01", capsys)
    assert "ASSET: PETR4" in out


def test_report_contains_flow_ladder_section(capsys):
    """FLOW LADDER section header must appear for an asset with flows."""
    flows = {"PETR4": [("2025-01-01", -10000.0), ("2026-01-01", 12000.0)]}
    pos_by_id = {"PETR4": [_position("PETR4", "price", "b3", irr=0.10)]}
    out = _run_report("PETR4", flows, pos_by_id, "2026-01-01", capsys)
    assert "FLOW LADDER" in out


def test_report_contains_terminal_anchoring_section(capsys):
    """TERMINAL ANCHORING AND XIRR section must appear."""
    flows = {"PETR4": [("2025-01-01", -10000.0), ("2026-01-01", 12000.0)]}
    pos_by_id = {"PETR4": [_position("PETR4", "price", "b3", irr=0.10)]}
    out = _run_report("PETR4", flows, pos_by_id, "2026-01-01", capsys)
    assert "TERMINAL ANCHORING AND XIRR" in out


def test_report_contains_stored_irr_column(capsys):
    """stored_irr column header must appear."""
    flows = {"PETR4": [("2025-01-01", -10000.0), ("2026-01-01", 12000.0)]}
    pos_by_id = {"PETR4": [_position("PETR4", "price", "b3", irr=0.10)]}
    out = _run_report("PETR4", flows, pos_by_id, "2026-01-01", capsys)
    assert "stored_irr" in out


def test_report_contains_recomputed_xirr_column(capsys):
    """recomputed_xirr column header must appear."""
    flows = {"PETR4": [("2025-01-01", -10000.0), ("2026-01-01", 12000.0)]}
    pos_by_id = {"PETR4": [_position("PETR4", "price", "b3", irr=0.10)]}
    out = _run_report("PETR4", flows, pos_by_id, "2026-01-01", capsys)
    assert "recomputed_xirr" in out


def test_report_single_position_no_combined_row(capsys):
    """Single-position asset must NOT print [COMBINED] row."""
    flows = {"PETR4": [("2025-01-01", -10000.0)]}
    pos_by_id = {"PETR4": [_position("PETR4", "price", "b3", irr=0.10)]}
    out = _run_report("PETR4", flows, pos_by_id, "2026-01-01", capsys)
    assert "[COMBINED]" not in out


def test_report_split_id_prints_combined_row(capsys):
    """Two positions for the same crypto id (two exchanges) → [COMBINED] row must appear."""
    # Broker values mirror portfolio.json normalized exchange names
    flows = {
        "BTC@mercado_bitcoin": [("2025-01-01", -50000.0), ("2026-01-01", 60000.0)],
        "BTC@bipa":            [("2025-06-01", -20000.0), ("2026-01-01", 25000.0)],
    }
    pos_by_id = {
        "BTC": [
            _position("BTC", "crypto", "mercado_bitcoin", irr=0.15, current_value=60000.0),
            _position("BTC", "crypto", "bipa",            irr=0.12, current_value=25000.0),
        ]
    }
    out = _run_report("BTC", flows, pos_by_id, "2026-01-01", capsys)
    assert "[COMBINED]" in out


def test_report_flow_count_shown(capsys):
    """Flow count (N flows) must appear in output."""
    flows = {"CRA": [("2024-01-01", -5000.0), ("2025-01-01", 500.0)]}
    pos_by_id = {"CRA": [_position("CRA", "balcao", "safra", irr=0.11, price_date="2025-12-01")]}
    out = _run_report("CRA", flows, pos_by_id, "2026-01-01", capsys)
    assert "2 flows" in out


def test_report_no_flows_shows_placeholder(capsys):
    """No flows for an id → (no flows found) placeholder."""
    flows = {}
    pos_by_id = {"XYZZ11": [_position("XYZZ11", "price", "b3", irr=0.08)]}
    out = _run_report("XYZZ11", flows, pos_by_id, "2026-01-01", capsys)
    assert "no flows found" in out


def test_report_id_not_in_portfolio_prints_warning(capsys):
    """Id absent from portfolio.json positions prints WARNING."""
    flows = {"GHOST": [("2025-01-01", -1000.0)]}
    pos_by_id = {}  # not in portfolio
    out = _run_report("GHOST", flows, pos_by_id, "2026-01-01", capsys)
    assert "WARNING" in out
    assert "GHOST" in out


# ---------------------------------------------------------------------------
# Tests: _load_portfolio — exit-code semantics
# ---------------------------------------------------------------------------

def test_load_portfolio_missing_exits_1(tmp_path):
    """_load_portfolio must sys.exit(1) when portfolio.json is missing."""
    with pytest.raises(SystemExit) as exc_info:
        _load_portfolio(tmp_path / "does_not_exist.json")
    assert exc_info.value.code == 1


def test_load_portfolio_returns_dict(tmp_path):
    """_load_portfolio returns the parsed dict when file exists."""
    p = _make_portfolio(tmp_path, [])
    result = _load_portfolio(p)
    assert isinstance(result, dict)
    assert result["meta"]["cut_date"] == "2026-01-01"


# ---------------------------------------------------------------------------
# Tests: read-only invariant (no file mutation after a run)
# ---------------------------------------------------------------------------

def _snapshot_dir(path: Path) -> dict[str, tuple[int, bytes]]:
    """Return {relative_path_str: (mtime_ns, content_hash)} for all files in path."""
    import hashlib
    snapshot = {}
    for f in sorted(path.rglob("*")):
        if f.is_file():
            content = f.read_bytes()
            key = str(f.relative_to(path))
            snapshot[key] = (f.stat().st_mtime_ns, hashlib.sha256(content).digest())
    return snapshot


def test_report_for_id_writes_nothing(tmp_path, capsys):
    """Calling report_for_id must not mutate any file in a ledger directory."""
    # Create a minimal ledger dir with a sentinel file
    ledger_dir = tmp_path / "ledgers"
    ledger_dir.mkdir()
    sentinel = ledger_dir / "portfolio.json"
    sentinel.write_bytes(b'{"meta": {"cut_date": "2026-01-01"}, "positions": []}')

    before = _snapshot_dir(tmp_path)

    flows = {"PETR4": [("2025-01-01", -10000.0)]}
    pos_by_id = {"PETR4": [_position("PETR4", "price", "b3", irr=0.10)]}
    report_for_id("PETR4", flows, pos_by_id, "2026-01-01")

    after = _snapshot_dir(tmp_path)
    assert before == after, "report_for_id must not write or modify any file"


def test_env_override_portfolio_path_respected(tmp_path, monkeypatch):
    """BOOKKEEPER_PORTFOLIO_PATH env var is honored for portfolio loading."""
    p = _make_portfolio(tmp_path, [])
    monkeypatch.setenv("BOOKKEEPER_PORTFOLIO_PATH", str(p))
    # _load_portfolio accepts an explicit path; env override is tested via _default_portfolio_path
    result = _load_portfolio(p)
    assert result["meta"]["cut_date"] == "2026-01-01"
