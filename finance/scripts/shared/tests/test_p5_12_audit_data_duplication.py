"""Tests for p5-12: audit_data_duplication cross-config duplicate auditor.

Verifies:
  1. find_cross_config_duplicates returns hits when a vendor appears in BOTH
     suppliers.json::default_category AND categories.json::value_based_mappings
     (OC-1 positive case).
  2. find_cross_config_duplicates returns empty list when stores are clean
     (no-duplicate case).
  3. CLI exits 1 when duplicates are found.
  4. CLI exits 0 when no duplicates are found.
  5. CLI exits 2 when config directory is missing.
  6. find_cross_config_duplicates never raises — returns [] on bad config.
  7. OC-3 self-transfer/alias overlap is detected.
  8. Concept relevance filtering: an unrelated concept does not surface
     OC-1 hits.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make the shared scripts directory importable so we can import
# audit_data_duplication directly (underscore module, standard import).
_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import audit_data_duplication as aud


# ---------------------------------------------------------------------------
# Fixtures — synthetic config directories
# ---------------------------------------------------------------------------

def _write_suppliers(config_dir: Path, suppliers_dict: dict) -> None:
    data = {"version": 1, "suppliers": suppliers_dict}
    (config_dir / "suppliers.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _write_categories(config_dir: Path, categories_data: dict) -> None:
    (config_dir / "categories.json").write_text(
        json.dumps(categories_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _minimal_categories(value_based: list | None = None,
                         self_transfer: list | None = None) -> dict:
    """Return a minimal categories.json structure."""
    return {
        "categories": {"alimentacao": {"description": "food"}},
        "value_based_mappings": value_based or [],
        "self_transfer_patterns": self_transfer or [],
        "recurrence_rules": {"default_by_category": {}, "vendor_overrides": {}},
        "reimbursement_mappings": {},
    }


# ---------------------------------------------------------------------------
# Unit: _check_oc1_vendor_category
# ---------------------------------------------------------------------------

def test_oc1_hit_when_vendor_in_both_stores():
    """Same vendor alias in suppliers AND in value_based_mappings → OC-1 hit."""
    suppliers = {
        "version": 1,
        "suppliers": {
            "some-vendor": {
                "canonical": "Some Vendor",
                "aliases": ["PAGAMENTO DE CONTA ITAÚ UNIBANCO"],
                "default_category": "casa",
            }
        },
    }
    categories = {
        "value_based_mappings": [
            {
                "vendor": "PAGAMENTO DE CONTA ITAÚ UNIBANCO",
                "amount": 3730,
                "category": "saude",
            }
        ],
    }
    hits = aud._check_oc1_vendor_category(suppliers, categories)
    assert len(hits) == 1
    h = hits[0]
    assert h["overlap_class"] == "OC-1"
    assert h["vendor"] == "PAGAMENTO DE CONTA ITAÚ UNIBANCO"
    assert h["suppliers_slug"] == "some-vendor"
    assert h["suppliers_category"] == "casa"
    assert h["value_based_category"] == "saude"


def test_oc1_no_hit_when_vendor_only_in_suppliers():
    """Vendor alias in suppliers only → no OC-1 hit."""
    suppliers = {
        "version": 1,
        "suppliers": {
            "some-vendor": {
                "canonical": "Some Vendor",
                "aliases": ["UNIQUE VENDOR"],
                "default_category": "alimentacao",
            }
        },
    }
    categories = {"value_based_mappings": []}
    hits = aud._check_oc1_vendor_category(suppliers, categories)
    assert hits == []


def test_oc1_no_hit_when_vendor_only_in_value_based():
    """Vendor in value_based_mappings but NOT in any alias → no OC-1 hit."""
    suppliers = {"version": 1, "suppliers": {}}
    categories = {
        "value_based_mappings": [
            {"vendor": "SOME VENDOR", "amount": 100, "category": "alimentacao"}
        ]
    }
    hits = aud._check_oc1_vendor_category(suppliers, categories)
    assert hits == []


def test_oc1_case_insensitive_matching():
    """Alias comparison is case-insensitive (vendor string uppercased)."""
    suppliers = {
        "version": 1,
        "suppliers": {
            "shop-a": {
                "canonical": "Shop A",
                "aliases": ["pagamento de conta itaú unibanco"],
                "default_category": "compras",
            }
        },
    }
    categories = {
        "value_based_mappings": [
            {
                "vendor": "PAGAMENTO DE CONTA ITAÚ UNIBANCO",
                "amount": 500,
                "category": "casa",
            }
        ]
    }
    hits = aud._check_oc1_vendor_category(suppliers, categories)
    assert len(hits) == 1


# ---------------------------------------------------------------------------
# Unit: _check_oc3_self_transfer_alias_overlap
# ---------------------------------------------------------------------------

def test_oc3_hit_when_pattern_also_an_alias():
    """Pattern in self_transfer_patterns AND as alias → OC-3 hit."""
    suppliers = {
        "version": 1,
        "suppliers": {
            "henrique": {
                "canonical": "Henrique",
                "aliases": ["HENRIQUE LEAL TEIXEIRA"],
            }
        },
    }
    categories = {
        "self_transfer_patterns": ["HENRIQUE LEAL TEIXEIRA"],
    }
    hits = aud._check_oc3_self_transfer_alias_overlap(suppliers, categories)
    assert len(hits) == 1
    h = hits[0]
    assert h["overlap_class"] == "OC-3"
    assert h["pattern"] == "HENRIQUE LEAL TEIXEIRA"
    assert h["suppliers_slug"] == "henrique"


def test_oc3_no_hit_when_pattern_not_in_suppliers():
    """Pattern not present in any supplier alias → no OC-3 hit."""
    suppliers = {"version": 1, "suppliers": {}}
    categories = {"self_transfer_patterns": ["HENRIQUE LEAL TEIXEIRA"]}
    hits = aud._check_oc3_self_transfer_alias_overlap(suppliers, categories)
    assert hits == []


def test_oc3_empty_patterns_no_hit():
    suppliers = {"version": 1, "suppliers": {"a": {"aliases": ["X"]}}}
    categories = {"self_transfer_patterns": []}
    hits = aud._check_oc3_self_transfer_alias_overlap(suppliers, categories)
    assert hits == []


# ---------------------------------------------------------------------------
# Integration: find_cross_config_duplicates (public API)
# ---------------------------------------------------------------------------

def test_find_duplicates_positive_oc1(tmp_path, monkeypatch):
    """find_cross_config_duplicates returns hit strings for OC-1 duplicate."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    _write_suppliers(config_dir, {
        "banco-itau": {
            "canonical": "Banco Itaú",
            "aliases": ["PAGAMENTO DE CONTA ITAÚ UNIBANCO"],
            "default_category": "casa",
        }
    })
    _write_categories(config_dir, _minimal_categories(
        value_based=[{
            "vendor": "PAGAMENTO DE CONTA ITAÚ UNIBANCO",
            "amount": 1639.36,
            "category": "saude",
        }]
    ))

    monkeypatch.setenv("BOOKKEEPER_CONFIG_DIR", str(config_dir))
    hits = aud.find_cross_config_duplicates("vendor to category mapping", None)
    assert len(hits) >= 1
    assert "OC-1" in hits[0]
    assert "PAGAMENTO DE CONTA ITAÚ UNIBANCO" in hits[0]


