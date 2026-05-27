"""Tests for gate #6 — Ledger upsert match tolerance = 0 (p4-16)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gate_ledger_tolerance import check_report, main


# ---------------------------------------------------------------------------
# check_report unit tests
# ---------------------------------------------------------------------------


def test_pass_when_no_fuzzy_matches():
    """No fuzzy matches in any ledger → gate passes."""
    report = {
        "orders.csv": {"inserted": 3, "skipped_exact": 10, "skipped_fuzzy": [], "forced_duplicates": [], "fee_updates": []},
        "proventos.csv": {"inserted": 1, "skipped_exact": 5, "skipped_fuzzy": [], "forced_duplicates": [], "fee_updates": []},
    }
    passed, count, details = check_report(report)
    assert passed is True
    assert count == 0
    assert details == []


def test_fail_when_fuzzy_match_present():
    """A fuzzy match in any ledger → gate fails."""
    report = {
        "orders.csv": {
            "inserted": 0,
            "skipped_exact": 0,
            "skipped_fuzzy": [
                {"date": "2026-04-08", "asset": "PETR4", "deltas": {"quantity": {"source": "100", "ledger": "100.1", "delta": "-0.1"}}}
            ],
            "forced_duplicates": [],
            "fee_updates": [],
        }
    }
    passed, count, details = check_report(report)
    assert passed is False
    assert count == 1
    assert details[0]["ledger"] == "orders.csv"


def test_aggregates_fuzzy_across_multiple_ledgers():
    """Fuzzy matches in multiple ledgers are all counted."""
    report = {
        "orders.csv": {"inserted": 0, "skipped_exact": 0, "skipped_fuzzy": [{"date": "2026-01-01", "asset": "A", "deltas": {}}], "forced_duplicates": [], "fee_updates": []},
        "balcao.csv": {"inserted": 0, "skipped_exact": 0, "skipped_fuzzy": [{"date": "2026-01-02", "asset": "B", "deltas": {}}], "forced_duplicates": [], "fee_updates": []},
    }
    passed, count, details = check_report(report)
    assert passed is False
    assert count == 2


def test_ignores_non_dict_entries():
    """Malformed non-dict ledger entries are skipped."""
    report = {"bad_ledger": "not a dict", "orders.csv": {"skipped_fuzzy": []}}
    passed, count, details = check_report(report)
    assert passed is True


# ---------------------------------------------------------------------------
# main() exit-code integration tests
# ---------------------------------------------------------------------------


def test_main_pass_exit_0(tmp_path, monkeypatch):
    report = {"orders.csv": {"inserted": 1, "skipped_exact": 0, "skipped_fuzzy": [], "forced_duplicates": [], "fee_updates": []}}
    report_file = tmp_path / "report.json"
    report_file.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", ["gate_ledger_tolerance.py", "--report", str(report_file)])
    assert main() == 0


def test_main_fail_exit_1(tmp_path, monkeypatch):
    report = {
        "orders.csv": {
            "inserted": 0, "skipped_exact": 0,
            "skipped_fuzzy": [{"date": "2026-04-01", "asset": "X", "deltas": {}}],
            "forced_duplicates": [], "fee_updates": [],
        }
    }
    report_file = tmp_path / "report.json"
    report_file.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", ["gate_ledger_tolerance.py", "--report", str(report_file)])
    assert main() == 1


def test_main_missing_file_exit_2(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(
        sys, "argv",
        ["gate_ledger_tolerance.py", "--report", str(tmp_path / "nope.json")],
    )
    assert main() == 2


def test_gate_pass_event_emitted(tmp_path, monkeypatch):
    """gate_pass event emitted when no fuzzy matches."""
    import shared.lib.audit as audit_mod
    audit_mod._reset_cache_for_tests()

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    report = {"orders.csv": {"skipped_fuzzy": []}}
    report_file = tmp_path / "report.json"
    report_file.write_text(json.dumps(report), encoding="utf-8")

    monkeypatch.setenv("BOOKKEEPER_AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "0")
    monkeypatch.setattr(sys, "argv", ["gate_ledger_tolerance.py", "--report", str(report_file)])

    result = main()
    assert result == 0

    event_files = list(audit_dir.glob("events-*.jsonl"))
    assert event_files
    events = [json.loads(line) for line in event_files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    gate_events = [e for e in events if e.get("event_type") == "gate_pass"]
    assert gate_events
    assert gate_events[0]["gate"]["name"] == "gate_6_ledger_tolerance"

    audit_mod._reset_cache_for_tests()
