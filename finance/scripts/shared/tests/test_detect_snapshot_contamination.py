"""Regression tests for detect_snapshot_contamination.py (p1-5).

Contracts tested:
  P1-5-A  Clean snapshot (all api-priced positions have price_date == cut_date)
           → contaminated=False, no offenders
  P1-5-B  Contaminated snapshot (api-priced position has price_date != cut_date)
           → contaminated=True, offender listed
  P1-5-C  Snapshot with all price_source='missing' → contaminated=False
           (missing positions are exempt from the check)
  P1-5-D  Snapshot with balcao/snapshot price_source → contaminated=False
           (only api-priced positions are subject to the check)
  P1-5-E  Multiple snapshots — only the contaminated one is flagged
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure the investimentos directory is importable.
_INVESTIMENTOS = Path(__file__).resolve().parents[2] / "investimentos"
if str(_INVESTIMENTOS) not in sys.path:
    sys.path.insert(0, str(_INVESTIMENTOS))

from detect_snapshot_contamination import check_snapshot, detect_contamination


def _write_snapshot(path: Path, cut_date: str, positions: list[dict]) -> Path:
    snapshot = {
        "meta": {"cut_date": cut_date, "generated_at": "2026-05-02T00:00:00"},
        "positions": positions,
    }
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# P1-5-A: clean snapshot — all api prices match cut_date
# ---------------------------------------------------------------------------

def test_clean_snapshot_not_contaminated(tmp_path):
    """All api-priced positions have price_date == cut_date → clean."""
    snap = _write_snapshot(
        tmp_path / "portfolio-2026-04-30.json",
        cut_date="2026-04-30",
        positions=[
            {"id": "IVVB11", "price_source": "api", "price_date": "2026-04-30"},
            {"id": "BPAC11", "price_source": "api", "price_date": "2026-04-30"},
        ],
    )
    result = check_snapshot(snap)
    assert result["contaminated"] is False
    assert result["offenders"] == []
    assert result["clean_priced"] == 2


# ---------------------------------------------------------------------------
# P1-5-B: contaminated snapshot — api price_date != cut_date
# ---------------------------------------------------------------------------

def test_contaminated_snapshot_flagged(tmp_path):
    """A position with price_source='api' and price_date != cut_date is an offender."""
    snap = _write_snapshot(
        tmp_path / "portfolio-2026-04-23.json",
        cut_date="2026-04-23",
        positions=[
            {"id": "IVVB11", "price_source": "api", "price_date": "2026-05-02"},
        ],
    )
    result = check_snapshot(snap)
    assert result["contaminated"] is True
    assert len(result["offenders"]) == 1
    assert result["offenders"][0]["id"] == "IVVB11"
    assert result["offenders"][0]["price_date"] == "2026-05-02"


# ---------------------------------------------------------------------------
# P1-5-C: all positions missing → clean (missing is exempt)
# ---------------------------------------------------------------------------

def test_all_missing_prices_is_clean(tmp_path):
    """Positions with price_source='missing' are exempt from contamination check."""
    snap = _write_snapshot(
        tmp_path / "portfolio-2025-12-31.json",
        cut_date="2025-12-31",
        positions=[
            {"id": "SIMH3", "price_source": "missing", "price_date": ""},
            {"id": "VALE3", "price_source": "missing", "price_date": ""},
        ],
    )
    result = check_snapshot(snap)
    assert result["contaminated"] is False
    assert result["missing"] == 2
    assert result["clean_priced"] == 0


# ---------------------------------------------------------------------------
# P1-5-D: balcao/snapshot source → exempt
# ---------------------------------------------------------------------------

def test_balcao_snapshot_source_exempt(tmp_path):
    """Positions with price_source='snapshot' (balcao) are not subject to the check."""
    snap = _write_snapshot(
        tmp_path / "portfolio-2026-04-23.json",
        cut_date="2026-04-23",
        positions=[
            # balcao position: price_date is the most recent snapshot, not cut_date — ok
            {"id": "porto_seguro_firf_di", "price_source": "snapshot", "price_date": "2026-03-31"},
        ],
    )
    result = check_snapshot(snap)
    assert result["contaminated"] is False
    assert result["offenders"] == []


# ---------------------------------------------------------------------------
# P1-5-E: multiple snapshots — only contaminated one flagged
# ---------------------------------------------------------------------------

def test_multiple_snapshots_only_contaminated_flagged(tmp_path):
    """detect_contamination must flag only the snapshot with api price_date mismatch."""
    _write_snapshot(
        tmp_path / "portfolio-2025-12-31.json",
        cut_date="2025-12-31",
        positions=[
            {"id": "VALE3", "price_source": "missing", "price_date": ""},
        ],
    )
    _write_snapshot(
        tmp_path / "portfolio-2026-04-23.json",
        cut_date="2026-04-23",
        positions=[
            {"id": "IVVB11", "price_source": "api", "price_date": "2026-05-02"},
        ],
    )

    results = detect_contamination(tmp_path)
    assert len(results) == 2

    clean = next(r for r in results if r["snapshot"] == "portfolio-2025-12-31.json")
    dirty = next(r for r in results if r["snapshot"] == "portfolio-2026-04-23.json")

    assert clean["contaminated"] is False
    assert dirty["contaminated"] is True
