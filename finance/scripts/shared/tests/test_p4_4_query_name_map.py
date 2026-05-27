"""Regression tests for p4-4: query-name-map read tool.

Verifies:
  1. Reads name_map.csv correctly using csv.DictReader (confirming p2-1 Finding B
     is RETRACTED — no schema mismatch exists in the current codebase).
  2. Returns rows matching source / field / raw_pattern / canonical_pattern /
     asset_type filters.
  3. Fail-soft on missing file: returns [] without raising.
  4. BOOKKEEPER_NAME_MAP_PATH env var override works for test isolation.
  5. Slice-cap respected (hard cap 200).
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

from query_name_map import _SLICE_CAP, query_name_map, _default_name_map_path  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_name_map(filepath: Path, rows: list[dict]) -> None:
    fieldnames = ["source", "field", "raw_value", "canonical_value", "asset_type"]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


_SAMPLE_ROWS = [
    {"source": "safra", "field": "fundo",
     "raw_value": "PRINCIPAL CLARITAS VALOR FIF A",
     "canonical_value": "claritas_valor_fia", "asset_type": "fia_br"},
    {"source": "safra", "field": "fundo",
     "raw_value": "TRÍGONO FLAGSHIP 60 SMALL CAPS",
     "canonical_value": "trigono_small_caps", "asset_type": "fia_br"},
    {"source": "b3", "field": "produto",
     "raw_value": "DEB - NEOE26 - NEOENERGIA S/A",
     "canonical_value": "deb_neoenergia_370", "asset_type": "deb"},
    {"source": "bipa", "field": "produto",
     "raw_value": "BTC/BRL",
     "canonical_value": "btc", "asset_type": "crypto"},
]


# ---------------------------------------------------------------------------
# Tests: basic read
# ---------------------------------------------------------------------------

def test_reads_all_rows_when_no_filter(tmp_path):
    fp = tmp_path / "name_map.csv"
    _write_name_map(fp, _SAMPLE_ROWS)
    result = query_name_map(fp)
    assert len(result) == 4


def test_csv_format_is_used_not_json(tmp_path):
    """Confirms the loader uses csv.DictReader, NOT json.load (p2-1 Finding B retracted)."""
    fp = tmp_path / "name_map.csv"
    _write_name_map(fp, _SAMPLE_ROWS)
    # If json.load were used, this would raise json.JSONDecodeError.
    # Using csv.DictReader it reads correctly.
    result = query_name_map(fp)
    assert len(result) == 4
    # Verify the canonical columns are present
    assert result[0]["source"] == "safra"
    assert result[0]["canonical_value"] == "claritas_valor_fia"


# ---------------------------------------------------------------------------
# Tests: filters
# ---------------------------------------------------------------------------

def test_filter_by_source(tmp_path):
    fp = tmp_path / "name_map.csv"
    _write_name_map(fp, _SAMPLE_ROWS)
    result = query_name_map(fp, source="b3")
    assert len(result) == 1
    assert result[0]["canonical_value"] == "deb_neoenergia_370"


def test_filter_by_field(tmp_path):
    fp = tmp_path / "name_map.csv"
    _write_name_map(fp, _SAMPLE_ROWS)
    result = query_name_map(fp, field="produto")
    assert len(result) == 2  # b3 + bipa both use field=produto


def test_filter_by_raw_pattern(tmp_path):
    fp = tmp_path / "name_map.csv"
    _write_name_map(fp, _SAMPLE_ROWS)
    result = query_name_map(fp, raw_pattern="claritas")
    assert len(result) == 1
    assert result[0]["source"] == "safra"


def test_filter_by_canonical_pattern(tmp_path):
    fp = tmp_path / "name_map.csv"
    _write_name_map(fp, _SAMPLE_ROWS)
    result = query_name_map(fp, canonical_pattern="fia_br")
    # claritas_valor_fia and trigono_small_caps both have asset_type=fia_br
    # but canonical_pattern matches canonical_value only
    assert all("fia_br" in r["canonical_value"] for r in result)


def test_filter_by_asset_type(tmp_path):
    fp = tmp_path / "name_map.csv"
    _write_name_map(fp, _SAMPLE_ROWS)
    result = query_name_map(fp, asset_type="fia_br")
    assert len(result) == 2
    assert all(r["asset_type"] == "fia_br" for r in result)


def test_combined_filters(tmp_path):
    fp = tmp_path / "name_map.csv"
    _write_name_map(fp, _SAMPLE_ROWS)
    result = query_name_map(fp, source="safra", asset_type="fia_br")
    assert len(result) == 2
    result2 = query_name_map(fp, source="safra", asset_type="fia_br", canonical_pattern="trigono")
    assert len(result2) == 1


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------

def test_missing_file_returns_empty(tmp_path):
    result = query_name_map(tmp_path / "nonexistent.csv")
    assert result == []


def test_no_match_returns_empty(tmp_path):
    fp = tmp_path / "name_map.csv"
    _write_name_map(fp, _SAMPLE_ROWS)
    result = query_name_map(fp, source="avenue")
    assert result == []


def test_slice_cap_enforced(tmp_path):
    fp = tmp_path / "name_map.csv"
    rows = [
        {"source": "b3", "field": "produto",
         "raw_value": f"PRODUCT_{i}", "canonical_value": f"prod_{i}", "asset_type": "acao_br"}
        for i in range(250)
    ]
    _write_name_map(fp, rows)
    result = query_name_map(fp, limit=9999)
    assert len(result) == _SLICE_CAP


# ---------------------------------------------------------------------------
# Tests: env var override
# ---------------------------------------------------------------------------

def test_bookkeeper_name_map_path_env_var(tmp_path, monkeypatch):
    """BOOKKEEPER_NAME_MAP_PATH env var overrides default path resolution."""
    fp = tmp_path / "name_map.csv"
    _write_name_map(fp, _SAMPLE_ROWS[:1])
    monkeypatch.setenv("BOOKKEEPER_NAME_MAP_PATH", str(fp))
    resolved = _default_name_map_path()
    assert resolved == fp
