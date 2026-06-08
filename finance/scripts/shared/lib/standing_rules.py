"""Standing-rules loader + rule-fire instrumentation.

Spec: `1-projects/finance-system/finance-system-v2-foundation/phase-1/p1-20.task.md`.

Loads the declarative standing-rules registry from
`.user/finance/bookkeeper/config/standing-rules.yaml` and provides a small
helper for in-script consumers (categorize.py today; more later) to count
rule-fires per script run and emit a single summary `rule_fired` audit event
at the end. Per the audit-event protocol's "one event per (source_file,
destination_path) per script run" granularity choice, per-row events are
intentionally avoided.

Failure mode is fail-loud at startup (per Standing-rules Decision: "Confirm
the same close without the YAML (rename it temporarily) produces a clean
fail-loud (not silent fallback)."). After load, the instrumentation helper
itself is best-effort — never raises into the calling script.

B2-SR1 consumers (p2-11…p2-16): each function reads its named section from
the standing-rules dict returned by `load_standing_rules` and applies
deterministic rule logic. Consumers are called from categorize.py; fires are
recorded via RuleFireCounter and emitted as a single `rule_fired` event at
the end of the run.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from . import audit


REQUIRED_TOP_LEVEL_SECTIONS = {
    "_meta",
    "supplier_rules",
}

REQUIRED_META_FIELDS = {"schema_version", "rule_set_version"}

SUPPORTED_SCHEMA_VERSION = 1


class StandingRulesError(RuntimeError):
    """Raised when the standing-rules YAML is missing or malformed."""


class ThresholdProvenanceError(StandingRulesError):
    """Raised when a config-provided gate threshold lacks valid provenance for
    the metric consuming it (compound cp-sb-bookkeeper-gates-measure-meaning,
    change 3).

    Two cases, both the "inherited / un-owned threshold" failure class exposed by
    the 2026-06-05 coverage-gate incident:
      - the threshold is present in config but carries no provenance block; or
      - the provenance block names a `metric` different from the metric the gate
        applies the threshold to (a number decided for metric X binding metric Y).

    Subclasses StandingRulesError so config-load handlers can still catch it, but
    gate programs MUST NOT swallow it into a fallback: a threshold the config DID
    provide must be honestly owned, never silently bypassed.
    """


def standing_rules_path(config_folder: Path | str) -> Path:
    """Canonical path to the rules file inside a bookkeeper config folder."""
    return Path(config_folder) / "standing-rules.yaml"


def load_standing_rules(config_folder: Path | str) -> dict[str, Any]:
    """Load + validate the declarative standing-rules registry.

    Raises `StandingRulesError` on any failure (missing file, parse error,
    missing required section, unsupported schema version). Callers SHOULD
    let the exception propagate so the script halts loudly rather than
    silently degrading.
    """
    path = standing_rules_path(config_folder)
    if not path.exists():
        raise StandingRulesError(
            f"standing-rules.yaml not found at {path}. The categorizer "
            f"requires the declarative rules registry to run."
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise StandingRulesError(
            f"standing-rules.yaml at {path} failed to parse: {e}"
        ) from e

    if not isinstance(data, dict):
        raise StandingRulesError(
            f"standing-rules.yaml at {path} must be a YAML mapping at the top level"
        )

    missing = REQUIRED_TOP_LEVEL_SECTIONS - data.keys()
    if missing:
        raise StandingRulesError(
            f"standing-rules.yaml missing required sections: {sorted(missing)}"
        )

    meta = data.get("_meta") or {}
    if not isinstance(meta, dict):
        raise StandingRulesError("standing-rules.yaml `_meta` must be a mapping")
    missing_meta = REQUIRED_META_FIELDS - meta.keys()
    if missing_meta:
        raise StandingRulesError(
            f"standing-rules.yaml `_meta` missing fields: {sorted(missing_meta)}"
        )
    if meta.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise StandingRulesError(
            f"standing-rules.yaml schema_version "
            f"{meta.get('schema_version')!r} unsupported; expected "
            f"{SUPPORTED_SCHEMA_VERSION}"
        )

    return data


def count_active_rules(rules: dict[str, Any]) -> int:
    """Count top-level rule sections marked `status: active`."""
    n = 0
    for key, value in rules.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and value.get("status") == "active":
            n += 1
    return n


# ---------------------------------------------------------------------------
# B2-SR1 consumers (p2-11…p2-16)
# Each reads its named section from `standing_rules` dict and raises on
# misconfiguration (fail-loud at startup). All are pure functions that accept
# the standing_rules mapping; no file I/O.
# ---------------------------------------------------------------------------


def validate_expenses_schema(
    standing_rules: dict[str, Any],
    actual_columns: list[str],
) -> None:
    """p2-11: assert the runtime column set contains all schema-mandated columns.

    Reads `expenses_schema.new_columns` from standing-rules.yaml and asserts
    every declared column is present in `actual_columns` (CATEGORIZED_COLUMNS).
    Also asserts the legacy column (`legacy_column_removed`) is NOT present.

    Raises StandingRulesError on misconfiguration (called at categorize.py
    startup — fail-loud, never silently defaults).
    """
    section = standing_rules.get("expenses_schema")
    if not isinstance(section, dict):
        raise StandingRulesError(
            "standing-rules.yaml missing or malformed `expenses_schema` section"
        )
    new_cols: list[str] = section.get("new_columns") or []
    legacy_col: str = section.get("legacy_column_removed") or ""
    missing = [c for c in new_cols if c not in actual_columns]
    if missing:
        raise StandingRulesError(
            f"expenses_schema: declared new_columns {sorted(missing)} are "
            f"absent from CATEGORIZED_COLUMNS — schema mismatch (p2-11)"
        )
    if legacy_col and legacy_col in actual_columns:
        raise StandingRulesError(
            f"expenses_schema: legacy column '{legacy_col}' must not appear "
            f"in CATEGORIZED_COLUMNS — it was removed in the schema migration (p2-11)"
        )


def load_name_canonicalization(standing_rules: dict[str, Any]) -> dict[str, Any]:
    """p2-12: return the name_canonicalization config section.

    Raises StandingRulesError if the section is missing or malformed.
    Callers apply `apply_name_canonicalization` to each supplier_canonical.
    """
    section = standing_rules.get("name_canonicalization")
    if not isinstance(section, dict):
        raise StandingRulesError(
            "standing-rules.yaml missing or malformed `name_canonicalization` section"
        )
    return section


def apply_name_canonicalization(name: str, cfg: dict[str, Any]) -> str:
    """p2-12: apply title-case + trademark-exception rule to a supplier name.

    Rules (from standing-rules.yaml::name_canonicalization):
      - default_style == 'titlecase_accented': apply str.title() to the name.
      - exceptions: a list of canonical strings whose casing is preserved as-is.

    Returns the canonical form. Empty / None names are returned unchanged.
    Pure.
    """
    if not name:
        return name
    exceptions: list[str] = cfg.get("exceptions") or []
    # Exact match (case-insensitive) in the exceptions list → preserve declared casing.
    for exc in exceptions:
        if name.upper() == exc.upper():
            return exc
    style: str = cfg.get("default_style") or "titlecase_accented"
    if style == "titlecase_accented":
        return name.title()
    return name


def load_competencia_rules(standing_rules: dict[str, Any]) -> dict[str, Any]:
    """p2-13: return the competencia_rules config section.

    Raises StandingRulesError if the section is missing or malformed.

    The deterministic sub-rule (`cc_installments`) is already implemented in
    `accrual.py::compute_data_competencia`. This consumer validates that the
    section loads correctly from config so the rule is config-driven (not just
    implemented in prose). The `travel_anchors` and `supplier_fixed` sub-rules
    require Pass 2 agent judgment and carry `runtime_actor: agent`.
    """
    section = standing_rules.get("competencia_rules")
    if not isinstance(section, dict):
        raise StandingRulesError(
            "standing-rules.yaml missing or malformed `competencia_rules` section"
        )
    return section


def load_tag_semantics(standing_rules: dict[str, Any]) -> dict[str, Any]:
    """p2-14: return the tag_semantics config section.

    Raises StandingRulesError if the section is missing or malformed.
    Callers use `validate_tag_amount_sign` to assert sign conventions.
    """
    section = standing_rules.get("tag_semantics")
    if not isinstance(section, dict):
        raise StandingRulesError(
            "standing-rules.yaml missing or malformed `tag_semantics` section"
        )
    return section


def validate_tag_amount_sign(
    tag: str,
    amount: float,
    tag_semantics_cfg: dict[str, Any],
) -> bool:
    """p2-14: return True iff the (tag, amount) pair is consistent with declared semantics.

    Reads sign conventions from tag_semantics_cfg (loaded via load_tag_semantics).
    Unknown tags (not in the semantics config) are unconditionally valid (open vocabulary).
    Pure.
    """
    rule = tag_semantics_cfg.get(tag)
    if not isinstance(rule, dict):
        return True  # no declared constraint for this tag
    sign: str = rule.get("amount_sign") or ""
    if sign == "negative":
        return amount < 0
    if sign == "positive":
        return amount > 0
    return True


def load_tag_application_rules(standing_rules: dict[str, Any]) -> dict[str, Any]:
    """p2-15: return the tag_application_rules config section.

    Raises StandingRulesError if the section is missing or malformed.
    Callers pass this to `apply_tag_application_rules` per transaction.
    """
    section = standing_rules.get("tag_application_rules")
    if not isinstance(section, dict):
        raise StandingRulesError(
            "standing-rules.yaml missing or malformed `tag_application_rules` section"
        )
    return section


def apply_tag_application_rules(
    supplier_canonical: str,
    category: str,
    amount: float,
    existing_tags: list[str],
    tag_rules_cfg: dict[str, Any],
    rule_counter: "RuleFireCounter | None" = None,
) -> list[str]:
    """p2-15: apply declarative tag-application rules to a classified row.

    Reads rules from tag_application_rules (loaded via load_tag_application_rules).
    Returns a new tag list (does not mutate `existing_tags`). Pure except for
    recording fires on rule_counter.

    Rules evaluated in declaration order:
      care_plus_receipt: supplier_canonical == 'Care Plus' AND amount > 0
        → always_apply these tags
      automotive_insurance: supplier_canonical in suppliers list
        → apply the declared tag
    """
    tags = list(existing_tags)

    # care_plus_receipt rule
    cp_rule = tag_rules_cfg.get("care_plus_receipt") or {}
    cp_condition = cp_rule.get("condition") or ""
    cp_always: list[str] = cp_rule.get("always_apply") or []
    if cp_always:
        # Evaluate deterministic condition: supplier == 'Care Plus' AND amount > 0
        if supplier_canonical == "Care Plus" and amount > 0:
            added = False
            for t in cp_always:
                if t not in tags:
                    tags.append(t)
                    added = True
            if added and rule_counter is not None:
                rule_counter.record("tag_application_care_plus_receipt")

    # automotive_insurance rule
    ai_rule = tag_rules_cfg.get("automotive_insurance") or {}
    ai_suppliers: list[str] = ai_rule.get("suppliers") or []
    ai_category: str = ai_rule.get("category") or ""
    ai_tag: str = ai_rule.get("tag") or ""
    if ai_suppliers and ai_tag:
        if supplier_canonical in ai_suppliers and (not ai_category or category == ai_category):
            if ai_tag not in tags:
                tags.append(ai_tag)
                if rule_counter is not None:
                    rule_counter.record("tag_application_automotive_insurance")

    return tags


def load_family_canonicals(standing_rules: dict[str, Any]) -> dict[str, Any]:
    """p2-16: return the family_canonicals config section.

    Raises StandingRulesError if the section is missing or malformed.
    """
    section = standing_rules.get("family_canonicals")
    if not isinstance(section, dict):
        raise StandingRulesError(
            "standing-rules.yaml missing or malformed `family_canonicals` section"
        )
    return section


def is_family_canonical(canonical: str, family_cfg: dict[str, Any]) -> bool:
    """p2-16: return True iff `canonical` is a declared family member name.

    Reads the `members` list from family_cfg (loaded via load_family_canonicals).
    Pure.
    """
    members: list[str] = family_cfg.get("members") or []
    return canonical in members


# ---------------------------------------------------------------------------
# B2-SR2 consumers (p2-17…p2-22)
# ---------------------------------------------------------------------------

# Sentinel value used as the tag_coverage threshold when S7 has not yet
# resolved the value. Any gate check against this sentinel fails by default,
# per the revolving plan rule: "threshold gates fail-by-default until their
# number lands" (S7, batch B4-GATE1). Replace with the real R$ value when S7
# lands.
_TAG_COVERAGE_THRESHOLD_UNRESOLVED = None  # S7 pending


def load_tag_coverage(standing_rules: dict[str, Any]) -> dict[str, Any]:
    """p2-17: return the tag_coverage config section.

    Raises StandingRulesError if the section is missing or malformed.

    `gate.untagged_amount_threshold_brl` is the SINGLE canonical R$ floor for
    untagged despesas (S7 RESOLVED = R$100; p5-8 removed the duplicate alias that
    formerly lived under gates.step_5_5_coverage). `check_tag_coverage_gate()`
    returns `False` (gate fails by default) when this key is absent or non-numeric,
    enforcing the "failing-by-default gate" invariant without inventing a number.
    """
    section = standing_rules.get("tag_coverage")
    if not isinstance(section, dict):
        raise StandingRulesError(
            "standing-rules.yaml missing or malformed `tag_coverage` section"
        )
    return section


def check_tag_coverage_gate(
    untagged_amount_brl: float,
    tag_coverage_cfg: dict[str, Any],
    rule_counter: "RuleFireCounter | None" = None,
) -> bool:
    """p2-17: return True iff the untagged-amount is below the configured threshold.

    Reads `gate.untagged_amount_threshold_brl` from tag_coverage_cfg (loaded
    via load_tag_coverage). Returns False (gate FAILS) when:
      - The threshold value is absent or non-numeric (S7 not yet resolved).
      - `untagged_amount_brl` >= threshold.

    Returns True (gate passes) only when the threshold is a valid number AND
    `untagged_amount_brl` < threshold.

    Per the revolving plan rule: threshold gates fail-by-default until their
    number lands. Callers MUST NOT treat a False return as a fatal error during
    S7-pending phases — it signals that the gate cannot yet be evaluated.
    """
    gate_cfg = (tag_coverage_cfg.get("gate") or {})
    threshold = gate_cfg.get("untagged_amount_threshold_brl")
    if threshold is None or not isinstance(threshold, (int, float)):
        # S7 not yet resolved — gate fails by default (never silently passes).
        if rule_counter is not None:
            rule_counter.record("tag_coverage_gate_s7_pending")
        return False
    passes = float(untagged_amount_brl) < float(threshold)
    if rule_counter is not None:
        rule_counter.record(
            "tag_coverage_gate_pass" if passes else "tag_coverage_gate_fail"
        )
    return passes


def load_cross_month_propagation(standing_rules: dict[str, Any]) -> dict[str, Any]:
    """p2-18: return the cross_month_propagation config section.

    Raises StandingRulesError if the section is missing or malformed.

    NOTE — P3 COUPLING: the full retroactive propagation mechanism is built in
    p3-2 (batch B3-PASS3, decision S4). That mechanism MUST reuse the S5
    provenance identity (tx_date|tx_description|tx_amount) per shape.md S5
    entry. This consumer only validates that the section loads correctly and
    that required fields are present. Status remains `pending_consumer` until
    p3-2 wires the runtime action. See shape.md Decisions S4 + S5.
    """
    section = standing_rules.get("cross_month_propagation")
    if not isinstance(section, dict):
        raise StandingRulesError(
            "standing-rules.yaml missing or malformed `cross_month_propagation` section"
        )
    required = {"enabled", "trigger", "scope", "action"}
    missing = required - section.keys()
    if missing:
        raise StandingRulesError(
            f"standing-rules.yaml `cross_month_propagation` missing fields: "
            f"{sorted(missing)}"
        )
    return section


def load_pass_2_rules(standing_rules: dict[str, Any]) -> dict[str, Any]:
    """p2-19: return the pass_2_rules config section.

    Raises StandingRulesError if the section is missing or malformed.

    The deterministic sub-rules (scope_filter, default_action, immutable_fields,
    mutable_fields, backfill_default_movable) are config-readable here.
    The runtime DISPATCH of Pass 2 is agent-driven (lib/boundary.py is invoked
    by the bookkeeper workflow agent, not deterministically by categorize.py).
    This consumer wires the config-load + validation step so the spec is
    config-driven (not prose-only). runtime_actor for the dispatch: agent.
    See p2-9 C-17 (CONFIRMED PENDING) and shape.md rule-promotion ladder.
    """
    section = standing_rules.get("pass_2_rules")
    if not isinstance(section, dict):
        raise StandingRulesError(
            "standing-rules.yaml missing or malformed `pass_2_rules` section"
        )
    required = {"scope_filter", "default_action", "immutable_fields", "mutable_fields"}
    missing = required - section.keys()
    if missing:
        raise StandingRulesError(
            f"standing-rules.yaml `pass_2_rules` missing fields: {sorted(missing)}"
        )
    return section


def load_cash_expense(standing_rules: dict[str, Any]) -> dict[str, Any]:
    """p2-20: return the cash_expense config section.

    Raises StandingRulesError if the section is missing or malformed.
    Consumer validates that source_type and supplier_canonical are declared.
    The cash-expense classification is applied by the bookkeeper workflow agent
    (manual entries carry match_confidence='manual'); this consumer validates
    that the rule is config-declared, not prose-only.
    """
    section = standing_rules.get("cash_expense")
    if not isinstance(section, dict):
        raise StandingRulesError(
            "standing-rules.yaml missing or malformed `cash_expense` section"
        )
    required = {"source_type", "supplier_canonical", "match_confidence"}
    missing = required - section.keys()
    if missing:
        raise StandingRulesError(
            f"standing-rules.yaml `cash_expense` missing fields: {sorted(missing)}"
        )
    return section


def is_cash_expense_row(
    source_type: str,
    supplier_canonical: str,
    cash_cfg: dict[str, Any],
    rule_counter: "RuleFireCounter | None" = None,
) -> bool:
    """p2-20: return True iff the row matches the cash-expense convention.

    Reads `source_type` and `supplier_canonical` from cash_cfg (loaded via
    load_cash_expense). Pure.
    """
    expected_source = str(cash_cfg.get("source_type") or "").strip()
    expected_canonical = str(cash_cfg.get("supplier_canonical") or "").strip()
    if (
        source_type.strip() == expected_source
        and supplier_canonical.strip() == expected_canonical
    ):
        if rule_counter is not None:
            rule_counter.record("cash_expense_matched")
        return True
    return False


def load_investment_rules(standing_rules: dict[str, Any]) -> dict[str, Any]:
    """p2-21: return the investment_rules config section.

    Raises StandingRulesError if the section is missing or malformed.
    Validates that the key sub-sections (ledger_immutability,
    code_migration_handling, field_ownership) are present.

    NOTE: position_calculator.py already partially consumes this section
    (code_migration_handling.file pointer). This consumer validates the full
    section is loadable from config. The remaining sub-rules (irr_warnings,
    fractional_handling, etc.) are consumed by calculate.py / position_calculator.py
    per their own runtime logic; this consumer wires the config-read contract.
    """
    section = standing_rules.get("investment_rules")
    if not isinstance(section, dict):
        raise StandingRulesError(
            "standing-rules.yaml missing or malformed `investment_rules` section"
        )
    required = {"ledger_immutability", "code_migration_handling", "field_ownership"}
    missing = required - section.keys()
    if missing:
        raise StandingRulesError(
            f"standing-rules.yaml `investment_rules` missing sub-sections: "
            f"{sorted(missing)}"
        )
    return section


def load_rf_naming(standing_rules: dict[str, Any]) -> dict[str, Any]:
    """p2-22: return the rf_naming config section.

    Raises StandingRulesError if the section is missing or malformed.
    Callers use `validate_rf_name()` to assert fixed-income asset names conform.
    """
    section = standing_rules.get("rf_naming")
    if not isinstance(section, dict):
        raise StandingRulesError(
            "standing-rules.yaml missing or malformed `rf_naming` section"
        )
    required = {"format", "tipo_enum"}
    missing = required - section.keys()
    if missing:
        raise StandingRulesError(
            f"standing-rules.yaml `rf_naming` missing fields: {sorted(missing)}"
        )
    return section


def validate_rf_name(
    name: str,
    rf_cfg: dict[str, Any],
    rule_counter: "RuleFireCounter | None" = None,
) -> bool:
    """p2-22: return True iff `name` starts with a declared tipo_enum token.

    Reads `tipo_enum` from rf_cfg (loaded via load_rf_naming). Checks that the
    name begins with one of the declared type tokens (e.g. 'LCA', 'CRI', etc.).
    A blank name is considered invalid. Pure.
    """
    if not name or not name.strip():
        return False
    tipos: list[str] = rf_cfg.get("tipo_enum") or []
    name_upper = name.strip().upper()
    for tipo in tipos:
        if name_upper.startswith(tipo.upper()):
            if rule_counter is not None:
                rule_counter.record("rf_naming_valid")
            return True
    if rule_counter is not None:
        rule_counter.record("rf_naming_invalid")
    return False


# ---------------------------------------------------------------------------
# B2-SR3 consumers (p2-23…p2-28)
# Each reads its named section from `standing_rules` dict and raises on
# misconfiguration (fail-loud at startup). All are pure functions.
# ---------------------------------------------------------------------------


def load_yoc(standing_rules: dict[str, Any]) -> dict[str, Any]:
    """p2-23: return the yoc config section.

    Raises StandingRulesError if the section is missing or malformed.

    YoC formulas (lifetime and ttm) are declared here; the runtime
    calculation lives in calculate.py / irr_calculator.py (investment
    pipeline). This consumer validates the section loads correctly from
    config so the rule is config-driven. runtime_actor: calculate.py.
    """
    section = standing_rules.get("yoc")
    if not isinstance(section, dict):
        raise StandingRulesError(
            "standing-rules.yaml missing or malformed `yoc` section"
        )
    required = {"lifetime", "ttm", "excluded_from_income"}
    missing = required - section.keys()
    if missing:
        raise StandingRulesError(
            f"standing-rules.yaml `yoc` missing fields: {sorted(missing)}"
        )
    return section


def load_options_rules(standing_rules: dict[str, Any]) -> dict[str, Any]:
    """p2-24: return the options_rules config section.

    Raises StandingRulesError if the section is missing or malformed.

    The expiration auto-generation rule and price-fetching skip are declared
    here; the runtime consumer is position_calculator.py (investment
    pipeline). This consumer validates the section loads correctly from
    config. runtime_actor: position_calculator.py.
    """
    section = standing_rules.get("options_rules")
    if not isinstance(section, dict):
        raise StandingRulesError(
            "standing-rules.yaml missing or malformed `options_rules` section"
        )
    required = {"expiration_auto_generation", "price_fetching"}
    missing = required - section.keys()
    if missing:
        raise StandingRulesError(
            f"standing-rules.yaml `options_rules` missing fields: {sorted(missing)}"
        )
    return section


def load_gates(standing_rules: dict[str, Any]) -> dict[str, Any]:
    """p2-25: return the gates config section.

    Raises StandingRulesError if the section is missing or malformed.

    Validates that the key gate sub-sections are present.

    THRESHOLD NOTE: the untagged-despesa floor is NOT stored under this section.
    p5-8 collapsed the former `step_5_5_coverage.untagged_amount_threshold` alias
    into the single canonical key `tag_coverage.gate.untagged_amount_threshold_brl`;
    `check_gates_coverage_threshold(standing_rules)` reads that canonical key.
    `step_5_5_coverage.threshold` (the 90% coverage ratio) remains here.
    """
    section = standing_rules.get("gates")
    if not isinstance(section, dict):
        raise StandingRulesError(
            "standing-rules.yaml missing or malformed `gates` section"
        )
    required = {
        "step_01_file_identification",
        "step_3d_unmatched_rows",
        "step_5_5_coverage",
    }
    missing = required - section.keys()
    if missing:
        raise StandingRulesError(
            f"standing-rules.yaml `gates` missing sub-sections: {sorted(missing)}"
        )
    return section


def check_gates_coverage_threshold(
    standing_rules: dict[str, Any],
    rule_counter: "RuleFireCounter | None" = None,
) -> float | None:
    """p2-25: return the untagged-despesa floor (R$), or None when it is unset.

    Reads the floor from the CANONICAL key
    `tag_coverage.gate.untagged_amount_threshold_brl`. p5-8 collapsed the former
    `gates.step_5_5_coverage.untagged_amount_threshold` alias into that one key, so
    this function now takes the full `standing_rules` mapping (not just the gates
    section) to reach `tag_coverage`.

    Returns the numeric threshold from config when present; None otherwise.
    Callers MUST treat None as "gate cannot yet be evaluated — fail by default."
    Per the revolving plan rule: threshold gates fail-by-default until their value lands.
    """
    tag_cov = (standing_rules.get("tag_coverage") or {})
    gate_section = (tag_cov.get("gate") or {}) if isinstance(tag_cov, dict) else {}
    threshold = gate_section.get("untagged_amount_threshold_brl")
    if threshold is None or not isinstance(threshold, (int, float)):
        if rule_counter is not None:
            rule_counter.record("gates_coverage_threshold_s7_pending")
        return None
    if rule_counter is not None:
        rule_counter.record("gates_coverage_threshold_read")
    return float(threshold)


def check_threshold_provenance(
    parent: dict[str, Any],
    threshold_key: str,
    applied_metric: str,
    *,
    provenance_key: str | None = None,
) -> dict[str, Any]:
    """Assert a config-provided threshold is owned by the metric consuming it.

    `parent` holds BOTH the threshold scalar (at `threshold_key`) and its
    provenance block (at `provenance_key`, default `f"{threshold_key}_provenance"`).
    `applied_metric` is the metric identifier the calling gate applies this
    threshold to.

    Returns the provenance dict on a clean match (its `metric` == applied_metric).
    Raises `ThresholdProvenanceError` when the provenance block is absent/malformed,
    or when its `metric` differs from `applied_metric` (the inherited-threshold
    class). Call ONLY when the threshold is actually present in config — a
    threshold the config does not provide (caller uses an in-code fallback) is not
    subject to this check. Pure.

    Compound: cp-sb-bookkeeper-gates-measure-meaning, change 3 (threshold
    provenance enforced in code).
    """
    pkey = provenance_key or f"{threshold_key}_provenance"
    prov = parent.get(pkey)
    if not isinstance(prov, dict):
        raise ThresholdProvenanceError(
            f"threshold '{threshold_key}' is present in config but has no "
            f"provenance block ('{pkey}'). A binding threshold MUST declare the "
            f"metric it was decided for. Add a sibling block:\n"
            f"  {pkey}:\n"
            f"    metric: {applied_metric}\n"
            f"    decided_on: <YYYY-MM-DD>\n"
            f"    decision: <why this number, for this metric>"
        )
    declared_metric = prov.get("metric")
    if declared_metric != applied_metric:
        raise ThresholdProvenanceError(
            f"threshold '{threshold_key}' was decided for metric "
            f"{declared_metric!r} but is being applied to metric "
            f"{applied_metric!r} — an inherited threshold (the failure class this "
            f"check prevents). Record a deliberate threshold + provenance for "
            f"{applied_metric!r}, or apply the threshold decided for it."
        )
    return prov


def load_batch_ui(standing_rules: dict[str, Any]) -> dict[str, Any]:
    """p2-26: return the batch_ui config section.

    Raises StandingRulesError if the section is missing or malformed.

    The batch_ui rules govern the UI decision surface for Pass 1 (categories,
    suppliers, tags decision shapes). The genuine runtime consumer is the
    bookkeeper workflow agent (not yet built in Phase 5). This consumer
    validates the section loads correctly from config.
    runtime_actor: bookkeeper agent (Phase 5).
    """
    section = standing_rules.get("batch_ui")
    if not isinstance(section, dict):
        raise StandingRulesError(
            "standing-rules.yaml missing or malformed `batch_ui` section"
        )
    required = {"categories", "suppliers", "tags"}
    missing = required - section.keys()
    if missing:
        raise StandingRulesError(
            f"standing-rules.yaml `batch_ui` missing sub-sections: {sorted(missing)}"
        )
    return section


def load_file_conventions(standing_rules: dict[str, Any]) -> dict[str, Any]:
    """p2-27: return the file_conventions config section.

    Raises StandingRulesError if the section is missing or malformed.

    The tag_column_separator and parser/serializer references are declared
    here. categorize.py hardcodes ';' in _format_tags; this consumer validates
    that the config-declared separator matches the implementation constant.
    Raises StandingRulesError when the config separator differs from the
    expected ';', making the discrepancy visible at startup (fail-loud).
    """
    section = standing_rules.get("file_conventions")
    if not isinstance(section, dict):
        raise StandingRulesError(
            "standing-rules.yaml missing or malformed `file_conventions` section"
        )
    # Validate the csv_encoding sub-section declares the separator.
    csv_enc = section.get("csv_encoding")
    if not isinstance(csv_enc, dict):
        raise StandingRulesError(
            "standing-rules.yaml `file_conventions.csv_encoding` must be a mapping"
        )
    separator = csv_enc.get("tag_column_separator")
    if separator is None:
        raise StandingRulesError(
            "standing-rules.yaml `file_conventions.csv_encoding` "
            "missing `tag_column_separator`"
        )
    if separator != ";":
        raise StandingRulesError(
            f"standing-rules.yaml `file_conventions.csv_encoding.tag_column_separator` "
            f"is {separator!r} but categorize.py implements ';'. Update either the "
            f"config or the implementation to match."
        )
    return section


def load_communication(standing_rules: dict[str, Any]) -> dict[str, Any]:
    """p2-28: return the communication config section.

    Raises StandingRulesError if the section is missing or malformed.

    The language rule (Portuguese for user-facing messages, English for
    technical terms) is agent-applied. This consumer validates the section
    loads correctly from config. runtime_actor: bookkeeper agent.
    """
    section = standing_rules.get("communication")
    if not isinstance(section, dict):
        raise StandingRulesError(
            "standing-rules.yaml missing or malformed `communication` section"
        )
    required = {"language", "applies_to"}
    missing = required - section.keys()
    if missing:
        raise StandingRulesError(
            f"standing-rules.yaml `communication` missing fields: {sorted(missing)}"
        )
    return section


class RuleFireCounter:
    """Aggregator for rule fires across a script run.

    Per-row instrumentation calls `record(...)`. At the end of the run, the
    consumer calls `emit_summary(...)` to produce a single `rule_fired`
    audit event with the aggregated counts.
    """

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._rows_seen: int = 0

    def record(self, rule_name: str) -> None:
        self._counts[rule_name] += 1

    def observe_row(self) -> None:
        self._rows_seen += 1

    @property
    def total_fires(self) -> int:
        return sum(self._counts.values())

    @property
    def rows_seen(self) -> int:
        return self._rows_seen

    def as_dict(self) -> dict[str, int]:
        return dict(self._counts)

    def emit_summary(
        self,
        *,
        source_function: str,
        rule_set_version: str | None = None,
        trigger_context: dict[str, Any] | None = None,
    ) -> None:
        """Emit one `rule_fired` audit event with the aggregated counts.

        Skips emission when no rules fired (no signal worth a log line).
        """
        if not self._counts:
            return
        summary: dict[str, Any] = {
            "rows_seen": self._rows_seen,
            "total_fires": self.total_fires,
            "fires_by_rule": dict(self._counts),
        }
        if rule_set_version is not None:
            summary["rule_set_version"] = rule_set_version
        audit.emit(
            "rule_fired",
            source_function=source_function,
            summary=summary,
            trigger_context=trigger_context,
        )
