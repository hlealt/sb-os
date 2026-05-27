"""Regression tests for p4-14: audit-aliases read tool.

Verifies:
  1. Duplicate alias across two suppliers is detected.
  2. Alias appearing under only one supplier is clean.
  3. Alias comparison is case-insensitive (matches categorize.py behavior).
  4. Empty suppliers.json produces no duplicates.
  5. Supplier with no aliases doesn't crash.
  6. audit() returns 0 when clean, 1 when duplicates found.
  7. audit() returns 1 when suppliers.json is missing.
  8. Multiple duplicates are all reported.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
# audit-aliases.py is in shared/ (hyphenated filename)
for _p in (_SCRIPTS_DIR,):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Import from hyphenated filename using importlib
import importlib.util as _ilu

_mod_path = _SCRIPTS_DIR / "audit-aliases.py"
_spec = _ilu.spec_from_file_location("audit_aliases", _mod_path)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

load_alias_map = _mod.load_alias_map
find_duplicates = _mod.find_duplicates
audit = _mod.audit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _suppliers_json(suppliers_dict: dict) -> dict:
    return {"suppliers": suppliers_dict}


def _write_suppliers(path: Path, suppliers_dict: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_suppliers_json(suppliers_dict), f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Unit tests: load_alias_map
# ---------------------------------------------------------------------------

def test_alias_map_built_correctly():
    suppliers = {
        "supplier-a": {"canonical": "Supplier A", "aliases": ["ALIAS X", "ALIAS Y"]},
        "supplier-b": {"canonical": "Supplier B", "aliases": ["ALIAS Z"]},
    }
    alias_map = load_alias_map(_suppliers_json(suppliers))
    assert alias_map.get("ALIAS X") == ["supplier-a"]
    assert alias_map.get("ALIAS Z") == ["supplier-b"]


def test_alias_map_case_insensitive():
    """Aliases are stored uppercased — matching categorize.py."""
    suppliers = {
        "supplier-a": {"aliases": ["Pagamento Conta Santander"]},
    }
    alias_map = load_alias_map(_suppliers_json(suppliers))
    assert "PAGAMENTO CONTA SANTANDER" in alias_map


def test_empty_alias_ignored():
    """Empty string alias is not added to the map."""
    suppliers = {"supplier-a": {"aliases": ["", "VALID ALIAS"]}}
    alias_map = load_alias_map(_suppliers_json(suppliers))
    assert "" not in alias_map


# ---------------------------------------------------------------------------
# Unit tests: find_duplicates
# ---------------------------------------------------------------------------

def test_duplicate_detected():
    """Same alias under two suppliers → 1 duplicate entry."""
    alias_map = {
        "ALIAS DUP": ["supplier-a", "supplier-b"],
        "ALIAS UNIQUE": ["supplier-c"],
    }
    dups = find_duplicates(alias_map)
    assert len(dups) == 1
    assert dups[0]["alias"] == "ALIAS DUP"
    assert set(dups[0]["slugs"]) == {"supplier-a", "supplier-b"}


def test_no_duplicates_returns_empty():
    """All aliases unique → no duplicates."""
    alias_map = {
        "ALIAS A": ["supplier-a"],
        "ALIAS B": ["supplier-b"],
    }
    dups = find_duplicates(alias_map)
    assert dups == []


def test_multiple_duplicates_all_reported():
    """Two different duplicate aliases → both reported."""
    alias_map = {
        "DUP ONE": ["s1", "s2"],
        "DUP TWO": ["s3", "s4"],
        "CLEAN": ["s5"],
    }
    dups = find_duplicates(alias_map)
    assert len(dups) == 2
    aliases = {d["alias"] for d in dups}
    assert "DUP ONE" in aliases
    assert "DUP TWO" in aliases


def test_supplier_without_aliases_no_crash():
    """Supplier entry with no aliases field doesn't cause a crash."""
    suppliers = {"supplier-x": {"canonical": "X"}}
    alias_map = load_alias_map(_suppliers_json(suppliers))
    dups = find_duplicates(alias_map)
    assert dups == []


# ---------------------------------------------------------------------------
# Integration: audit()
# ---------------------------------------------------------------------------

def test_audit_missing_file_exits_1(tmp_path):
    exit_code = audit(tmp_path / "suppliers.json", duplicates_only=False)
    assert exit_code == 1


def test_audit_clean_exits_0(tmp_path):
    _write_suppliers(tmp_path / "suppliers.json", {
        "supplier-a": {"aliases": ["UNIQUE ALIAS A"]},
        "supplier-b": {"aliases": ["UNIQUE ALIAS B"]},
    })
    exit_code = audit(tmp_path / "suppliers.json", duplicates_only=False)
    assert exit_code == 0


def test_audit_with_duplicates_exits_1(tmp_path, capsys):
    """Real-world pattern: same alias under two suppliers."""
    _write_suppliers(tmp_path / "suppliers.json", {
        "entre-contas": {"aliases": ["PAGAMENTO DE CONTA BANCO SANTANDER"]},
        "cartao-de-credito": {"aliases": ["PAGAMENTO DE CONTA BANCO SANTANDER"]},
    })
    exit_code = audit(tmp_path / "suppliers.json", duplicates_only=False)
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "PAGAMENTO DE CONTA BANCO SANTANDER" in out


def test_audit_empty_suppliers_exits_0(tmp_path):
    _write_suppliers(tmp_path / "suppliers.json", {})
    exit_code = audit(tmp_path / "suppliers.json", duplicates_only=False)
    assert exit_code == 0
