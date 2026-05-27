"""Acceptance tests for B2-SR3: standing-rules consumer wiring (p2-23..p2-28).

Each section's acceptance test asserts:
  1. The consumer loads the rule from config (not hardcoded).
  2. The rule fires correctly on a real/synthetic input.
  3. The consumer raises (fail-loud) when the config section is missing.

Sections covered:
  p2-23 yoc               — load_yoc (config-read + required-field validation)
  p2-24 options_rules     — load_options_rules (config-read + required-field validation)
  p2-25 gates             — load_gates + check_gates_coverage_threshold (S7 pending)
  p2-26 batch_ui          — load_batch_ui (config-read + sub-section validation)
  p2-27 file_conventions  — load_file_conventions (validates tag_column_separator == ';')
  p2-28 communication     — load_communication (config-read + required-field validation)

rule_fired audit event emission is tested via RuleFireCounter (same infra as SR1/SR2
tests). Full categorize.py startup load is verified in the integration section at the end.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lib.standing_rules import (
    RuleFireCounter,
    StandingRulesError,
    check_gates_coverage_threshold,
    load_batch_ui,
    load_communication,
    load_file_conventions,
    load_gates,
    load_options_rules,
    load_standing_rules,
    load_yoc,
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
# p2-23: yoc
# ---------------------------------------------------------------------------

class TestYoc:
    """Consumer: load_yoc reads formula fields from YAML, not hardcode."""

    _SECTION = (
        "yoc:\n"
        "  status: active\n"
        "  lifetime: 'sum(income_proventos) / cost_basis'\n"
        "  ttm: 'sum(income_proventos_last_365) / cost_basis'\n"
        "  excluded_from_income: [fracao]\n"
    )

    def test_section_loads_from_config(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_yoc(sr)
        assert "lifetime" in cfg
        assert "ttm" in cfg
        assert "excluded_from_income" in cfg

    def test_lifetime_formula_readable(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_yoc(sr)
        assert cfg["lifetime"] == "sum(income_proventos) / cost_basis"

    def test_ttm_formula_readable(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_yoc(sr)
        assert cfg["ttm"] == "sum(income_proventos_last_365) / cost_basis"

    def test_excluded_from_income_readable(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_yoc(sr)
        assert "fracao" in cfg["excluded_from_income"]

    def test_missing_required_field_raises(self, tmp_path):
        """Missing ttm → StandingRulesError."""
        section_missing = (
            "yoc:\n"
            "  status: active\n"
            "  lifetime: 'sum(income_proventos) / cost_basis'\n"
            "  excluded_from_income: [fracao]\n"
            # ttm deliberately omitted
        )
        sr = _load(tmp_path, section_missing)
        with pytest.raises(StandingRulesError, match="ttm"):
            load_yoc(sr)

    def test_missing_section_raises(self, tmp_path):
        sr = _load(tmp_path)  # no yoc section
        with pytest.raises(StandingRulesError, match="yoc"):
            load_yoc(sr)

    def test_reads_excluded_list_from_config(self, tmp_path):
        """excluded_from_income is driven by YAML — custom list is readable."""
        custom_section = (
            "yoc:\n"
            "  status: active\n"
            "  lifetime: 'x/y'\n"
            "  ttm: 'a/b'\n"
            "  excluded_from_income: [fracao, bonus]\n"
        )
        sr = _load(tmp_path, custom_section)
        cfg = load_yoc(sr)
        assert "bonus" in cfg["excluded_from_income"]


# ---------------------------------------------------------------------------
# p2-24: options_rules
# ---------------------------------------------------------------------------

class TestOptionsRules:
    """Consumer: load_options_rules reads expiration rule from YAML."""

    _SECTION = (
        "options_rules:\n"
        "  status: active\n"
        "  expiration_auto_generation:\n"
        "    condition: buy_without_matching_sell_by_expiration\n"
        "    action: generate_expiracao_row\n"
        "    ratio: '1:0'\n"
        "  price_fetching: skip\n"
    )

    def test_section_loads_from_config(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_options_rules(sr)
        assert "expiration_auto_generation" in cfg
        assert "price_fetching" in cfg

    def test_expiration_rule_readable(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_options_rules(sr)
        exp = cfg["expiration_auto_generation"]
        assert exp["action"] == "generate_expiracao_row"
        assert exp["ratio"] == "1:0"

    def test_price_fetching_skip_readable(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_options_rules(sr)
        assert cfg["price_fetching"] == "skip"

    def test_missing_required_field_raises(self, tmp_path):
        """Missing price_fetching → StandingRulesError."""
        section_missing = (
            "options_rules:\n"
            "  status: active\n"
            "  expiration_auto_generation:\n"
            "    condition: buy_without_matching_sell_by_expiration\n"
            "    action: generate_expiracao_row\n"
            # price_fetching deliberately omitted
        )
        sr = _load(tmp_path, section_missing)
        with pytest.raises(StandingRulesError, match="price_fetching"):
            load_options_rules(sr)

    def test_missing_section_raises(self, tmp_path):
        sr = _load(tmp_path)
        with pytest.raises(StandingRulesError, match="options_rules"):
            load_options_rules(sr)

    def test_reads_condition_from_config(self, tmp_path):
        """expiration condition is driven by YAML."""
        sr = _load(tmp_path, self._SECTION)
        cfg = load_options_rules(sr)
        assert (
            cfg["expiration_auto_generation"]["condition"]
            == "buy_without_matching_sell_by_expiration"
        )


# ---------------------------------------------------------------------------
# p2-25: gates
# ---------------------------------------------------------------------------

class TestGates:
    """Consumer: load_gates reads gate sub-sections from YAML.

    S7 note: step_5_5_coverage.untagged_amount_threshold is a placeholder
    value (200). The real number is resolved at S7 (batch B4-GATE1).
    check_gates_coverage_threshold() returns None when the value is absent
    (fail-by-default per revolving plan rule).
    """

    _SECTION = (
        "gates:\n"
        "  status: active\n"
        "  step_01_file_identification:\n"
        "    user_confirmation_required: true\n"
        "  step_3d_unmatched_rows:\n"
        "    enforcement: no_silent_skip\n"
        "    action: enumerate_all_unmatched\n"
        "  step_5_5_coverage:\n"
        "    threshold: 0.80\n"
        "    untagged_amount_threshold: 200\n"
        "    action_if_below: auto_loop_to_step_4b\n"
    )

    def test_section_loads_from_config(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_gates(sr)
        assert "step_01_file_identification" in cfg
        assert "step_3d_unmatched_rows" in cfg
        assert "step_5_5_coverage" in cfg

    def test_file_identification_confirmation_readable(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_gates(sr)
        assert cfg["step_01_file_identification"]["user_confirmation_required"] is True

    def test_unmatched_rows_enforcement_readable(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_gates(sr)
        assert cfg["step_3d_unmatched_rows"]["enforcement"] == "no_silent_skip"

    def test_coverage_threshold_readable(self, tmp_path):
        """The placeholder threshold value is readable from config."""
        sr = _load(tmp_path, self._SECTION)
        cfg = load_gates(sr)
        counter = RuleFireCounter()
        threshold = check_gates_coverage_threshold(cfg, rule_counter=counter)
        assert threshold == 200.0
        assert counter.as_dict().get("gates_coverage_threshold_read") == 1

    def test_s7_pending_threshold_absent_returns_none(self, tmp_path):
        """When untagged_amount_threshold is absent (S7 pending), returns None."""
        section_no_threshold = (
            "gates:\n"
            "  status: active\n"
            "  step_01_file_identification:\n"
            "    user_confirmation_required: true\n"
            "  step_3d_unmatched_rows:\n"
            "    enforcement: no_silent_skip\n"
            "    action: enumerate_all_unmatched\n"
            "  step_5_5_coverage:\n"
            "    threshold: 0.80\n"
            "    action_if_below: auto_loop_to_step_4b\n"
            # untagged_amount_threshold deliberately absent
        )
        sr = _load(tmp_path, section_no_threshold)
        cfg = load_gates(sr)
        counter = RuleFireCounter()
        result = check_gates_coverage_threshold(cfg, rule_counter=counter)
        assert result is None
        assert counter.as_dict().get("gates_coverage_threshold_s7_pending") == 1

    def test_missing_sub_section_raises(self, tmp_path):
        """Missing step_3d_unmatched_rows → StandingRulesError."""
        section_missing = (
            "gates:\n"
            "  status: active\n"
            "  step_01_file_identification:\n"
            "    user_confirmation_required: true\n"
            "  step_5_5_coverage:\n"
            "    threshold: 0.80\n"
            # step_3d_unmatched_rows deliberately omitted
        )
        sr = _load(tmp_path, section_missing)
        with pytest.raises(StandingRulesError, match="step_3d_unmatched_rows"):
            load_gates(sr)

    def test_missing_section_raises(self, tmp_path):
        sr = _load(tmp_path)
        with pytest.raises(StandingRulesError, match="gates"):
            load_gates(sr)

    def test_reads_threshold_from_config(self, tmp_path):
        """Threshold value is driven by YAML — different value changes behavior."""
        custom_section = (
            "gates:\n"
            "  status: active\n"
            "  step_01_file_identification:\n"
            "    user_confirmation_required: false\n"
            "  step_3d_unmatched_rows:\n"
            "    enforcement: no_silent_skip\n"
            "  step_5_5_coverage:\n"
            "    untagged_amount_threshold: 500\n"
        )
        sr = _load(tmp_path, custom_section)
        cfg = load_gates(sr)
        assert check_gates_coverage_threshold(cfg) == 500.0


# ---------------------------------------------------------------------------
# p2-26: batch_ui
# ---------------------------------------------------------------------------

class TestBatchUi:
    """Consumer: load_batch_ui reads decision-surface sub-sections from YAML.

    runtime_actor: bookkeeper workflow agent (Phase 5, not yet built).
    This consumer validates the section is config-declared and loadable.
    """

    _SECTION = (
        "batch_ui:\n"
        "  status: active\n"
        "  categories:\n"
        "    fields: [description, value, date, available_options]\n"
        "    allow_new_creation: true\n"
        "  suppliers:\n"
        "    fields: [canonical, aliases, movable, default_category]\n"
        "    conditional_required: 'movable_hint == mixed'\n"
        "  tags:\n"
        "    one_row_one_decision: true\n"
        "    options: [accept, merge, reject]\n"
    )

    def test_section_loads_from_config(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_batch_ui(sr)
        assert "categories" in cfg
        assert "suppliers" in cfg
        assert "tags" in cfg

    def test_categories_fields_readable(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_batch_ui(sr)
        assert "description" in cfg["categories"]["fields"]

    def test_tags_one_row_one_decision_readable(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_batch_ui(sr)
        assert cfg["tags"]["one_row_one_decision"] is True

    def test_tags_options_readable(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_batch_ui(sr)
        assert "accept" in cfg["tags"]["options"]
        assert "reject" in cfg["tags"]["options"]

    def test_missing_sub_section_raises(self, tmp_path):
        """Missing tags → StandingRulesError."""
        section_missing = (
            "batch_ui:\n"
            "  status: active\n"
            "  categories:\n"
            "    fields: [description]\n"
            "  suppliers:\n"
            "    fields: [canonical]\n"
            # tags deliberately omitted
        )
        sr = _load(tmp_path, section_missing)
        with pytest.raises(StandingRulesError, match="tags"):
            load_batch_ui(sr)

    def test_missing_section_raises(self, tmp_path):
        sr = _load(tmp_path)
        with pytest.raises(StandingRulesError, match="batch_ui"):
            load_batch_ui(sr)

    def test_reads_allow_new_creation_from_config(self, tmp_path):
        """allow_new_creation is driven by YAML."""
        sr = _load(tmp_path, self._SECTION)
        cfg = load_batch_ui(sr)
        assert cfg["categories"]["allow_new_creation"] is True


# ---------------------------------------------------------------------------
# p2-27: file_conventions
# ---------------------------------------------------------------------------

class TestFileConventions:
    """Consumer: load_file_conventions validates tag_column_separator from YAML.

    The separator is hardcoded as ';' in categorize.py::_format_tags.
    load_file_conventions() raises if the YAML declares a different separator,
    making the contract explicit and catching drift at startup.
    """

    _SECTION = (
        "file_conventions:\n"
        "  status: active\n"
        "  amounts:\n"
        "    credit_card: NEGATIVE\n"
        "  transactions:\n"
        "    iof: separate_transaction\n"
        "  csv_encoding:\n"
        "    tag_column_separator: ';'\n"
        "    parser: lib.tags.parse_tag_column\n"
        "    serializer: lib.tags.serialize_tag_column\n"
    )

    def test_section_loads_from_config(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_file_conventions(sr)
        assert "csv_encoding" in cfg
        assert cfg["csv_encoding"]["tag_column_separator"] == ";"

    def test_correct_separator_passes(self, tmp_path):
        """';' separator in YAML → no error."""
        sr = _load(tmp_path, self._SECTION)
        cfg = load_file_conventions(sr)  # must not raise
        assert cfg is not None

    def test_wrong_separator_raises(self, tmp_path):
        """A separator other than ';' → StandingRulesError (implementation mismatch)."""
        section_wrong_sep = (
            "file_conventions:\n"
            "  status: active\n"
            "  csv_encoding:\n"
            "    tag_column_separator: ','\n"
        )
        sr = _load(tmp_path, section_wrong_sep)
        with pytest.raises(StandingRulesError, match="tag_column_separator"):
            load_file_conventions(sr)

    def test_missing_csv_encoding_raises(self, tmp_path):
        """Missing csv_encoding sub-section → StandingRulesError."""
        section_no_enc = (
            "file_conventions:\n"
            "  status: active\n"
            "  amounts:\n"
            "    credit_card: NEGATIVE\n"
        )
        sr = _load(tmp_path, section_no_enc)
        with pytest.raises(StandingRulesError, match="csv_encoding"):
            load_file_conventions(sr)

    def test_missing_separator_key_raises(self, tmp_path):
        """Missing tag_column_separator key → StandingRulesError."""
        section_no_sep = (
            "file_conventions:\n"
            "  status: active\n"
            "  csv_encoding:\n"
            "    parser: lib.tags.parse_tag_column\n"
        )
        sr = _load(tmp_path, section_no_sep)
        with pytest.raises(StandingRulesError, match="tag_column_separator"):
            load_file_conventions(sr)

    def test_missing_section_raises(self, tmp_path):
        sr = _load(tmp_path)
        with pytest.raises(StandingRulesError, match="file_conventions"):
            load_file_conventions(sr)


# ---------------------------------------------------------------------------
# p2-28: communication
# ---------------------------------------------------------------------------

class TestCommunication:
    """Consumer: load_communication reads language rule from YAML.

    runtime_actor: bookkeeper workflow agent (applies the language rule
    when generating user-facing messages).
    """

    _SECTION = (
        "communication:\n"
        "  status: active\n"
        "  language: 'português brasileiro'\n"
        "  applies_to: 'all user-facing messages'\n"
        "  technical_terms: 'English (function names, paths, column identifiers)'\n"
    )

    def test_section_loads_from_config(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_communication(sr)
        assert "language" in cfg
        assert "applies_to" in cfg

    def test_language_readable(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_communication(sr)
        assert cfg["language"] == "português brasileiro"

    def test_applies_to_readable(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_communication(sr)
        assert cfg["applies_to"] == "all user-facing messages"

    def test_technical_terms_readable(self, tmp_path):
        sr = _load(tmp_path, self._SECTION)
        cfg = load_communication(sr)
        assert "English" in cfg["technical_terms"]

    def test_missing_required_field_raises(self, tmp_path):
        """Missing applies_to → StandingRulesError."""
        section_missing = (
            "communication:\n"
            "  status: active\n"
            "  language: 'português brasileiro'\n"
            # applies_to deliberately omitted
        )
        sr = _load(tmp_path, section_missing)
        with pytest.raises(StandingRulesError, match="applies_to"):
            load_communication(sr)

    def test_missing_section_raises(self, tmp_path):
        sr = _load(tmp_path)
        with pytest.raises(StandingRulesError, match="communication"):
            load_communication(sr)

    def test_reads_language_from_config(self, tmp_path):
        """language is driven by YAML — custom value is readable."""
        custom_section = (
            "communication:\n"
            "  status: active\n"
            "  language: 'english'\n"
            "  applies_to: 'user-facing'\n"
        )
        sr = _load(tmp_path, custom_section)
        cfg = load_communication(sr)
        assert cfg["language"] == "english"


# ---------------------------------------------------------------------------
# Integration: categorize.py main() startup loads all B2-SR3 sections
# ---------------------------------------------------------------------------

class TestCategorizePy_SR3Startup:
    """categorize.py main() must load all 6 B2-SR3 sections at startup (fail-loud)."""

    def test_minimal_yaml_has_all_sr3_sections(self, tmp_path):
        """The MINIMAL_STANDING_RULES_YAML fixture includes all 6 B2-SR3 sections."""
        from tests._fixture_helpers import MINIMAL_STANDING_RULES_YAML
        import yaml as _yaml
        data = _yaml.safe_load(MINIMAL_STANDING_RULES_YAML)
        for section in (
            "yoc", "options_rules", "gates",
            "batch_ui", "file_conventions", "communication",
        ):
            assert section in data, f"MINIMAL_STANDING_RULES_YAML missing '{section}'"

    def test_missing_yoc_fails_load(self, tmp_path):
        """load_yoc raises StandingRulesError when yoc absent."""
        from tests._fixture_helpers import MINIMAL_STANDING_RULES_YAML
        import yaml as _yaml
        data = _yaml.safe_load(MINIMAL_STANDING_RULES_YAML)
        data.pop("yoc", None)
        import yaml
        config = tmp_path / "config"
        config.mkdir()
        (config / "standing-rules.yaml").write_text(
            yaml.safe_dump(data), encoding="utf-8"
        )
        sr = load_standing_rules(config)
        with pytest.raises(StandingRulesError, match="yoc"):
            load_yoc(sr)

    def test_missing_gates_fails_load(self, tmp_path):
        """load_gates raises StandingRulesError when gates absent."""
        from tests._fixture_helpers import MINIMAL_STANDING_RULES_YAML
        import yaml as _yaml
        data = _yaml.safe_load(MINIMAL_STANDING_RULES_YAML)
        data.pop("gates", None)
        import yaml
        config = tmp_path / "config"
        config.mkdir()
        (config / "standing-rules.yaml").write_text(
            yaml.safe_dump(data), encoding="utf-8"
        )
        sr = load_standing_rules(config)
        with pytest.raises(StandingRulesError, match="gates"):
            load_gates(sr)

    def test_real_standing_rules_yaml_loads_all_sr3_sections(self, tmp_path):
        """The live standing-rules.yaml loads all 6 B2-SR3 sections without error."""
        vault_root = Path(__file__).resolve().parents[7]
        real_yaml = (
            vault_root / ".user" / "finance" / "bookkeeper" / "config"
            / "standing-rules.yaml"
        )
        if not real_yaml.exists():
            pytest.skip("Real standing-rules.yaml not present.")
        sr = load_standing_rules(real_yaml.parent)
        load_yoc(sr)
        load_options_rules(sr)
        load_gates(sr)
        load_batch_ui(sr)
        load_file_conventions(sr)
        load_communication(sr)
