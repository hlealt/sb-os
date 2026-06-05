"""Tests for gate #7 — Spot-check coverage: mandatory source classes (p4-18)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gate_spot_check_coverage import check_coverage, main


# ---------------------------------------------------------------------------
# check_coverage unit tests
# ---------------------------------------------------------------------------


def test_pass_when_all_required_classes_checked_no_conditional():
    """All always-required classes + all conditionals checked → pass."""
    record = {
        "checked": [
            "b3_orders", "b3_proventos", "safra_balcao",
            "avenue_orders", "avenue_fx", "crypto_exchange",
        ],
        "present_sources": [],
    }
    passed, missing = check_coverage(record)
    assert passed is True
    assert missing == []


def test_pass_with_only_always_required_when_no_present_sources():
    """Only always-required classes; no present_sources → all conditional classes required too.

    Without present_sources the gate is conservative: requires all.
    """
    record = {
        "checked": [
            "b3_orders", "b3_proventos", "safra_balcao",
            "avenue_orders", "avenue_fx", "crypto_exchange",
        ],
    }
    passed, missing = check_coverage(record)
    assert passed is True


def test_fail_when_b3_orders_missing():
    """b3_orders not checked → fail."""
    record = {
        "checked": ["b3_proventos", "safra_balcao"],
        "present_sources": ["b3", "safra_balcao"],
    }
    passed, missing = check_coverage(record)
    assert passed is False
    assert "b3_orders" in missing


def test_avenue_not_required_when_not_present():
    """avenue_orders/fx not required when avenue not in present_sources."""
    record = {
        "checked": ["b3_orders", "b3_proventos", "safra_balcao"],
        "present_sources": ["b3", "safra_balcao"],  # no avenue
    }
    passed, missing = check_coverage(record)
    assert passed is True


def test_crypto_required_when_present():
    """crypto_exchange required when crypto in present_sources and not checked → fail."""
    record = {
        "checked": ["b3_orders", "b3_proventos", "safra_balcao", "avenue_orders", "avenue_fx"],
        "present_sources": ["b3", "safra_balcao", "avenue", "crypto"],
    }
    passed, missing = check_coverage(record)
    assert passed is False
    assert "crypto_exchange" in missing


def test_pass_all_required_with_all_sources():
    """All six classes checked, all sources present → pass."""
    record = {
        "checked": [
            "b3_orders", "b3_proventos", "safra_balcao",
            "avenue_orders", "avenue_fx", "crypto_exchange",
        ],
        "present_sources": ["b3", "safra_balcao", "avenue", "crypto"],
    }
    passed, missing = check_coverage(record)
    assert passed is True
    assert missing == []


def test_malformed_record_returns_false():
    """Non-dict record → returns False with error."""
    passed, missing = check_coverage("not a dict")
    assert passed is False


# ---------------------------------------------------------------------------
# main() exit-code integration tests
# ---------------------------------------------------------------------------


def test_main_pass_exit_0(tmp_path, monkeypatch):
    record = {
        "checked": [
            "b3_orders", "b3_proventos", "safra_balcao",
            "avenue_orders", "avenue_fx", "crypto_exchange",
        ],
        "present_sources": ["b3", "safra_balcao", "avenue", "crypto"],
    }
    record_file = tmp_path / "coverage.json"
    record_file.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_spot_check_coverage.py", "--coverage-record", str(record_file)
    ])
    assert main() == 0


def test_main_fail_exit_1(tmp_path, monkeypatch):
    record = {
        "checked": ["b3_proventos", "safra_balcao"],
        "present_sources": ["b3", "safra_balcao"],
    }
    record_file = tmp_path / "coverage.json"
    record_file.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_spot_check_coverage.py", "--coverage-record", str(record_file)
    ])
    assert main() == 1


def test_main_missing_file_exit_2(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", [
        "gate_spot_check_coverage.py",
        "--coverage-record", str(tmp_path / "nope.json"),
    ])
    assert main() == 2


def test_gate_event_emitted_on_pass(tmp_path, monkeypatch):
    """gate_pass event is emitted."""
    import lib.audit as audit_mod
    audit_mod._reset_cache_for_tests()

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    record = {
        "checked": ["b3_orders", "b3_proventos", "safra_balcao"],
        "present_sources": ["b3", "safra_balcao"],
    }
    record_file = tmp_path / "coverage.json"
    record_file.write_text(json.dumps(record), encoding="utf-8")

    monkeypatch.setenv("BOOKKEEPER_AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "0")
    monkeypatch.setattr(sys, "argv", [
        "gate_spot_check_coverage.py", "--coverage-record", str(record_file)
    ])

    result = main()
    assert result == 0

    event_files = list(audit_dir.glob("events-*.jsonl"))
    assert event_files
    events = [json.loads(line) for line in event_files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    gate_events = [e for e in events if e.get("event_type") == "gate_pass"]
    assert gate_events
    assert gate_events[0]["gate"]["name"] == "gate_7_spot_check_coverage"

    audit_mod._reset_cache_for_tests()
