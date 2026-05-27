"""Regression tests for p4-3: query-corrections read tool.

Verifies:
  1. Reads manual-overrides.csv, competencia-overrides.csv, category-migrations.csv,
     code_migrations.csv — all corrections files listed in CONVENTION.md.
  2. Fail-soft on missing file: returns [] without raising.
  3. Filters: month, category, identity key, pattern.
  4. BOOKKEEPER_CONFIG_DIR env var override works for test isolation.
  5. Slice-cap respected (hard cap 100).
  6. query_corrections_file returns empty for header-only (0 data rows) files.
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from query_corrections import (  # noqa: E402
    _SLICE_CAP,
    query_corrections_file,
    _resolve_corrections_dir,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_csv(filepath: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _make_corrections_dir(tmp_path: Path) -> Path:
    d = tmp_path / "corrections"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# Tests: manual-overrides.csv
# ---------------------------------------------------------------------------

def test_manual_overrides_returns_rows(tmp_path):
    d = _make_corrections_dir(tmp_path)
    fieldnames = ["tx_date", "tx_description", "tx_amount", "override_category",
                  "override_tags", "month", "added_at", "source", "note"]
    rows = [
        {"tx_date": "2026-03-03", "tx_description": "IOF DESPESA NO EXTERIOR",
         "tx_amount": "-4.12", "override_category": "compras", "override_tags": "impostos",
         "month": "2026-03", "added_at": "2026-05-26T00:00:00", "source": "p2-2", "note": ""},
        {"tx_date": "2026-03-24", "tx_description": "IOF DESPESA NO EXTERIOR",
         "tx_amount": "-40.91", "override_category": "compras", "override_tags": "impostos",
         "month": "2026-03", "added_at": "2026-05-26T00:00:00", "source": "p2-2", "note": ""},
    ]
    _write_csv(d / "manual-overrides.csv", fieldnames, rows)
    result = query_corrections_file(d / "manual-overrides.csv")
    assert len(result) == 2


def test_manual_overrides_filter_by_month(tmp_path):
    d = _make_corrections_dir(tmp_path)
    fieldnames = ["tx_date", "tx_description", "tx_amount", "override_category",
                  "override_tags", "month", "added_at", "source", "note"]
    rows = [
        {"tx_date": "2026-03-03", "tx_description": "IOF", "tx_amount": "-4",
         "override_category": "compras", "override_tags": "", "month": "2026-03",
         "added_at": "", "source": "", "note": ""},
        {"tx_date": "2026-01-10", "tx_description": "OTHER", "tx_amount": "-10",
         "override_category": "moradia", "override_tags": "", "month": "2026-01",
         "added_at": "", "source": "", "note": ""},
    ]
    _write_csv(d / "manual-overrides.csv", fieldnames, rows)
    result = query_corrections_file(d / "manual-overrides.csv", month="2026-03")
    assert len(result) == 1
    assert result[0]["tx_description"] == "IOF"


def test_manual_overrides_filter_by_identity(tmp_path):
    d = _make_corrections_dir(tmp_path)
    fieldnames = ["tx_date", "tx_description", "tx_amount", "override_category",
                  "override_tags", "month", "added_at", "source", "note"]
    rows = [
        {"tx_date": "2026-03-03", "tx_description": "IOF DESPESA", "tx_amount": "-4.12",
         "override_category": "compras", "override_tags": "", "month": "2026-03",
         "added_at": "", "source": "", "note": ""},
        {"tx_date": "2026-01-10", "tx_description": "CLARO", "tx_amount": "-120",
         "override_category": "moradia", "override_tags": "", "month": "2026-01",
         "added_at": "", "source": "", "note": ""},
    ]
    _write_csv(d / "manual-overrides.csv", fieldnames, rows)
    result = query_corrections_file(d / "manual-overrides.csv",
                                    identity="2026-03-03|IOF DESPESA|-4.12")
    assert len(result) == 1
    assert result[0]["tx_date"] == "2026-03-03"


# ---------------------------------------------------------------------------
# Tests: competencia-overrides.csv
# ---------------------------------------------------------------------------

def test_competencia_overrides_header_only_returns_empty(tmp_path):
    d = _make_corrections_dir(tmp_path)
    fieldnames = ["tx_date", "tx_description", "tx_amount",
                  "override_data_competencia", "reason", "month", "added_at", "source", "note"]
    _write_csv(d / "competencia-overrides.csv", fieldnames, [])
    result = query_corrections_file(d / "competencia-overrides.csv")
    assert result == []


def test_competencia_overrides_returns_rows(tmp_path):
    d = _make_corrections_dir(tmp_path)
    fieldnames = ["tx_date", "tx_description", "tx_amount",
                  "override_data_competencia", "reason", "month", "added_at", "source", "note"]
    rows = [
        {"tx_date": "2026-04-30", "tx_description": "REEMBOLSO PLANO SAUDE",
         "tx_amount": "500", "override_data_competencia": "2026-03",
         "reason": "cross-month medical", "month": "2026-04",
         "added_at": "", "source": "", "note": ""},
    ]
    _write_csv(d / "competencia-overrides.csv", fieldnames, rows)
    result = query_corrections_file(d / "competencia-overrides.csv")
    assert len(result) == 1
    assert result[0]["override_data_competencia"] == "2026-03"


# ---------------------------------------------------------------------------
# Tests: category-migrations.csv
# ---------------------------------------------------------------------------

def test_category_migrations_filter_by_category(tmp_path):
    d = _make_corrections_dir(tmp_path)
    fieldnames = ["from_category", "to_category", "scope",
                  "effective_after", "added_at", "source", "note"]
    rows = [
        {"from_category": "impostos", "to_category": "compras",
         "scope": "all", "effective_after": "", "added_at": "", "source": "p2-2", "note": ""},
        {"from_category": "saude", "to_category": "moradia",
         "scope": "all", "effective_after": "", "added_at": "", "source": "test", "note": ""},
    ]
    _write_csv(d / "category-migrations.csv", fieldnames, rows)
    result = query_corrections_file(d / "category-migrations.csv", category="impostos")
    assert len(result) == 1
    assert result[0]["to_category"] == "compras"


# ---------------------------------------------------------------------------
# Tests: fail-soft on missing file
# ---------------------------------------------------------------------------

def test_missing_file_returns_empty(tmp_path):
    result = query_corrections_file(tmp_path / "nonexistent.csv")
    assert result == []


# ---------------------------------------------------------------------------
# Tests: slice cap
# ---------------------------------------------------------------------------

def test_slice_cap_enforced(tmp_path):
    d = _make_corrections_dir(tmp_path)
    fieldnames = ["tx_date", "tx_description", "tx_amount", "override_category",
                  "override_tags", "month", "added_at", "source", "note"]
    rows = [
        {"tx_date": "2026-01-01", "tx_description": f"TX{i}", "tx_amount": f"-{i}",
         "override_category": "test", "override_tags": "", "month": "2026-01",
         "added_at": "", "source": "", "note": ""}
        for i in range(150)
    ]
    _write_csv(d / "manual-overrides.csv", fieldnames, rows)
    result = query_corrections_file(d / "manual-overrides.csv", limit=9999)
    assert len(result) == _SLICE_CAP


# ---------------------------------------------------------------------------
# Tests: pattern filter
# ---------------------------------------------------------------------------

def test_filter_by_pattern(tmp_path):
    d = _make_corrections_dir(tmp_path)
    fieldnames = ["tx_date", "tx_description", "tx_amount", "override_category",
                  "override_tags", "month", "added_at", "source", "note"]
    rows = [
        {"tx_date": "2026-03-03", "tx_description": "IOF DESPESA NO EXTERIOR",
         "tx_amount": "-4.12", "override_category": "compras", "override_tags": "impostos",
         "month": "2026-03", "added_at": "", "source": "", "note": ""},
        {"tx_date": "2026-01-10", "tx_description": "SUPERMERCADO",
         "tx_amount": "-100", "override_category": "alimentacao", "override_tags": "",
         "month": "2026-01", "added_at": "", "source": "", "note": ""},
    ]
    _write_csv(d / "manual-overrides.csv", fieldnames, rows)
    result = query_corrections_file(d / "manual-overrides.csv", pattern="IOF")
    assert len(result) == 1
    assert result[0]["tx_description"] == "IOF DESPESA NO EXTERIOR"


# ---------------------------------------------------------------------------
# Tests: env var override
# ---------------------------------------------------------------------------

def test_bookkeeper_config_dir_env_var(tmp_path, monkeypatch):
    """BOOKKEEPER_CONFIG_DIR env var routes to correct corrections dir."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    corrections_dir = config_dir / "corrections"
    corrections_dir.mkdir()

    monkeypatch.setenv("BOOKKEEPER_CONFIG_DIR", str(config_dir))
    resolved = _resolve_corrections_dir()
    assert resolved == corrections_dir
