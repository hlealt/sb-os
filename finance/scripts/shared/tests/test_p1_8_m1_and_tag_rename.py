"""Regression tests for p1-8: M-1 fix + subcategory→tag rename.

Verifies:
  1. SECR. DA RECEITA FEDERAL classifies as category="receitas" with tag="impostos"
  2. The config key "tag" is read correctly by _value_subcategory()
  3. The legacy "subcategory" key is IGNORED (migration shim removed at
     expenses-backfill retirement, 2026-06)
  4. No reimbursement_mappings entry emits the invalid "seguro" category
"""
from __future__ import annotations

import pytest

from categorize import _category_only, _value_subcategory, categorize_transaction


# ---------------------------------------------------------------------------
# _value_subcategory — reads "tag" key (renamed from "subcategory")
# ---------------------------------------------------------------------------

def test_value_subcategory_reads_tag_key():
    """After rename, the 'tag' key is the authoritative source."""
    value = {"category": "receitas", "tag": "impostos"}
    assert _value_subcategory(value) == "impostos"


def test_value_subcategory_legacy_key_ignored():
    """Shim removed: the legacy 'subcategory' key no longer resolves."""
    value = {"category": "saude", "subcategory": "reembolso"}
    assert _value_subcategory(value) == ""


def test_value_subcategory_tag_read_with_legacy_key_present():
    """'tag' is read; a stray legacy 'subcategory' key is ignored."""
    value = {"category": "saude", "tag": "reembolso", "subcategory": "old-value"}
    assert _value_subcategory(value) == "reembolso"


def test_value_subcategory_plain_string_returns_empty():
    assert _value_subcategory("receitas") == ""


# ---------------------------------------------------------------------------
# M-1: SECR. DA RECEITA FEDERAL → receitas + impostos tag
# ---------------------------------------------------------------------------

REIMBURSEMENT_MAPPINGS = {
    "CARE PLUS": {
        "category": "saude",
        "tag": "reembolso",
    },
    "SECR. DA RECEITA FEDERAL": {
        "category": "receitas",
        "tag": "impostos",
    },
}

SELF_TRANSFER_PATTERNS: list[str] = []


def test_secr_receita_federal_classifies_receitas():
    """M-1 fix: SECR. DA RECEITA FEDERAL must emit category='receitas'."""
    cat, confidence, _, tags = categorize_transaction(
        description="PIX RECEBIDO SECR. DA RECEITA FEDERAL 1234",
        self_transfer_patterns=SELF_TRANSFER_PATTERNS,
        reimbursement_mappings=REIMBURSEMENT_MAPPINGS,
        supplier_index=None,
    )
    assert cat == "receitas", f"Expected 'receitas', got '{cat}'"
    assert confidence == "exact"


def test_secr_receita_federal_emits_impostos_tag():
    """M-1 fix: SECR. DA RECEITA FEDERAL must emit tag='impostos'."""
    _, _, _, tags = categorize_transaction(
        description="PIX RECEBIDO SECR. DA RECEITA FEDERAL 1234",
        self_transfer_patterns=SELF_TRANSFER_PATTERNS,
        reimbursement_mappings=REIMBURSEMENT_MAPPINGS,
        supplier_index=None,
    )
    assert "impostos" in tags, f"Expected 'impostos' in tags, got {tags}"


def test_secr_receita_federal_never_emits_seguro():
    """Regression: the invalid 'seguro' category must never be emitted."""
    cat, _, _, _ = categorize_transaction(
        description="SECR. DA RECEITA FEDERAL RESTITUICAO IR",
        self_transfer_patterns=SELF_TRANSFER_PATTERNS,
        reimbursement_mappings=REIMBURSEMENT_MAPPINGS,
        supplier_index=None,
    )
    assert cat != "seguro", "Invalid category 'seguro' was emitted — M-1 fix not applied"


def test_care_plus_still_classifies_saude_with_reembolso_tag():
    """Care Plus mapping still works with renamed 'tag' key."""
    cat, _, _, tags = categorize_transaction(
        description="CARE PLUS REEMBOLSO CONSULTA",
        self_transfer_patterns=SELF_TRANSFER_PATTERNS,
        reimbursement_mappings=REIMBURSEMENT_MAPPINGS,
        supplier_index=None,
    )
    assert cat == "saude"
    assert "reembolso" in tags
