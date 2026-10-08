"""Tests for sb_task.py — the completion-line gate behind `edit --status done`.

validate_completion_line reuses routed_date / valid_iso_date, so a CONFORMING
line is exactly a sweepable block.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sb_task as sb  # noqa: E402

TODAY = "2026-06-18"


def test_validate_conforming_line():
    r = sb.validate_completion_line("- [x] Do thing ✅ 2026-06-18", TODAY)
    assert r["status"] == "conforming"
    assert r["date"] == "2026-06-18"
    assert r["reason"] is None


def test_validate_no_date_is_violation():
    r = sb.validate_completion_line("- [x] Do thing", TODAY)
    assert r["status"] == "violation"
    assert "no valid" in r["reason"]


def test_validate_no_space_before_date_is_violation():
    r = sb.validate_completion_line("- [x] Do thing ✅2026-06-18", TODAY)
    assert r["status"] == "violation"


def test_validate_unpadded_date_is_violation():
    r = sb.validate_completion_line("- [x] Do thing ✅ 2026-6-1", TODAY)
    assert r["status"] == "violation"


def test_validate_impossible_calendar_date_is_violation():
    r = sb.validate_completion_line("- [x] Do thing ✅ 2026-13-40", TODAY)
    assert r["status"] == "violation"


def test_validate_multiple_distinct_dates_is_violation():
    r = sb.validate_completion_line(
        "- [x] did then redid ✅ 2026-06-18 again ✅ 2026-06-15", TODAY)
    assert r["status"] == "violation"
    assert "multiple distinct" in r["reason"]


def test_validate_same_date_twice_is_conforming():
    r = sb.validate_completion_line(
        "- [x] belt and braces ✅ 2026-06-18 (done ✅ 2026-06-18)", TODAY)
    assert r["status"] == "conforming"
    assert r["date"] == "2026-06-18"


def test_validate_indented_subtask_is_not_a_task():
    r = sb.validate_completion_line("  - [x] nested done ✅ 2026-06-18", TODAY)
    assert r["status"] == "not-a-task"


def test_validate_open_checkbox_is_not_a_task():
    r = sb.validate_completion_line("- [ ] still open", TODAY)
    assert r["status"] == "not-a-task"


def test_validate_non_checkbox_bullet_is_not_a_task():
    r = sb.validate_completion_line("- _Ref:_ a continuation bullet", TODAY)
    assert r["status"] == "not-a-task"


def test_validate_column0_strikethrough_crossref_no_date_is_violation():
    """The dumb-validator boundary: a column-0 `- [x]` strikethrough relocation
    cross-ref (no ✅ date) is reported VIOLATION — the checker cannot tell it from
    a forgotten-date completion. The workflow protects such lines by NOT
    validating them (it fires only on a genuine completion)."""
    line = "- [x] ~~Build the thing~~ — **MOVED 2026-06-18 → Phase 1**"
    r = sb.validate_completion_line(line, TODAY)
    assert r["status"] == "violation"
    assert "no valid" in r["reason"]


def test_validate_trailing_newline_ignored():
    r = sb.validate_completion_line("- [x] Do thing ✅ 2026-06-18\n", TODAY)
    assert r["status"] == "conforming"
