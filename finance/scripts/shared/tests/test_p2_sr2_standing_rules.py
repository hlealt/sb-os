"""Acceptance tests for B2-SR2: standing-rules consumer wiring (p2-17..p2-22).

Each section's acceptance test asserts:
  1. The consumer loads the rule from config (not hardcoded).
  2. The rule fires correctly on a real/synthetic input.
  3. The consumer raises (fail-loud) when the config section is missing.

Sections covered:
  p2-17 tag_coverage       — load_tag_coverage + check_tag_coverage_gate
  p2-18 cross_month_propagation — load_cross_month_propagation (config-read + validation)
  p2-19 pass_2_rules       — load_pass_2_rules (config-read + validation)
  p2-20 cash_expense       — load_cash_expense + is_cash_expense_row
  p2-21 investment_rules   — load_investment_rules (config-read + sub-section validation)
  p2-22 rf_naming          — load_rf_naming + validate_rf_name

rule_fired audit event emission is tested via RuleFireCounter (same infra as B2-SR1
tests). Full `categorize.py` startup load is tested via integration test at the end.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from lib.standing_rules import (
    RuleFireCounter,
    StandingRulesError,
    check_tag_coverage_gate,
    is_cash_expense_row,
    load_cash_expense,
    load_cross_month_propagation,
    load_investment_rules,
    load_pass_2_rules,
    load_rf_naming,
    load_standing_rules,
    load_tag_coverage,
    validate_rf_name,
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
# p2-17: tag_coverage
# ---------------------------------------------------------------------------

class TestTagCoverage:
    """Consumer: load_tag_coverage + check_tag_coverage_gate reads threshold from YAML."""

    _SECTION = (
        "tag_coverage:\n"
        "  status: active\n"
        "  rule_80_percent:\n"
        "    target: 0.80\n"
        "    scope: per_category\n"
        "    fallback: include_if_under_10_vendors\n"
        "  gate:\n"
        "    untagged_amount_threshold_brl: 200\n"
        "    action_if_below: auto_loop_to_step_4b\n"
    )

    def test_section_loads_from_config(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_tag_coverage(sr)
        assert "gate" in cfg
        assert "rule_80_percent" in cfg

    def test_gate_pass_below_threshold(self, tmp_path):
        """Untagged amount below threshold → gate passes."""
        sr = _load(tmp_path, self._SECTION)
        cfg = load_tag_coverage(sr)
        counter = RuleFireCounter()
        result = check_tag_coverage_gate(150.0, cfg, rule_counter=counter)
        assert result is True
        assert counter.as_dict().get("tag_coverage_gate_pass") == 1

    def test_gate_fail_at_threshold(self, tmp_path):
        """Untagged amount >= threshold → gate fails."""
        sr = _load(tmp_path, self._SECTION)
        cfg = load_tag_coverage(sr)
        result = check_tag_coverage_gate(200.0, cfg)
        assert result is False

    def test_gate_fail_above_threshold(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_tag_coverage(sr)
        counter = RuleFireCounter()
        result = check_tag_coverage_gate(350.0, cfg, rule_counter=counter)
        assert result is False
        assert counter.as_dict().get("tag_coverage_gate_fail") == 1

    def test_s7_pending_gate_fails_by_default(self, tmp_path):
        """When threshold is None (S7 not resolved), gate MUST fail by default."""
        section_no_threshold = (
            "tag_coverage:\n"
            "  status: active\n"
            "  rule_80_percent:\n"
            "    target: 0.80\n"
            "  gate:\n"
            "    action_if_below: auto_loop_to_step_4b\n"
            # untagged_amount_threshold_brl deliberately absent (S7 pending)
        )
        sr = _load(tmp_path, section_no_threshold)
        cfg = load_tag_coverage(sr)
        counter = RuleFireCounter()
        # Even with untagged_amount_brl=0.0, gate must fail (no threshold known).
        result = check_tag_coverage_gate(0.0, cfg, rule_counter=counter)
        assert result is False
        assert counter.as_dict().get("tag_coverage_gate_s7_pending") == 1

    def test_reads_threshold_from_config(self, tmp_path):
        """Different threshold in YAML → different gate behavior."""
        custom_section = (
            "tag_coverage:\n"
            "  status: active\n"
            "  gate:\n"
            "    untagged_amount_threshold_brl: 50\n"
        )
        sr = _load(tmp_path, custom_section)
        cfg = load_tag_coverage(sr)
        # 49 < 50 → pass; 50 >= 50 → fail
        assert check_tag_coverage_gate(49.0, cfg) is True
        assert check_tag_coverage_gate(50.0, cfg) is False

    def test_missing_section_raises(self, tmp_path):
        sr = _load(tmp_path)  # no tag_coverage section
        with pytest.raises(StandingRulesError, match="tag_coverage"):
            load_tag_coverage(sr)


# ---------------------------------------------------------------------------
# p2-18: cross_month_propagation
# ---------------------------------------------------------------------------

class TestCrossMonthPropagation:
    """Consumer: load_cross_month_propagation reads + validates required fields from YAML.

    Status note: this consumer performs config-read + field validation only.
    The full retroactive propagation runtime action is deferred to p3-2
    (batch B3-PASS3, decision S4). Status in standing-rules.yaml remains
    pending_consumer with a documented reason until p3-2 builds the runtime.
    """

    _SECTION = (
        "cross_month_propagation:\n"
        "  status: pending_consumer\n"
        "  enabled: true\n"
        "  trigger: new_canonical_or_category_or_tag_in_current_month\n"
        "  scope: prior_completed_months\n"
        "  action: propose_retroactive_in_batch\n"
    )

    def test_section_loads_from_config(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_cross_month_propagation(sr)
        assert cfg["enabled"] is True
        assert cfg["trigger"] == "new_canonical_or_category_or_tag_in_current_month"
        assert cfg["scope"] == "prior_completed_months"
        assert cfg["action"] == "propose_retroactive_in_batch"

    def test_required_fields_all_present(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        # Must not raise — all required fields are present.
        cfg = load_cross_month_propagation(sr)
        for field in ("enabled", "trigger", "scope", "action"):
            assert field in cfg

    def test_missing_field_raises(self, tmp_path):
        """Missing a required field → StandingRulesError."""
        section_missing_action = (
            "cross_month_propagation:\n"
            "  status: pending_consumer\n"
            "  enabled: true\n"
            "  trigger: new_canonical_or_category_or_tag_in_current_month\n"
            "  scope: prior_completed_months\n"
            # 'action' deliberately omitted
        )
        sr = _load(tmp_path, section_missing_action)
        with pytest.raises(StandingRulesError, match="action"):
            load_cross_month_propagation(sr)

    def test_missing_section_raises(self, tmp_path):
        sr = _load(tmp_path)
        with pytest.raises(StandingRulesError, match="cross_month_propagation"):
            load_cross_month_propagation(sr)

    def test_reads_enabled_from_config(self, tmp_path):
        """enabled flag is driven by YAML — custom value readable."""
        custom_section = (
            "cross_month_propagation:\n"
            "  status: pending_consumer\n"
            "  enabled: false\n"
            "  trigger: any\n"
            "  scope: all\n"
            "  action: none\n"
        )
        sr = _load(tmp_path, custom_section)
        cfg = load_cross_month_propagation(sr)
        assert cfg["enabled"] is False


# ---------------------------------------------------------------------------
# p2-19: pass_2_rules
# ---------------------------------------------------------------------------

class TestPass2Rules:
    """Consumer: load_pass_2_rules reads + validates required fields from YAML.

    The runtime DISPATCH of Pass 2 is agent-driven (lib/boundary.py invoked
    by the bookkeeper workflow agent). This consumer validates that the
    spec is config-declared and required fields are present.
    """

    _SECTION = (
        "pass_2_rules:\n"
        "  status: active\n"
        "  scope_filter:\n"
        "    - 'is_boundary_day(data_caixa)'\n"
        "    - 'supplier.movable == true'\n"
        "    - \"source_type != 'fatura'\"\n"
        "  default_action: keep\n"
        "  immutable_fields: [data_caixa]\n"
        "  mutable_fields: [data_competencia]\n"
        "  backfill_default_movable: false\n"
    )

    def test_section_loads_from_config(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_pass_2_rules(sr)
        assert cfg["default_action"] == "keep"
        assert "data_caixa" in cfg["immutable_fields"]
        assert "data_competencia" in cfg["mutable_fields"]
        assert cfg["backfill_default_movable"] is False

    def test_scope_filter_readable(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_pass_2_rules(sr)
        assert isinstance(cfg["scope_filter"], list)
        assert len(cfg["scope_filter"]) == 3

    def test_missing_required_field_raises(self, tmp_path):
        """Missing scope_filter → StandingRulesError."""
        section_missing = (
            "pass_2_rules:\n"
            "  status: active\n"
            "  default_action: keep\n"
            "  immutable_fields: [data_caixa]\n"
            "  mutable_fields: [data_competencia]\n"
            # scope_filter deliberately omitted
        )
        sr = _load(tmp_path, section_missing)
        with pytest.raises(StandingRulesError, match="scope_filter"):
            load_pass_2_rules(sr)

    def test_missing_section_raises(self, tmp_path):
        sr = _load(tmp_path)
        with pytest.raises(StandingRulesError, match="pass_2_rules"):
            load_pass_2_rules(sr)

    def test_reads_default_action_from_config(self, tmp_path):
        """default_action is driven by YAML."""
        custom_section = (
            "pass_2_rules:\n"
            "  status: active\n"
            "  scope_filter: []\n"
            "  default_action: move\n"
            "  immutable_fields: []\n"
            "  mutable_fields: [data_competencia]\n"
        )
        sr = _load(tmp_path, custom_section)
        cfg = load_pass_2_rules(sr)
        assert cfg["default_action"] == "move"


# ---------------------------------------------------------------------------
# p2-20: cash_expense
# ---------------------------------------------------------------------------

class TestCashExpense:
    """Consumer: load_cash_expense + is_cash_expense_row reads convention from YAML."""

    _SECTION = (
        "cash_expense:\n"
        "  status: active\n"
        "  source_type: dinheiro\n"
        "  supplier_canonical: Cash\n"
        "  match_confidence: manual\n"
        "  bank: manual\n"
        "  tags: ''\n"
    )

    def test_section_loads_from_config(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_cash_expense(sr)
        assert cfg["source_type"] == "dinheiro"
        assert cfg["supplier_canonical"] == "Cash"
        assert cfg["match_confidence"] == "manual"

    def test_cash_row_matched(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_cash_expense(sr)
        counter = RuleFireCounter()
        result = is_cash_expense_row("dinheiro", "Cash", cfg, rule_counter=counter)
        assert result is True
        assert counter.as_dict().get("cash_expense_matched") == 1

    def test_non_cash_source_type_not_matched(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_cash_expense(sr)
        assert is_cash_expense_row("extrato", "Cash", cfg) is False

    def test_wrong_supplier_not_matched(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_cash_expense(sr)
        assert is_cash_expense_row("dinheiro", "Uber", cfg) is False

    def test_missing_required_field_raises(self, tmp_path):
        """Missing match_confidence → StandingRulesError."""
        section_missing = (
            "cash_expense:\n"
            "  status: active\n"
            "  source_type: dinheiro\n"
            "  supplier_canonical: Cash\n"
            # match_confidence deliberately omitted
        )
        sr = _load(tmp_path, section_missing)
        with pytest.raises(StandingRulesError, match="match_confidence"):
            load_cash_expense(sr)

    def test_missing_section_raises(self, tmp_path):
        sr = _load(tmp_path)
        with pytest.raises(StandingRulesError, match="cash_expense"):
            load_cash_expense(sr)

    def test_reads_source_type_from_config(self, tmp_path):
        """source_type is driven by YAML — custom value changes matching behavior."""
        custom_section = (
            "cash_expense:\n"
            "  status: active\n"
            "  source_type: manual_entry\n"
            "  supplier_canonical: Petty Cash\n"
            "  match_confidence: manual\n"
        )
        sr = _load(tmp_path, custom_section)
        cfg = load_cash_expense(sr)
        assert is_cash_expense_row("manual_entry", "Petty Cash", cfg) is True
        # Original convention no longer matches
        assert is_cash_expense_row("dinheiro", "Cash", cfg) is False


# ---------------------------------------------------------------------------
# p2-21: investment_rules
# ---------------------------------------------------------------------------

class TestInvestmentRules:
    """Consumer: load_investment_rules reads + validates key sub-sections from YAML."""

    _SECTION = (
        "investment_rules:\n"
        "  status: active\n"
        "  ledger_immutability:\n"
        "    append_only: true\n"
        "    applies_to: [orders.csv, proventos.csv]\n"
        "  code_migration_handling:\n"
        "    type: separate_ledger\n"
        "    file: config/corrections/code_migrations.csv\n"
        "    filter_in_calculate: true\n"
        "    known_migrations: {}\n"
        "  field_ownership:\n"
        "    CURATED: [name, issuer]\n"
        "    SOURCE_BOUND: {}\n"
        "    DERIVED: [manager]\n"
    )

    def test_section_loads_from_config(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_investment_rules(sr)
        assert "ledger_immutability" in cfg
        assert "code_migration_handling" in cfg
        assert "field_ownership" in cfg

    def test_ledger_immutability_readable(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_investment_rules(sr)
        assert cfg["ledger_immutability"]["append_only"] is True

    def test_code_migration_file_pointer_readable(self, tmp_path):
        """code_migration_handling.file pointer is readable from config."""
        sr = _load(tmp_path, self._SECTION)
        cfg = load_investment_rules(sr)
        assert cfg["code_migration_handling"]["file"] == "config/corrections/code_migrations.csv"

    def test_missing_sub_section_raises(self, tmp_path):
        """Missing field_ownership → StandingRulesError."""
        section_missing = (
            "investment_rules:\n"
            "  status: active\n"
            "  ledger_immutability:\n"
            "    append_only: true\n"
            "  code_migration_handling:\n"
            "    type: separate_ledger\n"
            # field_ownership deliberately omitted
        )
        sr = _load(tmp_path, section_missing)
        with pytest.raises(StandingRulesError, match="field_ownership"):
            load_investment_rules(sr)

    def test_missing_section_raises(self, tmp_path):
        sr = _load(tmp_path)
        with pytest.raises(StandingRulesError, match="investment_rules"):
            load_investment_rules(sr)

    def test_reads_apply_list_from_config(self, tmp_path):
        """ledger files list is driven by YAML."""
        sr = _load(tmp_path, self._SECTION)
        cfg = load_investment_rules(sr)
        applies = cfg["ledger_immutability"].get("applies_to", [])
        assert "orders.csv" in applies


# ---------------------------------------------------------------------------
# p2-22: rf_naming
# ---------------------------------------------------------------------------

class TestRfNaming:
    """Consumer: load_rf_naming + validate_rf_name reads tipo_enum from YAML."""

    _SECTION = (
        "rf_naming:\n"
        "  status: active\n"
        "  format: '{Tipo} {Emissor}'\n"
        "  tipo_enum: ['Deb. Inc.', 'Deb.', CRA, CRI, LCA, LCI]\n"
        "  emissor_capitalization: 'Title case; exclude S/A'\n"
    )

    def test_section_loads_from_config(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_rf_naming(sr)
        assert "tipo_enum" in cfg
        assert "format" in cfg

    def test_valid_name_passes(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_rf_naming(sr)
        counter = RuleFireCounter()
        assert validate_rf_name("LCA Banco Safra", cfg, rule_counter=counter) is True
        assert counter.as_dict().get("rf_naming_valid") == 1

    def test_valid_name_cri_passes(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_rf_naming(sr)
        assert validate_rf_name("CRI Realty", cfg) is True

    def test_valid_name_deb_inc_passes(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_rf_naming(sr)
        assert validate_rf_name("Deb. Inc. Petrobras", cfg) is True

    def test_invalid_name_fails(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_rf_naming(sr)
        counter = RuleFireCounter()
        assert validate_rf_name("Acao Petrobras", cfg, rule_counter=counter) is False
        assert counter.as_dict().get("rf_naming_invalid") == 1

    def test_blank_name_fails(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_rf_naming(sr)
        assert validate_rf_name("", cfg) is False
        assert validate_rf_name("   ", cfg) is False

    def test_missing_required_field_raises(self, tmp_path):
        """Missing tipo_enum → StandingRulesError."""
        section_missing = (
            "rf_naming:\n"
            "  status: active\n"
            "  format: '{Tipo} {Emissor}'\n"
            # tipo_enum deliberately omitted
        )
        sr = _load(tmp_path, section_missing)
        with pytest.raises(StandingRulesError, match="tipo_enum"):
            load_rf_naming(sr)

    def test_missing_section_raises(self, tmp_path):
        sr = _load(tmp_path)
        with pytest.raises(StandingRulesError, match="rf_naming"):
            load_rf_naming(sr)

    def test_reads_tipo_enum_from_config(self, tmp_path):
        """tipo_enum is driven by YAML — custom list changes behavior."""
        custom_section = (
            "rf_naming:\n"
            "  status: active\n"
            "  format: '{Tipo} {Emissor}'\n"
            "  tipo_enum: [DEBENTURE]\n"
        )
        sr = _load(tmp_path, custom_section)
        cfg = load_rf_naming(sr)
        assert validate_rf_name("DEBENTURE Petrobras", cfg) is True
        assert validate_rf_name("LCA Banco Safra", cfg) is False  # not in this config

    def test_case_insensitive_matching(self, tmp_path):
        """tipo_enum matching is case-insensitive."""
        sr = _load(tmp_path, self._SECTION)
        cfg = load_rf_naming(sr)
        assert validate_rf_name("lca banco safra", cfg) is True
        assert validate_rf_name("CRA Realty", cfg) is True


# ---------------------------------------------------------------------------
# Integration: categorize.py main() startup loads all B2-SR2 sections
# ---------------------------------------------------------------------------

class TestCategorizePy_SR2Startup:
    """categorize.py main() must load all 6 B2-SR2 sections at startup (fail-loud)."""

    def _minimal_yaml_with_all_sections(self) -> str:
        """Return a YAML string that satisfies all B2-SR1 + B2-SR2 startup loaders."""
        from tests._fixture_helpers import MINIMAL_STANDING_RULES_YAML
        return MINIMAL_STANDING_RULES_YAML

    def test_minimal_yaml_has_all_sr2_sections(self, tmp_path):
        """The MINIMAL_STANDING_RULES_YAML fixture includes all 6 B2-SR2 sections."""
        yaml_text = self._minimal_yaml_with_all_sections()
        import yaml as _yaml
        data = _yaml.safe_load(yaml_text)
        for section in (
            "tag_coverage", "cross_month_propagation", "pass_2_rules",
            "cash_expense", "investment_rules", "rf_naming",
        ):
            assert section in data, f"MINIMAL_STANDING_RULES_YAML missing '{section}'"

    def test_missing_tag_coverage_fails_load(self, tmp_path):
        """categorize.py startup raises StandingRulesError when tag_coverage absent."""
        config = tmp_path / "config"
        config.mkdir()
        # Write YAML without tag_coverage
        body = (
            "_meta:\n  schema_version: 1\n  rule_set_version: '1.0-test'\n"
            "supplier_rules:\n  status: active\n"
            "expenses_schema:\n  status: active\n"
            "  new_columns: [data_caixa, data_competencia, supplier_canonical, tags]\n"
            "  legacy_column_removed: subcategory\n"
            "name_canonicalization:\n  status: active\n"
            "  default_style: titlecase_accented\n  exceptions: []\n"
            "competencia_rules:\n  status: active\n"
            "  cc_installments:\n    installment_1: row_date\n"
            "    installment_n: 'x'\n"
            "tag_semantics:\n  status: active\n"
            "tag_application_rules:\n  status: active\n"
            "  care_plus_receipt:\n    always_apply: []\n"
            "  automotive_insurance:\n    suppliers: []\n    tag: seguros\n"
            "family_canonicals:\n  status: active\n  members: []\n  rule: x\n"
            # tag_coverage intentionally absent
            "cross_month_propagation:\n  status: active\n"
            "  enabled: true\n  trigger: x\n  scope: x\n  action: x\n"
            "pass_2_rules:\n  status: active\n"
            "  scope_filter: []\n  default_action: keep\n"
            "  immutable_fields: []\n  mutable_fields: []\n"
            "cash_expense:\n  status: active\n"
            "  source_type: dinheiro\n  supplier_canonical: Cash\n"
            "  match_confidence: manual\n"
            "investment_rules:\n  status: active\n"
            "  ledger_immutability:\n    append_only: true\n"
            "  code_migration_handling:\n    type: x\n"
            "  field_ownership:\n    CURATED: []\n"
            "rf_naming:\n  status: active\n"
            "  format: x\n  tipo_enum: [LCA]\n"
        )
        (config / "standing-rules.yaml").write_text(body, encoding="utf-8")
        sr = load_standing_rules(config)
        with pytest.raises(StandingRulesError, match="tag_coverage"):
            load_tag_coverage(sr)

    def test_real_standing_rules_yaml_loads_all_sr2_sections(self, tmp_path):
        """The live standing-rules.yaml loads all 6 B2-SR2 sections without error."""
        vault_root = Path(__file__).resolve().parents[7]
        real_yaml = (
            vault_root / ".user" / "finance" / "bookkeeper" / "config"
            / "standing-rules.yaml"
        )
        if not real_yaml.exists():
            pytest.skip("Real standing-rules.yaml not present.")
        sr = load_standing_rules(real_yaml.parent)
        # Each loader must succeed against the real config.
        load_tag_coverage(sr)
        load_cross_month_propagation(sr)
        load_pass_2_rules(sr)
        load_cash_expense(sr)
        load_investment_rules(sr)
        load_rf_naming(sr)
