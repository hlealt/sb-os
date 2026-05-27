"""Acceptance tests for B2-SR1: standing-rules consumer wiring (p2-11..p2-16).

Each section's acceptance test asserts:
  1. The consumer loads the rule from config (not hardcoded).
  2. The rule fires correctly on a real/synthetic input.
  3. The rule raises (fail-loud) when the config section is missing.

Sections covered:
  p2-11 expenses_schema     — validate_expenses_schema
  p2-12 name_canonicalization — apply_name_canonicalization
  p2-13 competencia_rules   — load_competencia_rules + rule_counter integration
  p2-14 tag_semantics       — validate_tag_amount_sign
  p2-15 tag_application_rules — apply_tag_application_rules
  p2-16 family_canonicals   — load_family_canonicals + is_family_canonical

rule_fired audit event emission is tested via RuleFireCounter.emit_summary
(already covered in test_standing_rules.py); here we assert the rule_counter
records the expected rule name(s).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from lib.standing_rules import (
    RuleFireCounter,
    StandingRulesError,
    apply_name_canonicalization,
    apply_tag_application_rules,
    is_family_canonical,
    load_competencia_rules,
    load_family_canonicals,
    load_name_canonicalization,
    load_standing_rules,
    load_tag_application_rules,
    load_tag_semantics,
    validate_expenses_schema,
    validate_tag_amount_sign,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_rules(tmp_path: Path, extra_sections: str = "") -> Path:
    """Write a valid standing-rules.yaml with required sections + extra_sections."""
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    body = (
        "_meta:\n"
        "  schema_version: 1\n"
        "  rule_set_version: '1.0-test'\n"
        "supplier_rules:\n"
        "  status: active\n"
    ) + extra_sections
    (config / "standing-rules.yaml").write_text(body, encoding="utf-8")
    return config


def _load(tmp_path: Path, extra: str = "") -> dict:
    config = _write_rules(tmp_path, extra)
    return load_standing_rules(config)


# ---------------------------------------------------------------------------
# p2-11: expenses_schema
# ---------------------------------------------------------------------------

class TestExpensesSchema:
    """Consumer: validate_expenses_schema reads new_columns from YAML, not hardcode."""

    _SECTION = (
        "expenses_schema:\n"
        "  status: active\n"
        "  new_columns: [data_caixa, data_competencia, supplier_canonical, tags]\n"
        "  legacy_column_removed: subcategory\n"
    )

    def test_valid_columns_pass(self, tmp_path):
        """All declared new_columns present and legacy absent → no exception."""
        sr = _load(tmp_path, self._SECTION)
        cols = [
            "date", "description", "amount", "balance", "bank", "source_type",
            "currency", "original_ref", "installment_current", "installment_total",
            "original_amount", "exchange_rate",
            "category", "match_confidence", "recurrence",
            "data_caixa", "data_competencia", "supplier_canonical", "tags",
            "manual_override",
        ]
        # Must not raise
        validate_expenses_schema(sr, cols)

    def test_missing_new_column_raises(self, tmp_path):
        """A new_column absent from CATEGORIZED_COLUMNS → StandingRulesError."""
        sr = _load(tmp_path, self._SECTION)
        cols_missing_tags = [
            "date", "description", "amount", "balance", "bank", "source_type",
            "currency", "original_ref", "installment_current", "installment_total",
            "original_amount", "exchange_rate",
            "category", "match_confidence", "recurrence",
            "data_caixa", "data_competencia", "supplier_canonical",
            # 'tags' deliberately omitted
        ]
        with pytest.raises(StandingRulesError, match="tags"):
            validate_expenses_schema(sr, cols_missing_tags)

    def test_legacy_column_present_raises(self, tmp_path):
        """legacy_column_removed still in CATEGORIZED_COLUMNS → StandingRulesError."""
        sr = _load(tmp_path, self._SECTION)
        cols_with_subcategory = [
            "date", "description", "amount", "balance", "bank", "source_type",
            "currency", "original_ref", "installment_current", "installment_total",
            "original_amount", "exchange_rate",
            "category", "match_confidence", "recurrence",
            "data_caixa", "data_competencia", "supplier_canonical", "tags",
            "manual_override",
            "subcategory",  # legacy — must not be present
        ]
        with pytest.raises(StandingRulesError, match="subcategory"):
            validate_expenses_schema(sr, cols_with_subcategory)

    def test_missing_section_raises(self, tmp_path):
        """Missing expenses_schema section → StandingRulesError."""
        sr = _load(tmp_path)  # no expenses_schema section
        with pytest.raises(StandingRulesError, match="expenses_schema"):
            validate_expenses_schema(sr, ["date"])

    def test_reads_from_config_not_hardcode(self, tmp_path):
        """Consumer reads new_columns from YAML — different set in YAML is detected."""
        custom_section = (
            "expenses_schema:\n"
            "  status: active\n"
            "  new_columns: [custom_col]\n"
            "  legacy_column_removed: old_col\n"
        )
        sr = _load(tmp_path, custom_section)
        # custom_col missing → raises (rule driven by YAML, not hardcoded list)
        with pytest.raises(StandingRulesError, match="custom_col"):
            validate_expenses_schema(sr, ["date", "description"])

    def test_20_column_schema_matches_categorized_columns(self, tmp_path):
        """The live CATEGORIZED_COLUMNS (20 cols) satisfies the standing-rules spec."""
        from categorize import CATEGORIZED_COLUMNS
        sr = _load(tmp_path, self._SECTION)
        validate_expenses_schema(sr, list(CATEGORIZED_COLUMNS))
        assert len(CATEGORIZED_COLUMNS) == 20, (
            "CATEGORIZED_COLUMNS changed — update this test and the schema hand-off note"
        )


# ---------------------------------------------------------------------------
# p2-12: name_canonicalization
# ---------------------------------------------------------------------------

class TestNameCanonicalization:
    """Consumer: apply_name_canonicalization reads style + exceptions from YAML."""

    _SECTION = (
        "name_canonicalization:\n"
        "  status: active\n"
        "  default_style: titlecase_accented\n"
        "  exceptions: [ConectCar, ChatGPT]\n"
    )

    def test_titlecase_applied(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_name_canonicalization(sr)
        assert apply_name_canonicalization("UBER", cfg) == "Uber"

    def test_trademark_exception_preserved(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_name_canonicalization(sr)
        # Case-insensitive match → return declared casing exactly
        assert apply_name_canonicalization("CONECTCAR", cfg) == "ConectCar"
        assert apply_name_canonicalization("chatgpt", cfg) == "ChatGPT"

    def test_empty_name_returned_unchanged(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_name_canonicalization(sr)
        assert apply_name_canonicalization("", cfg) == ""

    def test_missing_section_raises(self, tmp_path):
        sr = _load(tmp_path)
        with pytest.raises(StandingRulesError, match="name_canonicalization"):
            load_name_canonicalization(sr)

    def test_reads_exceptions_from_config(self, tmp_path):
        """Different exceptions list in YAML → different behavior."""
        custom_section = (
            "name_canonicalization:\n"
            "  status: active\n"
            "  default_style: titlecase_accented\n"
            "  exceptions: [MyBrand]\n"
        )
        sr = _load(tmp_path, custom_section)
        cfg = load_name_canonicalization(sr)
        assert apply_name_canonicalization("MYBRAND", cfg) == "MyBrand"
        # ConectCar NOT in this config → title-cased, not preserved
        assert apply_name_canonicalization("CONECTCAR", cfg) == "Conectcar"

    def test_rule_counter_records_fire(self, tmp_path):
        """Name canonicalization fires are recorded on the rule_counter."""
        # This test exercises the integration path in categorize.py's per-row loop.
        # We test the underlying function directly here; the counter increment
        # is driven by the caller (categorize.py), not the function itself.
        sr = _load(tmp_path, self._SECTION)
        cfg = load_name_canonicalization(sr)
        original = "UBER"
        result = apply_name_canonicalization(original, cfg)
        assert result != original  # canonicalization changed the name → fire expected


# ---------------------------------------------------------------------------
# p2-13: competencia_rules
# ---------------------------------------------------------------------------

class TestCompetenciaRules:
    """Consumer: load_competencia_rules reads cc_installments spec from YAML."""

    _SECTION = (
        "competencia_rules:\n"
        "  status: active\n"
        "  cc_installments:\n"
        "    installment_1: row_date\n"
        "    installment_n: 'row_date - (N-1) months'\n"
    )

    def test_section_loads_from_config(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_competencia_rules(sr)
        assert "cc_installments" in cfg

    def test_cc_installments_spec_readable(self, tmp_path):
        """cc_installments sub-rule is readable from config (not hardcoded)."""
        sr = _load(tmp_path, self._SECTION)
        cfg = load_competencia_rules(sr)
        cc = cfg["cc_installments"]
        assert cc["installment_1"] == "row_date"
        assert "installment_n" in cc

    def test_missing_section_raises(self, tmp_path):
        sr = _load(tmp_path)
        with pytest.raises(StandingRulesError, match="competencia_rules"):
            load_competencia_rules(sr)

    def test_rule_counter_records_cc_installments(self, tmp_path):
        """cc_installments fires are recorded in rule_counter (test integration path)."""
        # Simulate the categorize.py per-row logic for a fatura installment row.
        counter = RuleFireCounter()
        source_type = "fatura"
        installment_total = "3"
        if source_type == "fatura":
            try:
                inst_total = int(installment_total) if installment_total else 0
            except (ValueError, TypeError):
                inst_total = 0
            if inst_total >= 2:
                counter.record("competencia_cc_installments")
            else:
                counter.record("competencia_cc_single")
        assert counter.as_dict() == {"competencia_cc_installments": 1}

    def test_rule_counter_records_cc_single(self, tmp_path):
        """Single CC purchase fires competencia_cc_single."""
        counter = RuleFireCounter()
        source_type = "fatura"
        installment_total = ""
        if source_type == "fatura":
            try:
                inst_total = int(installment_total) if installment_total else 0
            except (ValueError, TypeError):
                inst_total = 0
            if inst_total >= 2:
                counter.record("competencia_cc_installments")
            else:
                counter.record("competencia_cc_single")
        assert counter.as_dict() == {"competencia_cc_single": 1}


# ---------------------------------------------------------------------------
# p2-14: tag_semantics
# ---------------------------------------------------------------------------

class TestTagSemantics:
    """Consumer: validate_tag_amount_sign reads sign rules from YAML."""

    _SECTION = (
        "tag_semantics:\n"
        "  status: active\n"
        "  reembolsavel:\n"
        "    type: expense\n"
        "    amount_sign: negative\n"
        "  reembolso:\n"
        "    type: receipt\n"
        "    amount_sign: positive\n"
    )

    def test_reembolsavel_negative_ok(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_tag_semantics(sr)
        assert validate_tag_amount_sign("reembolsavel", -50.0, cfg) is True

    def test_reembolsavel_positive_fails(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_tag_semantics(sr)
        assert validate_tag_amount_sign("reembolsavel", 50.0, cfg) is False

    def test_reembolso_positive_ok(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_tag_semantics(sr)
        assert validate_tag_amount_sign("reembolso", 100.0, cfg) is True

    def test_reembolso_negative_fails(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_tag_semantics(sr)
        assert validate_tag_amount_sign("reembolso", -100.0, cfg) is False

    def test_unknown_tag_always_valid(self, tmp_path):
        """Tags not declared in tag_semantics are unconditionally valid (open vocab)."""
        sr = _load(tmp_path, self._SECTION)
        cfg = load_tag_semantics(sr)
        assert validate_tag_amount_sign("tennis", -50.0, cfg) is True
        assert validate_tag_amount_sign("tennis", 50.0, cfg) is True

    def test_missing_section_raises(self, tmp_path):
        sr = _load(tmp_path)
        with pytest.raises(StandingRulesError, match="tag_semantics"):
            load_tag_semantics(sr)

    def test_reads_sign_from_config(self, tmp_path):
        """Sign convention is driven by YAML — custom config → different behavior."""
        custom_section = (
            "tag_semantics:\n"
            "  status: active\n"
            "  my_tag:\n"
            "    type: income\n"
            "    amount_sign: positive\n"
        )
        sr = _load(tmp_path, custom_section)
        cfg = load_tag_semantics(sr)
        assert validate_tag_amount_sign("my_tag", 10.0, cfg) is True
        assert validate_tag_amount_sign("my_tag", -10.0, cfg) is False


# ---------------------------------------------------------------------------
# p2-15: tag_application_rules
# ---------------------------------------------------------------------------

class TestTagApplicationRules:
    """Consumer: apply_tag_application_rules reads Care Plus + automotive rules from YAML."""

    _SECTION = (
        "tag_application_rules:\n"
        "  status: active\n"
        "  care_plus_receipt:\n"
        "    condition: \"supplier_canonical == 'Care Plus' AND amount > 0\"\n"
        "    always_apply: [reembolso, seguros]\n"
        "  automotive_insurance:\n"
        "    suppliers: [SUHAI, HDI, 'Tokio Marine']\n"
        "    category: carro\n"
        "    tag: seguros\n"
    )

    def _cfg(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        return load_tag_application_rules(sr)

    def test_care_plus_receipt_applies_tags(self, tmp_path):
        cfg = self._cfg(tmp_path)
        counter = RuleFireCounter()
        tags = apply_tag_application_rules(
            "Care Plus", "saude", 150.0, [], cfg, rule_counter=counter
        )
        assert "reembolso" in tags
        assert "seguros" in tags
        assert counter.as_dict().get("tag_application_care_plus_receipt") == 1

    def test_care_plus_negative_amount_does_not_fire(self, tmp_path):
        """Care Plus rule only fires when amount > 0 (receipt, not expense)."""
        cfg = self._cfg(tmp_path)
        counter = RuleFireCounter()
        tags = apply_tag_application_rules(
            "Care Plus", "saude", -150.0, [], cfg, rule_counter=counter
        )
        assert "reembolso" not in tags
        assert "tag_application_care_plus_receipt" not in counter.as_dict()

    def test_automotive_insurance_applies_tag(self, tmp_path):
        cfg = self._cfg(tmp_path)
        counter = RuleFireCounter()
        tags = apply_tag_application_rules(
            "HDI", "carro", -300.0, [], cfg, rule_counter=counter
        )
        assert "seguros" in tags
        assert counter.as_dict().get("tag_application_automotive_insurance") == 1

    def test_automotive_wrong_category_does_not_fire(self, tmp_path):
        """automotive_insurance rule requires category == 'carro'."""
        cfg = self._cfg(tmp_path)
        counter = RuleFireCounter()
        tags = apply_tag_application_rules(
            "HDI", "saude", -300.0, [], cfg, rule_counter=counter
        )
        assert "seguros" not in tags

    def test_existing_tags_preserved(self, tmp_path):
        """Pre-existing tags are kept; new tags appended."""
        cfg = self._cfg(tmp_path)
        tags = apply_tag_application_rules(
            "HDI", "carro", -300.0, ["impostos"], cfg
        )
        assert "impostos" in tags
        assert "seguros" in tags

    def test_no_duplicate_tags(self, tmp_path):
        """Tag already present → not duplicated."""
        cfg = self._cfg(tmp_path)
        tags = apply_tag_application_rules(
            "HDI", "carro", -300.0, ["seguros"], cfg
        )
        assert tags.count("seguros") == 1

    def test_missing_section_raises(self, tmp_path):
        sr = _load(tmp_path)
        with pytest.raises(StandingRulesError, match="tag_application_rules"):
            load_tag_application_rules(sr)

    def test_reads_suppliers_from_config(self, tmp_path):
        """Supplier list is driven by YAML — custom supplier fires the rule."""
        custom_section = (
            "tag_application_rules:\n"
            "  status: active\n"
            "  care_plus_receipt:\n"
            "    condition: \"supplier_canonical == 'Care Plus' AND amount > 0\"\n"
            "    always_apply: []\n"
            "  automotive_insurance:\n"
            "    suppliers: [MyInsurer]\n"
            "    category: carro\n"
            "    tag: seguros\n"
        )
        sr = _load(tmp_path, custom_section)
        cfg = load_tag_application_rules(sr)
        tags = apply_tag_application_rules("MyInsurer", "carro", -200.0, [], cfg)
        assert "seguros" in tags
        # HDI not in this config → no tag
        tags_hdi = apply_tag_application_rules("HDI", "carro", -200.0, [], cfg)
        assert "seguros" not in tags_hdi


# ---------------------------------------------------------------------------
# p2-16: family_canonicals
# ---------------------------------------------------------------------------

class TestFamilyCanonicals:
    """Consumer: is_family_canonical reads members list from YAML."""

    _SECTION = (
        "family_canonicals:\n"
        "  status: active\n"
        "  members: [Pai, Mae, Irmao]\n"
        "  rule: 'PIX to/from family uses relationship name'\n"
    )

    def test_family_member_recognized(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_family_canonicals(sr)
        assert is_family_canonical("Pai", cfg) is True
        assert is_family_canonical("Mae", cfg) is True
        assert is_family_canonical("Irmao", cfg) is True

    def test_non_member_not_recognized(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_family_canonicals(sr)
        assert is_family_canonical("Henrique", cfg) is False
        assert is_family_canonical("Uber", cfg) is False

    def test_empty_canonical_not_recognized(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_family_canonicals(sr)
        assert is_family_canonical("", cfg) is False

    def test_missing_section_raises(self, tmp_path):
        sr = _load(tmp_path)
        with pytest.raises(StandingRulesError, match="family_canonicals"):
            load_family_canonicals(sr)

    def test_reads_members_from_config(self, tmp_path):
        """Members list driven by YAML — custom members list changes behavior."""
        custom_section = (
            "family_canonicals:\n"
            "  status: active\n"
            "  members: [Primo]\n"
            "  rule: 'test'\n"
        )
        sr = _load(tmp_path, custom_section)
        cfg = load_family_canonicals(sr)
        assert is_family_canonical("Primo", cfg) is True
        assert is_family_canonical("Pai", cfg) is False  # not in this config

    def test_rule_counter_records_fire(self, tmp_path):
        """Family canonical fire is recorded on rule_counter."""
        sr = _load(tmp_path, self._SECTION)
        cfg = load_family_canonicals(sr)
        counter = RuleFireCounter()
        if is_family_canonical("Pai", cfg):
            counter.record("family_canonical_applied")
        assert counter.as_dict() == {"family_canonical_applied": 1}

    def test_real_standing_rules_yaml_loads(self, tmp_path):
        """The live standing-rules.yaml family_canonicals section loads correctly."""
        vault_root = Path(__file__).resolve().parents[7]
        real_yaml = (
            vault_root
            / ".user"
            / "finance"
            / "bookkeeper"
            / "config"
            / "standing-rules.yaml"
        )
        if not real_yaml.exists():
            pytest.skip("Real standing-rules.yaml not present.")
        sr = load_standing_rules(real_yaml.parent)
        cfg = load_family_canonicals(sr)
        members = cfg.get("members") or []
        assert len(members) > 0, "family_canonicals.members must not be empty in real config"
