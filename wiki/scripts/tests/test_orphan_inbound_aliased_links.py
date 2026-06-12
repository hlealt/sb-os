"""Tests for orphan-inbound detection counting aliased wikilinks.

Bug (found 2026-06-12): `structural_walk`'s orphan inbound map built link
edges with `re.findall(r"\\[\\[([^\\]|#]+?\\.md)\\]\\]", text)`. The `[^\\]|#]`
class excludes `|`, so a `.md` target immediately followed by `|alias]]` never
matched and the inbound edge was missed — a page linked ONLY via aliased
wikilinks (`[[target.md|Display Text]]`) was falsely reported as an orphan.
`detect_broken_wikilinks` used a wider regex, so the two extractors disagreed.

Fix: widen the orphan-inbound regex to capture the target before an optional
`#anchor` and/or `|alias`, mirroring the rename extractors.

Run from the sb-os repo root:
    python -m pytest wiki/scripts/tests/test_orphan_inbound_aliased_links.py -v
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

structural_walk = _mod.structural_walk
Report = _mod.Report


def _entity(wiki_root: Path, name: str, body: str) -> None:
    page = wiki_root / "wiki" / "entities" / name
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(f"---\ntype: entity\n---\n\n{body}\n", encoding="utf-8")


def _orphans(wiki_root: Path) -> list[str]:
    report = Report(mode="check")
    structural_walk(wiki_root, report, apply_changes=False)
    return report.detected["orphans"]


def test_aliased_inbound_link_counts_as_inbound(tmp_path: Path) -> None:
    # A links B ONLY via an aliased wikilink. B must NOT be an orphan.
    wiki_root = tmp_path / "kb"
    _entity(wiki_root, "a.md", "See [[b.md|Display Text]] for details.")
    _entity(wiki_root, "b.md", "Standalone body.")
    orphans = _orphans(wiki_root)
    assert "b.md" not in orphans
    # A has no inbound link of its own — it stays an orphan (sanity anchor).
    assert "a.md" in orphans


def test_aliased_inbound_link_with_anchor_counts_as_inbound(tmp_path: Path) -> None:
    # Target followed by both a #heading anchor and an |alias.
    wiki_root = tmp_path / "kb"
    _entity(wiki_root, "a.md", "See [[b.md#Section|Display Text]].")
    _entity(wiki_root, "b.md", "Standalone body.")
    assert "b.md" not in _orphans(wiki_root)


def test_plain_inbound_link_still_counts(tmp_path: Path) -> None:
    # Regression guard: the widened regex must not break plain links.
    wiki_root = tmp_path / "kb"
    _entity(wiki_root, "a.md", "See [[b.md]].")
    _entity(wiki_root, "b.md", "Standalone body.")
    assert "b.md" not in _orphans(wiki_root)


def test_unlinked_page_is_still_orphan(tmp_path: Path) -> None:
    # Negative control: a page nobody links remains an orphan.
    wiki_root = tmp_path / "kb"
    _entity(wiki_root, "a.md", "No links here.")
    _entity(wiki_root, "b.md", "Nor here.")
    orphans = _orphans(wiki_root)
    assert "a.md" in orphans and "b.md" in orphans
