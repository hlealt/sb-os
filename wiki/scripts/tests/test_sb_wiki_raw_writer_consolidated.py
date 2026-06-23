"""Regression tests for the consolidated raw-index writer (KEYSTONE — task p1-2).

The source code shipped by p1-2 is correct on disk; ADX-2 persists the
regression coverage its prior dispatch built, ran, then deleted. These tests
lock the in-force keystone behaviors (ADX-1 option C — structural fixes only,
no legacy-header normalization / Description migration):

  Rule 1 (Locator UPDATE) — ``build_raw_edit`` flips ``Wiki`` by the MATCHED
      ROW's own layout, never the header's ``Wiki`` index. A 4-col data row
      appended under a legacy 3-col ``File|Description|Wiki`` header is flipped
      at its own last cell (idx 3), never the header's Wiki idx (2 = the wider
      row's Date cell). Asserts the Date cell is byte-unchanged and ONLY the
      Wiki cell flips, under BOTH a 3-col and a 4-col header.
  Rule 3 (Producer) — ``sync_raw_indexes`` sizes an appended row to the ACTUAL
      header width of the index it edits (no 4-col-under-3-col mix manufactured).
  Rule 5 (Twin D1) — a regenerable PDF twin (``twin_extractor:`` /
      ``Original PDF:`` + same-stem ``.pdf``) is EXCLUDED from the row-adding
      loop; a caiso/engie-brasil dated clip (no marker, no same-stem ``.pdf``)
      is NOT excluded.
  Rule 6 (Consolidate) — the single name-keyed writer is the sole row builder:
      the lint module's ``build_raw_row`` / ``set_raw_row_wiki`` /
      ``raw_row_wiki_index`` / ``repair_raw_row_width`` are the SAME objects the
      transaction module exposes (the 3 writers route through ONE authority).
  Broken 5-col repair — ``repair_raw_row_width`` merges a split-subtitle 5-col
      row back into ONE Title, preserving the Title text.

Behavior is proven DIRECTLY (cell contents / positions asserted), never by
row-count alone.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def _load(module_name: str, filename: str):
    """Load a hyphenated sibling script by path (the suite's standard seam)."""
    if module_name in sys.modules:
        return sys.modules[module_name]
    mod_path = _SCRIPTS_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, mod_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod  # register before exec so dataclasses resolve
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_TX = _load("sb_wiki_index_transaction", "sb-wiki-index-transaction.py")
_LINT = _load("sb_wiki_lint_deterministic", "sb-wiki-lint-deterministic.py")

# Transaction module (the single writer authority)
build_raw_edit = _TX.build_raw_edit
build_raw_row = _TX.build_raw_row
set_raw_row_wiki = _TX.set_raw_row_wiki
raw_row_wiki_index = _TX.raw_row_wiki_index
repair_raw_row_width = _TX.repair_raw_row_width
tx_split_row = _TX.split_row

# Lint module (the producer + twin gate)
sync_raw_indexes = _LINT.sync_raw_indexes
is_regenerable_pdf_twin = _LINT.is_regenerable_pdf_twin
Report = _LINT.Report
lint_split_row_cells = _LINT.split_row_cells


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

HEADER_4COL = "| File | Title | Date | Wiki |\n|------|-------|------|------|\n"
HEADER_3COL = "| File | Description | Wiki |\n|------|-------------|------|\n"


def _write_index(path: Path, header: str, data_rows: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "".join(r + "\n" for r in data_rows), encoding="utf-8")
    return path


def _row_cells(index_path: Path, raw_filename: str) -> list[str]:
    """Return the parsed cells of the data row whose File cell links the raw."""
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = tx_split_row(line)
        if cells and f"[[{raw_filename}]]" in cells[0]:
            return cells
    raise AssertionError(f"row for {raw_filename} not found in {index_path}")


def _raw_md(wiki_root: Path, origin: str, filename: str, *, title: str, date: str,
            twin_marker: str | None = None) -> Path:
    d = wiki_root / "raw" / origin
    d.mkdir(parents=True, exist_ok=True)
    fm = f"---\ntitle: {title}\ndate: {date}\n"
    if twin_marker == "frontmatter":
        fm += "twin_extractor: sb-wiki-pdf-twin.py\n"
    fm += "---\n\n"
    body = f"# {title}\n"
    if twin_marker == "reference":
        body += "\nOriginal PDF: original.pdf\n"
    (d / filename).write_text(fm + body, encoding="utf-8")
    return d / filename


def _raw_pdf(wiki_root: Path, origin: str, filename: str) -> Path:
    d = wiki_root / "raw" / origin
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    p.write_bytes(b"%PDF-1.4 fake\n")
    return p


# ---------------------------------------------------------------------------
# Rule 1 — Locator UPDATE never misfires into the Date cell
# ---------------------------------------------------------------------------

def test_update_4col_flips_only_wiki_date_byte_unchanged(tmp_path: Path):
    """4-col header: flipping a No->Yes row touches ONLY the Wiki cell; the Date
    cell is byte-identical before and after."""
    raw = "2026-05-28-charts.md"
    idx = _write_index(
        tmp_path / "a16z.md", HEADER_4COL,
        [f"| [[{raw}]] | Charts | 2026-05-28 | No |"],
    )
    before_date = _row_cells(idx, raw)[2]
    edit = build_raw_edit(idx, raw, title=None, date=None)
    idx.write_text(edit.after, encoding="utf-8", newline="")
    cells = _row_cells(idx, raw)
    assert cells[2] == before_date == "2026-05-28"   # Date cell untouched
    assert cells[3] == "Yes"                          # only Wiki flipped
    assert cells[1] == "Charts"                        # Title untouched
    assert "SET raw Wiki" in edit.action


def test_update_3col_legacy_flips_last_cell_not_header_wiki_index(tmp_path: Path):
    """Legacy 3-col File|Description|Wiki header: the Wiki flag is the row's OWN
    last cell (idx 2), and the Description cell is byte-unchanged — proving the
    flip keys off the matched row, not a fixed header index."""
    raw = "2026-05-27-andreessen.md"
    idx = _write_index(
        tmp_path / "every.md", HEADER_3COL,
        [f"| [[{raw}]] | A long legacy summary of the piece | No |"],
    )
    before_desc = _row_cells(idx, raw)[1]
    edit = build_raw_edit(idx, raw, title=None, date=None)
    idx.write_text(edit.after, encoding="utf-8", newline="")
    cells = _row_cells(idx, raw)
    assert len(cells) == 3                              # row width preserved
    assert cells[1] == before_desc == "A long legacy summary of the piece"
    assert cells[2] == "Yes"                            # row's own last cell


def test_update_4col_row_under_3col_header_no_date_misfire(tmp_path: Path):
    """The 5B core: a 4-col DATA row appended beneath a legacy 3-col header.
    The header's Wiki index is 2 (= the wider row's DATE cell). The flip MUST
    land in the row's own last cell (idx 3), leaving the Date cell (idx 2)
    byte-unchanged — never misfiring Yes into Date."""
    raw = "2026-06-01-mixed.md"
    idx = _write_index(
        tmp_path / "mails.md", HEADER_3COL,
        [f"| [[{raw}]] | A mixed-width title | 2026-06-01 | No |"],
    )
    before_date = _row_cells(idx, raw)[2]
    edit = build_raw_edit(idx, raw, title=None, date=None)
    idx.write_text(edit.after, encoding="utf-8", newline="")
    cells = _row_cells(idx, raw)
    assert cells[2] == before_date == "2026-06-01"      # Date NOT clobbered
    assert cells[3] == "Yes"                            # row's own last cell
    assert "2026-06-01" not in cells[3]                 # date never leaked into Wiki


def test_update_unrecognized_width_refuses(tmp_path: Path):
    """A 5-col (unrecognized) row is REFUSED, not misfired into."""
    import pytest
    raw = "2026-06-02-wide.md"
    idx = _write_index(
        tmp_path / "wide.md", HEADER_4COL,
        [f"| [[{raw}]] | Part A | Part B | 2026-06-02 | No |"],
    )
    with pytest.raises(_TX.TransactionError) as exc:
        build_raw_edit(idx, raw, title=None, date=None)
    assert "unrecognized" in str(exc.value)


# ---------------------------------------------------------------------------
# Rule 3 — Producer sizes appended rows to the ACTUAL header
# ---------------------------------------------------------------------------

def test_producer_appends_4col_row_under_4col_header(tmp_path: Path):
    wr = tmp_path / "kb"
    idx = _write_index(wr / "raw" / "blog" / "blog.md", HEADER_4COL, [])
    raw = _raw_md(wr, "blog", "2026-05-10-post.md", title="Post", date="2026-05-10")
    sync_raw_indexes(wr, Report(mode="apply"), apply_changes=True)
    cells = _row_cells(idx, raw.name)
    assert len(cells) == 4                              # sized to 4-col header
    assert cells[1] == "Post" and cells[2] == "2026-05-10"
    assert cells[3] == "No"


def test_producer_appends_3col_row_under_3col_header_no_mix(tmp_path: Path):
    """Under a legacy 3-col header the producer appends a 3-col row (no 4-col mix
    manufactured): File + blank Description + Wiki, with Wiki as the last cell."""
    wr = tmp_path / "kb"
    idx = _write_index(wr / "raw" / "every" / "every.md", HEADER_3COL, [])
    raw = _raw_md(wr, "every", "2026-05-11-essay.md", title="Essay", date="2026-05-11")
    sync_raw_indexes(wr, Report(mode="apply"), apply_changes=True)
    cells = _row_cells(idx, raw.name)
    assert len(cells) == 3                              # NOT 4 — no mix manufactured
    assert cells[2] == "No"                             # Wiki is the last cell
    assert "2026-05-11" not in cells                    # no Date column created


# ---------------------------------------------------------------------------
# Rule 5 — Twin exclusion (regenerable twin out; dated clip in)
# ---------------------------------------------------------------------------

def test_regenerable_twin_frontmatter_excluded(tmp_path: Path):
    wr = tmp_path / "kb"
    idx = _write_index(wr / "raw" / "papers" / "papers.md", HEADER_4COL, [])
    _raw_pdf(wr, "papers", "report.pdf")
    twin = _raw_md(wr, "papers", "report.md", title="Report", date="2026-01-01",
                   twin_marker="frontmatter")
    assert is_regenerable_pdf_twin(twin) is True
    sync_raw_indexes(wr, Report(mode="apply"), apply_changes=True)
    body = idx.read_text(encoding="utf-8")
    assert "[[report.md]]" not in body                  # twin .md got NO row


def test_regenerable_twin_original_pdf_reference_excluded(tmp_path: Path):
    wr = tmp_path / "kb"
    idx = _write_index(wr / "raw" / "papers" / "papers.md", HEADER_4COL, [])
    _raw_pdf(wr, "papers", "safety.pdf")
    twin = _raw_md(wr, "papers", "safety.md", title="Safety", date="2026-01-02",
                   twin_marker="reference")
    assert is_regenerable_pdf_twin(twin) is True
    sync_raw_indexes(wr, Report(mode="apply"), apply_changes=True)
    assert "[[safety.md]]" not in idx.read_text(encoding="utf-8")


def test_caiso_dated_clip_not_excluded(tmp_path: Path):
    """A caiso/engie-brasil dated CLIP (no twin marker, no same-stem .pdf) is a
    real source and MUST get its own row."""
    wr = tmp_path / "kb"
    idx = _write_index(wr / "raw" / "caiso" / "caiso.md", HEADER_4COL, [])
    clip = _raw_md(wr, "caiso", "2026-04-09-caiso-grid.md",
                   title="CAISO grid clip", date="2026-04-09")
    assert is_regenerable_pdf_twin(clip) is False
    sync_raw_indexes(wr, Report(mode="apply"), apply_changes=True)
    cells = _row_cells(idx, clip.name)
    assert cells[1] == "CAISO grid clip" and cells[3] == "No"


def test_engie_clip_with_no_pdf_not_excluded(tmp_path: Path):
    wr = tmp_path / "kb"
    idx = _write_index(wr / "raw" / "engie" / "engie.md", HEADER_4COL, [])
    clip = _raw_md(wr, "engie", "2026-05-02-engie-brasil.md",
                   title="Engie Brasil note", date="2026-05-02")
    assert is_regenerable_pdf_twin(clip) is False
    sync_raw_indexes(wr, Report(mode="apply"), apply_changes=True)
    assert "[[2026-05-02-engie-brasil.md]]" in idx.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Rule 6 — Single-writer authority (the 3 writers route through ONE module)
# ---------------------------------------------------------------------------

def test_lint_helpers_are_the_transaction_authority():
    """The lint module's raw-row primitives ARE the transaction module's objects
    (identity, not a copy) — proving consolidation onto ONE name-keyed writer."""
    assert _LINT.build_raw_row is _TX.build_raw_row
    assert _LINT.set_raw_row_wiki is _TX.set_raw_row_wiki
    assert _LINT.raw_row_wiki_index is _TX.raw_row_wiki_index
    assert _LINT.repair_raw_row_width is _TX.repair_raw_row_width


def test_build_raw_row_places_by_name_not_fixed_index():
    """The single writer places by column NAME: a 3-col legacy header yields a
    3-col row with Wiki last; a 4-col header yields File/Title/Date/Wiki."""
    row3 = build_raw_row(["File", "Description", "Wiki"], "x.md", "T", "2026-01-01", "Yes")
    cells3 = tx_split_row(row3)
    assert len(cells3) == 3 and cells3[0] == "[[x.md]]" and cells3[2] == "Yes"
    assert cells3[1] == ""                              # Description left blank (no migration)

    row4 = build_raw_row(["File", "Title", "Date", "Wiki"], "x.md", "T", "2026-01-01", "No")
    cells4 = tx_split_row(row4)
    assert cells4 == ["[[x.md]]", "T", "2026-01-01", "No"]


def test_raw_row_wiki_index_keys_on_row_width():
    assert raw_row_wiki_index(["[[a]]", "desc", "No"]) == 2          # 3-col -> last
    assert raw_row_wiki_index(["[[a]]", "t", "2026-01-01", "No"]) == 3  # 4-col -> last
    assert raw_row_wiki_index(["[[a]]", "b", "c", "d", "e"]) is None    # 5-col -> refuse


def test_set_raw_row_wiki_only_touches_wiki_cell():
    cells = ["[[a.md]]", "Title", "2026-01-01", "No"]
    new_cells, prev = set_raw_row_wiki(cells, "Yes")
    assert prev == "No"
    assert new_cells == ["[[a.md]]", "Title", "2026-01-01", "Yes"]
    # unrecognized width refused, returns previous=None and unchanged cells
    wide = ["a", "b", "c", "d", "e"]
    same, none_prev = set_raw_row_wiki(wide, "Yes")
    assert none_prev is None and same == wide


# ---------------------------------------------------------------------------
# Broken 5-col repair — merge split subtitle back to one Title
# ---------------------------------------------------------------------------

def test_repair_merges_split_subtitle_preserving_title():
    """A 5-col row caused by a split subtitle (Title | Subtitle) merges back to a
    single Title cell joined with '--', preserving both halves of the Title."""
    cells = ["[[post.md]]", "Main Title", "The Subtitle", "2026-03-01", "No"]
    repaired, changed = repair_raw_row_width(cells, header_width=4)
    assert changed is True
    assert repaired == ["[[post.md]]", "Main Title -- The Subtitle", "2026-03-01", "No"]
    assert "Main Title" in repaired[1] and "The Subtitle" in repaired[1]


def test_repair_noop_on_correct_width():
    cells = ["[[post.md]]", "Title", "2026-03-01", "No"]
    repaired, changed = repair_raw_row_width(cells, header_width=4)
    assert changed is False and repaired == cells


def test_repair_noop_on_non_plus_one_overwidth():
    """Only a row exactly ONE cell wider than a 4-col header is repaired; a wider
    bespoke row is left for report, never guessed."""
    cells = ["[[post.md]]", "a", "b", "c", "2026-03-01", "No"]  # 6 cells
    repaired, changed = repair_raw_row_width(cells, header_width=4)
    assert changed is False and repaired == cells
