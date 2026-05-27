"""Regression tests for p4-9: task_status_check read tool.

Verifies:
  1. Finds a task block by title substring (case-insensitive).
  2. Returns NOT_YET when the anchor file does not exist.
  3. Returns SHIPPED when the anchor file exists at the cited line.
  4. Returns STALE when the cited line exceeds the file's length.
  5. Returns UNCLEAR when the line spec is unparseable.
  6. Handles project folder name → tasks file resolution.
  7. Handles direct path to tasks file.
  8. Exit 1 when no task found matching the title.
  9. Exit 1 when project tasks file does not exist.
  10. Subtask lines are extracted and reported.
  11. _extract_ref_anchors parses file:line and file:range formats.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
for _p in (_SCRIPTS_DIR,):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from task_status_check import (  # noqa: E402
    _find_task_block,
    _extract_ref_anchors,
    _extract_subtask_lines,
    _check_anchor,
    run_check,
    _resolve_tasks_file,
)


# ---------------------------------------------------------------------------
# Sample task markdown fixture
# ---------------------------------------------------------------------------

SAMPLE_TASKS = """---
type: tasks
---

- [x] Tornar TIR confiável ✅ 2026-05-03
  - _Goal:_ Garantir que XIRR por ativo...
  - _Ref:_
    - `3-resources/tools/sb-os/finance/scripts/investimentos/irr_calculator.py:1-10`
    - `3-resources/tools/sb-os/finance/scripts/investimentos/calculate.py:39-76`
  - _Subtasks (todas concluídas):_
    - ✅ Mapear cada Lancamento para o tipo de evento
    - ✅ Decidir tratamento de Saldo Anterior

- [ ] Tarefa pendente
  - _Goal:_ Make something new.
  - _Ref:_
    - `scripts/investimentos/new_feature.py:100`
  - _Subtasks:_
    - [ ] Implement step one
    - [ ] Implement step two
"""
# Note: real tasks file format uses `_Ref:_` (colon before closing underscore)
# The parser accepts both `_Ref_:` and `_Ref:_` patterns


# ---------------------------------------------------------------------------
# Tests: _find_task_block
# ---------------------------------------------------------------------------

def test_find_task_block_case_insensitive():
    block = _find_task_block(SAMPLE_TASKS, "tornar tir")
    assert block is not None
    assert "irr_calculator" in block


def test_find_task_block_not_found():
    block = _find_task_block(SAMPLE_TASKS, "nonexistent task title xyz")
    assert block is None


def test_find_task_block_stops_at_next_task():
    block = _find_task_block(SAMPLE_TASKS, "Tornar TIR")
    assert "Tarefa pendente" not in block


# ---------------------------------------------------------------------------
# Tests: _extract_ref_anchors
# ---------------------------------------------------------------------------

def test_extract_ref_anchors_line_range():
    block = """- [x] Some task
  - _Ref:_
    - `scripts/investimentos/irr_calculator.py:1-10`
"""
    anchors = _extract_ref_anchors(block)
    assert len(anchors) >= 1
    assert anchors[0]["file"] == "scripts/investimentos/irr_calculator.py"
    assert anchors[0]["line_spec"] == "1-10"


def test_extract_ref_anchors_single_line():
    block = """- [x] Some task
  - _Ref:_
    - `scripts/investimentos/calculate.py:42`
