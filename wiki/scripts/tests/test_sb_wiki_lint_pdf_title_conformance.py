"""Tests for `detect_pdf_title_conformance` sourcing the title from the PDF's
source-page frontmatter (post-ADX-9/10 raw-index reduction).

ADX-9/10 removed the raw-index `Title` column, leaving the detector dormant
(0 proposals). This restores it: the title is read from the ingested PDF's 1:1
source page (`wiki/sources/{origin}/{slug}.md` `title:` frontmatter, else first
H1). Coverage:

  (a) ingested PDF (mirror) whose filename != source-page title -> proposal.
  (b) un-ingested PDF (no source page) -> NO proposal (dormant).
  (c) ingested PDF whose filename already == source-page title-slug -> NO proposal.
  (d) source page located via `raw:` backlink (divergent stem) -> proposal.
  (e) source page located via `Original PDF:` body backlink -> proposal.
  (f) first-H1 fallback (no `title:` frontmatter) -> proposal.
  (g) legacy 4-col raw-index Title still supplies a title in transition.
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

detect_pdf_title_conformance = _mod.detect_pdf_title_conformance
Report = _mod.Report

RAW_HEADER_2COL = "| File | Wiki |\n|------|------|\n"
RAW_HEADER_4COL = "| File | Title | Date | Wiki |\n|------|-------|------|------|\n"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _pdf(wiki_root: Path, origin: str, filename: str) -> None:
    d = wiki_root / "raw" / origin
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_bytes(b"%PDF-1.4 stub\n")


def _raw_index_2col(wiki_root: Path, origin: str, rows: list[tuple[str, str]]) -> None:
    d = wiki_root / "raw" / origin
    d.mkdir(parents=True, exist_ok=True)
    body = RAW_HEADER_2COL + "".join(f"| [[{f}]] | {w} |\n" for f, w in rows)
    (d / f"{origin}.md").write_text(body, encoding="utf-8")


def _raw_index_4col(wiki_root: Path, origin: str, rows: list[tuple[str, str, str, str]]) -> None:
    d = wiki_root / "raw" / origin
    d.mkdir(parents=True, exist_ok=True)
    body = RAW_HEADER_4COL + "".join(
        f"| [[{f}]] | {t} | {dt} | {w} |\n" for f, t, dt, w in rows
    )
    (d / f"{origin}.md").write_text(body, encoding="utf-8")


def _source_page(
    wiki_root: Path,
    origin: str,
    filename: str,
    *,
    title: str | None = None,
    h1: str | None = None,
    raw_link: str | None = None,
    original_pdf: str | None = None,
) -> None:
    d = wiki_root / "wiki" / "sources" / origin
    d.mkdir(parents=True, exist_ok=True)
    fm = "---\ntype: source\n"
    if title is not None:
        fm += f'title: "{title}"\n'
    if raw_link is not None:
        fm += f'raw: "[[{raw_link}]]"\n'
    fm += "---\n\n"
    body = ""
    if h1 is not None:
        body += f"# {h1}\n\n"
    if original_pdf is not None:
        body += f"Original PDF: [[{original_pdf}]]\n"
    (d / filename).write_text(fm + body, encoding="utf-8")


def _run(wiki_root: Path) -> Report:
    report = Report(mode="check")
    detect_pdf_title_conformance(wiki_root, report)
    return report


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_ingested_pdf_mismatch_proposes_rename(tmp_path: Path):
    """(a) Mirror source page; filename != title-slug -> a rename proposal."""
    wr = tmp_path / "kb"
    pdf = "2602.21012v1.pdf"  # cryptic arXiv name
    _pdf(wr, "papers", pdf)
    _raw_index_2col(wr, "papers", [(pdf, "Yes")])
    # source page is the title-slug .md (same stem as the PROPOSED name);
    # title frontmatter carries the real title.
    _source_page(
        wr, "papers", "international-ai-safety-report-2026.md",
        title="International AI Safety Report 2026", raw_link=pdf,
    )
    report = _run(wr)
    proposals = report.detected["rename_proposals"]
    assert proposals == [
        {"origin": "papers", "old_stem": "2602.21012v1",
         "new_stem": "international-ai-safety-report-2026"}
    ]


def test_uningested_pdf_no_proposal(tmp_path: Path):
    """(b) No source page anywhere -> dormant, NO proposal (criterion 2)."""
    wr = tmp_path / "kb"
    pdf = "kolmbook-eng-scan.pdf"
    _pdf(wr, "papers", pdf)
    _raw_index_2col(wr, "papers", [(pdf, "No")])
    report = _run(wr)
    assert report.detected["rename_proposals"] == []
    assert report.detected["duplicate_raws"] == []
    assert report.detected["title_disambiguation_needed"] == []


def test_filename_matches_title_no_proposal(tmp_path: Path):
    """(c) Filename already == title-slug -> conforming, NO proposal."""
    wr = tmp_path / "kb"
    pdf = "international-ai-safety-report-2026.pdf"
    _pdf(wr, "papers", pdf)
    _raw_index_2col(wr, "papers", [(pdf, "Yes")])
    _source_page(
        wr, "papers", "international-ai-safety-report-2026.md",
        title="International AI Safety Report 2026",
    )
    report = _run(wr)
    assert report.detected["rename_proposals"] == []


def test_source_via_raw_backlink_divergent_stem(tmp_path: Path):
    """(d) Source page stem differs from the PDF stem; only `raw:` links it."""
    wr = tmp_path / "kb"
    pdf = "scan-dump-0001.pdf"
    _pdf(wr, "papers", pdf)
    _raw_index_2col(wr, "papers", [(pdf, "Yes")])
    _source_page(
        wr, "papers", "differently-named-source.md",
        title="You Only Look Once", raw_link=pdf,
    )
    report = _run(wr)
    assert report.detected["rename_proposals"] == [
        {"origin": "papers", "old_stem": "scan-dump-0001",
         "new_stem": "you-only-look-once"}
    ]


def test_source_via_original_pdf_body_backlink(tmp_path: Path):
    """(e) Legacy dated-clip origin: the source page names the bare PDF in body."""
    wr = tmp_path / "kb"
    pdf = "caiso-raw-export.pdf"
    _pdf(wr, "caiso", pdf)
    _raw_index_2col(wr, "caiso", [(pdf, "Yes")])
    _source_page(
        wr, "caiso", "2026-05-01-grid-report.md",
        title="Grid Operations Report", original_pdf=pdf,
    )
    report = _run(wr)
    assert report.detected["rename_proposals"] == [
        {"origin": "caiso", "old_stem": "caiso-raw-export",
         "new_stem": "grid-operations-report"}
    ]


def test_first_h1_fallback_when_no_title_frontmatter(tmp_path: Path):
    """(f) No `title:` -> first H1 is the title source."""
    wr = tmp_path / "kb"
    pdf = "2511.99999v2.pdf"
    _pdf(wr, "papers", pdf)
    _raw_index_2col(wr, "papers", [(pdf, "Yes")])
    _source_page(
        wr, "papers", "attention-is-all-you-need.md",
        h1="Attention Is All You Need", raw_link=pdf,
    )
    report = _run(wr)
    assert report.detected["rename_proposals"] == [
        {"origin": "papers", "old_stem": "2511.99999v2",
         "new_stem": "attention-is-all-you-need"}
    ]


def test_legacy_4col_index_title_still_used_in_transition(tmp_path: Path):
    """(g) A not-yet-migrated legacy 4-col index still supplies the Title."""
    wr = tmp_path / "kb"
    pdf = "cryptic-name.pdf"
    _pdf(wr, "papers", pdf)
    _raw_index_4col(wr, "papers", [(pdf, "Real Paper Title", "2026-01-01", "No")])
    # No source page exists; the legacy index Title is the only source.
    report = _run(wr)
    assert report.detected["rename_proposals"] == [
        {"origin": "papers", "old_stem": "cryptic-name",
         "new_stem": "real-paper-title"}
    ]


def test_source_page_title_overrides_legacy_4col_title(tmp_path: Path):
    """(h) When BOTH a source-page title and a legacy 4-col index Title exist,
    the source-page title is PRIMARY (the `source_titles or legacy_titles`
    precedence) — the legacy index Title is fallback-only, never overriding."""
    wr = tmp_path / "kb"
    pdf = "cryptic-name.pdf"
    _pdf(wr, "papers", pdf)
    # Legacy index supplies one title; the ingested source page supplies another.
    _raw_index_4col(wr, "papers", [(pdf, "Stale Index Title", "2026-01-01", "Yes")])
    _source_page(
        wr, "papers", "cryptic-name.md",
        title="Authoritative Source Title", raw_link=pdf,
    )
    report = _run(wr)
    # Proposal slug comes from the SOURCE page title, not the legacy index Title.
    assert report.detected["rename_proposals"] == [
        {"origin": "papers", "old_stem": "cryptic-name",
         "new_stem": "authoritative-source-title"}
    ]


def test_target_slug_pdf_already_exists_reports_duplicate(tmp_path: Path):
    """(i) The proposed `{slug}.pdf` already exists on disk -> NOT a rename;
    reported as a duplicate raw (never auto-renamed over an existing file).

    The canonical-named PDF exists but is NOT itself ingested (no source page
    mirrors or backlinks it), so only the cryptic PDF is in the slug group —
    isolating the single-member duplicate branch (not disambiguation)."""
    wr = tmp_path / "kb"
    cryptic = "2602.21012v1.pdf"
    canonical = "international-ai-safety-report-2026.pdf"
    _pdf(wr, "papers", cryptic)
    _pdf(wr, "papers", canonical)  # the slug target already exists, un-ingested
    _raw_index_2col(wr, "papers", [(cryptic, "Yes"), (canonical, "No")])
    # The ingested source page's stem must NOT mirror the canonical PDF stem,
    # else the canonical PDF would also pick up the title via the mirror arm and
    # the group would become a 2-member disambiguation instead of a duplicate.
    _source_page(
        wr, "papers", "divergent-source-stem.md",
        title="International AI Safety Report 2026", raw_link=cryptic,
    )
    report = _run(wr)
    assert report.detected["rename_proposals"] == []
    assert report.detected["duplicate_raws"] == [
        {"origin": "papers", "file": "2602.21012v1.pdf",
         "existing": "international-ai-safety-report-2026.pdf"}
    ]


def test_two_pdfs_same_title_slug_need_disambiguation(tmp_path: Path):
    """(j) Two distinct PDFs whose ingested titles slug to the SAME value ->
    disambiguation queue, NOT silent renames (preserves the contract return
    shape's `title_disambiguation_needed` branch)."""
    wr = tmp_path / "kb"
    a = "scan-a.pdf"
    b = "scan-b.pdf"
    _pdf(wr, "papers", a)
    _pdf(wr, "papers", b)
    _raw_index_2col(wr, "papers", [(a, "Yes"), (b, "Yes")])
    _source_page(wr, "papers", "src-a.md", title="Same Title", raw_link=a)
    _source_page(wr, "papers", "src-b.md", title="Same Title", raw_link=b)
    report = _run(wr)
    assert report.detected["rename_proposals"] == []
    assert report.detected["duplicate_raws"] == []
    dis = report.detected["title_disambiguation_needed"]
    assert sorted(d["file"] for d in dis) == ["scan-a.pdf", "scan-b.pdf"]
    assert all(d["title_slug"] == "same-title" for d in dis)
    assert all(d["origin"] == "papers" for d in dis)
