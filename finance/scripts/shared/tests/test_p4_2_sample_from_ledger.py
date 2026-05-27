"""Regression tests for p4-2: sample-from-ledger read tool.

Verifies:
  1. Returns a bounded slice matching filter criteria.
  2. Slice-size guardrail: --limit is capped at SLICE_CAP (50); full ledger
     is never returned if it exceeds the cap.
  3. Returns empty list (not error) when no rows match.
  4. Returns empty list when ledger file does not exist (fail-soft).
  5. Filters: month, category, vendor, amount-min, amount-max, offset.
  6. BOOKKEEPER_LEDGER_DIR env var overrides base path for test isolation.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from sample_from_ledger import _SLICE_CAP, sample_ledger, _resolve_ledger_path  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_extrato(tmp_path: Path, rows: list[dict]) -> Path:
    """Write a minimal extrato CSV fixture to tmp_path."""
    filepath = tmp_path / "bradesco_extrato.csv"
    fieldnames = ["date", "description", "amount", "balance", "bank", "source_type",
                  "currency", "original_ref", "installment_current", "installment_total"]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)
    return filepath


def _make_transactions(tmp_path: Path, rows: list[dict]) -> Path:
    filepath = tmp_path / "transactions.csv"
    fieldnames = ["date", "description", "amount", "balance", "bank", "source_type",
                  "currency", "original_ref", "installment_current", "installment_total",
                  "original_amount", "exchange_rate", "category", "match_confidence",
                  "recurrence", "data_caixa", "data_competencia", "supplier_canonical",
                  "tags", "manual_override"]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)
    return filepath


_EXTRATO_DEFAULTS = {
    "balance": "0",
    "bank": "bradesco_extrato",
    "source_type": "extrato",
    "currency": "BRL",
    "original_ref": "",
    "installment_current": "",
    "installment_total": "",
}

_TX_DEFAULTS = {
    "balance": "0",
    "bank": "bradesco_extrato",
    "source_type": "extrato",
    "currency": "BRL",
    "original_ref": "",
    "installment_current": "",
    "installment_total": "",
    "original_amount": "",
    "exchange_rate": "",
    "match_confidence": "exact",
    "recurrence": "",
    "data_caixa": "",
    "data_competencia": "",
    "supplier_canonical": "",
    "tags": "",
    "manual_override": "",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_basic_slice_returns_rows(tmp_path):
    rows = [
        {**_EXTRATO_DEFAULTS, "date": "2026-01-05", "description": "SUPERMERCADO", "amount": "-150.0"},
        {**_EXTRATO_DEFAULTS, "date": "2026-01-10", "description": "FARMACIA", "amount": "-50.0"},
    ]
    fp = _make_extrato(tmp_path, rows)
    result = sample_ledger(fp)
    assert len(result) == 2
    assert result[0]["description"] == "SUPERMERCADO"


def test_slice_cap_is_enforced(tmp_path):
    """Requesting more than SLICE_CAP rows never returns more than SLICE_CAP."""
    rows = [
        {**_EXTRATO_DEFAULTS, "date": "2026-01-01", "description": f"TX{i}", "amount": f"-{i}.0"}
        for i in range(80)
    ]
    fp = _make_extrato(tmp_path, rows)
    result = sample_ledger(fp, limit=200)  # way above cap
    assert len(result) == _SLICE_CAP
    assert len(result) <= _SLICE_CAP


def test_full_ledger_never_returned_when_exceeds_cap(tmp_path):
    """The full 80-row ledger is never returned; cap of 50 is the ceiling."""
    rows = [
        {**_EXTRATO_DEFAULTS, "date": "2026-01-01", "description": f"TX{i}", "amount": f"-{i}.0"}
        for i in range(80)
    ]
    fp = _make_extrato(tmp_path, rows)
    result = sample_ledger(fp, limit=9999)
    assert len(result) == _SLICE_CAP  # guardrail fires


def test_filter_by_month(tmp_path):
    rows = [
        {**_EXTRATO_DEFAULTS, "date": "2026-01-05", "description": "JANEIRO", "amount": "-10"},
        {**_EXTRATO_DEFAULTS, "date": "2026-02-05", "description": "FEVEREIRO", "amount": "-20"},
    ]
    fp = _make_extrato(tmp_path, rows)
    result = sample_ledger(fp, month="2026-01")
    assert len(result) == 1
    assert result[0]["description"] == "JANEIRO"


def test_filter_by_category(tmp_path):
    rows = [
        {**_TX_DEFAULTS, "date": "2026-01-05", "description": "CLARO", "amount": "-120", "category": "moradia"},
        {**_TX_DEFAULTS, "date": "2026-01-06", "description": "IFOOD", "amount": "-50", "category": "alimentacao"},
    ]
    fp = _make_transactions(tmp_path, rows)
    result = sample_ledger(fp, category="moradia")
    assert len(result) == 1
    assert result[0]["description"] == "CLARO"


def test_filter_by_vendor(tmp_path):
    rows = [
        {**_EXTRATO_DEFAULTS, "date": "2026-01-05", "description": "SUPERMERCADO EXTRA", "amount": "-150"},
        {**_EXTRATO_DEFAULTS, "date": "2026-01-06", "description": "FARMACIA DROGASIL", "amount": "-40"},
    ]
    fp = _make_extrato(tmp_path, rows)
    result = sample_ledger(fp, vendor="farmacia")
    assert len(result) == 1
    assert "FARMACIA" in result[0]["description"]


def test_filter_by_amount_min(tmp_path):
    rows = [
        {**_EXTRATO_DEFAULTS, "date": "2026-01-05", "description": "BIG", "amount": "-1000"},
        {**_EXTRATO_DEFAULTS, "date": "2026-01-06", "description": "SMALL", "amount": "-5"},
    ]
    fp = _make_extrato(tmp_path, rows)
    result = sample_ledger(fp, amount_min=500.0)
    assert len(result) == 1
    assert result[0]["description"] == "BIG"


def test_filter_by_amount_max(tmp_path):
    rows = [
        {**_EXTRATO_DEFAULTS, "date": "2026-01-05", "description": "BIG", "amount": "-1000"},
        {**_EXTRATO_DEFAULTS, "date": "2026-01-06", "description": "SMALL", "amount": "-5"},
    ]
    fp = _make_extrato(tmp_path, rows)
    result = sample_ledger(fp, amount_max=10.0)
    assert len(result) == 1
    assert result[0]["description"] == "SMALL"


def test_offset_paginates(tmp_path):
    rows = [
        {**_EXTRATO_DEFAULTS, "date": "2026-01-01", "description": f"TX{i}", "amount": f"-{i}"}
        for i in range(5)
    ]
    fp = _make_extrato(tmp_path, rows)
    first_page = sample_ledger(fp, limit=2, offset=0)
    second_page = sample_ledger(fp, limit=2, offset=2)
    assert len(first_page) == 2
    assert len(second_page) == 2
    assert first_page[0]["description"] != second_page[0]["description"]


def test_no_match_returns_empty(tmp_path):
    rows = [
        {**_EXTRATO_DEFAULTS, "date": "2026-01-05", "description": "SUPERMERCADO", "amount": "-150"},
    ]
    fp = _make_extrato(tmp_path, rows)
    result = sample_ledger(fp, vendor="INEXISTENT")
    assert result == []


def test_missing_file_returns_empty(tmp_path):
    fp = tmp_path / "nonexistent.csv"
    result = sample_ledger(fp)
    assert result == []


def test_ledger_dir_env_var(tmp_path, monkeypatch):
    """BOOKKEEPER_LEDGER_DIR env var is respected."""
    rows = [
        {**_EXTRATO_DEFAULTS, "date": "2026-01-05", "description": "ENV_TEST", "amount": "-1"},
    ]
    ledger_dir = tmp_path / "ledgers"
    ledger_dir.mkdir()
    fp = ledger_dir / "my_extrato.csv"
    fieldnames = list(rows[0].keys())
    with open(fp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)

    monkeypatch.setenv("BOOKKEEPER_LEDGER_DIR", str(ledger_dir))
    resolved = _resolve_ledger_path("my_extrato.csv")
    assert resolved == fp
