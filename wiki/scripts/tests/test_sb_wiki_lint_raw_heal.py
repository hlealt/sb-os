"""Tests for the raw-index stale-`Wiki=No` heal (Step-1.7 remaining half, D13b).

Covers `heal_raw_wiki_cells` + `ingested_raw_filenames`:

  (a) `No`→`Yes` via filename-mirror (same-stem source page exists).
  (b) `No`→`Yes` via `raw:` backlink (source page names the raw, divergent stem).
  (c) `Partial` / `Duplicate (…)` / `Yes` rows are NEVER touched.
  (d) genuinely-pending `No` (no source page) stays `No`, not in healed.
  (e) dangling row (File cell → raw file absent on disk) is reported, never
      flipped (even if a same-stem source page exists) and never deleted.
  (f) check-mode (apply_changes=False) writes nothing; detection still populated.
  (g) PDF raw whose source page is the title-slug `.md` heals via mirror.
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

heal_raw_wiki_cells = _mod.heal_raw_wiki_cells
Report = _mod.Report

RAW_HEADER = "| File | Title | Date | Wiki |\n|------|-------|------|------|\n"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _raw_index(wiki_root: Path, origin: str, rows: list[tuple[str, str, str, str]]) -> Path:
    d = wiki_root / "raw" / origin
    d.mkdir(parents=True, exist_ok=True)
    body = RAW_HEADER + "".join(
        f"| [[{f}]] | {t} | {dt} | {w} |\n" for f, t, dt, w in rows
    )
    idx = d / f"{origin}.md"
    idx.write_text(body, encoding="utf-8")
    return idx


def _raw_file(wiki_root: Path, origin: str, filename: str) -> None:
    d = wiki_root / "raw" / origin
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(f"# {filename}\n", encoding="utf-8")


def _source_page(wiki_root: Path, origin: str, filename: str, raw_link: str | None) -> None:
    d = wiki_root / "wiki" / "sources" / origin
    d.mkdir(parents=True, exist_ok=True)
    fm = "---\ntype: source\n"
    if raw_link is not None:
        fm += f'raw: "[[{raw_link}]]"\n'
    fm += "---\n\n# page\n"
    (d / filename).write_text(fm, encoding="utf-8")


def _wiki_cell(idx_path: Path, raw_filename: str) -> str:
    for line in idx_path.read_text(encoding="utf-8").splitlines():
        if f"[[{raw_filename}]]" in line:
            return line.rstrip("|").rsplit("|", 1)[-1].strip()
    raise AssertionError(f"row for {raw_filename} not found")


def _run(wiki_root: Path, apply: bool = True) -> Report:
    report = Report(mode="apply" if apply else "check")
    heal_raw_wiki_cells(wiki_root, report, apply)
    return report


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_heals_via_filename_mirror(tmp_path: Path):
    wr = tmp_path / "kb"
    raw = "2026-05-28-charts.md"
    _raw_index(wr, "a16z", [(raw, "Charts", "2026-05-28", "No")])
    _raw_file(wr, "a16z", raw)
    _source_page(wr, "a16z", raw, raw_link=None)  # mirror only, no raw: field
    report = _run(wr)
    assert _wiki_cell(wr / "raw/a16z/a16z.md", raw) == "Yes"
    healed = report.detected["raw_wiki_healed"]
    assert len(healed) == 1
    assert healed[0]["signal"] == "filename-mirror"


def test_heals_via_raw_backlink_divergent_stem(tmp_path: Path):
    wr = tmp_path / "kb"
    raw = "2026-05-27-andreessen.md"
    _raw_index(wr, "ainvest", [(raw, "A16Z bet", "2026-05-27", "No")])
    _raw_file(wr, "ainvest", raw)
    # source page filename differs from raw stem; only the raw: backlink links it
    _source_page(wr, "ainvest", "differently-named-source.md", raw_link=raw)
    report = _run(wr)
    assert _wiki_cell(wr / "raw/ainvest/ainvest.md", raw) == "Yes"
    assert report.detected["raw_wiki_healed"][0]["signal"] == "raw-backlink"


def test_never_touches_partial_duplicate_yes(tmp_path: Path):
    wr = tmp_path / "kb"
    rows = [
        ("a.md", "A", "2026-01-01", "Partial"),
        ("b.md", "B", "2026-01-02", "Duplicate (of [[c.md]])"),
        ("d.md", "D", "2026-01-03", "Yes"),
    ]
    _raw_index(wr, "blog", rows)
    for f, *_ in rows:
        _raw_file(wr, "blog", f)
        _source_page(wr, "blog", f, raw_link=f)  # every one has a source page
    report = _run(wr)
    assert _wiki_cell(wr / "raw/blog/blog.md", "a.md") == "Partial"
    assert _wiki_cell(wr / "raw/blog/blog.md", "b.md") == "Duplicate (of [[c.md]])"
    assert _wiki_cell(wr / "raw/blog/blog.md", "d.md") == "Yes"
    assert report.detected["raw_wiki_healed"] == []


def test_genuinely_pending_no_stays_no(tmp_path: Path):
    wr = tmp_path / "kb"
    raw = "2026-06-09-pending.md"
    _raw_index(wr, "neofeed", [(raw, "Pending", "2026-06-09", "No")])
    _raw_file(wr, "neofeed", raw)  # raw exists but NO source page
    report = _run(wr)
    assert _wiki_cell(wr / "raw/neofeed/neofeed.md", raw) == "No"
    assert report.detected["raw_wiki_healed"] == []
    assert report.detected["raw_wiki_dangling"] == []


def test_dangling_reported_not_flipped(tmp_path: Path):
    wr = tmp_path / "kb"
    phantom = "2026-04-30-atms-didnt.md"   # apostrophe variant — file absent
    real = "2026-04-30-atms-didnt-real.md"
    _raw_index(wr, "substack", [
        (phantom, "ATMs", "2026-04-09", "No"),
        (real, "ATMs", "2026-04-30", "Yes"),
    ])
    _raw_file(wr, "substack", real)  # only the real raw exists on disk
    # a same-stem source page for the phantom DOES exist — must still NOT flip,
    # because the row's raw file is absent (dangling beats heal).
    _source_page(wr, "substack", phantom, raw_link=None)
    report = _run(wr)
    assert _wiki_cell(wr / "raw/substack/substack.md", phantom) == "No"
    assert report.detected["raw_wiki_healed"] == []
    dangling = report.detected["raw_wiki_dangling"]
    assert dangling == [{"origin": "substack", "file": phantom}]


def test_check_mode_writes_nothing(tmp_path: Path):
    wr = tmp_path / "kb"
    raw = "x.md"
    idx = _raw_index(wr, "blog", [(raw, "X", "2026-01-01", "No")])
    _raw_file(wr, "blog", raw)
    _source_page(wr, "blog", raw, raw_link=raw)
    before = idx.read_text(encoding="utf-8")
    report = _run(wr, apply=False)
    assert idx.read_text(encoding="utf-8") == before  # no write in check mode
    assert len(report.detected["raw_wiki_healed"]) == 1  # detection still reported


def test_pdf_raw_heals_via_mirror(tmp_path: Path):
    wr = tmp_path / "kb"
    pdf = "international-ai-safety-report-2026.pdf"
    _raw_index(wr, "papers", [(pdf, "Intl AI Safety", "2026-01-01", "No")])
    _raw_file(wr, "papers", pdf)
    # source page is the title-slug .md (same stem as the PDF)
    _source_page(wr, "papers", "international-ai-safety-report-2026.md", raw_link=None)
    _run(wr)
    assert _wiki_cell(wr / "raw/papers/papers.md", pdf) == "Yes"