def test_find_duplicates_clean_returns_empty(tmp_path, monkeypatch):
    """find_cross_config_duplicates returns [] when stores are clean."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    _write_suppliers(config_dir, {
        "shop-a": {
            "canonical": "Shop A",
            "aliases": ["UNIQUE SHOP ALIAS"],
            "default_category": "compras",
        }
    })
    _write_categories(config_dir, _minimal_categories(
        value_based=[{
            "vendor": "COMPLETELY DIFFERENT VENDOR",
            "amount": 100,
            "category": "alimentacao",
        }]
    ))

    monkeypatch.setenv("BOOKKEEPER_CONFIG_DIR", str(config_dir))
    hits = aud.find_cross_config_duplicates("vendor to category mapping", None)
    assert hits == []


def test_find_duplicates_missing_config_dir_returns_empty(tmp_path, monkeypatch):
    """find_cross_config_duplicates returns [] when config dir missing — fail-soft."""
    monkeypatch.setenv("BOOKKEEPER_CONFIG_DIR", str(tmp_path / "nonexistent"))
    # Must not raise; must return []
    hits = aud.find_cross_config_duplicates("vendor to category mapping", None)
    assert hits == []


def test_find_duplicates_never_raises_on_corrupt_json(tmp_path, monkeypatch):
    """find_cross_config_duplicates never raises even when JSON is invalid."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "suppliers.json").write_text("NOT JSON", encoding="utf-8")
    (config_dir / "categories.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("BOOKKEEPER_CONFIG_DIR", str(config_dir))
    hits = aud.find_cross_config_duplicates("vendor to category mapping", None)
    assert isinstance(hits, list)


def test_find_duplicates_concept_relevance_filter(tmp_path, monkeypatch):
    """An unrelated concept does not surface OC-1 hits."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    _write_suppliers(config_dir, {
        "banco-itau": {
            "canonical": "Banco Itaú",
            "aliases": ["PAGAMENTO DE CONTA ITAÚ UNIBANCO"],
            "default_category": "casa",
        }
    })
    _write_categories(config_dir, _minimal_categories(
        value_based=[{
            "vendor": "PAGAMENTO DE CONTA ITAÚ UNIBANCO",
            "amount": 3730,
            "category": "saude",
        }]
    ))

    monkeypatch.setenv("BOOKKEEPER_CONFIG_DIR", str(config_dir))
    # A completely unrelated concept should not surface vendor/category hits
    hits = aud.find_cross_config_duplicates(
        "annual carbon footprint estimate", None
    )
    assert hits == []


# ---------------------------------------------------------------------------
# CLI: main()
# ---------------------------------------------------------------------------

def test_cli_exits_1_on_duplicates(tmp_path, monkeypatch, capsys):
    """CLI exits 1 when cross-config duplicates are found."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    _write_suppliers(config_dir, {
        "itau": {
            "canonical": "Itaú",
            "aliases": ["PAGAMENTO DE CONTA ITAÚ UNIBANCO"],
            "default_category": "casa",
        }
    })
    _write_categories(config_dir, _minimal_categories(
        value_based=[{
            "vendor": "PAGAMENTO DE CONTA ITAÚ UNIBANCO",
            "amount": 1639.36,
            "category": "saude",
        }]
    ))

    monkeypatch.setattr(sys, "argv", [
        "audit_data_duplication.py",
        "--config-dir", str(config_dir),
    ])
    exit_code = aud.main()
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "OC-1" in out


def test_cli_exits_0_on_clean(tmp_path, monkeypatch, capsys):
    """CLI exits 0 when no cross-config duplicates are found."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    _write_suppliers(config_dir, {
        "shop-b": {
            "canonical": "Shop B",
            "aliases": ["ONLY HERE"],
            "default_category": "compras",
        }
    })
    _write_categories(config_dir, _minimal_categories())

    monkeypatch.setattr(sys, "argv", [
        "audit_data_duplication.py",
        "--config-dir", str(config_dir),
    ])
    exit_code = aud.main()
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "No cross-config duplicates" in out


def test_cli_exits_2_on_missing_config_dir(tmp_path, monkeypatch):
    """CLI exits 2 when --config-dir does not exist."""
    monkeypatch.setattr(sys, "argv", [
        "audit_data_duplication.py",
        "--config-dir", str(tmp_path / "nonexistent"),
    ])
    exit_code = aud.main()
    assert exit_code == 2
