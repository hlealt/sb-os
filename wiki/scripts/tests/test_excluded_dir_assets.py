"""Tests for the global ``excluded_dir`` asset-folder fix.

Bug (found 2026-06-12): ``excluded_dir`` skipped ANY path segment literally
named ``assets``, which collided with the semantic entity sub-folder
``wiki/entities/assets/`` (asset-class financial entities: gold, us-dollar,
brent-crude, ...). Every lint function gating on ``excluded_dir`` silently
dropped those content pages — broken-link, stub, disputed-callout, type-tag,
and structural checks never saw them, and links pointing AT them were falsely
flagged broken (the pages were absent from the valid-page-name set).

Fix: ``excluded_dir`` now skips ONLY genuine binary-dump folders (``_assets``
and ``*-assets``) — the same predicate the normalize-filenames scan already
used as ``_binary_asset_dir`` — so the semantic ``assets`` content folder is
linted like any other entity folder while binary dumps stay excluded.

Run from the sb-os repo root:
    python -m pytest wiki/scripts/tests/test_excluded_dir_assets.py -v
"""

import importlib.util
import sys
from pathlib import Path

# Import the module under test directly (hyphen in filename requires importlib).
_SCRIPT_PATH = Path(__file__).parent.parent / "sb-wiki-lint-deterministic.py"
_spec = importlib.util.spec_from_file_location("sb_wiki_lint_deterministic", _SCRIPT_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["sb_wiki_lint_deterministic"] = _mod
_spec.loader.exec_module(_mod)

excluded_dir = _mod.excluded_dir
collect_wiki_pages = _mod.collect_wiki_pages
wiki_page_names = _mod.wiki_page_names


# ---------------------------------------------------------------------------
# excluded_dir predicate — semantic `assets/` included, binary dumps excluded
# ---------------------------------------------------------------------------

def test_semantic_assets_content_folder_not_excluded():
    # The bug: this returned True, dropping the whole content folder.
    assert excluded_dir(Path("wiki/entities/assets/gold.md")) is False


def test_bare_assets_segment_anywhere_not_excluded():
    assert excluded_dir(Path("wiki/entities/assets")) is False
    assert excluded_dir(Path("wiki/entities/assets/us-dollar.md")) is False


def test_underscore_assets_binary_dump_excluded():
    # `raw/_assets` is an image/PDF dump — must stay excluded.
    assert excluded_dir(Path("raw/_assets/_assets.md")) is True
    assert excluded_dir(Path("raw/_assets/01-board-overview.png")) is True


def test_hyphen_assets_binary_dump_excluded():
    # Per-source `<slug>-assets` dump folders stay excluded.
    assert excluded_dir(Path("raw/_unrouted/some-source-assets/img.png")) is True
    assert excluded_dir(Path("wiki/entities/foo-assets/dump.md")) is True


def test_non_asset_path_not_excluded():
    assert excluded_dir(Path("wiki/entities/oil.md")) is False
    assert excluded_dir(Path("wiki/concepts/inflation.md")) is False


# ---------------------------------------------------------------------------
# Structural walk: collect_wiki_pages sees an `assets/` content page
# ---------------------------------------------------------------------------

def _make_wiki(tmp_path: Path) -> Path:
    wiki_root = tmp_path / "kb"
    for sub in ("wiki/entities/assets", "wiki/entities/foo-assets",
                "wiki/concepts", "wiki/topics", "wiki/sources"):
        (wiki_root / sub).mkdir(parents=True, exist_ok=True)
    return wiki_root


def test_collect_wiki_pages_includes_assets_content_page(tmp_path):
    wiki_root = _make_wiki(tmp_path)
    gold = wiki_root / "wiki" / "entities" / "assets" / "gold.md"
    gold.write_text("---\ntype: entity\n---\n\nbody\n", encoding="utf-8")
    oil = wiki_root / "wiki" / "entities" / "oil.md"
    oil.write_text("---\ntype: entity\n---\n\nbody\n", encoding="utf-8")

    cet, _sources = collect_wiki_pages(wiki_root)
    assert gold in cet
    assert oil in cet


def test_collect_wiki_pages_excludes_assets_index_and_binary_dump(tmp_path):
    wiki_root = _make_wiki(tmp_path)
    # The folder index (assets/assets.md) is a leaf index, never a content page.
    index = wiki_root / "wiki" / "entities" / "assets" / "assets.md"
    index.write_text("---\ntype: index\n---\n\nindex\n", encoding="utf-8")
    # A binary-dump folder under entities stays excluded.
    dump = wiki_root / "wiki" / "entities" / "foo-assets" / "dump.md"
    dump.write_text("x\n", encoding="utf-8")

    cet, _sources = collect_wiki_pages(wiki_root)
    assert index not in cet
    assert dump not in cet


def test_wiki_page_names_includes_assets_pages_as_valid_link_targets(tmp_path):
    # Links pointing AT asset pages must resolve — the pages belong in the
    # valid-page-name set so they are not falsely flagged as broken links.
    wiki_root = _make_wiki(tmp_path)
    (wiki_root / "wiki" / "entities" / "assets" / "us-dollar.md").write_text(
        "---\ntype: entity\n---\n\nbody\n", encoding="utf-8")
    all_names, _topics, _theses = wiki_page_names(wiki_root)
    assert "us-dollar.md" in all_names
