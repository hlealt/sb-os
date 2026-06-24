"""Regression: `sync_raw_indexes` never crashes on a binary/non-UTF-8 `.md`
placed directly under `raw/<origin>/`.

Before the guard, an undecodable `.md` next to a same-stem `.pdf` reached
`is_regenerable_pdf_twin` → `read_text` and aborted the WHOLE lint run with an
unhandled `UnicodeDecodeError`. The fix probes each raw `.md`'s decodability in
the row-adding loop, then skips it (no index row) and surfaces it under
`report.detected["raw_undecodable"]` — the run completes.

Covers:
  (a) undecodable `.md` WITH a same-stem `.pdf` (the original crash path) — no
      crash, file surfaced, no own row, the `.pdf` and a well-formed sibling row.
  (b) bare undecodable `.md` (no sibling `.pdf`) — no crash, surfaced, no row.
  (c) clean corpus — `raw_undecodable` is the empty list (key always present).
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

sync_raw_indexes = _mod.sync_raw_indexes
Report = _mod.Report

# A byte sequence that is NOT valid UTF-8 (0xff is never a valid start byte).
BINARY_BYTES = b"\xff\xfe\x00\x01binary\x80\x81\x82 not utf-8"


def _origin(wiki_root: Path, origin: str) -> Path:
    d = wiki_root / "raw" / origin
    d.mkdir(parents=True, exist_ok=True)
    return d


def _good_raw(d: Path, filename: str) -> None:
    d.joinpath(filename).write_text(f"# {filename}\n\nbody\n", encoding="utf-8")


def _binary_raw(d: Path, filename: str) -> None:
    d.joinpath(filename).write_bytes(BINARY_BYTES)


def _index_rows(wiki_root: Path, origin: str) -> list[str]:
    idx = wiki_root / "raw" / origin / f"{origin}.md"
    if not idx.exists():
        return []
    return [
        line for line in idx.read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith("| [[")
    ]


def _run(wiki_root: Path, apply: bool = True) -> Report:
    report = Report(mode="apply" if apply else "check")
    # Must NOT raise — that is the regression.
    sync_raw_indexes(wiki_root, report, apply)
    return report


def test_undecodable_md_with_sibling_pdf_no_crash(tmp_path: Path):
    """The original crash path: binary `.md` + same-stem `.pdf`."""
    wr = tmp_path / "kb"
    d = _origin(wr, "papers")
    _good_raw(d, "good-source.md")
    _binary_raw(d, "binary-source.md")
    d.joinpath("binary-source.pdf").write_bytes(b"%PDF-1.4 fake")

    report = _run(wr)

    assert report.detected["raw_undecodable"] == ["raw/papers/binary-source.md"]
    rows = _index_rows(wr, "papers")
    # The binary `.md` got NO own row; the good `.md` and the `.pdf` did.
    assert not any("[[binary-source.md]]" in r for r in rows)
    assert any("[[good-source.md]]" in r for r in rows)
    assert any("[[binary-source.pdf]]" in r for r in rows)


def test_bare_undecodable_md_no_crash(tmp_path: Path):
    """A binary `.md` with no sibling `.pdf` is still surfaced and skipped."""
    wr = tmp_path / "kb"
    d = _origin(wr, "blog")
    _good_raw(d, "ok.md")
    _binary_raw(d, "junk.md")

    report = _run(wr)

    assert report.detected["raw_undecodable"] == ["raw/blog/junk.md"]
    rows = _index_rows(wr, "blog")
    assert not any("[[junk.md]]" in r for r in rows)
    assert any("[[ok.md]]" in r for r in rows)


def test_clean_corpus_empty_undecodable_list(tmp_path: Path):
    """No undecodable raws → key present and empty (always-set contract)."""
    wr = tmp_path / "kb"
    d = _origin(wr, "neofeed")
    _good_raw(d, "a.md")
    _good_raw(d, "b.md")

    report = _run(wr)

    assert report.detected["raw_undecodable"] == []
