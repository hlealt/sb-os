"""Tests for the kept-original (`Wiki = Original (twin: …)`) discovery exclusion
in sb-wiki-ingest-all-manifest.py.

A source PDF whose content is ingested via a NON-same-stem `.md` twin is marked
`Original (twin: [[<twin>]])` on its raw row. The manifest MUST:

  (a) NOT offer the kept-original `.pdf` as a missing ingest candidate;
  (b) count it under `totals.twin_originals` + `twin_original_files`, NOT under
      `duplicates` (a kept original needs no disposition and must never be
      confused with a deletable content-duplicate);
  (c) keep `duplicate_rows()` matching ONLY `Duplicate (…)` — a sweep keying on
      "duplicate" never matches a kept original.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_MOD_PATH = _SCRIPTS_DIR / "sb-wiki-ingest-all-manifest.py"
_spec = importlib.util.spec_from_file_location("sb_wiki_ingest_all_manifest", _MOD_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["sb_wiki_ingest_all_manifest"] = _mod
_spec.loader.exec_module(_mod)  # type: ignore

collect = _mod.collect
duplicate_rows = _mod.duplicate_rows
twin_original_rows = _mod.twin_original_rows

RAW_HEADER_2COL = "| File | Wiki |\n|------|------|\n"


def _build_kept_original_vault(tmp_path: Path) -> Path:
    """A `dhl` origin: a kept-original `.pdf` marked `Original (twin: …)`, its
    ingested `.md` twin (Wiki=Yes, with a source page), and an unrelated
    not-yet-ingested `.md` clip that SHOULD surface as missing."""
    wr = tmp_path / "kb"
    origin_dir = wr / "raw" / "dhl"
    origin_dir.mkdir(parents=True)

    pdf = "dhl-global-connectedness-report-2026.pdf"
    twin = "2026-06-06-dhl-global-connectedness-report-2026.md"
    pending = "2026-06-20-dhl-something-new.md"

    (origin_dir / pdf).write_bytes(b"%PDF-1.4 fake")
    (origin_dir / twin).write_text("# twin\n", encoding="utf-8")
    (origin_dir / pending).write_text("# pending\n", encoding="utf-8")

    (origin_dir / "dhl.md").write_text(
        RAW_HEADER_2COL
        + f"| [[{pdf}]] | Original (twin: [[{twin}]]) |\n"
        + f"| [[{twin}]] | Yes |\n"
        + f"| [[{pending}]] | No |\n",
        encoding="utf-8",
    )

    # The twin .md is the ingested source; its source page backlinks it.
    src_dir = wr / "wiki" / "sources" / "dhl"
    src_dir.mkdir(parents=True)
    (src_dir / twin).write_text(
        f'---\ntype: source\nraw: "[[{twin}]]"\n---\n\n# DHL\n', encoding="utf-8"
    )
    return wr


def test_kept_original_excluded_from_missing(tmp_path: Path):
    wr = _build_kept_original_vault(tmp_path)
    result = collect(wr, exclude=set(), only_origin=None)

    missing_names = {it["filename"] for it in result["items"]}
    # The kept-original PDF is NOT a missing candidate; the genuine pending clip is.
    assert "dhl-global-connectedness-report-2026.pdf" not in missing_names
    assert "2026-06-20-dhl-something-new.md" in missing_names
    assert result["totals"]["missing"] == 1


def test_kept_original_counted_as_twin_original_not_duplicate(tmp_path: Path):
    wr = _build_kept_original_vault(tmp_path)
    result = collect(wr, exclude=set(), only_origin=None)

    assert result["totals"]["twin_originals"] == 1
    assert result["twin_original_files"] == ["dhl/dhl-global-connectedness-report-2026.pdf"]
    # A kept original is NEVER a duplicate.
    assert result["totals"]["duplicates"] == 0
    assert result["duplicate_files"] == []


def test_row_matchers_keyed_on_distinct_prefixes(tmp_path: Path):
    wr = _build_kept_original_vault(tmp_path)
    origin_dir = wr / "raw" / "dhl"
    # `twin_original_rows` matches the kept original; `duplicate_rows` does not.
    assert twin_original_rows(origin_dir) == {"dhl-global-connectedness-report-2026.pdf"}
    assert duplicate_rows(origin_dir) == set()
