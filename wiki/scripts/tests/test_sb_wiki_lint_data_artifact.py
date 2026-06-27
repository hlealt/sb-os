"""Tests for the finance data-artifact raw class (`*-xbrl-companyfacts.json`).

Covers `sync_raw_indexes` + `heal_raw_wiki_cells` + `_is_recognized_wiki_value`
under the finance wiki extension (authority:
finance/wiki-ext/lint-rules.ext.md § "Data-Artifact Raw Class"):

  (a) finance registered → an un-indexed `*-xbrl-companyfacts.json` gets a row
      with `Wiki = N/A (data artifact)` (never `No`).
  (b) finance NOT registered → the `.json` is NOT indexed (base wiki unchanged).
  (c) a stray `.json` that is NOT companyfacts is never indexed, even with
      finance registered.
  (d) the add is idempotent — an existing `N/A (data artifact)` row is not
      duplicated on a second run.
  (e) heal CORRECTS a helper-created `No` on a data-artifact row to
      `N/A (data artifact)`, reported under `raw_data_artifact_corrected`.
  (f) heal corrects to `N/A`, NEVER `Yes`, even if a same-stem source page
      happens to exist (the data-artifact branch precedes the backlink/mirror heal).
  (g) finance NOT registered → a data-artifact `No` row is left `No` (no correction).
  (h) check-mode (apply_changes=False) writes nothing; detection still populated.
  (i) `N/A (data artifact)` is a recognized Wiki value, so the 2-col migration
      preserves the row (never bespoke) and a legacy 4-col row migrates verbatim.
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

_MOD_PATH = _SCRIPTS_DIR / "sb-wiki-lint-deterministic.py"
_spec = importlib.util.spec_from_file_location("sb_wiki_lint_deterministic", _MOD_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["sb_wiki_lint_deterministic"] = _mod
_spec.loader.exec_module(_mod)  # type: ignore

sync_raw_indexes = _mod.sync_raw_indexes
heal_raw_wiki_cells = _mod.heal_raw_wiki_cells
migrate_raw_indexes_to_file_wiki = _mod.migrate_raw_indexes_to_file_wiki
_is_recognized_wiki_value = _mod._is_recognized_wiki_value
is_data_artifact_raw = _mod.is_data_artifact_raw
DATA_ARTIFACT_WIKI_CELL = _mod.DATA_ARTIFACT_WIKI_CELL
Report = _mod.Report

RAW_HEADER_2COL = "| File | Wiki |\n|------|------|\n"
RAW_HEADER_4COL = "| File | Title | Date | Wiki |\n|------|-------|------|------|\n"

DA_JSON = "2026-06-04-atlassian-xbrl-companyfacts.json"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _manifest(vault_root: Path, extensions: list[str] | None) -> None:
    """Write the vault-root sb-os.json the helper walks up to find.

    *extensions* None → no `wiki_extensions` field at all; [] → empty list.
    """
    data: dict = {"wiki_root": "kb"}
    if extensions is not None:
        data["wiki_extensions"] = extensions
    (vault_root / "sb-os.json").write_text(json.dumps(data), encoding="utf-8")


def _raw_index_2col(wiki_root: Path, origin: str, rows: list[tuple[str, str]]) -> Path:
    d = wiki_root / "raw" / origin
    d.mkdir(parents=True, exist_ok=True)
    body = RAW_HEADER_2COL + "".join(f"| [[{f}]] | {w} |\n" for f, w in rows)
    idx = d / f"{origin}.md"
    idx.write_text(body, encoding="utf-8")
    return idx


def _raw_index_4col(wiki_root: Path, origin: str, rows: list[tuple[str, str, str, str]]) -> Path:
    d = wiki_root / "raw" / origin
    d.mkdir(parents=True, exist_ok=True)
    body = RAW_HEADER_4COL + "".join(
        f"| [[{f}]] | {t} | {dt} | {w} |\n" for f, t, dt, w in rows
    )
    idx = d / f"{origin}.md"
    idx.write_text(body, encoding="utf-8")
    return idx


def _raw_file(wiki_root: Path, origin: str, filename: str, content: str = "{}") -> None:
    d = wiki_root / "raw" / origin
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(content, encoding="utf-8")


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


def _rows_for(idx_path: Path, raw_filename: str) -> int:
    return sum(
        1
        for line in idx_path.read_text(encoding="utf-8").splitlines()
        if f"[[{raw_filename}]]" in line
    )


def _setup(tmp_path: Path, extensions: list[str] | None) -> Path:
    """Create a vault with sb-os.json and return its wiki_root (kb)."""
    wr = tmp_path / "kb"
    wr.mkdir(parents=True, exist_ok=True)
    _manifest(tmp_path, extensions)
    return wr


# ---------------------------------------------------------------------------
# Tests — sync (row creation)
# ---------------------------------------------------------------------------

def test_sync_adds_data_artifact_row_with_na_cell(tmp_path: Path):
    wr = _setup(tmp_path, ["finance"])
    _raw_index_2col(wr, "sec", [])
    _raw_file(wr, "sec", DA_JSON)
    report = Report(mode="apply")
    sync_raw_indexes(wr, report, apply_changes=True)
    assert _wiki_cell(wr / "raw/sec/sec.md", DA_JSON) == "N/A (data artifact)"


def test_sync_skips_json_when_finance_not_registered(tmp_path: Path):
    wr = _setup(tmp_path, None)  # no wiki_extensions field at all
    _raw_index_2col(wr, "sec", [])
    _raw_file(wr, "sec", DA_JSON)
    report = Report(mode="apply")
    sync_raw_indexes(wr, report, apply_changes=True)
    assert _rows_for(wr / "raw/sec/sec.md", DA_JSON) == 0


def test_sync_skips_json_when_extensions_empty(tmp_path: Path):
    wr = _setup(tmp_path, [])  # explicit empty list
    _raw_index_2col(wr, "sec", [])
    _raw_file(wr, "sec", DA_JSON)
    report = Report(mode="apply")
    sync_raw_indexes(wr, report, apply_changes=True)
    assert _rows_for(wr / "raw/sec/sec.md", DA_JSON) == 0


def test_sync_ignores_non_companyfacts_json(tmp_path: Path):
    wr = _setup(tmp_path, ["finance"])
    _raw_index_2col(wr, "sec", [])
    _raw_file(wr, "sec", "2026-06-04-something-else.json")
    report = Report(mode="apply")
    sync_raw_indexes(wr, report, apply_changes=True)
    assert _rows_for(wr / "raw/sec/sec.md", "2026-06-04-something-else.json") == 0


def test_sync_is_idempotent_no_duplicate_row(tmp_path: Path):
    wr = _setup(tmp_path, ["finance"])
    # Hand-added row already present (mirrors the live raw/sec/sec.md state).
    _raw_index_2col(wr, "sec", [(DA_JSON, "N/A (data artifact)")])
    _raw_file(wr, "sec", DA_JSON)
    report = Report(mode="apply")
    sync_raw_indexes(wr, report, apply_changes=True)
    assert _rows_for(wr / "raw/sec/sec.md", DA_JSON) == 1
    assert _wiki_cell(wr / "raw/sec/sec.md", DA_JSON) == "N/A (data artifact)"


# ---------------------------------------------------------------------------
# Tests — heal (No -> N/A correction)
# ---------------------------------------------------------------------------

def test_heal_corrects_no_to_na(tmp_path: Path):
    wr = _setup(tmp_path, ["finance"])
    _raw_index_2col(wr, "sec", [(DA_JSON, "No")])
    _raw_file(wr, "sec", DA_JSON)
    report = Report(mode="apply")
    heal_raw_wiki_cells(wr, report, apply_changes=True)
    assert _wiki_cell(wr / "raw/sec/sec.md", DA_JSON) == "N/A (data artifact)"
    corrected = report.detected["raw_data_artifact_corrected"]
    assert corrected == [
        {"origin": "sec", "file": DA_JSON, "from": "No", "to": "N/A (data artifact)"}
    ]
    # Not counted as a No->Yes heal.
    assert report.detected["raw_wiki_healed"] == []


def test_heal_never_sets_data_artifact_to_yes(tmp_path: Path):
    """Even if a same-stem source page exists, a data-artifact `No` is corrected
    to `N/A (data artifact)`, never flipped to `Yes` (the class default wins)."""
    wr = _setup(tmp_path, ["finance"])
    _raw_index_2col(wr, "sec", [(DA_JSON, "No")])
    _raw_file(wr, "sec", DA_JSON)
    _source_page(wr, "sec", DA_JSON, raw_link=DA_JSON)  # would normally heal -> Yes
    report = Report(mode="apply")
    heal_raw_wiki_cells(wr, report, apply_changes=True)
    assert _wiki_cell(wr / "raw/sec/sec.md", DA_JSON) == "N/A (data artifact)"
    assert report.detected["raw_wiki_healed"] == []
    assert len(report.detected["raw_data_artifact_corrected"]) == 1


def test_heal_leaves_no_when_finance_not_registered(tmp_path: Path):
    wr = _setup(tmp_path, None)
    _raw_index_2col(wr, "sec", [(DA_JSON, "No")])
    _raw_file(wr, "sec", DA_JSON)
    report = Report(mode="apply")
    heal_raw_wiki_cells(wr, report, apply_changes=True)
    assert _wiki_cell(wr / "raw/sec/sec.md", DA_JSON) == "No"
    assert report.detected["raw_data_artifact_corrected"] == []


def test_heal_check_mode_writes_nothing(tmp_path: Path):
    wr = _setup(tmp_path, ["finance"])
    idx = _raw_index_2col(wr, "sec", [(DA_JSON, "No")])
    _raw_file(wr, "sec", DA_JSON)
    before = idx.read_text(encoding="utf-8")
    report = Report(mode="check")
    heal_raw_wiki_cells(wr, report, apply_changes=False)
    assert idx.read_text(encoding="utf-8") == before
    assert len(report.detected["raw_data_artifact_corrected"]) == 1  # detection still reported


# ---------------------------------------------------------------------------
# Tests — recognized value + migration safety
# ---------------------------------------------------------------------------

def test_na_is_a_recognized_wiki_value():
    assert _is_recognized_wiki_value("N/A (data artifact)")
    assert _is_recognized_wiki_value("n/a (data artifact)")


def test_is_data_artifact_raw_pattern():
    assert is_data_artifact_raw(DA_JSON)
    assert is_data_artifact_raw("2026-06-09-microsoft-xbrl-companyfacts.json")
    assert not is_data_artifact_raw("2026-06-04-atlassian.md")
    assert not is_data_artifact_raw("something.json")
    assert not is_data_artifact_raw("xbrl-companyfacts.json")  # needs `-` prefix segment


def test_migration_preserves_na_2col_row(tmp_path: Path):
    wr = _setup(tmp_path, ["finance"])
    idx = _raw_index_2col(wr, "sec", [(DA_JSON, "N/A (data artifact)")])
    report = Report(mode="apply")
    migrate_raw_indexes_to_file_wiki(wr, report, apply_changes=True)
    assert _wiki_cell(idx, DA_JSON) == "N/A (data artifact)"
    # No bespoke / non-conforming report for the data-artifact row.
    assert not report.detected.get("raw_index_bespoke_reported")


def test_migration_collapses_legacy_4col_na_row_verbatim(tmp_path: Path):
    wr = _setup(tmp_path, ["finance"])
    idx = _raw_index_4col(
        wr, "sec", [(DA_JSON, "Atlassian XBRL", "2026-06-04", "N/A (data artifact)")]
    )
    report = Report(mode="apply")
    migrate_raw_indexes_to_file_wiki(wr, report, apply_changes=True)
    # Collapsed to 2-col, Wiki value preserved verbatim.
    assert idx.read_text(encoding="utf-8").splitlines()[0] == "| File | Wiki |"
    assert _wiki_cell(idx, DA_JSON) == "N/A (data artifact)"
    assert report.judgment_needed == []
