"""Regression tests for the snapshot-triplet consistency gate (p3-4 / DC-1-E).

Contracts tested:
  P3-4-CG-A  A consistent triplet (portfolio-{D}.json + snapshots.json entry +
             balance rows for D) passes the gate.
  P3-4-CG-B  INTERRUPTED CLOSE — the Safra parser ran (balance-snapshots.csv
             has rows dated D) but calculate.py did NOT (no portfolio-{D}.json,
             no snapshots.json entry). The gate CATCHES it and the CLI HALTS
             (exit 1). This is the core p3-4 scenario.
  P3-4-CG-C  Stale manifest — portfolio-{D}.json exists but snapshots.json does
             not list D → drift caught.
  P3-4-CG-D  Missing snapshot — snapshots.json lists D but portfolio-{D}.json is
             absent → drift caught.
  P3-4-CG-E  NO false alarm — a snapshot cut on a date with no same-date
             balance-snapshots row is consistent (Safra valuation dates need
             not coincide with the close date).
  P3-4-CG-F  The object-array snapshots.json schema is read correctly
             (forward-compatible with inv-data.js).
"""
from __future__ import annotations

import csv
import json

from lib import snapshot_consistency as sc


# ---------------------------------------------------------------------------
# Ledger-dir fixture builders
# ---------------------------------------------------------------------------

def _write_manifest(ledger_dir, dates):
    (ledger_dir / "snapshots.json").write_text(
        json.dumps(dates), encoding="utf-8"
    )


def _write_portfolio(ledger_dir, date):
    (ledger_dir / f"portfolio-{date}.json").write_text(
        json.dumps({"meta": {"cut_date": date}}), encoding="utf-8"
    )


def _write_balance_rows(ledger_dir, rows):
    path = ledger_dir / "balance-snapshots.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "product_id", "balance", "source"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_consistent_triplet_passes(tmp_path):
    d = "2026-04-30"
    _write_portfolio(tmp_path, d)
    _write_manifest(tmp_path, [d])
    _write_balance_rows(tmp_path, [
        {"date": d, "product_id": "fund_a", "balance": "100.0", "source": "safra"},
    ])

    result = sc.check_triplet_consistency(d, tmp_path)
    assert result.consistent, result.report()
    assert sc.main([d, "--ledger-dir", str(tmp_path)]) == 0


def test_interrupted_close_is_caught_and_halts(tmp_path):
    """Parser ran (balance rows for D) but calculate.py did not — no
    portfolio-{D}.json, no snapshots.json entry. Gate must CATCH and HALT."""
    d = "2026-04-30"
    # snapshots.json exists but does NOT list D; no portfolio-{D}.json.
    _write_manifest(tmp_path, ["2025-12-31"])
    _write_balance_rows(tmp_path, [
        {"date": d, "product_id": "fund_a", "balance": "100.0", "source": "safra"},
        {"date": d, "product_id": "fund_b", "balance": "200.0", "source": "safra"},
    ])

    result = sc.check_triplet_consistency(d, tmp_path)
    assert not result.consistent
    assert any("interrupted close" in p for p in result.problems), result.report()
    # CLI halts with exit 1 — the close is NOT shipped.
    assert sc.main([d, "--ledger-dir", str(tmp_path)]) == 1


def test_stale_manifest_caught(tmp_path):
    d = "2026-04-30"
    _write_portfolio(tmp_path, d)
    _write_manifest(tmp_path, [])  # portfolio exists but manifest does not list it
    result = sc.check_triplet_consistency(d, tmp_path)
    assert not result.consistent
    assert any("stale" in p for p in result.problems), result.report()


def test_missing_snapshot_caught(tmp_path):
    d = "2026-04-30"
    _write_manifest(tmp_path, [d])  # listed but file absent
    result = sc.check_triplet_consistency(d, tmp_path)
    assert not result.consistent
    assert any("missing" in p for p in result.problems), result.report()


def test_no_false_alarm_when_balance_date_differs(tmp_path):
    """A snapshot cut on D with balance rows only on other dates is consistent."""
    d = "2026-04-23"
    _write_portfolio(tmp_path, d)
    _write_manifest(tmp_path, [d])
    _write_balance_rows(tmp_path, [
        {"date": "2026-04-30", "product_id": "fund_a", "balance": "100.0", "source": "safra"},
    ])
    result = sc.check_triplet_consistency(d, tmp_path)
    assert result.consistent, result.report()


def test_object_array_manifest_schema_supported(tmp_path):
    d = "2026-04-30"
    _write_portfolio(tmp_path, d)
    (tmp_path / "snapshots.json").write_text(
        json.dumps([{"date": d, "total_brl": 1000, "position_count": 3}]),
        encoding="utf-8",
    )
    result = sc.check_triplet_consistency(d, tmp_path)
    assert result.in_manifest
    assert result.consistent, result.report()