"""
    anchors = _extract_ref_anchors(block)
    assert len(anchors) >= 1
    assert anchors[0]["line_spec"] == "42"


def test_extract_ref_anchors_no_ref_section():
    block = "- [ ] A task with no ref section"
    anchors = _extract_ref_anchors(block)
    assert anchors == []


def test_extract_ref_anchors_from_sample():
    block = _find_task_block(SAMPLE_TASKS, "tornar tir")
    anchors = _extract_ref_anchors(block)
    assert len(anchors) == 2
    files = [a["file"] for a in anchors]
    assert any("irr_calculator" in f for f in files)
    assert any("calculate" in f for f in files)


# ---------------------------------------------------------------------------
# Tests: _extract_subtask_lines
# ---------------------------------------------------------------------------

def test_extract_subtask_lines_from_sample():
    block = _find_task_block(SAMPLE_TASKS, "tornar tir")
    subtasks = _extract_subtask_lines(block)
    assert len(subtasks) >= 2


def test_extract_subtask_unchecked():
    block = _find_task_block(SAMPLE_TASKS, "Tarefa pendente")
    subtasks = _extract_subtask_lines(block)
    # The task's own checkbox line + 2 sub-items = 3 total
    assert len(subtasks) >= 2


# ---------------------------------------------------------------------------
# Tests: _check_anchor
# ---------------------------------------------------------------------------

def test_check_anchor_not_yet_missing_file(tmp_path):
    anchor = {"ref": "nonexistent.py:10", "file": "nonexistent.py", "line_spec": "10"}
    result = _check_anchor(anchor, tmp_path)
    assert result["status"] == "NOT_YET"


def test_check_anchor_shipped_file_exists_with_line(tmp_path):
    script = tmp_path / "my_script.py"
    script.write_text("\n".join(["line1", "line2", "def foo():", "    pass"]), encoding="utf-8")
    anchor = {"ref": "my_script.py:3", "file": "my_script.py", "line_spec": "3"}
    result = _check_anchor(anchor, tmp_path)
    assert result["status"] == "SHIPPED"
    assert "foo" in result["detail"]


def test_check_anchor_stale_line_beyond_eof(tmp_path):
    script = tmp_path / "short.py"
    script.write_text("x = 1\n", encoding="utf-8")
    anchor = {"ref": "short.py:999", "file": "short.py", "line_spec": "999"}
    result = _check_anchor(anchor, tmp_path)
    assert result["status"] == "STALE"


def test_check_anchor_unclear_bad_line_spec(tmp_path):
    script = tmp_path / "ok.py"
    script.write_text("x = 1\n", encoding="utf-8")
    anchor = {"ref": "ok.py:abc", "file": "ok.py", "line_spec": "abc"}
    result = _check_anchor(anchor, tmp_path)
    assert result["status"] == "UNCLEAR"


def test_check_anchor_no_line_spec_file_exists(tmp_path):
    script = tmp_path / "nolinespec.py"
    script.write_text("x = 1\n", encoding="utf-8")
    anchor = {"ref": "nolinespec.py", "file": "nolinespec.py", "line_spec": None}
    result = _check_anchor(anchor, tmp_path)
    assert result["status"] == "SHIPPED"


# ---------------------------------------------------------------------------
# Tests: run_check integration
# ---------------------------------------------------------------------------

def test_run_check_all_shipped(tmp_path):
    # Write a tasks file with a real script anchor
    script = tmp_path / "my_calc.py"
    script.write_text("# calculate\ndef build():\n    pass\n", encoding="utf-8")

    tasks_content = f"""---
type: tasks
---

- [ ] Build the portfolio calc
  - _Ref:_
    - `my_calc.py:2`
  - _Subtasks:_
    - [ ] Implement step one
"""
    tasks_file = tmp_path / "project-tasks.md"
    tasks_file.write_text(tasks_content, encoding="utf-8")

    exit_code = run_check(str(tasks_file), "portfolio calc", None, tmp_path)
    assert exit_code == 0


def test_run_check_not_yet(tmp_path):
    tasks_content = """---
type: tasks
---

- [ ] Build new thing
  - _Ref:_
    - `nonexistent_tool.py:50`
"""
    tasks_file = tmp_path / "p-tasks.md"
    tasks_file.write_text(tasks_content, encoding="utf-8")

    exit_code = run_check(str(tasks_file), "new thing", None, tmp_path)
    assert exit_code == 1


def test_run_check_task_not_found_exits_1(tmp_path):
    tasks_file = tmp_path / "p-tasks.md"
    tasks_file.write_text("- [ ] Something else\n", encoding="utf-8")
    exit_code = run_check(str(tasks_file), "completely missing task", None, tmp_path)
    assert exit_code == 1


def test_run_check_project_not_found_exits_1(tmp_path):
    exit_code = run_check("nonexistent-project", "any task", None, tmp_path)
    assert exit_code == 1


def test_resolve_tasks_file_from_project_name(tmp_path):
    # Create the expected folder structure
    proj_dir = tmp_path / "1-projects" / "test-proj"
    proj_dir.mkdir(parents=True)
    tasks_file = proj_dir / "test-proj-tasks.md"
    tasks_file.write_text("# tasks\n", encoding="utf-8")
    result = _resolve_tasks_file("test-proj", tmp_path)
    assert result == tasks_file
