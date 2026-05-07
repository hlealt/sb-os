"""Tests for the standing-rules loader + rule-fire counter (`lib.standing_rules`).

Spec: p1-20 task — `1-projects/finance-system/finance-system-v2-foundation/phase-1/p1-20.task.md`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lib import standing_rules
from lib.standing_rules import (
    RuleFireCounter,
    StandingRulesError,
    load_standing_rules,
)


VALID_YAML = """
_meta:
  schema_version: 1
  rule_set_version: "1.0"
supplier_rules:
  status: active
  matching_order: [self_transfer, reimbursement]
"""


def _write_rules(tmp_path: Path, body: str) -> Path:
    config = tmp_path / "config"
    config.mkdir()
    (config / "standing-rules.yaml").write_text(body, encoding="utf-8")
    return config


def _audit_dir() -> Path:
    return Path(os.environ["BOOKKEEPER_AUDIT_LOG_DIR"])


def _read_events() -> list[dict]:
    audit_dir = _audit_dir()
    if not audit_dir.exists():
        return []
    out: list[dict] = []
    for p in sorted(audit_dir.glob("events-*.jsonl")):
        out.extend(
            json.loads(line)
            for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return out


def test_load_returns_expected_rule_set(tmp_path):
    config = _write_rules(tmp_path, VALID_YAML)
    data = load_standing_rules(config)
    assert data["_meta"]["rule_set_version"] == "1.0"
    assert data["supplier_rules"]["status"] == "active"
    assert standing_rules.count_active_rules(data) == 1


def test_missing_file_fails_loud(tmp_path):
    with pytest.raises(StandingRulesError, match="not found"):
        load_standing_rules(tmp_path / "nonexistent")


def test_missing_required_section_fails_loud(tmp_path):
    body = """
_meta:
  schema_version: 1
  rule_set_version: "1.0"
"""
    config = _write_rules(tmp_path, body)
    with pytest.raises(StandingRulesError, match="missing required sections"):
        load_standing_rules(config)


def test_unsupported_schema_version_fails_loud(tmp_path):
    body = """
_meta:
  schema_version: 99
  rule_set_version: "1.0"
supplier_rules:
  status: active
"""
    config = _write_rules(tmp_path, body)
    with pytest.raises(StandingRulesError, match="schema_version"):
        load_standing_rules(config)


def test_rule_counter_records_and_aggregates():
    counter = RuleFireCounter()
    counter.observe_row()
    counter.record("self_transfer")
    counter.observe_row()
    counter.record("reimbursement")
    counter.observe_row()
    counter.record("reimbursement")
    assert counter.rows_seen == 3
    assert counter.total_fires == 3
    assert counter.as_dict() == {"self_transfer": 1, "reimbursement": 2}


def test_emit_summary_writes_rule_fired_event(tmp_path):
    counter = RuleFireCounter()
    counter.observe_row()
    counter.record("value_based_splits")
    counter.observe_row()
    counter.record("self_transfer")

    counter.emit_summary(
        source_function="test.fn",
        rule_set_version="1.0",
        trigger_context={"input_dir": "x"},
    )

    events = _read_events()
    rule_events = [e for e in events if e["event_type"] == "rule_fired"]
    assert len(rule_events) == 1
    e = rule_events[0]
    assert e["source"]["function"] == "test.fn"
    assert e["summary"]["rows_seen"] == 2
    assert e["summary"]["total_fires"] == 2
    assert e["summary"]["fires_by_rule"] == {
        "value_based_splits": 1,
        "self_transfer": 1,
    }
    assert e["summary"]["rule_set_version"] == "1.0"
    assert e["trigger_context"]["input_dir"] == "x"


def test_emit_summary_skips_when_no_fires():
    counter = RuleFireCounter()
    counter.observe_row()
    counter.observe_row()
    counter.emit_summary(source_function="test.fn")
    assert _read_events() == []


def test_real_vault_yaml_loads(tmp_path):
    """Sanity check: the real `.user/finance/bookkeeper/config/standing-rules.yaml`
    in the vault parses + validates against the loader."""
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
        pytest.skip("Real standing-rules.yaml not present (running outside vault).")
    data = load_standing_rules(real_yaml.parent)
    assert data["_meta"]["schema_version"] == 1
    assert "supplier_rules" in data
