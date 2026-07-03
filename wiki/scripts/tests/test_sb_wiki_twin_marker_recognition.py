"""Marker-based PDF-twin recognition (Trinity misfire fix).

A regenerable PDF twin `.md` used to be recognized ONLY when a *same-stem* `.pdf`
sat beside it. When the title-conformance pass (Step 7.6) renamed the PDF to a
new stem but the twin kept its old stem, the stems diverged and the twin stopped
being recognized — lint gave it a `| … | No |` row, ingest-all discovery treated
it as un-ingested, and Step 1.7 / U10 flagged the genuine twin as a duplicate
(the Trinity case, 2026-07-02).

The predicate is now MARKER-based: a `.md` carrying a twin marker
(`twin_extractor:`/`source_pdf:` frontmatter, or a legacy `Original PDF:` body
ref) that resolves to a `.pdf` in its folder (via `source_pdf:`, same-stem, an
`Original PDF:` ref, or a sole in-folder PDF) is a twin regardless of stem. This
covers all four surfaces plus Option B (the rename executor keeps the pair in
lockstep):

  (A1) manifest `_resolve_twin_pdf` resolves a diverged twin via `source_pdf:`;
  (A2) manifest discovery excludes a diverged twin from `missing`;
  (A3) lint `is_regenerable_pdf_twin` recognizes a diverged twin;
  (A4) lint `sync_raw_indexes` gives a diverged twin NO own raw-index row;
  (A5) lint U10 `detect_md_duplicate_raws` never flags a diverged twin;
  (B)  lint `execute_renames` renames the twin in lockstep + refreshes source_pdf.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def _load(mod_filename: str, mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, _SCRIPTS_DIR / mod_filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_manifest = _load("sb-wiki-ingest-all-manifest.py", "sb_wiki_ingest_all_manifest")
_lint = _load("sb-wiki-lint-deterministic.py", "sb_wiki_lint_deterministic")

collect = _manifest.collect
manifest_resolve_twin_pdf = _manifest._resolve_twin_pdf

resolve_twin_pdf = _lint.resolve_twin_pdf
is_regenerable_pdf_twin = _lint.is_regenerable_pdf_twin
sync_raw_indexes = _lint.sync_raw_indexes
detect_md_duplicate_raws = _lint.detect_md_duplicate_raws
execute_renames = _lint.execute_renames
Report = _lint.Report

RAW_HEADER_2COL = "| File | Wiki |\n|------|------|\n"

# The renamed (title-slug) PDF stem and the twin's diverged (kept-old) stem.
PDF = "trinity-evolved-coordinator.pdf"
TWIN = "2026-06-24-trinity.md"
TWIN_BODY = (
    "---\n"
    "twin_extractor: pymupdf+marker\n"
    "twin_fidelity: true\n"
    f"source_pdf: {PDF}\n"
    "pages: 30\n"
    "---\n\n"
    "# Trinity: An Evolved LLM Coordinator\n\nbody\n"
)


def _raw_index(wiki_root: Path, origin: str, rows: list[tuple[str, str]]) -> Path:
    d = wiki_root / "raw" / origin
    d.mkdir(parents=True, exist_ok=True)
    idx = d / f"{origin}.md"
    idx.write_text(
        RAW_HEADER_2COL + "".join(f"| [[{f}]] | {w} |\n" for f, w in rows),
        encoding="utf-8",
    )
    return idx


# ---------------------------------------------------------------------------
# A1/A2 — manifest resolver + discovery
# ---------------------------------------------------------------------------

def _manifest_vault(tmp_path: Path) -> Path:
    """`papers` origin: a renamed (title-slug) PDF marked Yes, its diverged twin
    (kept old stem, source_pdf naming the renamed PDF), a second ingested PDF (so
    the folder is multi-PDF — the sole-PDF fallback cannot be what resolves), and
    a genuinely-pending clip that SHOULD surface as missing."""
    wr = tmp_path / "kb"
    d = wr / "raw" / "papers"
    d.mkdir(parents=True)
    (d / PDF).write_bytes(b"%PDF-1.4 fake")
    (d / "mixture-of-experts.pdf").write_bytes(b"%PDF-1.4 fake")
    (d / TWIN).write_text(TWIN_BODY, encoding="utf-8")
    (d / "2026-06-30-new-thing.md").write_text("# New thing\n", encoding="utf-8")
    _raw_index(
        wr, "papers",
        [(PDF, "Yes"), ("mixture-of-experts.pdf", "Yes"), ("2026-06-30-new-thing.md", "No")],
    )
    return wr


def test_manifest_resolver_resolves_diverged_twin(tmp_path: Path):
    """(A1) `_resolve_twin_pdf` maps the diverged twin to the renamed PDF via
    `source_pdf:` — even though no same-stem `.pdf` exists."""
    wr = _manifest_vault(tmp_path)
    twin_path = wr / "raw" / "papers" / TWIN
    assert not twin_path.with_suffix(".pdf").exists()  # stems diverged
    assert manifest_resolve_twin_pdf(twin_path) == PDF
    # A non-twin clip (no marker) resolves to None.
    assert manifest_resolve_twin_pdf(wr / "raw" / "papers" / "2026-06-30-new-thing.md") is None


def test_manifest_excludes_diverged_twin_from_missing(tmp_path: Path):
    """(A2) discovery excludes the diverged twin; only the genuine pending clip
    surfaces as missing, and the twin is never a duplicate/twin-original."""
    wr = _manifest_vault(tmp_path)
    result = collect(wr, exclude=set(), only_origin=None)
    missing = {it["filename"] for it in result["items"]}
    assert TWIN not in missing
    assert missing == {"2026-06-30-new-thing.md"}
    assert result["totals"]["missing"] == 1
    assert result["totals"]["duplicates"] == 0
    assert result["twin_original_files"] == []


# ---------------------------------------------------------------------------
# A3/A4 — lint predicate + sync_raw_indexes row exclusion
# ---------------------------------------------------------------------------

def _lint_raw_vault(tmp_path: Path) -> Path:
    """Same shape as the manifest vault but the index lists ONLY the two PDFs, so
    sync_raw_indexes must add a row for the pending clip yet NOT for the twin."""
    wr = tmp_path / "kb"
    d = wr / "raw" / "papers"
    d.mkdir(parents=True)
    (d / PDF).write_bytes(b"%PDF-1.4 fake")
    (d / "mixture-of-experts.pdf").write_bytes(b"%PDF-1.4 fake")
    (d / TWIN).write_text(TWIN_BODY, encoding="utf-8")
    (d / "2026-06-30-new-thing.md").write_text("# New thing\n", encoding="utf-8")
    _raw_index(wr, "papers", [(PDF, "Yes"), ("mixture-of-experts.pdf", "Yes")])
    return wr


def test_lint_predicate_recognizes_diverged_twin(tmp_path: Path):
    """(A3) `is_regenerable_pdf_twin` recognizes the diverged twin; a non-twin
    clip is not a twin."""
    wr = _lint_raw_vault(tmp_path)
    d = wr / "raw" / "papers"
    assert resolve_twin_pdf(d / TWIN) == PDF
    assert is_regenerable_pdf_twin(d / TWIN) is True
    assert is_regenerable_pdf_twin(d / "2026-06-30-new-thing.md") is False


def test_sync_gives_diverged_twin_no_row(tmp_path: Path):
    """(A4) sync_raw_indexes adds a row for the genuine pending clip but NEVER for
    the marker-based twin whose same-stem `.pdf` was renamed away."""
    wr = _lint_raw_vault(tmp_path)
    report = Report(mode="apply")
    sync_raw_indexes(wr, report, apply_changes=True)
    index_text = (wr / "raw" / "papers" / "papers.md").read_text(encoding="utf-8")
    assert f"[[{TWIN}]]" not in index_text           # twin gets NO own row
    assert "[[2026-06-30-new-thing.md]]" in index_text  # ordinary raw does


# ---------------------------------------------------------------------------
# A5 — lint U10 md_duplicate_raws never flags a twin
# ---------------------------------------------------------------------------

def test_u10_never_flags_diverged_twin(tmp_path: Path):
    """(A5) The twin's title matches its ingested source page, but it is a
    recognized twin → NOT flagged. A non-twin re-clip with the same title IS
    flagged, proving the detector still works and the skip is twin-specific."""
    wr = tmp_path / "kb"
    d = wr / "raw" / "papers"
    d.mkdir(parents=True)
    (d / PDF).write_bytes(b"%PDF-1.4 fake")
    (d / TWIN).write_text(TWIN_BODY, encoding="utf-8")
    # Non-twin re-clip: same title, NO twin marker → a genuine duplicate.
    reclip = "2026-06-25-trinity-reclip.md"
    (d / reclip).write_text(
        "---\ntitle: Trinity: An Evolved LLM Coordinator\n---\n\nreclip\n",
        encoding="utf-8",
    )
    _raw_index(wr, "papers", [(PDF, "Yes"), (TWIN, "No"), (reclip, "No")])
    # Ingested source page: raw: names the PDF (NOT the twin), so neither the twin
    # nor the reclip is covered by the ingested-skip — both reach the title check.
    sp = wr / "wiki" / "sources" / "papers"
    sp.mkdir(parents=True)
    (sp / "trinity-evolved-coordinator.md").write_text(
        "---\ntype: source\ntitle: Trinity: An Evolved LLM Coordinator\n"
        f'raw: "[[{PDF}]]"\n---\n\n# Trinity\n',
        encoding="utf-8",
    )
    report = Report(mode="check")
    detect_md_duplicate_raws(wr, report)
    flagged = {f["raw"] for f in report.detected["md_duplicate_raws"]}
    assert f"raw/papers/{TWIN}" not in flagged        # twin never flagged
    assert f"raw/papers/{reclip}" in flagged          # non-twin duplicate IS flagged


# ---------------------------------------------------------------------------
# B — execute_renames keeps the twin in lockstep
# ---------------------------------------------------------------------------

def test_execute_renames_renames_twin_in_lockstep(tmp_path: Path):
    """(B) When the PDF is renamed, its same-stem twin `.md` is renamed in
    lockstep and its `source_pdf:` frontmatter is refreshed — so the pair never
    diverges at the title-conformance rename."""
    wr = tmp_path / "kb"
    d = wr / "raw" / "papers"
    d.mkdir(parents=True)
    old, new = "old-trinity", "trinity-evolved-coordinator"
    (d / f"{old}.pdf").write_bytes(b"%PDF-1.4 fake")
    (d / f"{old}.md").write_text(
        "---\ntwin_extractor: pymupdf\ntwin_fidelity: true\n"
        f"source_pdf: {old}.pdf\npages: 3\n---\n\n# Trinity\n\nbody\n",
        encoding="utf-8",
    )
    _raw_index(wr, "papers", [(f"{old}.pdf", "Yes")])
    sp = wr / "wiki" / "sources" / "papers"
    sp.mkdir(parents=True)
    (sp / f"{old}.md").write_text(
        f'---\ntype: source\nraw: "[[{old}.md]]"\n---\n\n# Trinity\n',
        encoding="utf-8",
    )
    plan = wr / "plan.json"
    plan.write_text(
        json.dumps([{"origin": "papers", "old_stem": old, "new_stem": new}]),
        encoding="utf-8",
    )
    report = Report(mode="apply")
    execute_renames(wr, plan, report)

    # PDF + twin both moved to the new stem; old files gone.
    assert (d / f"{new}.pdf").exists() and not (d / f"{old}.pdf").exists()
    assert (d / f"{new}.md").exists() and not (d / f"{old}.md").exists()
    # Twin's source_pdf frontmatter refreshed to the new PDF name.
    twin_text = (d / f"{new}.md").read_text(encoding="utf-8")
    assert f"source_pdf: {new}.pdf" in twin_text
    assert f"source_pdf: {old}.pdf" not in twin_text
    # Source page moved and its raw: backlink rewritten to the renamed twin.
    assert (sp / f"{new}.md").exists() and not (sp / f"{old}.md").exists()
    assert f"[[{new}.md]]" in (sp / f"{new}.md").read_text(encoding="utf-8")
    # The twin rename is recorded in the moved list; no errors.
    moved = report.detected["renames"]["moved"]
    assert f"raw/papers/{old}.md -> {new}.md" in moved
    assert report.detected["renames"]["errors"] == []
    # Post-rename the pair is same-stem again → recognized via the same-stem arm.
    assert is_regenerable_pdf_twin(d / f"{new}.md") is True
