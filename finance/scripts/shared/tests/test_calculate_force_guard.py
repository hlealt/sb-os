"""Regression tests for calculate.py --force guard (p1-4 / D14).

Contracts tested:
  P1-4-A  write_portfolio with cut_date on a NEW path → writes without --force
  P1-4-B  write_portfolio with cut_date on an EXISTING snapshot → raises SystemExit
           without force=True
  P1-4-C  write_portfolio with cut_date on an EXISTING snapshot + force=True → overwrites
  P1-4-D  write_portfolio without cut_date → never touches dated snapshot (immutability
           invariant: live portfolio.json is always rewritable)
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure the investimentos directory is importable.
# __file__ = shared/tests/test_calculate_force_guard.py
# parents[0] = shared/tests/
# parents[1] = shared/
# parents[2] = scripts/
_INVESTIMENTOS = Path(__file__).resolve().parents[2] / "investimentos"
if str(_INVESTIMENTOS) not in sys.path:
    sys.path.insert(0, str(_INVESTIMENTOS))


# ---------------------------------------------------------------------------
# Minimal portfolio fixture
# ---------------------------------------------------------------------------

def _minimal_portfolio() -> dict:
    return {
        "meta": {"generated_at": "2026-01-01T00:00:00", "cut_date": None},
        "summary": {"total_value": 0.0},
        "positions": [],
        "income": {},
    }


# ---------------------------------------------------------------------------
# P1-4-A: new snapshot path → write succeeds without force
# ---------------------------------------------------------------------------

def test_new_snapshot_written_without_force(tmp_path, monkeypatch):
    """When no prior snapshot exists, write_portfolio must succeed with force=False."""
    import calculate

    monkeypatch.setattr(calculate, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(calculate, "SNAPSHOTS_JSON", tmp_path / "snapshots.json")

    portfolio = _minimal_portfolio()
    calculate.write_portfolio(portfolio, cut_date="2025-12-31", force=False)

    assert (tmp_path / "portfolio-2025-12-31.json").exists()


# ---------------------------------------------------------------------------
# P1-4-B: existing snapshot + force=False → SystemExit(1)
# ---------------------------------------------------------------------------

def test_existing_snapshot_refuses_without_force(tmp_path, monkeypatch):
    """When a dated snapshot already exists, write_portfolio must refuse (SystemExit)
    if force=False."""
    import calculate

    monkeypatch.setattr(calculate, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(calculate, "SNAPSHOTS_JSON", tmp_path / "snapshots.json")

    # Pre-create the snapshot file
    existing = tmp_path / "portfolio-2025-12-31.json"
    existing.write_text('{"meta": {"cut_date": "2025-12-31"}}', encoding="utf-8")

    portfolio = _minimal_portfolio()
    with pytest.raises(SystemExit) as exc_info:
        calculate.write_portfolio(portfolio, cut_date="2025-12-31", force=False)

    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# P1-4-C: existing snapshot + force=True → overwrites
# ---------------------------------------------------------------------------

def test_existing_snapshot_overwritten_with_force(tmp_path, monkeypatch):
    """When force=True, write_portfolio must overwrite an existing dated snapshot."""
    import calculate

    monkeypatch.setattr(calculate, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(calculate, "SNAPSHOTS_JSON", tmp_path / "snapshots.json")

    # Pre-create the snapshot file with sentinel content
    existing = tmp_path / "portfolio-2025-12-31.json"
    existing.write_text('{"old": true}', encoding="utf-8")

    portfolio = _minimal_portfolio()
    calculate.write_portfolio(portfolio, cut_date="2025-12-31", force=True)

    written = json.loads(existing.read_text(encoding="utf-8"))
    assert "old" not in written, "Overwrite must replace prior content"
    assert "summary" in written


# ---------------------------------------------------------------------------
# P1-4-D: no cut_date → live portfolio.json always rewritten (no snapshot touched)
# ---------------------------------------------------------------------------

def test_live_portfolio_written_without_cut_date(tmp_path, monkeypatch):
    """Without cut_date, write_portfolio must write portfolio.json and NOT create
    any dated snapshot file."""
    import calculate

    monkeypatch.setattr(calculate, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(calculate, "SNAPSHOTS_JSON", tmp_path / "snapshots.json")

    portfolio = _minimal_portfolio()
    calculate.write_portfolio(portfolio, cut_date=None, force=False)

    assert (tmp_path / "portfolio.json").exists()
    # No dated snapshots should be created
    dated = list(tmp_path.glob("portfolio-*.json"))
    assert len(dated) == 0, f"No dated snapshots expected; found: {dated}"
