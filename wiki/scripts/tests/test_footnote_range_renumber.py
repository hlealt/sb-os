"""Regression: the C3 footnote renumber must not rewrite a marker range.

Bug (2026-09-29, agent-memory-architectures.md): a callout referring to
footnotes by number ("[^1] and [^10]–[^23]") was renumbered like citations —
the range was garbled ("[^2]–[^3]") and, sitting first, the callout drove the
renumber order of the whole page. A range is not a citation form
(citation-format.md), so the walk reports it and leaves the page untouched.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "sb_wiki_lint_deterministic", _SCRIPTS_DIR / "sb-wiki-lint-deterministic.py"
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["sb_wiki_lint_deterministic"] = _mod
_spec.loader.exec_module(_mod)  # type: ignore

DEFS = "".join(f"[^{n}]: [[s{n}.md]]\n" for n in range(1, 6))


def _walk(tmp_path: Path, body: str) -> tuple[dict, str]:
    page = tmp_path / "wiki" / "topics" / "t.md"
    page.parent.mkdir(parents=True)
    page.write_text(f"---\ncreated: 2026-09-01\n---\n{body}\n\n## Sources\n\n{DEFS}", encoding="utf-8")
    report = _mod.Report(mode="apply")
    _mod.structural_walk(tmp_path, report, apply_changes=True)
    return report.detected, page.read_text(encoding="utf-8")


def test_range_blocks_renumber_and_is_reported(tmp_path: Path) -> None:
    body = (
        "> [!note] footnotes [^1] and [^3]–[^5] are vendor posts.\n\n"
        "A[^1] B[^2] C[^3] D[^4] E[^5]."
    )
    detected, after = _walk(tmp_path, body)
    assert detected["renumbered"] == []
    assert body in after  # page byte-stable
    issues = detected["footnote_issues"][0]["issues"]
    assert any(i.startswith("footnote range") and "[^3]-[^5]" in i for i in issues)


def test_adjacent_markers_still_renumber(tmp_path: Path) -> None:
    detected, after = _walk(tmp_path, "A[^2][^1] B[^3] C[^4] D[^5].")
    assert detected["renumbered"] and "A[^1][^2]" in after
    assert detected["footnote_issues"] == []
