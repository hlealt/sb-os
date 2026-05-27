"""Tests for gate #11 — Pass-1 queue zero before Pass-2 fires (p4-15)."""

import json
import os
import sys
from pathlib import Path

import pytest

# Make shared/ importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gate_pass_1_queue import check_queue_state, main


# ---------------------------------------------------------------------------
# check_queue_state unit tests
# ---------------------------------------------------------------------------


def test_pass_when_pass1_empty_and_pass2_pending():
    """Pass-1 empty, Pass-2 has items → gate passes."""
    state = {"pass_1_items": [], "pass_2_items": [{"transaction_id": 0}]}
    passed, detail = check_queue_state(state)
    assert passed is True
    assert "Pass-1 queue is empty" in detail


def test_fail_when_pass1_nonempty_and_pass2_pending():
    """Pass-1 has items, Pass-2 also has items → QueueOrderingError condition → FAIL."""
    state = {
        "pass_1_items": [{"transaction_id": 0, "item_type": "category"}],
        "pass_2_items": [{"transaction_id": 1}],
    }
    passed, detail = check_queue_state(state)
    assert passed is False
    assert "1 Pass-1 item(s) unresolved" in detail


def test_vacuous_pass_when_pass2_empty():
    """Pass-2 not yet queued → gate not triggered → passes regardless of Pass-1."""
    state = {
        "pass_1_items": [{"transaction_id": 0}],
        "pass_2_items": [],
    }
    passed, detail = check_queue_state(state)
    assert passed is True
    assert "not triggered" in detail


def test_fully_empty_queues():
    """Both queues empty → vacuous pass."""
    state = {"pass_1_items": [], "pass_2_items": []}
    passed, detail = check_queue_state(state)
    assert passed is True


def test_malformed_lists_returns_false():
    """Malformed (non-list) queue entries → returns False with error detail."""
    state = {"pass_1_items": "bad", "pass_2_items": [{}]}
    passed, detail = check_queue_state(state)
    assert passed is False


# ---------------------------------------------------------------------------
# main() exit-code integration tests
# ---------------------------------------------------------------------------


def test_main_pass_exit_code_0(tmp_path, monkeypatch):
    """Passing queue state → exit code 0."""
    state_file = tmp_path / "queue_state.json"
    state_file.write_text(
        json.dumps({"pass_1_items": [], "pass_2_items": [{"x": 1}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", ["gate_pass_1_queue.py", "--queue-state", str(state_file)])
    assert main() == 0


def test_main_fail_exit_code_1(tmp_path, monkeypatch):
    """Failing queue state → exit code 1."""
    state_file = tmp_path / "queue_state.json"
    state_file.write_text(
        json.dumps({
            "pass_1_items": [{"transaction_id": 0}],
            "pass_2_items": [{"transaction_id": 1}],
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", ["gate_pass_1_queue.py", "--queue-state", str(state_file)])
    assert main() == 1


def test_main_missing_file_exit_code_2(tmp_path, monkeypatch):
    """Missing queue state file → exit code 2."""
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(
        sys, "argv",
        ["gate_pass_1_queue.py", "--queue-state", str(tmp_path / "nonexistent.json")],
    )
    assert main() == 2


def test_main_no_state_file_vacuous_pass(monkeypatch):
    """No --queue-state provided → vacuous pass (exit 0)."""
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "1")
    monkeypatch.setattr(sys, "argv", ["gate_pass_1_queue.py"])
    assert main() == 0


def test_gate_event_emitted_on_fail(tmp_path, monkeypatch):
    """gate_fail event is emitted when gate fails."""
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    state_file = tmp_path / "queue_state.json"
    state_file.write_text(
        json.dumps({
            "pass_1_items": [{"transaction_id": 0}],
            "pass_2_items": [{"transaction_id": 1}],
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("BOOKKEEPER_AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("BOOKKEEPER_AUDIT_DISABLED", "0")
    monkeypatch.setattr(sys, "argv", ["gate_pass_1_queue.py", "--queue-state", str(state_file)])

    # Import lib.audit and reset caches so the log dir override takes effect.
    import importlib
    import shared.lib.audit as audit_mod
    audit_mod._reset_cache_for_tests()

    result = main()
    assert result == 1

    # Verify at least one event file was written.
    event_files = list(audit_dir.glob("events-*.jsonl"))
    assert event_files, "Expected an audit event file to be written"

    events = [json.loads(line) for line in event_files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    gate_events = [e for e in events if e.get("event_type") == "gate_fail"]
    assert gate_events, f"Expected gate_fail event; got: {[e.get('event_type') for e in events]}"
    assert gate_events[0]["gate"]["name"] == "gate_11_pass_1_queue"

    audit_mod._reset_cache_for_tests()
