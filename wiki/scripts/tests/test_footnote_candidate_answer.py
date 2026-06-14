"""Regression: the citation-integrity gate (`check-pages`) must not misread a
mid-line `Candidate answer[^N]:` occurrence as anything other than a genuine
inline use of footnote `[^N]`.

Bug (surfaced 2026-06-14 during ingest UAT): `footnote_state` counted inline
uses with `\\[\\^(\\d+)\\](?!:)`, so a `[^N]` sitting immediately before a `:`
(the questions-layer `Candidate answer[^N]:` convention) was excluded from the
inline set. A footnote whose ONLY inline use was such an occurrence then read as
an unreferenced definition and FAILED the gate.

Covers:
  (a) a page whose sole use of `[^N]` is inside `Candidate answer[^N]:` passes;
  (b) a genuine unreferenced definition still fails (detection unchanged);
  (c) `cmd_check_pages` exit codes match (0 = clean, 1 = failure).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_MOD_PATH = _SCRIPTS_DIR / "sb-wiki-lint-deterministic.py"
_spec = importlib.util.spec_from_file_location("sb_wiki_lint_deterministic", _MOD_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["sb_wiki_lint_deterministic"] = _mod
_spec.loader.exec_module(_mod)  # type: ignore

footnote_state = _mod.footnote_state
cmd_check_pages = _mod.cmd_check_pages


# ---------------------------------------------------------------------------
# footnote_state — unit level
# ---------------------------------------------------------------------------

def test_candidate_answer_counts_as_inline_use():
    """`Candidate answer[^1]:` is the ONLY use of `[^1]` — it must count as inline."""
    text = (
        "## Open questions\n\n"
        "- What is X?\n"
        "  Candidate answer[^1]: yes, per the source.\n\n"
        "[^1]: [[some-source.md]]\n"
    )
    state = footnote_state(text)
    assert state["defs"] == ["1"]
    assert state["inline"] == ["1"]
    # def and inline match → no integrity issue
    assert set(state["defs"]) == set(state["inline"])


def test_definition_marker_not_double_counted():
    """The line-start `[^1]:` definition marker must NOT itself be an inline use."""
    text = "body text[^1] here.\n\n[^1]: [[source.md]]\n"
    state = footnote_state(text)
    assert state["defs"] == ["1"]
    # exactly one inline use (the in-body `[^1]`), not two
    assert state["inline"] == ["1"]


def test_genuine_unreferenced_def_still_detected():
    """A definition with no inline use anywhere must remain detectable as stale."""
    text = "Some prose with no citation.\n\n[^1]: [[orphan-source.md]]\n"
    state = footnote_state(text)
    assert state["defs"] == ["1"]
    assert state["inline"] == []
    assert set(state["defs"]) - set(state["inline"]) == {"1"}


# ---------------------------------------------------------------------------
# cmd_check_pages — command/exit-code level
# ---------------------------------------------------------------------------

def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_check_pages_passes_candidate_answer_only_use(tmp_path, capsys):
    page = _write(
        tmp_path,
        "questions.md",
        "## Q\n\n  Candidate answer[^3]: confirmed.\n\n[^3]: [[src.md]]\n",
    )
    rc = cmd_check_pages([str(page)])
    capsys.readouterr()
    assert rc == 0


def test_check_pages_fails_genuine_orphan_def(tmp_path, capsys):
    page = _write(
        tmp_path,
        "questions.md",
        "## Q\n\nNo citations here.\n\n[^3]: [[orphan.md]]\n",
    )
    rc = cmd_check_pages([str(page)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "def without inline ref" in out
