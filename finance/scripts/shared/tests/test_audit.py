"""Tests for the audit-event protocol helper (`lib.audit`)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from lib import audit


@pytest.fixture
def isolated_vault(tmp_path):
    """Yields the tmp vault root configured by the conftest autouse fixture."""
    return tmp_path


def _audit_dir() -> Path:
    return Path(os.environ["BOOKKEEPER_AUDIT_LOG_DIR"])


def _read_events(_vault: Path) -> list[dict]:
    out: list[dict] = []
    audit_dir = _audit_dir()
    if not audit_dir.exists():
        return out
    for p in sorted(audit_dir.glob("events-*.jsonl")):
        out.extend(
            json.loads(line)
            for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return out


def test_emit_writes_jsonl_line(isolated_vault):
    audit.emit(
        "ledger_write",
        source_function="test",
        destination=isolated_vault / "x.csv",
        action="overwrite",
        materiality="high",
        summary={"bytes_before": 0, "bytes_after": 10},
    )
    events = _read_events(isolated_vault)
    assert len(events) == 1
    e = events[0]
    assert e["schema_version"] == 1
    assert e["event_type"] == "ledger_write"
    assert e["materiality"] == "high"
    assert e["destination"] == "x.csv"
    assert e["summary"]["bytes_after"] == 10
    assert "run_id" in e and len(e["run_id"]) > 0


def test_track_write_captures_before_after(isolated_vault):
    dest = isolated_vault / "ledger.csv"
    dest.write_text("col\n", encoding="utf-8")  # header only, 0 rows
    with audit.track_write(dest, materiality="high", action="overwrite"):
        dest.write_text("col\na\nb\nc\n", encoding="utf-8")
    events = _read_events(isolated_vault)
    assert len(events) == 1
    s = events[0]["summary"]
    assert s["rows_before"] == 0
    assert s["rows_after"] == 3
    assert s["delta_rows"] == 3
    assert s["bytes_after"] > s["bytes_before"]


def test_track_write_skips_on_exception(isolated_vault):
    dest = isolated_vault / "ledger.csv"
    dest.write_text("col\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        with audit.track_write(dest, materiality="high"):
            raise RuntimeError("boom")
    assert _read_events(isolated_vault) == []


def test_run_id_consistent_across_emits(isolated_vault):
    audit.emit("state_write", source_function="t1")
    audit.emit("state_write", source_function="t2")
    events = _read_events(isolated_vault)
    assert events[0]["run_id"] == events[1]["run_id"]


def test_run_id_honors_env_var(isolated_vault, monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_RUN_ID", "fixed-run-id-123")
    audit._reset_cache_for_tests()
    audit.emit("state_write", source_function="t")
    events = _read_events(isolated_vault)
    assert events[0]["run_id"] == "fixed-run-id-123"


def test_actor_resolution(isolated_vault, monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_ACTOR", "bookkeeper")
    audit._reset_cache_for_tests()
    audit.emit("state_write", source_function="t")
    events = _read_events(isolated_vault)
    assert events[0]["actor"] == "bookkeeper"


def test_actor_default_is_direct_cli(isolated_vault):
    audit.emit("state_write", source_function="t")
    events = _read_events(isolated_vault)
    assert events[0]["actor"] == "direct_cli"


def test_log_is_append_only(isolated_vault):
    audit.emit("state_write", source_function="t1")
    first_path = next(_audit_dir().glob("events-*.jsonl"))
    first_content = first_path.read_text(encoding="utf-8")
    audit.emit("state_write", source_function="t2")
    second_content = first_path.read_text(encoding="utf-8")
    assert second_content.startswith(first_content)
    assert second_content.count("\n") == 2


def test_failure_is_fail_soft(isolated_vault, monkeypatch, capsys):
    real_mkdir = Path.mkdir

    def boom(self, *a, **kw):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "mkdir", boom)
    audit.emit("state_write", source_function="t")
    monkeypatch.setattr(Path, "mkdir", real_mkdir)
    err = capsys.readouterr().err
    assert "[audit]" in err


def test_gate_event_schema(isolated_vault):
    audit.emit_gate(
        "supplier_coverage",
        metric="uncategorized_pct",
        value=0.078,
        threshold=0.05,
        passed=False,
        source_function="categorize.main",
        trigger_context={"month": "2026-04"},
    )
    events = _read_events(isolated_vault)
    assert len(events) == 1
    e = events[0]
    assert e["event_type"] == "gate_fail"
    assert e["gate"]["passed"] is False
    assert e["gate"]["threshold"] == 0.05
    assert "destination" not in e
    assert "action" not in e


def test_coverage_event_no_passed_field(isolated_vault):
    audit.emit_coverage(
        "rows_normalized",
        142.0,
        threshold=None,
        source_function="normalize.main",
    )
    events = _read_events(isolated_vault)
    assert events[0]["event_type"] == "coverage_progress"
    assert "passed" not in events[0]["gate"]


def test_json_destination_summary(isolated_vault):
    dest = isolated_vault / "portfolio.json"
    dest.write_text(json.dumps({"a": 1, "b": 2}), encoding="utf-8")
    with audit.track_write(dest, materiality="high"):
        dest.write_text(json.dumps({"a": 1, "b": 2, "c": 3, "d": 4}), encoding="utf-8")
    events = _read_events(isolated_vault)
    s = events[0]["summary"]
    assert s["key_count_before"] == 2
    assert s["key_count_after"] == 4
    assert "delta_rows" not in s
