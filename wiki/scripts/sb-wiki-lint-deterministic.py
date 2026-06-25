#!/usr/bin/env python3
"""Deterministic support pass for sb-wiki-lint.

This script handles only mechanical wiki maintenance. It never writes the
judgment-bearing index `Description` cell (the unified sources/topics/concepts/
entities cell, U11). Those gaps are emitted as a JSON queue for the LLM lint
workflow.

Incremental lint state spine
----------------------------
The helper computes a dirty set of pages whose content changed since the
last run. Stamps are persisted in the report JSON (reused as state file).
Run with ``--full`` to treat every page as dirty. A missing, corrupt, or
schema-mismatched state file triggers automatic full-mode fallback.
Stamps reflect the helper-run snapshot; if the overall lint workflow is
interrupted after the helper but before LLM passes complete, re-run with
``--full`` to force re-reading.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import re
import hashlib
import subprocess
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Consolidated raw-index writer authority (U2b)
# ---------------------------------------------------------------------------
# The ONE name-keyed writer lives in sb-wiki-index-transaction.py (U2b home —
# it holds the row primitives and is what /sb-wiki-ingest calls). The filename
# is hyphenated, so import it by path. Every raw-index structural mutation in
# THIS file routes through these helpers; no row is built independently here.
def _load_raw_index_writer():
    name = "sb_wiki_index_transaction"
    if name in sys.modules:
        return sys.modules[name]
    mod_path = Path(__file__).resolve().parent / "sb-wiki-index-transaction.py"
    spec = importlib.util.spec_from_file_location(name, mod_path)
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so the module's @dataclass can resolve its __module__.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_RAW_WRITER = _load_raw_index_writer()
build_raw_row = _RAW_WRITER.build_raw_row
set_raw_row_wiki = _RAW_WRITER.set_raw_row_wiki
raw_row_wiki_index = _RAW_WRITER.raw_row_wiki_index
repair_raw_row_width = _RAW_WRITER.repair_raw_row_width


# ADX-9/ADX-10: the raw index is reduced to `| File | Wiki |` — the summary
# (Title/Description) AND the Date column are both dropped. Legacy 4-col/3-col
# headers are still RECOGNIZED and MIGRATED by migrate_raw_indexes_to_file_wiki.
RAW_HEADER = "| File | Wiki |\n|------|------|\n"
CONCEPT_HEADER = "| File | Description |\n|------|-------------|\n"
ENTITY_HEADER = "| File | Description |\n|------|-------------|\n"
# U11: topics leaf index unified to `| File | Description |` (was `| File | Scope |`).
TOPIC_HEADER = "| File | Description |\n|------|-------------|\n"
# The unified 2-col wiki sources index header (U11 — `My take` column dropped,
# `What it says` renamed to `Description`).
SOURCES_HEADER = "| File | Description |\n|------|-------------|\n"
LEAF_INDEX_FRONTMATTER = "---\ntype: index\n---\n\n"
STATE_SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Token-overlap algorithm (Step 3·7b spec) — DEGRADE path only (D11)
# ---------------------------------------------------------------------------
# Callers (ingest 3·7b/3·7c, lint 7.7a) fire this signal ONLY when the semantic
# tier is unavailable; semantic membership is primary when Voyage is up. The
# tokenization rule below is UNCHANGED (stopword list NOT patched — D11) and
# stays byte-consistent with the binding 3·7b prose.

_STOPWORDS = {
    "the", "a", "an", "of", "for", "in", "on", "and", "or", "to",
    "is", "are", "with", "by", "that", "this", "it", "as",
}


def tokenize(text: str) -> set[str]:
    """Return the set of substantive tokens for *text*.

    Tokenize both: lowercase, strip stopwords
    (`the/a/an/of/for/in/on/and/or/to/is/are/with/by/that/this/it/as`),
    preserve kebab-case as a single token AND its hyphen-split parts
    (e.g. `marginal-returns-to-intelligence` contributes
    `marginal-returns-to-intelligence`, `marginal`, `returns`,
    `intelligence`).

    Non-ASCII / accented tokens are handled consistently via
    `str.casefold()` rather than `str.lower()`.
    """
    text = text.casefold()
    tokens: set[str] = set()
    for match in re.finditer(r"[a-z0-9]+(?:-[a-z0-9]+)*", text):
        token = match.group(0)
        if token in _STOPWORDS:
            continue
        tokens.add(token)
        if "-" in token:
            for part in token.split("-"):
                if part and part not in _STOPWORDS:
                    tokens.add(part)
    return tokens


def token_overlap(text_a: str, text_b: str) -> tuple[set[str], str]:
    """Compare two texts and return (shared_tokens, verdict).

    Threshold: ≥2 distinct substantive tokens shared → ``"fire"``,
    otherwise ``"no-fire"``.
    """
    shared = tokenize(text_a) & tokenize(text_b)
    verdict = "fire" if len(shared) >= 2 else "no-fire"
    return shared, verdict


def compute_stamp(path: Path) -> str:
    """Return a SHA256 hex digest of the file content as a content stamp."""
    return hashlib.sha256(read_text(path).encode("utf-8")).hexdigest()


def load_state(state_path: Path) -> tuple[dict[str, str], str | None, int]:
    """Load previous stamps and run counter from the state file.

    Returns (stamps, fallback_reason, runs_completed).  fallback_reason is
    None on success, or a string explaining why full-mode fallback was
    triggered.  runs_completed defaults to 0 when absent or unreadable.
    """
    if not state_path.exists():
        return {}, "first-run", 0
    try:
        data = json.loads(read_text(state_path))
        version = data.get("state_schema_version", "")
        if version != STATE_SCHEMA_VERSION:
            return {}, f"schema-mismatch (expected {STATE_SCHEMA_VERSION}, got {version!r})", 0
        stamps = data.get("stamps", {})
        if not isinstance(stamps, dict):
            return {}, "corrupt-state", 0
        runs_completed = data.get("runs_completed", 0)
        if not isinstance(runs_completed, int):
            runs_completed = 0
        return stamps, None, runs_completed
    except Exception:
        return {}, "corrupt-state", 0


def collect_tracked_pages(wiki_root: Path) -> list[Path]:
    """Collect pages tracked for incremental dirty-set computation.

    Scope = CET pages + source pages + the root questions.md queue (when the
    questions layer is ON), matching the LLM-read passes in the lint workflow
    (Step 6 My-take resync, Step 7 judgment fills, Step 7.7 answer-sweep). Raw
    pages and other wiki pages are excluded — they are handled by deterministic
    checks which remain full-corpus.

    questions.md is the questions-layer queue (its open entries are one of the
    two answer-sweep homes at Step 7.7a). It is a single multi-entry file, so
    its stamp is a whole-file "changed since last run" signal: when questions.md
    is NOT in the dirty set, no entry was added/edited and the entire
    questions.md-home sweep is skippable; when it IS dirty, re-sweep its open
    entries. This is the helper signal Step 7.7a needs for the "open questions
    added since last run" scoping (spec rule 5). Topic-home open questions ride
    on their own topic-page stamps (topics are CET, already tracked).
    """
    cet, sources = collect_wiki_pages(wiki_root)
    tracked = cet + sources
    questions = wiki_root / "questions.md"
    if questions.exists():
        tracked.append(questions)
    return tracked
DASH = "\u2014"
NON_SOURCE_FILES = {"AGENTS.md", "CLAUDE.md", "QWEN.md", "README.md"}
ACTIVE_LOG_TYPES = {
    "candidate-topic",
    "candidate-mention",
    "proposed-new-thesis",
    "speculative-thesis-update",
}
# Canonical writer mapping: each active log type lives in exactly one file under
# {wiki_root}/logs/. The scanner reads each entry's type from its own H2 header
# (so prune never depends on this map), but every writer MUST honor it.
LOG_TYPE_FILES = {
    "candidate-topic": "logs/topics.md",
    "candidate-mention": "logs/mentions.md",
    "proposed-new-thesis": "logs/theses.md",
    "speculative-thesis-update": "logs/theses.md",
}
RETIRED_LOG_TYPES = {
    "ingest",
    "concept-created",
    "entity-created",
    "topic-created",
    "topic-updated",
    "topic-coverage-candidate",
    "lint",
    "query",
}
LOG_HEADER_RE = re.compile(r"^## \[([^\]]+)\]\s+([a-z0-9-]+)\s*\|\s*(.*)$")
STUB_AGE_FLOOR_DAYS = 30
CANDIDATE_AGE_FLOOR_DAYS = 7
SOURCE_AGENT_HALF = {"Substance", "Notable quotes", "Connections"}

# Firm-match relevance (update-backfill gather). A firm row fires because the
# source's `## Substance` wikilinks a concept the topic lists in its `## Key
# concepts` / `## Key entities`. Not all such matches are equally meaningful: a
# match on a HUB concept (appears in dozens of sources) is incidental, while a
# match on a RARE, topic-specific concept is strong. The gather recomputes each
# firm row's overlap concept(s) and scores by SOURCE DOCUMENT FREQUENCY — how
# many source pages mention it. `weak` = the rarest shared concept still appears
# in >= FIRM_RELEVANCE_WEAK_T sources. ADVISORY ONLY — never drops a firm row
# (total-coverage invariant). Configurable via `--weak-threshold`. Default 25 is
# the p75 calibration from the 2026-06-10 backfill run.
FIRM_RELEVANCE_WEAK_T = 25


@dataclass
class Report:
    mode: str
    writes: list[str] = field(default_factory=list)
    judgment_needed: list[dict[str, str]] = field(default_factory=list)
    detected: dict[str, object] = field(default_factory=dict)
    dirty_set: list[str] = field(default_factory=list)
    stamps: dict[str, str] = field(default_factory=dict)
    state_schema_version: str = STATE_SCHEMA_VERSION
    full_mode: bool = False
    state_fallback_reason: str | None = None
    stamp_commit_policy: str = (
        "stamps reflect helper-run snapshot; LLM-pass interruption is not "
        "detected by the helper. If a lint run was interrupted after the helper "
        "but before LLM passes completed, re-run with --full to force re-reading."
    )


def today() -> datetime.date:
    return datetime.date.today()


def excluded_dir(path: Path) -> bool:
    """Binary-dump asset exclusion: skip ONLY genuine binary-dump folders.

    Skips ``_assets`` and ``*-assets`` (image/PDF dumps) and NEVER a semantic
    content folder literally named ``assets`` — ``wiki/entities/assets/`` holds
    asset-class entity ``.md`` pages (gold, us-dollar, brent-crude, ...) that
    must be linted like any other entity page. The earlier predicate skipped
    any ``assets`` segment, which silently dropped that whole content folder
    from every ``excluded_dir``-gated check (structural walk, type-tag sync,
    disputed-callout scan, valid-page-name set). Bare ``assets`` is reserved
    for semantic content; binary dumps are always ``_assets`` or ``*-assets``.
    """
    return any(part == "_assets" or part.endswith("-assets") for part in path.parts)


def _fspath(path: Path) -> str:
    """Return an OS path safe to open on Windows past the 260-char MAX_PATH.

    Local-drive paths at/over the limit get the extended-length prefix so the
    standard file APIs can open them. Non-Windows and short paths pass through.
    """
    raw = os.path.abspath(os.fspath(path))
    if os.name == "nt" and len(raw) >= 260 and not raw.startswith("\\\\?\\"):
        return "\\\\?\\" + raw
    return raw


def read_text(path: Path) -> str:
    with open(_fspath(path), "r", encoding="utf-8") as handle:
        return handle.read()


def write_text(path: Path, content: str, report: Report, apply_changes: bool) -> None:
    old = read_text(path) if os.path.exists(_fspath(path)) else None
    if old == content:
        return
    report.writes.append(str(path))
    if apply_changes:
        os.makedirs(_fspath(path.parent), exist_ok=True)
        with open(_fspath(path), "w", encoding="utf-8") as handle:
            handle.write(content)


def frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, flags=re.S)
    if not match:
        return {}
    data: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key_match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if key_match:
            data[key_match.group(1)] = key_match.group(2).strip().strip("\"'")
    return data


def first_h1(text: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", text, flags=re.M)
    return match.group(1).strip() if match else ""


def table_links(text: str) -> set[str]:
    return set(re.findall(r"\[\[([^\]]+?\.md)\]\]", text))


def make_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


# ADX-9/ADX-10: derive_raw_title_and_date + _filename_date REMOVED. The raw index
# is now `| File | Wiki |` — no Title or Date cell is produced, so the deterministic
# title/date derivation they backed has no index-facing consumer left. (The
# ingest-all manifest keeps its own describe_pdf/filename_date for token estimation;
# this index path no longer needs them.)


def raw_index_header_columns(lines: list[str]) -> list[str] | None:
    """Return the raw index's actual header columns (e.g. ``['File','Title','Date',
    'Wiki']`` or the legacy ``['File','Description','Wiki']``), or ``None`` when no
    header row is present. The producer sizes appended rows to THIS header (Rule
    3), never a hard-coded 4-col, so it stops manufacturing 4-col-under-legacy
    mix.
    """
    for line in lines:
        if line.lstrip().startswith("|") and not re.match(r"^\s*\|\s*-+", line):
            return split_row_cells(line)
    return None


def is_regenerable_pdf_twin(raw_file: Path) -> bool:
    """A raw ``.md`` is a regenerable PDF twin (Rule 5) when it carries the
    twin marker AND a same-stem ``.pdf`` original exists alongside it.

    Markers: ``twin_extractor:`` frontmatter (written by sb-wiki-pdf-twin.py) or a
    legacy ``Original PDF:`` reference. The ``.pdf`` is the canonical D1 row; the
    regenerable ``.md`` twin gets NO separate row, so it is excluded from the
    row-adding loop. caiso/engie dated CLIPS are NOT twins (their ``.md`` carries
    no ``twin_extractor`` / ``Original PDF:`` AND has no same-stem ``.pdf``), so
    this never excludes them.
    """
    if raw_file.suffix != ".md":
        return False
    if not os.path.exists(_fspath(raw_file.with_suffix(".pdf"))):
        return False
    text = read_text(raw_file)
    if "twin_extractor" in frontmatter(text):
        return True
    return bool(re.search(r"^\s*Original PDF:", text, flags=re.M))


def sync_raw_indexes(wiki_root: Path, report: Report, apply_changes: bool) -> None:
    """Add a missing raw-index row for every raw SOURCE file (PDF-aware) while
    keeping ONE row per logical source (duplicate-safe — U1b step 2).

    PDF-aware: the row-adding loop globs ``*.md`` AND ``*.pdf`` so a bare PDF raw
    with no row gets one. Duplicate-safe — a source contributes exactly one row:

      - A regenerable PDF twin ``.md`` (same-stem ``.pdf`` exists + twin marker)
        is keyed on the ``.pdf`` (D1), so it gets NO own row (Rule 5).
      - A bare ``.pdf`` ALREADY REPRESENTED by an existing source page — a legacy
        dated-clip-first source (caiso/engie) whose clip ``.md`` is the index row
        and whose source page names the PDF via ``raw:`` / ``Original PDF:`` — gets
        NO ``.pdf`` row. Detected via the SINGLE union authority
        ``ingested_raw_filenames`` (its ``Original PDF:`` arm names exactly these
        bare PDFs). This is the gate that stops re-creating the 5A duplicate row:
        without it, globbing ``*.pdf`` would add a second row for caiso/engie.
      - Everything else (a forward-twin PDF whose ``.md`` twin is excluded, an
        ordinary ``.md`` raw, a genuinely-uncaptured bare PDF) gets its row.
    """
    raw_root = wiki_root / "raw"
    if not raw_root.exists():
        return
    # The union authority: raw filenames already represented by a source page
    # (raw: / Original PDF: backlinks across ALL origins). A bare PDF in this set
    # is covered by an existing (clip) row — adding a .pdf row would duplicate it.
    backlink_targets, _ = ingested_raw_filenames(wiki_root)
    # Binary/non-UTF-8 `.md` files dropped directly under raw/<origin>/ that the
    # row-adding loop skips+surfaces instead of crashing on (mirrors the dedup
    # detector's decode guard). Accumulated across all origins, reported once.
    undecodable_raws: list[str] = []
    for origin_dir in sorted(p for p in raw_root.iterdir() if p.is_dir() and p.name != "assets"):
        index_path = origin_dir / f"{origin_dir.name}.md"
        index_text = read_text(index_path) if index_path.exists() else RAW_HEADER
        if not index_path.exists():
            write_text(index_path, index_text, report, apply_changes)
        # Existing-row guard must be EXTENSION-AGNOSTIC: this loop now adds .pdf
        # rows too, and table_links() captures only `.md` wikilinks — so a `.pdf`
        # row it already wrote would be re-appended every run (non-idempotent).
        # Match any [[…]] File-cell target by basename instead.
        links = {Path(t).name for t in re.findall(r"\[\[([^\]|#]+?)\]\]", index_text)}
        lines = index_text.rstrip("\n").splitlines() if index_text.strip() else RAW_HEADER.rstrip("\n").splitlines()
        # Size appended rows to the ACTUAL header of THIS index (Rule 3), via the
        # consolidated writer. A not-yet-migrated legacy index keeps its 4-col/3-col
        # header until migrate_raw_indexes_to_file_wiki collapses it; an appended
        # row is sized to that header so the index stays internally consistent until
        # the migration pass runs. The canonical (and headerless/garbled fallback)
        # form is the 2-col `| File | Wiki |` (ADX-9/ADX-10).
        columns = raw_index_header_columns(lines) or ["File", "Wiki"]
        changed = False
        for raw_file in sorted(p for p in origin_dir.glob("*.*") if p.suffix in (".md", ".pdf")):
            if raw_file.name == index_path.name or raw_file.name in NON_SOURCE_FILES or raw_file.name in links:
                continue
            # A binary/non-UTF-8 `.md` directly in raw/<origin>/ cannot be a real
            # source: probe its decodability FIRST (before is_regenerable_pdf_twin
            # reads it and crashes the whole run on UnicodeDecodeError), then skip
            # it (no row) and surface it. `.pdf` raws are binary by nature — the
            # row-adding loop never reads their bytes, so they are not probed.
            if raw_file.suffix == ".md":
                try:
                    read_text(raw_file)
                except (UnicodeDecodeError, OSError):
                    undecodable_raws.append(
                        str(raw_file.relative_to(wiki_root)).replace("\\", "/")
                    )
                    continue
            # Rule 5 — a regenerable PDF twin .md is keyed on the .pdf, not its
            # own row; exclude it from the row-adding loop.
            if is_regenerable_pdf_twin(raw_file):
                continue
            # Duplicate-safe — a bare PDF already represented by a source page
            # (legacy dated-clip origins: the clip .md is the row, the page's
            # Original PDF:/raw: names this PDF) gets NO separate .pdf row.
            if raw_file.suffix == ".pdf" and raw_file.name in backlink_targets:
                continue
            # ADX-9/ADX-10: a new row carries only File + Wiki=No. Title/Date are no
            # longer produced, so a row can never be "non-deterministic" — every
            # uncaptured raw gets its row unconditionally (no judgment_needed path).
            # build_raw_row places by column name; the unused title/date args are
            # dropped for a 2-col header (kept blank for a not-yet-migrated legacy
            # header, which the migration then collapses).
            lines.append(build_raw_row(columns, raw_file.name, "", "", "No"))
            changed = True
        if changed:
            write_text(index_path, "\n".join(lines) + "\n", report, apply_changes)
    report.detected["raw_undecodable"] = sorted(undecodable_raws)


ORIGINAL_PDF_RE = re.compile(r"^Original PDF:\s*\[\[([^\]|#]+?)\]\]", flags=re.M)


def ingested_raw_filenames(wiki_root: Path) -> tuple[set[str], dict[str, set[str]]]:
    """Inventory which raws have a 1:1 source page, by the THREE union signals.

    This is the SINGLE authority for "does a raw have a 1:1 source page?" (U1b).
    A raw is "ingested" when ANY signal fires — all keyed on the raw FILENAME /
    stem so .md and .pdf raws are handled uniformly:

      - ``raw:`` backlink — the source page's ``raw:`` frontmatter wikilinks
        the raw filename (the canonical 1:1 link per the wiki schema). Returned
        as a set of raw filenames across ALL source pages, any origin.
      - ``Original PDF:`` body backlink — a PDF-sourced page ingested via a dated
        ``.md`` clip (so its source-page stem mirrors the CLIP, not the bare PDF)
        carries ``Original PDF: [[<bare-pdf>.pdf]]`` in its body. This arm is what
        matches the legacy dated-clip-first sources (caiso/engie) whose bare PDF
        the ``raw:``/same-stem arms miss. Folded into ``backlink_targets`` because
        an ``Original PDF:`` target is a raw filename exactly like a ``raw:`` one.
      - filename mirror — a source page ``wiki/sources/{origin}/{stem}.md``
        whose stem equals the raw's stem (a .md raw mirrors 1:1; a .pdf raw's
        source page is the title-slug ``.md``, same stem). Returned per origin.

    Returns ``(backlink_targets, mirror_stems_by_origin)`` so the caller can
    record WHICH signal healed each row.
    """
    sources_root = wiki_root / "wiki" / "sources"
    backlink_targets: set[str] = set()
    mirror_stems_by_origin: dict[str, set[str]] = {}
    if not sources_root.exists():
        return backlink_targets, mirror_stems_by_origin
    for origin_dir in sorted(p for p in sources_root.iterdir() if p.is_dir()):
        index_name = f"{origin_dir.name}.md"
        stems: set[str] = set()
        for page in sorted(origin_dir.glob("*.md")):
            if page.name == index_name or page.name in NON_SOURCE_FILES:
                continue
            stems.add(page.stem)
            text = read_text(page)
            raw_val = frontmatter(text).get("raw", "")
            for target in re.findall(r"\[\[([^\]|#]+?)\]\]", raw_val):
                backlink_targets.add(Path(target).name)
            # Original PDF: body backlink — the third union arm (the bare PDF of
            # a dated-clip-first source). Same key space as raw: (raw filenames).
            for target in ORIGINAL_PDF_RE.findall(text):
                backlink_targets.add(Path(target).name)
        mirror_stems_by_origin[origin_dir.name] = stems
    return backlink_targets, mirror_stems_by_origin


def heal_raw_wiki_cells(wiki_root: Path, report: Report, apply_changes: bool) -> None:
    """Flip stale ``Wiki = No`` raw-index rows to ``Yes`` when the raw's 1:1
    source page exists; report dangling rows (File cell → missing raw file).

    A raw counts as ingested when EITHER signal from ``ingested_raw_filenames``
    fires (the source page's ``raw:`` backlink names it, OR a same-stem source
    page exists in the origin). ONLY an exact ``No`` cell is flipped — ``Partial``,
    ``Duplicate (…)``, and ``Yes`` are never touched. A row whose raw FILE is
    absent on disk is DANGLING: reported, never auto-flipped and never deleted
    (a raw may have been moved — same policy as step 7 missing-raw rows; the user
    disposes phantoms manually). Closes the Step-1.7 stale-``No`` masking class:
    the ingest content-duplicate gate keys its comparison set on source-page
    existence, so healing the cell removes the data inconsistency itself.
    """
    raw_root = wiki_root / "raw"
    healed: list[dict[str, str]] = []
    dangling: list[dict[str, str]] = []
    if not raw_root.exists():
        report.detected["raw_wiki_healed"] = healed
        report.detected["raw_wiki_dangling"] = dangling
        return
    backlink_targets, mirror_stems = ingested_raw_filenames(wiki_root)
    for origin_dir in sorted(
        p for p in raw_root.iterdir()
        if p.is_dir() and p.name != "assets" and not excluded_dir(p.relative_to(wiki_root))
    ):
        index_path = origin_dir / f"{origin_dir.name}.md"
        if not index_path.exists():
            continue
        lines = read_text(index_path).splitlines()
        origin_stems = mirror_stems.get(origin_dir.name, set())
        modified_rows: list[int] = []
        for idx, line in enumerate(lines):
            if not line.strip().startswith("|") or re.match(r"^\s*\|\s*-+", line):
                continue
            cells = split_row_cells(line)
            if not cells or cells[0] == "File":
                continue
            # Locate the Wiki cell by the row's OWN layout (Rule 1/6) — the
            # consolidated authority. An unrecognized-width row has no Wiki index;
            # skip it (never misfire). Recognized widths are 2 (canonical
            # File|Wiki), 3 (legacy File|Description|Wiki), 4 (legacy File|Title|Date|Wiki).
            wiki_idx = raw_row_wiki_index(cells)
            if wiki_idx is None:
                continue
            match = re.search(r"\[\[([^\]|#]+?)\]\]", cells[0])
            if not match:
                continue
            raw_filename = Path(match.group(1)).name
            if not os.path.exists(_fspath(origin_dir / raw_filename)):
                # Dangling: File cell points at a raw file not on disk. Never
                # heal (no real raw) and never delete (may be a moved raw).
                dangling.append({"origin": origin_dir.name, "file": raw_filename})
                continue
            if cells[wiki_idx].strip() != "No":
                continue
            backlink_hit = raw_filename in backlink_targets
            mirror_hit = Path(raw_filename).stem in origin_stems
            if backlink_hit or mirror_hit:
                new_cells, _ = set_raw_row_wiki(cells, "Yes")
                lines[idx] = make_row(new_cells)
                modified_rows.append(idx)
                healed.append(
                    {
                        "origin": origin_dir.name,
                        "file": raw_filename,
                        "from": "No",
                        "to": "Yes",
                        "signal": "raw-backlink" if backlink_hit else "filename-mirror",
                    }
                )
        if modified_rows:
            # Post-rewrite shape guard (Rule 8 — KEEP until the writer is the sole
            # path AND indexes are normalized): every modified row must still be a
            # recognized raw width (2, 3, or 4). A violation is a script bug —
            # refuse the write.
            broken = [lines[i] for i in modified_rows if raw_row_wiki_index(split_row_cells(lines[i])) is None]
            if broken:
                report.detected.setdefault("row_shape_errors", []).extend(
                    f"{index_path}: {row}" for row in broken
                )
            else:
                write_text(index_path, "\n".join(lines) + "\n", report, apply_changes)
    report.detected["raw_wiki_healed"] = healed
    report.detected["raw_wiki_dangling"] = dangling


# Recognized Wiki-cell values (the LAST cell of every raw row). A row whose last
# cell is none of these is NOT a clean raw row — never collapse it (report it).
# `Duplicate (…)` is matched case-insensitively by its `duplicate` prefix.
_RAW_WIKI_LITERALS = {"no", "yes", "partial"}


def _is_recognized_wiki_value(value: str) -> bool:
    v = value.strip().lower()
    return v in _RAW_WIKI_LITERALS or v.startswith("duplicate")


def migrate_raw_indexes_to_file_wiki(wiki_root: Path, report: Report, apply_changes: bool) -> None:
    """One-off (idempotent) migration: collapse every raw leaf index to the 2-col
    ``| File | Wiki |`` schema (ADX-9/ADX-10).

    Per-index behavior:
      - Header is canonical 4-col ``| File | Title | Date | Wiki |`` or legacy
        3-col ``| File | Description | Wiki |`` → MIGRATE: header + separator are
        rewritten to the 2-col form, and each data row collapses to
        ``| [[file]] | <Wiki-value> |`` — the File cell (cell 0) and the Wiki
        value (the LAST cell — ``No``/``Yes``/``Partial``/``Duplicate (…)``) are
        PRESERVED VERBATIM; the Title/Description + Date cells are dropped.
      - Header is already 2-col ``| File | Wiki |`` → left byte-stable (idempotent;
        a second pass is a no-op). Data rows are validated for drift and reported
        if bespoke, but never rewritten.
      - A bespoke/garbled header (neither canonical 4-col, legacy 3-col, nor the
        unified 2-col) → REPORTED, never force-rewritten (mirrors the source-index
        preserve rule).
      - A data row whose LAST cell is not a recognized Wiki value (a spilled /
        broken row) → REPORTED as ``judgment_needed`` and the index's migration is
        ABORTED (never persist a half-migrated table; never guess a Wiki value).
    """
    raw_root = wiki_root / "raw"
    migrated = 0
    bespoke: list[str] = []
    if not raw_root.exists():
        report.detected["raw_index_migrated_to_file_wiki"] = migrated
        return
    for origin_dir in sorted(
        p for p in raw_root.iterdir()
        if p.is_dir() and p.name != "assets" and not excluded_dir(p.relative_to(wiki_root))
    ):
        index_path = origin_dir / f"{origin_dir.name}.md"
        if not index_path.exists():
            continue
        text = read_text(index_path)
        lines = text.splitlines()

        # Locate the index header row (first non-separator table row).
        header_idx = None
        header_cells: list[str] = []
        for i, line in enumerate(lines):
            if line.lstrip().startswith("|") and not re.match(r"^\s*\|\s*-+", line):
                header_idx = i
                header_cells = [c.lower() for c in split_row_cells(line)]
                break

        canonical_4col = header_cells == ["file", "title", "date", "wiki"]
        legacy_3col = header_cells == ["file", "description", "wiki"]
        unified_2col = header_cells == ["file", "wiki"]

        if header_idx is None or not (canonical_4col or legacy_3col or unified_2col):
            if header_idx is not None:
                bespoke.append(
                    f"{index_path}: header {split_row_cells(lines[header_idx])!r} "
                    f"is neither canonical 4-col, legacy 3-col, nor unified 2-col — "
                    f"reported, not rewritten"
                )
            continue

        if unified_2col:
            # Already migrated: validate row widths, report bespoke drift, leave
            # the file byte-stable (idempotent — the no-op a second lint pass needs).
            for line in lines[header_idx + 2:]:
                if not line.lstrip().startswith("|") or re.match(r"^\s*\|\s*-+", line):
                    continue
                cells = split_row_cells(line)
                if cells and cells[0] == "File":
                    continue
                if len(cells) != 2 or not _is_recognized_wiki_value(cells[-1]):
                    bespoke.append(
                        f"{index_path}: 2-col index has a non-conforming data row "
                        f"{line.strip()!r} — reported, not rewritten"
                    )
            continue

        # Canonical 4-col or legacy 3-col → migrate to 2-col. Rewrite header +
        # separator; collapse each data row to File + Wiki (last cell).
        new_lines = list(lines)
        new_lines[header_idx] = "| File | Wiki |"
        if header_idx + 1 < len(new_lines) and re.match(r"^\s*\|\s*-+", new_lines[header_idx + 1]):
            new_lines[header_idx + 1] = "|------|------|"
        aborted = False
        for j in range(header_idx + 2, len(new_lines)):
            line = new_lines[j]
            if not line.lstrip().startswith("|") or re.match(r"^\s*\|\s*-+", line):
                continue
            cells = split_row_cells(line)
            if cells and cells[0] == "File":
                continue
            # The Wiki value is the LAST cell (the locator invariant — true for the
            # canonical, legacy, AND any spilled wider row). If it is not a
            # recognized Wiki value, this is a broken/bespoke row: report + abort,
            # never guess.
            if not cells or not _is_recognized_wiki_value(cells[-1]):
                bespoke.append(
                    f"{index_path}: data row {line.strip()!r} has an unrecognized "
                    f"Wiki value (last cell) — index NOT migrated"
                )
                report.judgment_needed.append(
                    {
                        "index": str(index_path),
                        "file": cells[0] if cells else line.strip(),
                        "cell": "Wiki",
                        "reason": "raw-index row last cell is not a recognized Wiki "
                                  "value (No/Yes/Partial/Duplicate); not collapsed",
                    }
                )
                aborted = True
                break
            new_lines[j] = make_row([cells[0], cells[-1]])
        if aborted:
            continue
        new_text = "\n".join(new_lines) + ("\n" if text.endswith("\n") else "")
        if new_text != text:
            write_text(index_path, new_text, report, apply_changes)
            migrated += 1
    report.detected["raw_index_migrated_to_file_wiki"] = migrated
    if bespoke:
        report.detected.setdefault("raw_index_bespoke_reported", []).extend(bespoke)


def sync_wiki_leaf_headers_and_queue(wiki_root: Path, report: Report, apply_changes: bool) -> None:
    # U11: every leaf-index family is unified to `| File | Description |`. The
    # topics index, formerly `| File | Scope |`, is migrated here (header +
    # separator renamed; row TEXT preserved verbatim — the Scope text becomes
    # the Description text, only the column label changes, so no data moves).
    specs = [
        ("concepts", "concepts.md", CONCEPT_HEADER, "Description"),
        ("entities", "entities.md", ENTITY_HEADER, "Description"),
        ("topics", "topics.md", TOPIC_HEADER, "Description"),
    ]
    topics_migrated = 0
    for folder, index_name, header, judgment_cell in specs:
        leaf_dir = wiki_root / "wiki" / folder
        if not leaf_dir.exists():
            continue
        index_path = leaf_dir / index_name
        if not index_path.exists():
            write_text(index_path, header, report, apply_changes)
            index_text = header
        else:
            index_text = read_text(index_path)
            # Topics header migration (U11): rename a legacy `| File | Scope |`
            # header (and its separator) to `| File | Description |`. The data
            # rows are unchanged — Scope and Description are both the 2nd cell,
            # so no cell content moves; only the header label is rewritten.
            # Idempotent: a header already reading `Description` is left as-is.
            if folder == "topics":
                migrated_text, did_migrate = migrate_scope_header_to_description(index_text)
                if did_migrate:
                    write_text(index_path, migrated_text, report, apply_changes)
                    index_text = migrated_text
                    topics_migrated += 1
        links = table_links(index_text)
        for page in sorted(leaf_dir.glob("*.md")):
            if page.name == index_name or page.name in links or page.name in NON_SOURCE_FILES:
                continue
            report.judgment_needed.append(
                {
                    "index": str(index_path),
                    "file": str(page),
                    "cell": judgment_cell,
                    "reason": f"wiki leaf row missing; {judgment_cell} requires LLM judgment",
                }
            )
    if topics_migrated:
        report.detected["topics_index_migrated_to_description"] = topics_migrated


def migrate_scope_header_to_description(text: str) -> tuple[str, bool]:
    """Rename a legacy topics-index `| File | Scope |` header to the unified
    `| File | Description |` (U11). Returns ``(new_text, changed)``.

    Only the header row's `Scope` label (2nd cell) and the matching separator
    are rewritten; every data row is preserved byte-for-byte (the Scope text is
    already in the Description position — column 2 — so nothing moves). A header
    already in the `Description` form, or a bespoke layout with neither label,
    is left untouched (changed=False) — idempotent and bespoke-safe.
    """
    lines = text.splitlines(keepends=True)
    changed = False
    for i, line in enumerate(lines):
        stripped = line.rstrip("\n").rstrip("\r")
        if not stripped.lstrip().startswith("|") or re.match(r"^\s*\|\s*-+", stripped):
            continue
        cells = split_row_cells(stripped)
        if len(cells) == 2 and cells[0].lower() == "file" and cells[1].lower() == "scope":
            eol = line[len(stripped):]
            lines[i] = "| File | Description |" + eol
            # Rewrite the immediately-following separator row to the 2-col width.
            if i + 1 < len(lines):
                sep = lines[i + 1].rstrip("\n").rstrip("\r")
                if re.match(r"^\s*\|\s*-+", sep):
                    sep_eol = lines[i + 1][len(sep):]
                    lines[i + 1] = "|------|-------------|" + sep_eol
            changed = True
            break  # only the FIRST header row is the index header
    return ("".join(lines), changed)


NON_PAGE_TYPES = {"purpose", "questions", "questions-index", "source-queue"}


def _parse_inline_tags(value: str) -> list[str]:
    inner = value.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    return [item.strip().strip("\"'") for item in inner.split(",") if item.strip().strip("\"'")]


def sync_type_tags(wiki_root: Path, report: Report, apply_changes: bool) -> None:
    """Ensure every wiki page carries its `type:` value as a frontmatter tag.

    Deterministic: the tag IS the type value — no judgment. Leaf/router indexes
    (stem == parent dir name) missing `type:` get `type: index`. Pages with no
    frontmatter and no deterministic type are reported, never guessed.
    """
    wiki_dir = wiki_root / "wiki"
    if not wiki_dir.exists():
        return
    tags_added = 0
    type_index_added = 0
    unresolved: list[str] = []
    for page in sorted(wiki_dir.rglob("*.md")):
        rel = page.relative_to(wiki_root)
        if excluded_dir(rel) or page.name in NON_SOURCE_FILES:
            continue
        raw_text = read_text(page)
        bom = "﻿" if raw_text.startswith("﻿") else ""
        text = raw_text[len(bom) :]
        rel_str = str(rel).replace("\\", "/")
        is_index = page.stem == page.parent.name
        fm_match = re.match(r"^---[ \t]*\n(.*?)\n---[ \t]*\n", text, flags=re.S)
        if not fm_match:
            if is_index:
                new_text = f"{bom}---\ntype: index\ntags: [index]\n---\n\n{text}"
                write_text(page, new_text, report, apply_changes)
                type_index_added += 1
                tags_added += 1
            else:
                unresolved.append(f"{rel_str}: no frontmatter and type not deterministic")
            continue
        fm_text = fm_match.group(1)
        type_match = re.search(r"^type:\s*(\S+)\s*$", fm_text, flags=re.M)
        if type_match:
            type_val = type_match.group(1).strip().strip("\"'")
        elif is_index:
            type_val = "index"
            fm_text = f"type: index\n{fm_text}"
            type_index_added += 1
        else:
            unresolved.append(f"{rel_str}: missing type: and not an index file")
            continue
        if type_val in NON_PAGE_TYPES:
            continue
        tags_match = re.search(r"^tags:[ \t]*(.*)$", fm_text, flags=re.M)
        if tags_match:
            value = tags_match.group(1).strip()
            if value:  # inline form: tags: [...] or tags: a
                items = _parse_inline_tags(value)
                if type_val not in items:
                    items.append(type_val)
                    new_line = "tags: [" + ", ".join(items) + "]"
                    fm_text = fm_text[: tags_match.start()] + new_line + fm_text[tags_match.end() :]
                    tags_added += 1
            else:  # block form: tags: followed by "- item" lines (or nothing)
                rest = fm_text[tags_match.end() :]
                block_match = re.match(r"((?:\n[ \t]+-[ \t]*\S[^\n]*)*)", rest)
                block = block_match.group(1) if block_match else ""
                items = [
                    line.strip().lstrip("-").strip().strip("\"'")
                    for line in block.splitlines()
                    if line.strip().startswith("-")
                ]
                if type_val not in items:
                    insert_at = tags_match.end() + len(block)
                    fm_text = fm_text[:insert_at] + f"\n  - {type_val}" + fm_text[insert_at:]
                    tags_added += 1
        else:
            fm_text = fm_text + f"\ntags: [{type_val}]"
            tags_added += 1
        new_text = f"{bom}---\n{fm_text}\n---\n" + text[fm_match.end() :]
        if new_text != raw_text:
            write_text(page, new_text, report, apply_changes)
    report.detected["type_tags"] = {
        "tags_added": tags_added,
        "type_index_added": type_index_added,
        "unresolved": unresolved,
    }


def section_body(text: str, heading: str) -> str:
    pattern = re.compile(rf"^##+\s+{re.escape(heading)}\s*$", flags=re.M)
    match = pattern.search(text)
    if not match:
        return ""
    rest = text[match.end() :]
    next_heading = re.search(r"^##+\s+", rest, flags=re.M)
    body = rest[: next_heading.start()] if next_heading else rest
    return re.sub(r"^\s*---\s*$", "", body, flags=re.M).strip()


def flatten_wikilinks(text: str) -> str:
    """Replace [[target|alias]] with alias and [[target]] with target text."""
    return re.sub(
        r"\[\[([^\]|]+?)(?:\|([^\]]*?))?\]\]",
        lambda m: (m.group(2) if m.group(2) is not None else m.group(1)).strip(),
        text,
    )


def split_row_cells(line: str) -> list[str]:
    """Split a Markdown table row on UNESCAPED pipes only (`\\|` stays in-cell)."""
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", inner)]


def migrate_sources_index_to_description(wiki_root: Path, report: Report, apply_changes: bool) -> None:
    """Unify every wiki sources leaf index to `| File | Description |` (U11).

    Replaces the retired `sync_source_my_take_and_queue` (which maintained the
    dropped `My take` column + its three-state / 7-day-staleness machinery).

    Per-index behavior:
      - Legacy 3-col `| File | What it says | My take |` → migrate to 2-col
        `| File | Description |`: the header + separator are rewritten, each
        data row's `What it says` text (cell 2) is PRESERVED verbatim as the
        `Description`, and the `My take` cell (cell 3) is DROPPED. The
        authored take is NOT lost — it lives canonically in the source-page
        body `## My take` section, untouched by this migration.
      - Already 2-col `| File | Description |` → left byte-stable (idempotent;
        a second lint pass is a no-op).
      - A bespoke / user-customized layout (a header that is neither the
        canonical legacy 3-col nor the unified 2-col, OR data rows whose width
        does not match the header) → REPORTED for hand-review, NEVER
        force-rewritten.
      - A missing source row (a source page with no index row) → reported as
        `judgment_needed` (Description requires LLM judgment).
    """
    sources_root = wiki_root / "wiki" / "sources"
    if not sources_root.exists():
        return
    migrated = 0
    bespoke: list[str] = []
    for origin_dir in sorted(p for p in sources_root.iterdir() if p.is_dir()):
        index_path = origin_dir / f"{origin_dir.name}.md"
        if not index_path.exists():
            continue
        text = read_text(index_path)
        lines = text.splitlines()

        # Locate the index header row (first non-separator table row).
        header_idx = None
        header_cells: list[str] = []
        for i, line in enumerate(lines):
            if line.lstrip().startswith("|") and not re.match(r"^\s*\|\s*-+", line):
                header_idx = i
                header_cells = [c.lower() for c in split_row_cells(line)]
                break

        legacy_3col = header_cells == ["file", "what it says", "my take"]
        unified_2col = header_cells == ["file", "description"]

        if header_idx is None or not (legacy_3col or unified_2col):
            # No recognized header (empty/no table) OR a bespoke header: report,
            # never rewrite. An index file with no table at all is reported so a
            # human can decide; a recognized-empty file is skipped silently.
            if header_idx is not None:
                bespoke.append(
                    f"{index_path}: header {split_row_cells(lines[header_idx])!r} "
                    f"is neither legacy 3-col nor unified 2-col — reported, not rewritten"
                )
            # Still report missing rows so coverage is not lost.
            _report_missing_source_rows(origin_dir, index_path, text, report)
            continue

        if unified_2col:
            # Already migrated: validate row widths for bespoke drift, report
            # missing rows, leave the file byte-stable (idempotent).
            for line in lines[header_idx + 2:]:
                if not line.lstrip().startswith("|") or re.match(r"^\s*\|\s*-+", line):
                    continue
                cells = split_row_cells(line)
                if len(cells) != 2:
                    bespoke.append(
                        f"{index_path}: 2-col index has a {len(cells)}-cell data row "
                        f"{line.strip()!r} — reported, not rewritten"
                    )
            _report_missing_source_rows(origin_dir, index_path, text, report)
            continue

        # Legacy 3-col → migrate to 2-col. Rewrite header + separator; drop the
        # My-take cell from every data row, preserving the What-it-says text.
        new_lines = list(lines)
        new_lines[header_idx] = "| File | Description |"
        if header_idx + 1 < len(new_lines) and re.match(r"^\s*\|\s*-+", new_lines[header_idx + 1]):
            new_lines[header_idx + 1] = "|------|-------------|"
        had_bespoke_row = False
        for j in range(header_idx + 2, len(new_lines)):
            line = new_lines[j]
            if not line.lstrip().startswith("|") or re.match(r"^\s*\|\s*-+", line):
                continue
            cells = split_row_cells(line)
            if cells and cells[0] == "File":
                continue
            if len(cells) != 3:
                # A data row that is not 3-col under a 3-col header is malformed/
                # bespoke — never reshape it. Report and abort this index's
                # migration to avoid persisting a half-migrated table.
                bespoke.append(
                    f"{index_path}: legacy 3-col index has a {len(cells)}-cell data row "
                    f"{line.strip()!r} — reported, index NOT migrated"
                )
                had_bespoke_row = True
                break
            # Preserve File + What-it-says (Description); drop My-take (cell 3).
            new_lines[j] = make_row([cells[0], cells[1]])
        if had_bespoke_row:
            _report_missing_source_rows(origin_dir, index_path, text, report)
            continue
        new_text = "\n".join(new_lines) + ("\n" if text.endswith("\n") else "")
        if new_text != text:
            write_text(index_path, new_text, report, apply_changes)
            migrated += 1
        _report_missing_source_rows(origin_dir, index_path, new_text, report)
    report.detected["sources_index_migrated_to_description"] = migrated
    if bespoke:
        report.detected.setdefault("sources_index_bespoke_reported", []).extend(bespoke)


def _report_missing_source_rows(origin_dir: Path, index_path: Path, index_text: str, report: Report) -> None:
    """Report each source page under *origin_dir* that has no index row as
    `judgment_needed` (the `Description` is LLM-derived from the source page)."""
    linked = table_links(index_text)
    for source_page in sorted(origin_dir.glob("*.md")):
        if source_page.name == index_path.name or source_page.name in linked:
            continue
        report.judgment_needed.append(
            {
                "index": str(index_path),
                "file": str(source_page),
                "cell": "Description",
                "reason": "wiki sources row missing; factual summary requires LLM judgment",
            }
        )


SUBDIVISION_NAMING_POLICY: dict[str, tuple[str, bool]] = {
    "model": ("ai-models", True),
    "person": ("persons", False),
    "company": ("organizations", False),
    "tool": ("tools", False),
    "product": ("products", False),
    "benchmark": ("ai-benchmarks", True),
    "data-format": ("data-formats", False),
    "inference-scaffold": ("inference-scaffolds", False),
    "automation-economics": ("automation-economics", False),
    "cognitive-displacement": ("cognitive-displacements", False),
    "ai-collaboration-model": ("ai-collaboration-models", False),
}
SUBDIVISION_PROPOSE_FLOOR = 10  # authority: wiki/workflows/shared/folder-structure.md (≥10)
SUBDIVISION_TYPE_FOLDERS = ("concepts", "entities")

# Irregular and uncountable kind -> subfolder mappings for kinds NOT in the
# explicit naming policy. The blind-reader test still applies downstream (the
# LLM lint pass may override a proposed name at step 9), but proposals should
# carry correct English plurals rather than a naive "+s".
SUBDIVISION_IRREGULAR = {
    "phenomenon": "phenomena",
    "analysis": "analyses",
    "thesis": "theses",
    "hypothesis": "hypotheses",
    "taxonomy": "taxonomies",
}
# Uncountable / already-plural-shaped kinds: subfolder == kind, no suffix.
SUBDIVISION_UNCOUNTABLE = {"ai-safety", "research"}


def pluralize_kind(kind: str) -> str:
    """English-plural a `kind:` value for a proposed subfolder name.

    Order: irregular map, uncountable map, already-plural detection, then
    standard rules (consonant+y -> ies; sibilant -> es; else +s).
    """
    if kind in SUBDIVISION_IRREGULAR:
        return SUBDIVISION_IRREGULAR[kind]
    if kind in SUBDIVISION_UNCOUNTABLE:
        return kind
    if kind.endswith("s") or kind.endswith("ics"):
        return kind  # already plural-shaped (e.g. automation-economics)
    if re.search(r"[^aeiou]y$", kind):
        return kind[:-1] + "ies"
    if kind.endswith(("x", "z", "ch", "sh")):
        return kind + "es"
    return kind + "s"


def collect_kind_pages(type_dir: Path) -> tuple[dict[str, list[Path]], list[Path]]:
    """Walk a type folder (flat root + per-kind subfolders) and group by `kind:`.

    Returns (kinds_map, kind_missing_pages).
    """
    pages: list[Path] = []
    leaf_index_names = {f"{type_dir.name}.md"}
    for item in type_dir.iterdir():
        if item.is_file() and item.suffix == ".md":
            if item.name in leaf_index_names or item.name in NON_SOURCE_FILES:
                continue
            pages.append(item)
        elif item.is_dir():
            sub_index = f"{item.name}.md"
            for sub in item.glob("*.md"):
                if sub.name == sub_index or sub.name in NON_SOURCE_FILES:
                    continue
                pages.append(sub)

    kinds: dict[str, list[Path]] = {}
    missing: list[Path] = []
    for page in pages:
        fm = frontmatter(read_text(page))
        kind = fm.get("kind", "").strip()
        if not kind:
            missing.append(page)
            continue
        kinds.setdefault(kind, []).append(page)
    return kinds, missing


def detect_subdivision(wiki_root: Path, report: Report) -> None:
    """Detect kinds in concepts/ and entities/ that warrant subdivision.

    Emits subdivision_proposals (count >=5), kind_missing (pages without
    a kind: value), and generic_kind_flags (a flat kind whose suggested
    subfolder collides with the parent type folder — a re-kind signal, never
    a subdivision proposal). Never moves files; the LLM lint workflow surfaces
    proposals at step 9 and executes on user accept.
    """
    proposals: list[dict] = []
    stragglers: list[dict] = []
    kind_missing: list[str] = []
    generic_kind_flags: list[dict] = []
    for type_folder in SUBDIVISION_TYPE_FOLDERS:
        type_dir = wiki_root / "wiki" / type_folder
        if not type_dir.exists():
            continue
        kinds, missing = collect_kind_pages(type_dir)
        for page in missing:
            kind_missing.append(str(page.relative_to(wiki_root)).replace("\\", "/"))
        for kind, pages in kinds.items():
            subfolder, prefixed = SUBDIVISION_NAMING_POLICY.get(
                kind, (pluralize_kind(kind), False)
            )
            flat = [p for p in pages if p.parent == type_dir]
            # A kind whose subfolder already exists has graduated — never
            # re-propose it. Instead, flag any flat pages of that kind as
            # stragglers to relocate into the existing subfolder.
            already_graduated = subfolder != type_folder and (type_dir / subfolder).is_dir()
            if already_graduated:
                if flat:
                    stragglers.append(
                        {
                            "type": type_folder,
                            "kind": kind,
                            "subfolder": subfolder,
                            "count": len(flat),
                            "pages": sorted(p.name for p in flat),
                        }
                    )
                continue
            # Propose subdivision only on FLAT pages — pages already in a
            # subfolder are not eligible to graduate again.
            count = len(flat)
            if count < SUBDIVISION_PROPOSE_FLOOR:
                continue
            sample = sorted(p.stem for p in flat)[:5]
            # A proposed subfolder equal to the parent type folder name
            # (e.g. kind `concept` -> `concepts/` under concepts/) is a
            # degenerate collision: the generic kind fails the blind-reader
            # test and cannot graduate into a same-named subfolder. Emitting a
            # subdivision proposal here would re-fire an unexecutable suggestion
            # on every lint, so record a re-kind flag instead and skip it.
            if subfolder == type_folder:
                generic_kind_flags.append(
                    {
                        "type": type_folder,
                        "kind": kind,
                        "count": count,
                        "sample_pages": sample,
                    }
                )
                continue
            proposals.append(
                {
                    "type": type_folder,
                    "kind": kind,
                    "count": count,
                    "suggested_subfolder": subfolder,
                    "domain_prefix_applied": prefixed,
                    "sample_pages": sample,
                    "naming_heuristic_applied": kind not in SUBDIVISION_NAMING_POLICY,
                }
            )
    report.detected["subdivision_proposals"] = proposals
    report.detected["subdivision_stragglers"] = stragglers
    report.detected["kind_missing"] = kind_missing
    report.detected["generic_kind_flags"] = generic_kind_flags


_FOLD_TRANS = {
    "‘": "'", "’": "'", "“": '"', "”": '"',  # curly quotes
    "–": "-", "—": "-", "−": "-",                  # en/em dash, minus
}


def fold_key(name: str) -> str:
    """Normalize a filename for fuzzy bucket-A matching.

    Folds the differences that produce typo/encoding broken links: casing,
    accents, curly quotes vs straight, en/em-dash vs hyphen, and separator
    runs. Drops the `.md` extension. Two names that differ ONLY in those
    dimensions collapse to the same key — a unique collision against an
    existing file is the bucket-A "did you mean" signal.
    """
    text = "".join(_FOLD_TRANS.get(ch, ch) for ch in name)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    if text.endswith(".md"):
        text = text[:-3]
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def detect_broken_wikilinks(wiki_root: Path, report: Report) -> None:
    """Inventory + classify every broken wikilink target.

    bucket `A`            — a UNIQUE existing file fold-matches the target
                            (typo / curly quote / dash / accent / case). The
                            exact existing filename rides as `suggestion` —
                            mechanically auto-fixable via --execute-link-fixes.
    bucket `needs-judgment` — no unique fold-match. Either a genuinely-missing
                            page (LLM bucket B: author a stub) or unresolvable
                            (LLM bucket C). When >=2 existing files share the
                            fold key the target is ambiguous; the candidates
                            ride along so the LLM/user can disambiguate.
    """
    targets: set[str] = set()
    fold_map: dict[str, set[str]] = {}
    for root in [wiki_root / "wiki", wiki_root / "raw"]:
        if not root.exists():
            continue
        for item in root.rglob("*.md"):
            if "raw/_assets" not in item.as_posix():
                targets.add(item.name)
                fold_map.setdefault(fold_key(item.name), set()).add(item.name)
    broken: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    wiki_dir = wiki_root / "wiki"
    if wiki_dir.exists():
        for page in sorted(wiki_dir.rglob("*.md")):
            rel = str(page.relative_to(wiki_root)).replace("\\", "/")
            text = read_text(page)
            for embed, target in re.findall(r"(!)?\[\[([^\]|#]+)", text):
                target = target.strip()
                if embed and not target.endswith(".md"):
                    continue
                if not target.endswith(".md") or Path(target).name in targets:
                    continue
                key = (rel, target)
                if key in seen:
                    continue
                seen.add(key)
                matches = sorted(fold_map.get(fold_key(Path(target).name), set()))
                if len(matches) == 1:
                    broken.append({"source": rel, "target": target, "bucket": "A", "suggestion": matches[0]})
                else:
                    broken.append(
                        {
                            "source": rel,
                            "target": target,
                            "bucket": "needs-judgment",
                            "suggestion": None,
                            "candidates": matches,
                        }
                    )
    report.detected["broken_wikilinks"] = broken


DISPUTED_HEADER_RE = re.compile(r"^>\s*\[!warning\][-+]?\s*Disputed\b", re.M)
DISPUTED_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
DISPUTED_LINK_RE = re.compile(r"\[\[([^\]|#]+?\.md)")


def detect_disputed_callouts(wiki_root: Path, report: Report) -> None:
    """Flag unresolved `> [!warning] Disputed` callouts. Deterministic Step 3.

    Resolution = page exists: a Disputed callout is RESOLVED when a topic page
    it references (`See topic [[slug.md]]`) exists in `wiki/topics/`. An
    UNRESOLVED callout is one with no existing resolving topic page AND a
    flagged date >30 days old. The flagged date is the first `YYYY-MM-DD` in
    the callout body — robust to the format drift seen in the wild
    (bracketed/unbracketed stamp, placeholder `HH:MM`). A callout with no
    resolving topic AND no parseable date cannot be aged — surfaced separately
    for manual review (fail loud, never silently dropped).
    """
    _, topic_names, _ = wiki_page_names(wiki_root)
    unresolved: list[dict[str, object]] = []
    unparseable: list[str] = []
    for type_folder in ("concepts", "entities"):
        type_dir = wiki_root / "wiki" / type_folder
        if not type_dir.exists():
            continue
        for page in sorted(type_dir.rglob("*.md")):
            if page.name in NON_SOURCE_FILES or page.stem == page.parent.name or excluded_dir(page):
                continue
            rel = str(page.relative_to(wiki_root)).replace("\\", "/")
            lines = read_text(page).splitlines()
            for idx, line in enumerate(lines):
                if not DISPUTED_HEADER_RE.match(line):
                    continue
                body = [line]
                for follow in lines[idx + 1 :]:
                    if follow.lstrip().startswith(">"):
                        body.append(follow)
                    else:
                        break
                blob = "\n".join(body)
                # Resolution: any referenced page that is an existing topic page.
                if any(Path(t).name in topic_names for t in DISPUTED_LINK_RE.findall(blob)):
                    continue
                date_match = DISPUTED_DATE_RE.search(blob)
                if not date_match:
                    unparseable.append(rel)
                    continue
                date_str = date_match.group(1)
                try:
                    age = (today() - datetime.date.fromisoformat(date_str)).days
                except ValueError:
                    unparseable.append(rel)
                    continue
                if age > STUB_AGE_FLOOR_DAYS:
                    unresolved.append({"page": rel, "flagged": date_str, "age_days": age})
    report.detected["disputed_callouts"] = unresolved
    report.detected["disputed_callouts_unparseable"] = sorted(set(unparseable))


# ---------------------------------------------------------------------------
# C1 — log prune-test + questions.md link check (always-on detection)
# ---------------------------------------------------------------------------


def normalize_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9.-]+", "-", name.lower()).strip("-")


def wiki_page_names(wiki_root: Path) -> tuple[set[str], set[str], set[str]]:
    """(all wiki page filenames, topic page filenames, theses page filenames) — leaf indexes excluded."""
    all_names: set[str] = set()
    topic_names: set[str] = set()
    theses_names: set[str] = set()
    wiki_dir = wiki_root / "wiki"
    if not wiki_dir.exists():
        return all_names, topic_names, theses_names
    for page in wiki_dir.rglob("*.md"):
        if page.name in NON_SOURCE_FILES or page.stem == page.parent.name or excluded_dir(page):
            continue
        all_names.add(page.name)
        parts = page.relative_to(wiki_dir).parts
        if "topics" in parts:
            topic_names.add(page.name)
        if "theses" in parts:
            theses_names.add(page.name)
    return all_names, topic_names, theses_names


def split_log_blocks(text: str) -> tuple[str, list[str]]:
    """(preamble, H2 blocks). Split on every `^## ` line — plain headings
    (e.g. `## Candidate-mentions (review queue ...)`) survive as their own
    blocks (pitfall 4)."""
    lines = text.splitlines(keepends=True)
    preamble: list[str] = []
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if line.startswith("## "):
            if current is not None:
                blocks.append(current)
            current = [line]
        elif current is None:
            preamble.append(line)
        else:
            current.append(line)
    if current is not None:
        blocks.append(current)
    return "".join(preamble), ["".join(b) for b in blocks]


def scan_log(
    wiki_root: Path,
    report: Report,
    prune: bool,
    candidate_age_floor: int = CANDIDATE_AGE_FLOOR_DAYS,
) -> None:
    """Prune-test every entry across the split logs under {wiki_root}/logs/.

    Each entry carries its type in its own H2 header, so the scanner walks every
    file in logs/ and resolves per type (resolution = page exists):
      - candidate-topic       -> topic pages
      - candidate-mention     -> ALL page names
      - proposed-new-thesis   -> theses pages (like candidate-topic)
      - speculative-thesis-update -> NEVER auto-pruned; aged + surfaced as
        "awaiting investor decision" (the page already exists, so there is no
        "page exists" resolution signal — DEC-2).

    Unpromoted candidate-topics aged AT OR ABOVE ``candidate_age_floor`` days
    (default CANDIDATE_AGE_FLOOR_DAYS; 0 = every pending candidate) surface in
    ``detected.log_aging_candidate_topics`` — they feed the lint step-4 aging
    line and the step-9 CANDIDATE-TOPIC PROMOTION block. Candidate-topic
    headers with no parseable ``YYYY-MM-DD`` date cannot be aged and surface
    in ``detected.log_unparseable_timestamps`` (kept, report-only).
    """
    logs_dir = wiki_root / "logs"
    if not os.path.exists(_fspath(logs_dir)):
        return
    all_names, topic_names, theses_names = wiki_page_names(wiki_root)
    spent: list[dict[str, str]] = []
    aging: list[dict[str, object]] = []
    unknown: list[str] = []
    retired: list[str] = []
    awaiting: list[dict[str, object]] = []
    unparseable: list[str] = []
    pruned_spent = 0
    pruned_retired = 0
    for log_path in sorted(logs_dir.glob("*.md")):
        preamble, blocks = split_log_blocks(read_text(log_path))
        keep: list[str] = []
        file_spent = 0
        file_retired = 0
        for block in blocks:
            header = block.splitlines()[0].rstrip()
            match = LOG_HEADER_RE.match(header)
            if not match:
                keep.append(block)  # plain heading — never an entry, never pruned
                continue
            timestamp, entry_type, brief = match.groups()
            if entry_type in RETIRED_LOG_TYPES:
                retired.append(header)
                file_retired += 1
                continue  # dropped on prune
            if entry_type not in ACTIVE_LOG_TYPES:
                unknown.append(header)  # kept + reported, never deleted (Defect 3)
                keep.append(block)
                continue
            if entry_type == "speculative-thesis-update":
                # NEVER auto-pruned (no "page exists" signal — the thesis page
                # already exists). Age + surface as awaiting investor decision.
                date_match = re.match(r"(\d{4}-\d{2}-\d{2})", timestamp)
                age_days = (
                    (today() - datetime.date.fromisoformat(date_match.group(1))).days
                    if date_match
                    else None
                )
                awaiting.append(
                    {
                        "brief": brief,
                        "logged": date_match.group(1) if date_match else None,
                        "age_days": age_days,
                    }
                )
                keep.append(block)
                continue
            candidates = {normalize_slug(brief)}
            name_match = re.search(r"^- name:\s*(.+)$", block, flags=re.M)
            if name_match:
                candidates.add(normalize_slug(name_match.group(1)))
            if entry_type == "candidate-topic":
                page_set = topic_names
            elif entry_type == "proposed-new-thesis":
                page_set = theses_names
            else:  # candidate-mention
                page_set = all_names
            matched = next((f"{c}.md" for c in candidates if f"{c}.md" in page_set), None)
            if matched:
                spent.append({"header": header, "matched_page": matched})
                file_spent += 1
                continue  # dropped on prune (resolution = page exists)
            if entry_type == "candidate-topic":
                date_match = re.match(r"(\d{4}-\d{2}-\d{2})", timestamp)
                if date_match:
                    age = (today() - datetime.date.fromisoformat(date_match.group(1))).days
                    if age >= candidate_age_floor:
                        trigger_match = re.search(r"^- trigger:\s*(.+)$", block, flags=re.M)
                        aging.append(
                            {
                                "slug": brief,
                                "logged": date_match.group(1),
                                "age_days": age,
                                "trigger": trigger_match.group(1).strip() if trigger_match else None,
                            }
                        )
                else:
                    unparseable.append(header)
            keep.append(block)
        if prune and (file_spent or file_retired):
            write_text(log_path, preamble + "".join(keep), report, apply_changes=True)
            pruned_spent += file_spent
            pruned_retired += file_retired
    report.detected["log_spent_entries"] = spent
    report.detected["log_retired_entries"] = retired
    report.detected["log_unknown_type_entries"] = unknown
    report.detected["log_aging_candidate_topics"] = aging
    report.detected["log_unparseable_timestamps"] = unparseable
    report.detected["log_awaiting_thesis_decisions"] = awaiting
    if prune and (pruned_spent or pruned_retired):
        report.detected["log_pruned"] = {"spent": pruned_spent, "retired": pruned_retired}


# ---------------------------------------------------------------------------
# Source-queue rule-3 prune (finance lint extension) — deterministic matcher
# ---------------------------------------------------------------------------
# A source-queue.md entry is "spent" once its wiki source page exists. The
# finance extension (wiki-ext/lint-rules.ext.md rule 3) resolves this
# DETERMINISTICALLY (decision 2026-06-10, source-queue-adjudication-2026-06-10.md
# § Rule-3 implementation), in priority order:
#   1. URL — entry `url:` matched (normalized, prefix-tolerant) against a
#      source-page `url:` frontmatter, within the SAME origin folder. Authoritative.
#   2. DOI — a DOI extracted from the entry url/title appears in the page.
#   3. exact title — entry title normalizes EQUAL to the page H1 or filename stem.
# NEVER a title-token-overlap heuristic: that produced the IEA false-negative
# (real page fell under the 60% cutoff) and the ENGIE false-collapse (two
# quarters onto one page) on the real queue.
#
# source-queue.md exists ONLY via the finance capture tool, so its presence is
# the scope guard: absent -> silent no-op (general wikis never carry it).

SOURCE_QUEUE_FILENAME = "source-queue.md"
SOURCE_QUEUE_HEADER_RE = re.compile(rf"^##\s+(\S+)\s+{DASH}\s+(.+?)\s*$")
_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>)\]]+")


def _norm_source_url(url: str) -> str:
    """Normalize a URL for prefix-tolerant matching: drop scheme, www, trailing slash."""
    u = (url or "").strip().strip("\"'").lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/")


def _norm_title_exact(text: str) -> str:
    """Fold a title/H1/stem to a canonical form for EXACT (not fuzzy) comparison.

    Casefold, fold smart quotes / dashes, strip accents, collapse every run of
    non-alphanumerics to a single space. Two strings that differ only in
    punctuation, case, accent, or separator collapse equal; a differing
    substantive token (`3t25` vs `4t25`) keeps them distinct — the property the
    token-overlap heuristic lacked.
    """
    text = "".join(_FOLD_TRANS.get(ch, ch) for ch in (text or ""))
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _extract_dois(text: str) -> set[str]:
    return {m.rstrip(".").lower() for m in _DOI_RE.findall(text or "")}


def _load_source_queue_pages(wiki_root: Path, origin: str) -> list[dict[str, str]]:
    """Source pages under wiki/sources/{origin}/ (leaf index + non-source files excluded)."""
    out: list[dict[str, str]] = []
    if not origin:
        return out
    origin_dir = wiki_root / "wiki" / "sources" / origin
    if not origin_dir.is_dir():
        return out
    index_name = f"{origin}.md"
    for page in sorted(origin_dir.glob("*.md")):
        if page.name == index_name or page.name in NON_SOURCE_FILES:
            continue
        text = read_text(page)
        out.append(
            {
                "name": page.name,
                "stem": page.stem,
                "url": frontmatter(text).get("url", ""),
                "h1": first_h1(text),
                "text": text,
            }
        )
    return out


def _match_source_queue_entry(
    entry: dict[str, str], pages: list[dict[str, str]]
) -> tuple[str, str] | None:
    """Return (matched_page_filename, signal) or None. Signal is url|doi|title."""
    # Signal 1 — URL (authoritative, prefix-tolerant).
    qn = _norm_source_url(entry.get("url", ""))
    if qn:
        for p in pages:
            pn = _norm_source_url(p["url"])
            if pn and (pn == qn or pn.startswith(qn) or qn.startswith(pn)):
                return p["name"], "url"
    # Signal 2 — a DOI shared between the entry (url/title) and a page.
    qdois = _extract_dois(entry.get("url", "")) | _extract_dois(entry.get("title", ""))
    if qdois:
        for p in pages:
            if qdois & (_extract_dois(p["url"]) | _extract_dois(p["text"])):
                return p["name"], "doi"
    # Signal 3 — exact normalized title vs page H1 or filename stem.
    qt = _norm_title_exact(entry.get("title", ""))
    if qt:
        for p in pages:
            stem_words = p["stem"].replace("-", " ").replace("_", " ")
            if qt == _norm_title_exact(p["h1"]) or qt == _norm_title_exact(stem_words):
                return p["name"], "title"
    return None


def scan_source_queue(wiki_root: Path, report: Report, prune: bool) -> None:
    """Rule-3: resolve spent source-queue entries deterministically; optionally prune.

    Detection ALWAYS runs (check mode surfaces prune candidates in the report).
    The delete is applied only when ``prune`` is True (the owner-gated
    --prune-source-queue flow). Absent file -> silent no-op (scope guard).
    Present but no parseable H2 entry -> WARN via report, skip, NEVER abort.
    Mirrors the logs/ prune pattern in ``scan_log``.
    """
    queue_path = wiki_root / SOURCE_QUEUE_FILENAME
    if not os.path.exists(_fspath(queue_path)):
        return
    preamble, blocks = split_log_blocks(read_text(queue_path))
    resolved: list[dict[str, str]] = []
    open_entries: list[dict[str, str]] = []
    keep: list[str] = []
    pruned = 0
    parsed_any = False
    for block in blocks:
        header = block.splitlines()[0].rstrip()
        match = SOURCE_QUEUE_HEADER_RE.match(header)
        if not match:
            keep.append(block)  # plain heading — never an entry, never pruned
            continue
        parsed_any = True
        state, date = match.group(1), match.group(2).strip()
        entry: dict[str, str] = {"state": state, "date": date}
        for key in ("title", "url", "source"):
            field_match = re.search(rf"^-\s+{key}:\s*(.+)$", block, flags=re.M)
            if field_match:
                entry[key] = field_match.group(1).strip()
        pages = _load_source_queue_pages(wiki_root, entry.get("source", ""))
        hit = _match_source_queue_entry(entry, pages)
        if hit:
            matched_page, signal = hit
            resolved.append(
                {
                    "state": state,
                    "date": date,
                    "title": entry.get("title", ""),
                    "origin": entry.get("source", ""),
                    "matched_page": matched_page,
                    "signal": signal,
                }
            )
            pruned += 1
            continue  # dropped on prune (resolution = page exists)
        open_entries.append(
            {
                "state": state,
                "date": date,
                "title": entry.get("title", ""),
                "origin": entry.get("source", ""),
            }
        )
        keep.append(block)
    if blocks and not parsed_any:
        # Present but no parseable H2 entry — warn, skip, never abort.
        report.detected["source_queue_malformed"] = str(queue_path)
        return
    report.detected["source_queue_resolved"] = resolved
    report.detected["source_queue_open"] = open_entries
    if prune and pruned:
        write_text(queue_path, preamble + "".join(keep), report, apply_changes=True)
        report.detected["source_queue_pruned"] = pruned


def check_questions_links(wiki_root: Path, report: Report) -> None:
    questions_path = wiki_root / "questions.md"
    if not os.path.exists(_fspath(questions_path)):
        return  # questions layer OFF — skip silently
    targets: set[str] = set()
    for root in [wiki_root / "wiki", wiki_root / "raw"]:
        if not root.exists():
            continue
        for item in root.rglob("*.md"):
            if not excluded_dir(item.relative_to(wiki_root)):
                targets.add(item.name)
    broken = [
        target
        for target in re.findall(r"\[\[([^\]|#]+?\.md)\]\]", read_text(questions_path))
        if Path(target).name not in targets
    ]
    report.detected["questions_broken_links"] = broken


# ---------------------------------------------------------------------------
# C2 — structural walk: stubs, orphans, footnote state (+ C3 safe renumber)
# ---------------------------------------------------------------------------


def collect_wiki_pages(wiki_root: Path) -> tuple[list[Path], list[Path]]:
    """(cet_pages, source_pages) — leaf indexes, CLAUDE.md, assets excluded."""
    cet: list[Path] = []
    sources: list[Path] = []
    for type_folder in ("concepts", "entities", "topics"):
        type_dir = wiki_root / "wiki" / type_folder
        if not type_dir.exists():
            continue
        for page in type_dir.rglob("*.md"):
            if page.name in NON_SOURCE_FILES or page.stem == page.parent.name or excluded_dir(page):
                continue
            cet.append(page)
    sources_dir = wiki_root / "wiki" / "sources"
    if sources_dir.exists():
        for page in sources_dir.rglob("*.md"):
            if page.name in NON_SOURCE_FILES or page.stem == page.parent.name or excluded_dir(page):
                continue
            sources.append(page)
    return cet, sources


def body_after_frontmatter(text: str) -> str:
    match = re.match(r"^---\s*\n.*?\n---\s*\n", text, flags=re.S)
    return text[match.end():] if match else text


def split_h2_sections(body: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {"_pre": []}
    current = "_pre"
    for line in body.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = match.group(1)
            sections.setdefault(current, [])
        else:
            sections[current].append(line)
    return {name: "\n".join(lines) for name, lines in sections.items()}


def substantive_word_count(text: str) -> int:
    flat = flatten_wikilinks(text)
    flat = re.sub(r"\[\^\d+\]:?", " ", flat)
    flat = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", flat)
    flat = re.sub(r"[#>*`|]+", " ", flat)
    return len(flat.split())


def footnote_state(text: str) -> dict[str, object]:
    defs = re.findall(r"^\[\^(\d+)\]:", text, flags=re.M)
    # Strip ONLY the line-start definition marker (``[^N]:``) so it is not
    # double-counted as an inline use. Everything else — including a mid-line
    # ``Candidate answer[^N]:`` occurrence (questions-layer answer accretion),
    # where ``[^N]`` sits immediately before a ``:`` — is a genuine inline use.
    # A blanket ``(?!:)`` lookahead wrongly excluded those mid-line uses,
    # leaving a real reference invisible and failing the integrity gate.
    body = re.sub(r"^\[\^\d+\]:", "", text, flags=re.M)
    inline_all = re.findall(r"\[\^(\d+)\]", body)
    order: list[str] = []
    for marker in inline_all:
        if marker not in order:
            order.append(marker)
    return {"defs": defs, "inline": inline_all, "order": order}


def cmd_check_pages(args_list: list[str]) -> int:
    """Citation-integrity gate (``check-pages``) — ingest/heal commit hard-gate.

    Validates the footnote state of the named pages only: every inline
    ``[^N]`` marker has a definition, every definition has at least one
    inline marker (the marker-pairing assertion — a ``Sources`` ``[^N]:``
    def with NO in-text ``[^N]`` marker is an ORPHAN footnote, reported as
    ``def without inline ref: <N,...>``), and no definition number is
    duplicated.  Ordering is NOT checked — the C3 renumber pass owns
    normalization.  Exits 1 on any issue, naming each failing page in the
    ``failures[]`` JSON, so workflow callers HARD-GATE on the result:
    the single-page ingest post-commit gate (``sb-wiki-ingest`` Step 10)
    and the bulk/orchestrated single-commit gate (``sb-wiki-ingest-healing``
    Step 4 orchestrated path — U7) both block the commit while this exits
    non-zero.  Read the exit code off the UN-PIPED process (a pipe reports
    the pipe's status, masking a failure).
    """
    parser = argparse.ArgumentParser(
        description="Citation-integrity check on specific pages."
    )
    parser.add_argument("--vault-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "pages",
        nargs="+",
        type=Path,
        help="page paths (absolute or vault-root-relative)",
    )
    args = parser.parse_args(args_list)
    vault_root = args.vault_root.resolve()

    failures: list[dict[str, object]] = []
    for raw_path in args.pages:
        page = raw_path if raw_path.is_absolute() else vault_root / raw_path
        if not page.exists():
            failures.append({"page": str(raw_path), "issues": ["file not found"]})
            continue
        state = footnote_state(read_text(page))
        defs, inline = state["defs"], state["inline"]
        issues: list[str] = []
        if len(defs) != len(set(defs)):
            issues.append("duplicate defs")
        missing = sorted(set(inline) - set(defs), key=int)
        if missing:
            issues.append(f"inline without def: {','.join(missing)}")
        stale = sorted(set(defs) - set(inline), key=int)
        if stale:
            issues.append(f"def without inline ref: {','.join(stale)}")
        if issues:
            failures.append({"page": str(raw_path), "issues": issues})

    print(
        json.dumps(
            {"checked": len(args.pages), "failures": failures},
            indent=2,
            ensure_ascii=False,
        )
    )
    return 1 if failures else 0


def structural_walk(wiki_root: Path, report: Report, apply_changes: bool) -> None:
    cet_pages, source_pages = collect_wiki_pages(wiki_root)
    stubs_aged: list[dict[str, object]] = []
    stubs_no_created: list[str] = []
    stubs_fresh = 0
    footnote_issues: list[dict[str, object]] = []
    provenance_only = 0
    renumbered: list[dict[str, object]] = []
    inbound: dict[str, int] = {}
    cet_names = {p.name for p in cet_pages}

    for page in cet_pages + source_pages:
        text = read_text(page)
        rel = str(page.relative_to(wiki_root)).replace("\\", "/")
        is_source = page in source_pages
        body = body_after_frontmatter(text)
        sections = split_h2_sections(body)

        # --- C2a stub state + age ---
        substantive = False
        for name, content in sections.items():
            if name in {"_pre", "Sources"}:
                continue
            if is_source and name not in SOURCE_AGENT_HALF:
                continue  # user-half exemption
            if substantive_word_count(content) > 50:
                substantive = True
                break
        if not substantive:
            fm = frontmatter(text)
            created = fm.get("created", "") or fm.get("date", "")
            try:
                age = (today() - datetime.date.fromisoformat(created)).days
            except ValueError:
                age = None
            if age is None:
                stubs_no_created.append(rel)
            elif age > STUB_AGE_FLOOR_DAYS:
                stubs_aged.append({"page": rel, "created": created, "age": age})
            else:
                stubs_fresh += 1

        # --- C2b orphan inbound map (STRICT: cet pages are the only sources) ---
        if not is_source:
            for target in set(re.findall(r"\[\[([^\]|#]+?\.md)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]", text)):
                target_name = Path(target).name
                if target_name != page.name and target_name in cet_names:
                    inbound[target_name] = inbound.get(target_name, 0) + 1

        # --- C2c footnote state ---
        state = footnote_state(text)
        defs, inline, order = state["defs"], state["inline"], state["order"]
        if defs and not inline:
            if substantive:
                # Born-cited regression: a substantive page whose defs have
                # zero inline markers is a content defect, not stub shape.
                footnote_issues.append(
                    {"page": rel, "issues": ["provenance-only (substantive page)"]}
                )
            else:
                provenance_only += 1  # stub-provenance shape — report bucket only, NEVER touch
            continue
        issues: list[str] = []
        if len(defs) != len(set(defs)):
            issues.append("duplicate defs")
        missing = sorted(set(inline) - set(defs), key=int)
        if missing:
            issues.append(f"inline without def: {','.join(missing)}")
        stale = sorted(set(defs) - set(inline), key=int)
        if inline and stale:
            issues.append(f"stale defs: {','.join(stale)}")
        non_sequential = order != [str(i) for i in range(1, len(order) + 1)]
        if non_sequential:
            issues.append("non-sequential")
        # --- C3 safe renumber: ONLY pure bijections with no other issue ---
        if non_sequential and len(issues) == 1 and set(inline) == set(defs):
            mapping = {old: str(new) for new, old in enumerate(order, start=1)}
            new_text = text
            for old in mapping:
                new_text = new_text.replace(f"[^{old}]", f"[^@TMP{old}@]")
            for old, new in mapping.items():
                new_text = new_text.replace(f"[^@TMP{old}@]", f"[^{new}]")
            write_text(page, new_text, report, apply_changes)
            renumbered.append({"page": rel, "map": mapping})
        elif issues:
            footnote_issues.append({"page": rel, "issues": issues})

    report.detected["stubs_aged_gt30"] = stubs_aged
    report.detected["stubs_fresh_count"] = stubs_fresh
    report.detected["stubs_no_created"] = stubs_no_created
    report.detected["orphans"] = sorted(p.name for p in cet_pages if inbound.get(p.name, 0) == 0)
    report.detected["footnote_issues"] = footnote_issues
    report.detected["provenance_only_count"] = provenance_only
    report.detected["renumbered"] = renumbered


# ---------------------------------------------------------------------------
# C4 — PDF title-conformance: detection (always-on) + rename executor (gated)
# ---------------------------------------------------------------------------


def title_slug(title: str) -> str:
    """Kebab-slug per naming-convention.md § Title-slug algorithm."""
    slug = title.lower()
    slug = re.sub(r"[\s+/:–—]+", "-", slug)
    # Step 3: remove "? ! , . " ' ( ) [ ]" AND any other punctuation. Separators
    # are already mapped to "-" above, so anything left that is not a lowercase
    # letter, digit, or hyphen (e.g. "#", "&", ";", "@") is punctuation to drop.
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


def raw_index_titles(origin_dir: Path) -> dict[str, str]:
    """Map raw filename -> index Title cell (empty when no row OR no Title cell).

    ADX-9/ADX-10: the canonical raw index is 2-col ``| File | Wiki |`` — it carries
    NO Title cell. Only a NOT-YET-MIGRATED legacy 4-col ``| File | Title | Date |
    Wiki |`` row has a Title (cell 1). A 2-col row's cell 1 is the Wiki value, NOT a
    title — returning it would make PDF title-conformance slug-compare against
    ``No``/``Yes`` and propose nonsense renames. So a Title is returned ONLY for a
    recognized 4-col legacy row; 2-col and 3-col rows yield no title (the detector
    skips them via its ``if not title`` guard). This is a TRANSITION-ONLY fallback:
    the primary publish-time source of an ingested PDF's title is now its source
    page (``title:`` frontmatter, else first H1) via ``pdf_source_titles`` — this
    legacy index path only supplies a title for a not-yet-migrated 4-col index.
    """
    index_path = origin_dir / f"{origin_dir.name}.md"
    titles: dict[str, str] = {}
    if not index_path.exists():
        return titles
    for line in read_text(index_path).splitlines():
        if not line.strip().startswith("|") or re.match(r"^\s*\|\s*-+", line):
            continue
        cells = split_row_cells(line)
        if cells and cells[0] == "File":
            continue
        # Title lives at cell 1 ONLY in a legacy 4-col row. A 2-col `File|Wiki` row
        # (cell 1 = Wiki) and a 3-col `File|Description|Wiki` row (cell 1 =
        # Description, not a title) carry no usable PDF title here.
        if len(cells) != 4:
            continue
        match = re.search(r"\[\[([^\]|#]+?)\]\]", cells[0])
        if match:
            titles[Path(match.group(1)).name] = cells[1]
    return titles


def source_page_title(text: str) -> str:
    """Return a source page's title: its ``title:`` frontmatter, else its first H1.

    Empty when neither is present. This is the post-ADX-9/10 publish-time source
    of a PDF's title for lint title-conformance (the raw index no longer carries a
    Title column).
    """
    title = frontmatter(text).get("title", "").strip()
    if title:
        return title
    return first_h1(text)


def pdf_source_titles(wiki_root: Path, origin_dir: Path) -> dict[str, str]:
    """Map each PDF raw filename in *origin_dir* -> its ingested source-page title.

    The title is read from the PDF's 1:1 source page (``title:`` frontmatter, else
    first H1). The source page is located by the SAME three union signals as
    ``ingested_raw_filenames`` (U1b), keyed on the PDF filename:

      - filename mirror — ``wiki/sources/{origin}/{pdf-stem}.md`` (a PDF's source
        page is the title-slug ``.md``, same stem).
      - ``raw:`` frontmatter backlink — a source page whose ``raw:`` wikilinks the
        PDF filename (divergent stem, e.g. a dated-clip-first source).
      - ``Original PDF:`` body backlink — a source page whose body names the bare
        PDF (legacy dated-clip origins: caiso/engie).

    A PDF with NO source page yields no entry (the detector then stays dormant for
    that file — owner-accepted until ingest). The wiki sources root is resolved the
    way the rest of the engine resolves it (``wiki_root / "wiki" / "sources" /
    {origin}``), never a hardcoded vault path.
    """
    titles: dict[str, str] = {}
    pdf_names = {p.name for p in origin_dir.glob("*.pdf")}
    if not pdf_names:
        return titles
    sources_dir = wiki_root / "wiki" / "sources" / origin_dir.name
    if not sources_dir.exists():
        return titles
    index_name = f"{sources_dir.name}.md"
    # mirror: a same-stem source page maps to a same-stem PDF (papers).
    pdf_stems = {Path(n).stem: n for n in pdf_names}
    for page in sorted(sources_dir.glob("*.md")):
        if page.name == index_name or page.name in NON_SOURCE_FILES:
            continue
        text = read_text(page)
        title = source_page_title(text)
        if not title:
            continue
        # raw: frontmatter backlink + Original PDF: body backlink — both name a
        # raw FILENAME; bind the title to any PDF they reference.
        targets: set[str] = set()
        raw_val = frontmatter(text).get("raw", "")
        for t in re.findall(r"\[\[([^\]|#]+?)\]\]", raw_val):
            targets.add(Path(t).name)
        for t in ORIGINAL_PDF_RE.findall(text):
            targets.add(Path(t).name)
        for target in targets:
            if target in pdf_names:
                titles.setdefault(target, title)
        # filename mirror — the source page stem equals the PDF stem.
        mirror_pdf = pdf_stems.get(page.stem)
        if mirror_pdf is not None:
            titles.setdefault(mirror_pdf, title)
    return titles


def detect_pdf_title_conformance(wiki_root: Path, report: Report) -> None:
    proposals: list[dict[str, str]] = []
    duplicates: list[dict[str, str]] = []
    disambiguation: list[dict[str, str]] = []
    raw_root = wiki_root / "raw"
    if not raw_root.exists():
        for key in ("rename_proposals", "duplicate_raws", "title_disambiguation_needed"):
            report.detected[key] = []
        return
    for origin_dir in sorted(p for p in raw_root.iterdir() if p.is_dir() and not excluded_dir(p.relative_to(wiki_root))):
        # Primary title source (ADX-9/10): the PDF's ingested source-page
        # `title:` frontmatter (else first H1). Legacy 4-col raw-index Title is a
        # transition-only fallback for a not-yet-migrated index.
        source_titles = pdf_source_titles(wiki_root, origin_dir)
        legacy_titles = raw_index_titles(origin_dir)
        slug_groups: dict[str, list[tuple[str, str]]] = {}
        for pdf in sorted(origin_dir.glob("*.pdf")):
            title = source_titles.get(pdf.name) or legacy_titles.get(pdf.name, "")
            if not title:
                continue  # un-ingested PDF (no source page) — dormant until ingest
            slug_groups.setdefault(title_slug(title), []).append((pdf.stem, title))
        for slug, members in slug_groups.items():
            if not slug:
                continue
            nonconforming = [(stem, title) for stem, title in members if stem != slug]
            if not nonconforming:
                continue
            if len(members) > 1:
                disambiguation.extend(
                    {"origin": origin_dir.name, "file": f"{stem}.pdf", "title": title, "title_slug": slug}
                    for stem, title in members
                )
                continue
            stem, _title = nonconforming[0]
            if (origin_dir / f"{slug}.pdf").exists():
                duplicates.append({"origin": origin_dir.name, "file": f"{stem}.pdf", "existing": f"{slug}.pdf"})
            else:
                proposals.append({"origin": origin_dir.name, "old_stem": stem, "new_stem": slug})
    report.detected["rename_proposals"] = proposals
    report.detected["duplicate_raws"] = duplicates
    report.detected["title_disambiguation_needed"] = disambiguation


# ---------------------------------------------------------------------------
# U3 — missing-link detector (signal-1, report-only)
# ---------------------------------------------------------------------------
# Diagnosis Finding 2: concept->concept / concept->source links are created
# ONLY at ingest, ONLY onto pages the ingested source NAMES. Nothing backfills
# an obvious link from a later source that did not name the page. Lint repairs
# only BROKEN links and flags only zero-inbound orphans — so a missing-but-
# obvious link is invisible to lint today. Example: attention-mechanism.md says
# "the transformer architecture" in unlinked prose but never links
# [[transformer.md]], though transformer.md exists.
#
# SIGNAL-1 (high precision, the ONLY signal shipped here — signal-2 co-membership
# is deferred per the spec): a wiki page's EXACT name appears as plain UNLINKED
# text in ANOTHER page's prose AND a page by that name exists. Case- and
# hyphen-insensitive ("Self Attention" / "self-attention" / "self attention" all
# match self-attention.md).
#
# DETERMINISTIC + REPORT-ONLY. Pure text scan — no LLM judgment, no writes to any
# page. It REPORTS into `detected.missing_links` and writes a standalone report
# file the human-gated update-links lint sub-mode reads. It NEVER appends a
# `[[link]]` — applying a link is the separate, owner-gated Stage-2 step (the
# `update-links` sub-command in this script + the lint Step-9 handler). Detection
# never auto-links (diagnosis §3.4 / decision #33 — detection SIGNALS the owner).

# Report file the Stage-2 update-links sub-mode reads (under wiki_root).
MISSING_LINK_REPORT = "missing-links.md"
# Registry of owner-rejected proposals (under wiki_root). A `term -> target`
# pair listed here is suppressed from every future detection run (spec guard:
# "dedupe against links the owner already REJECTED"). Owner-maintained: the
# update-links sub-mode appends a row on a `reject`; the detector reads it.
MISSING_LINK_REJECTED = "missing-links-rejected.md"

# A page-name token is a single kebab-or-space word run; we tokenize a page's
# stem into its component words and match the same run, separator-insensitive,
# inside another page's prose. Multi-word names (self-attention -> "self",
# "attention") match "self attention" / "Self-Attention" / "self  attention".
_NAME_WORD_RE = re.compile(r"[a-z0-9]+")


def _name_words(stem: str) -> list[str]:
    """Lowercase word tokens of a page stem (separators folded away).

    `self-attention` -> ['self', 'attention']; `transformer` -> ['transformer'].
    Diacritics folded so an accented prose mention still matches.
    """
    folded = unicodedata.normalize("NFKD", stem)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return _NAME_WORD_RE.findall(folded.casefold())


def _prose_only(text: str) -> str:
    """Body text with linkable structure stripped so a name inside an existing
    link, a code span, a footnote def, a frontmatter block, or an embed is NOT
    counted as an UNLINKED prose mention.

    Removed: frontmatter; fenced/inline code; image embeds; existing `[[..]]`
    wikilinks (the whole token, target + alias); markdown `[text](url)` links;
    footnote DEFINITION lines (`[^N]: ...`, the Sources graph edges). What
    remains is plain prose where an unlinked name is a real missing-link signal.
    """
    body = body_after_frontmatter(text)
    body = re.sub(r"```.*?```", " ", body, flags=re.S)      # fenced code
    body = re.sub(r"`[^`]*`", " ", body)                     # inline code
    body = re.sub(r"^\[\^\d+\]:.*$", " ", body, flags=re.M)  # footnote defs
    body = re.sub(r"!\[\[[^\]]*\]\]", " ", body)             # ![[embed]]
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", body)        # ![alt](src)
    body = re.sub(r"\[\[[^\]]*\]\]", " ", body)              # [[wikilink]]
    body = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", body)         # [text](url)
    return body


def _name_pattern(words: list[str]) -> "re.Pattern[str] | None":
    """Compiled whole-token, separator-insensitive matcher for a page-name word
    run. Whole-token = bounded by a non-alphanumeric on each side, so
    `transformer` does NOT match inside `transformers` or `transformative`; the
    words run in order separated only by non-alphanumeric runs (space/hyphen/
    slash). Compiled ONCE per name (the prose it scans is pre-casefolded), so
    the corpus-wide scan never recompiles a pattern per page-pair.
    """
    if not words:
        return None
    body = r"[^a-z0-9]+".join(re.escape(w) for w in words)
    return re.compile(r"(?<![a-z0-9])" + body + r"(?![a-z0-9])")


def _existing_link_targets(text: str) -> set[str]:
    """Filenames this page ALREADY links — body wikilinks + `related:` frontmatter.

    A page already linking the target is never re-proposed (spec edge case)."""
    targets: set[str] = set()
    for target in re.findall(r"\[\[([^\]|#]+?\.md)", text):
        targets.add(Path(target.strip()).name)
    return targets


def _load_rejected_pairs(wiki_root: Path) -> set[tuple[str, str]]:
    """Owner-rejected `(term, target.md)` pairs, normalized for comparison.

    Reads the markdown table in `missing-links-rejected.md` (columns
    `term | proposed-link`). Absent file -> empty set. Term is casefolded;
    target is the bare `.md` filename. Malformed rows are skipped, never fatal.
    """
    path = wiki_root / MISSING_LINK_REJECTED
    if not os.path.exists(_fspath(path)):
        return set()
    rejected: set[tuple[str, str]] = set()
    for line in read_text(path).splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        term, link = cells[0], cells[1]
        if term.casefold() in ("term", "---") or set(term) <= {"-", " ", ":"}:
            continue
        link_name = Path(flatten_wikilinks(link).strip()).name
        if link_name.endswith(".md"):
            rejected.add((term.casefold(), link_name))
    return rejected


def _missing_link_table(rows: list[dict[str, object]]) -> str:
    """Render a proposal table (header + rows, or a one-line none state)."""
    head = (
        "| term | proposed-link | source file | target page | #mentions |\n"
        "|------|---------------|-------------|-------------|-----------|\n"
    )
    if not rows:
        return head + "| _(none)_ | | | | |\n"
    return head + "\n".join(
        f"| {r['term']} | [[{r['target']}]] | {r['source']} | {r['target']} | {r['mentions']} |"
        for r in rows
    ) + "\n"


def _render_missing_link_report(
    main_rows: list[dict[str, object]],
    hub_rows: list[dict[str, object]],
) -> str:
    """The standalone report file the Stage-2 update-links sub-mode reads.

    Two sections: the MAIN proposal list (multi-word targets — the actionable
    set the update-links step reads) and the SINGLE-TOKEN-HUB SUPPRESSED list
    (single-token targets like ai.md/llm.md — low precision, retained but NOT in
    the main list; ADX-7). Columns: term | proposed-link | source file | target
    page | #mentions. Rows arrive pre-sorted by #mentions desc."""
    return (
        "---\n"
        "type: missing-links-report\n"
        "tags: [missing-links-report]\n"
        "---\n\n"
        "# Missing-link proposals (signal-1)\n\n"
        "> Generated by `/sb-wiki-lint` (deterministic, report-only). Each row: a "
        "wiki page's exact name appears as UNLINKED prose in the source file where "
        "a page by that name exists. The human-gated `update-links` step reads the "
        "MAIN list below; nothing is auto-linked. Sorted by `#mentions` descending.\n\n"
        f"## Main proposals ({len(main_rows)})\n\n"
        + _missing_link_table(main_rows)
        + (
            f"\n## Single-token-hub suppressed ({len(hub_rows)})\n\n"
            "> Single-token TARGET names (no hyphen/space in the page stem — e.g. "
            "`ai.md`, `llm.md`) match a common word in most pages, so they are "
            "SUPPRESSED from the main list (low precision). Retained here for "
            "inspection — never silently dropped (ADX-7). The `update-links` step "
            "does NOT read this section; promote a row manually only if it is a "
            "genuine link.\n\n"
            + _missing_link_table(hub_rows)
        )
    )


def detect_missing_links(wiki_root: Path, report: Report, apply_changes: bool) -> None:
    """Signal-1 prose-mention scan. Report-only — NEVER writes a link.

    Walks concept / entity / topic / source pages. For each ORDERED pair
    (source_page, target_page) where target's exact name appears as unlinked
    prose in source AND source does not already link target AND the pair is not
    owner-rejected, emit a proposal row. Rows sorted by #mentions desc. Writes
    the report FILE only under --apply (mirrors the helper's other auto-applied
    report writes); detection itself is pure and never mutates a page.
    """
    cet, sources = collect_wiki_pages(wiki_root)
    pages = cet + sources
    # Per-name index, each computed ONCE: word tokens, the display term, a
    # first-token fast-path key, and a compiled whole-token matcher. Leaf
    # indexes are already excluded by collect_wiki_pages; a page never proposes
    # a link to itself. Precompiling here keeps the corpus scan O(pages × names)
    # in cheap substring checks, running the regex only when the fast-path hits.
    name_index: list[tuple[str, list[str], str, str, "re.Pattern[str]"]] = []
    for page in pages:
        words = _name_words(page.stem)
        if not words:
            continue
        pat = _name_pattern(words)
        if pat is None:
            continue
        name_index.append((page.name, words, " ".join(words), words[0], pat))

    rejected = _load_rejected_pairs(wiki_root)
    rows: list[dict[str, object]] = []

    for page in pages:
        text = read_text(page)
        prose_fold = _prose_only(text).casefold()
        already = _existing_link_targets(text)
        rel = str(page.relative_to(wiki_root)).replace("\\", "/")
        for target_name, words, term, first, pat in name_index:
            if target_name == page.name:
                continue                      # never self-link
            if target_name in already:
                continue                      # already linked — not re-proposed
            # cheap fast-path: skip if the name's first token never appears
            if first not in prose_fold:
                continue
            count = len(pat.findall(prose_fold))
            if count == 0:
                continue
            if (term, target_name) in rejected:
                continue                      # owner already rejected this pair
            rows.append(
                {
                    "term": term,
                    "target": target_name,
                    "source": rel,
                    "mentions": count,
                }
            )

    rows.sort(key=lambda r: (-int(r["mentions"]), str(r["source"]), str(r["target"])))

    # ADX-7 — single-token-hub suppression (report-side, never loses info).
    # A single-token TARGET name (no hyphen AND no space in the page stem, e.g.
    # ai.md / llm.md) matches a common word in nearly every page → high-volume
    # low-precision noise. SUPPRESS those from the main list, but RETAIN them
    # under a separate key + a visible count so nothing is lost (owner rule).
    # The "single token" test keys on the TARGET stem: its word-token count is 1.
    main_rows: list[dict[str, object]] = []
    hub_rows: list[dict[str, object]] = []
    for r in rows:
        if len(str(r["term"]).split()) <= 1:
            hub_rows.append(r)
        else:
            main_rows.append(r)

    report.detected["missing_links"] = main_rows
    report.detected["missing_links_hub_suppressed"] = hub_rows
    report.detected["missing_links_hub_suppressed_count"] = len(hub_rows)
    report.detected["missing_links_report"] = MISSING_LINK_REPORT
    report.detected["missing_links_rejected_registry"] = MISSING_LINK_REJECTED

    report_path = wiki_root / MISSING_LINK_REPORT
    write_text(report_path, _render_missing_link_report(main_rows, hub_rows), report, apply_changes)


# ---------------------------------------------------------------------------
# U10 — raw-`.md` duplicate detector (report-only)
# ---------------------------------------------------------------------------
# detect_pdf_title_conformance (above) already surfaces a PDF raw whose
# title-slug collides with an existing `.pdf` (`duplicate_raws`). U10 EXTENDS
# that idea to markdown raws: flag a NOT-yet-ingested raw `.md` whose normalized
# title OR normalized URL OR exact byte content-hash matches an ALREADY-ingested
# source. This is the dedup gap diagnosis Finding 1 / §8 names — duplicate
# detection is title/URL-only and only at ingest time; lint never flagged a
# duplicate `.md` raw.
#
# DETERMINISTIC + REPORT-ONLY. The scan is pure string/hash comparison — no LLM
# judgment. It REPORTS into `detected.md_duplicate_raws`; it NEVER deletes,
# renames, or mutates a raw or any other file. The owner disposes a flagged
# duplicate manually (the same posture as `duplicate_raws`).
#
# LIMIT (stated in `detected.md_duplicate_raws_limit` and the lint report):
# catches same-normalized-title / same-normalized-URL / byte-identical content;
# does NOT catch reworded same-material (a paraphrase shares no exact title,
# URL, or hash).

MD_DUPLICATE_LIMIT = (
    "Catches same-normalized-title / same-normalized-URL / byte-identical "
    "content only; does NOT catch reworded same-material (a paraphrase of an "
    "already-ingested source shares no exact title, URL, or content-hash)."
)


def _ingested_source_signals(
    wiki_root: Path,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Inventory the title / URL / content-hash of every ALREADY-ingested source.

    Returns three maps keyed on the signal value, each pointing at a stable
    descriptor of the ingested source it came from (``wiki/sources/{origin}/
    {page}.md`` relative path for title/URL; the backing raw's relative path for
    content-hash):

      - ``title_map``   — ``_norm_title_exact`` of the source page's frontmatter
        ``title:`` or H1 → source-page rel path.
      - ``url_map``     — ``_norm_source_url`` of the source page's ``url:``
        frontmatter → source-page rel path.
      - ``hash_map``    — SHA256 of the BYTES of the raw file the source page's
        ``raw:`` frontmatter backlinks (the only place the source carries the
        original raw bytes; the source-page body is synthesis, not raw bytes) →
        backing-raw rel path.

    Empty signal values are dropped so a blank title/URL never matches a blank.
    """
    title_map: dict[str, str] = {}
    url_map: dict[str, str] = {}
    hash_map: dict[str, str] = {}
    sources_root = wiki_root / "wiki" / "sources"
    if not sources_root.exists():
        return title_map, url_map, hash_map
    raw_root = wiki_root / "raw"
    for origin_dir in sorted(p for p in sources_root.iterdir() if p.is_dir()):
        index_name = f"{origin_dir.name}.md"
        for page in sorted(origin_dir.glob("*.md")):
            if page.name == index_name or page.name in NON_SOURCE_FILES:
                continue
            text = read_text(page)
            fm = frontmatter(text)
            rel = str(page.relative_to(wiki_root)).replace("\\", "/")
            ntitle = _norm_title_exact(fm.get("title", "") or first_h1(text))
            if ntitle:
                title_map.setdefault(ntitle, rel)
            nurl = _norm_source_url(fm.get("url", ""))
            if nurl:
                url_map.setdefault(nurl, rel)
            # Content-hash: hash the backing raw the source backlinks via `raw:`.
            # Resolve the backlink basename inside this origin's raw folder; hash
            # only when that raw file is present on disk. Hash via the SAME text
            # read the candidate side uses (`read_text` → UTF-8) so the two
            # hashes are line-ending-agnostic: under git `core.autocrlf=true` a
            # byte-identical `.md` lands with CRLF, and a binary-vs-text read of
            # the same content would otherwise diverge (CRLF preserved vs folded
            # to LF) and MISS a true duplicate. A candidate `.md` can only be a
            # duplicate of a `.md` backing raw, so a backing raw that is not
            # UTF-8 text (a PDF or other binary) is skipped for the hash signal.
            for target in re.findall(r"\[\[([^\]|#]+?)\]\]", fm.get("raw", "")):
                raw_name = Path(target).name
                raw_path = raw_root / origin_dir.name / raw_name
                if not os.path.exists(_fspath(raw_path)):
                    continue
                try:
                    raw_bytes = read_text(raw_path).encode("utf-8")
                except (UnicodeDecodeError, OSError):
                    continue  # binary/undecodable backing raw — not a `.md` dup
                digest = hashlib.sha256(raw_bytes).hexdigest()
                raw_rel = str(raw_path.relative_to(wiki_root)).replace("\\", "/")
                hash_map.setdefault(digest, raw_rel)
    return title_map, url_map, hash_map


def detect_md_duplicate_raws(wiki_root: Path, report: Report) -> None:
    """Flag a NOT-yet-ingested raw `.md` that duplicates an already-ingested source.

    Deterministic, REPORT-ONLY (U10). For each raw `.md` whose 1:1 source page
    does NOT already exist (``ingested_raw_filenames`` union — a raw that is
    already ingested is not a duplicate of itself), compute its three signals
    and report a match against the ingested-source inventory:

      - title — ``_norm_title_exact`` of the raw's frontmatter ``title:`` / H1
      - url   — ``_norm_source_url`` of the raw's ``url:`` frontmatter
      - content-hash — SHA256 of the raw `.md` bytes vs a backing raw's bytes

    NEVER deletes/renames/mutates anything — the owner disposes a flagged
    duplicate manually. The stated limit rides in ``md_duplicate_raws_limit``.
    """
    report.detected["md_duplicate_raws_limit"] = MD_DUPLICATE_LIMIT
    raw_root = wiki_root / "raw"
    if not raw_root.exists():
        report.detected["md_duplicate_raws"] = []
        return
    title_map, url_map, hash_map = _ingested_source_signals(wiki_root)
    backlink_targets, mirror_stems = ingested_raw_filenames(wiki_root)
    findings: list[dict[str, str]] = []
    for origin_dir in sorted(
        p for p in raw_root.iterdir()
        if p.is_dir() and p.name != "assets" and not excluded_dir(p.relative_to(wiki_root))
    ):
        origin_stems = mirror_stems.get(origin_dir.name, set())
        for raw_file in sorted(origin_dir.glob("*.md")):
            if raw_file.name == f"{origin_dir.name}.md" or raw_file.name in NON_SOURCE_FILES:
                continue
            # Skip a raw that is ALREADY ingested (it is not a duplicate of
            # itself) — same union signal heal_raw_wiki_cells keys on.
            if raw_file.name in backlink_targets or raw_file.stem in origin_stems:
                continue
            try:
                text = read_text(raw_file)
            except (UnicodeDecodeError, OSError):
                continue  # undecodable raw `.md` — cannot signal-compare, never crash
            fm = frontmatter(text)
            rel = str(raw_file.relative_to(wiki_root)).replace("\\", "/")
            # content-hash — byte-identical to a backing raw of an ingested source.
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if digest in hash_map and hash_map[digest] != rel:
                findings.append(
                    {"raw": rel, "signal": "content-hash", "matches": hash_map[digest]}
                )
                continue  # one finding per raw; content-hash is the strongest
            # url — exact normalized-URL match.
            nurl = _norm_source_url(fm.get("url", ""))
            if nurl and nurl in url_map:
                findings.append(
                    {"raw": rel, "signal": "url", "matches": url_map[nurl]}
                )
                continue
            # title — exact normalized-title match.
            ntitle = _norm_title_exact(fm.get("title", "") or first_h1(text))
            if ntitle and ntitle in title_map:
                findings.append(
                    {"raw": rel, "signal": "title", "matches": title_map[ntitle]}
                )
                continue
    report.detected["md_duplicate_raws"] = findings


def rename_referrer_files(wiki_root: Path) -> list[Path]:
    """Rewrite scope per Defect-4 fix: wiki/**, logs/**, raw INDEX files only."""
    files: list[Path] = []
    wiki_dir = wiki_root / "wiki"
    if wiki_dir.exists():
        files.extend(
            p for p in wiki_dir.rglob("*.md")
            if p.name not in NON_SOURCE_FILES and not excluded_dir(p.relative_to(wiki_root))
        )
    logs_dir = wiki_root / "logs"
    if logs_dir.exists():
        files.extend(sorted(logs_dir.glob("*.md")))
    raw_root = wiki_root / "raw"
    if raw_root.exists():
        for origin_dir in raw_root.iterdir():
            if origin_dir.is_dir() and not excluded_dir(origin_dir.relative_to(wiki_root)):
                index_path = origin_dir / f"{origin_dir.name}.md"
                if index_path.exists():
                    files.append(index_path)
    return files


def execute_renames(wiki_root: Path, plan_path: Path, report: Report) -> None:
    plan = json.loads(read_text(plan_path))
    rewritten: list[str] = []
    moved: list[str] = []
    skipped_url_mentions: list[str] = []
    errors: list[str] = []
    for row in plan:
        origin, old, new = row["origin"], row["old_stem"], row["new_stem"]
        raw_old = wiki_root / "raw" / origin / f"{old}.pdf"
        raw_new = wiki_root / "raw" / origin / f"{new}.pdf"
        source_old = wiki_root / "wiki" / "sources" / origin / f"{old}.md"
        source_new = wiki_root / "wiki" / "sources" / origin / f"{new}.md"
        if not raw_old.exists():
            errors.append(f"{origin}/{old}.pdf: raw file missing — row skipped")
            continue
        if raw_new.exists() or (source_old.exists() and source_new.exists()):
            errors.append(f"{origin}/{old}.pdf: target name taken (duplicate-raw contract) — row skipped")
            continue
        for path in rename_referrer_files(wiki_root):
            text = read_text(path)  # re-read immediately before writing (pitfall 6)
            updated = text.replace(f"[[{old}.pdf", f"[[{new}.pdf").replace(f"[[{old}.md", f"[[{new}.md")
            if updated != text:
                write_text(path, updated, report, apply_changes=True)
                rewritten.append(str(path.relative_to(wiki_root)).replace("\\", "/"))
        os.replace(_fspath(raw_old), _fspath(raw_new))
        moved.append(f"raw/{origin}/{old}.pdf -> {new}.pdf")
        if source_old.exists():
            os.replace(_fspath(source_old), _fspath(source_new))
            moved.append(f"wiki/sources/{origin}/{old}.md -> {new}.md")
        # Verify: remaining old-stem occurrences must be legitimate (URLs, raw bodies)
        for path in (wiki_root / "wiki").rglob("*.md") if (wiki_root / "wiki").exists() else []:
            if excluded_dir(path.relative_to(wiki_root)):
                continue
            for line in read_text(path).splitlines():
                if old in line:
                    bucket = skipped_url_mentions if "http" in line else errors
                    bucket.append(f"{path.relative_to(wiki_root)}: {line.strip()[:160]}")
    report.detected["renames"] = {
        "rewritten_files": sorted(set(rewritten)),
        "moved": moved,
        "skipped_url_mentions": skipped_url_mentions,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# C5 — subdivision executor (user-gated)
# ---------------------------------------------------------------------------


def execute_subdivision(wiki_root: Path, plan_path: Path, report: Report) -> None:
    plan = json.loads(read_text(plan_path))
    moved: list[str] = []
    rows_moved = 0
    claude_md_pending: list[dict[str, str]] = []
    errors: list[str] = []
    today_str = today().isoformat()
    for row in plan:
        type_folder, slug, subfolder = row["type_folder"], row["slug"], row["target_subfolder"]
        type_dir = wiki_root / "wiki" / type_folder
        src = type_dir / f"{slug}.md"
        dst_dir = type_dir / subfolder
        dst = dst_dir / f"{slug}.md"
        if not src.exists():
            errors.append(f"{type_folder}/{slug}.md: source missing — row skipped")
            continue
        if dst.exists():
            errors.append(f"{type_folder}/{subfolder}/{slug}.md: target exists — row skipped")
            continue
        text = read_text(src)
        kind = frontmatter(text).get("kind", "")
        text = re.sub(r"^last-touched:.*$", f"last-touched: {today_str}", text, count=1, flags=re.M)
        os.makedirs(_fspath(dst_dir), exist_ok=True)
        with open(_fspath(dst), "w", encoding="utf-8") as handle:
            handle.write(text)
        os.remove(_fspath(src))
        moved.append(f"{type_folder}/{slug}.md -> {type_folder}/{subfolder}/{slug}.md")

        # Index row surgery — key on the `| [[{slug}.md]] |` prefix only (pitfall 8)
        parent_index = type_dir / f"{type_folder}.md"
        row_line: str | None = None
        if parent_index.exists():
            lines = read_text(parent_index).splitlines()  # re-read before write (pitfall 6)
            kept: list[str] = []
            for line in lines:
                if row_line is None and line.strip().startswith(f"| [[{slug}.md]]"):
                    row_line = line
                else:
                    kept.append(line)
            if row_line is not None:
                write_text(parent_index, "\n".join(kept) + "\n", report, apply_changes=True)
        leaf_index = dst_dir / f"{subfolder}.md"
        if row_line is not None:
            leaf_text = (
                read_text(leaf_index)
                if leaf_index.exists()
                else LEAF_INDEX_FRONTMATTER + f"# {subfolder}\n\n" + CONCEPT_HEADER
            )
            if not leaf_text.endswith("\n"):
                leaf_text += "\n"
            write_text(leaf_index, leaf_text + row_line + "\n", report, apply_changes=True)
            rows_moved += 1
        else:
            report.judgment_needed.append(
                {
                    "index": str(leaf_index),
                    "file": str(dst),
                    "cell": "Description",
                    "reason": "moved page had no parent-index row; leaf row needs LLM judgment",
                }
            )
        # Router `## Subfolders` table: insert the subfolder row (alphabetical)
        # when the parent is already a router; a first-time router rewrite is
        # judgment content and stays with the agent.
        if parent_index.exists():
            router_text = read_text(parent_index)
            if f"[[{subfolder}]]" not in router_text and "## Subfolders" in router_text:
                new_row = f"| [[{subfolder}]] | `kind: {kind}` | [[{subfolder}.md]] |"
                lines = router_text.splitlines()
                section_rows: list[int] = []
                in_section = False
                for i, line in enumerate(lines):
                    if line.startswith("## "):
                        in_section = line.strip() == "## Subfolders"
                    elif in_section and re.match(r"^\|\s*\[\[", line):
                        section_rows.append(i)
                if section_rows:
                    insert_at = next(
                        (i for i in section_rows if lines[i] > new_row), section_rows[-1] + 1
                    )
                    lines.insert(insert_at, new_row)
                    router_text = "\n".join(lines) + ("\n" if not router_text.endswith("\n") else "")
                    router_text = re.sub(
                        r"^last-touched:.*$", f"last-touched: {today_str}", router_text, count=1, flags=re.M
                    )
                    write_text(parent_index, router_text, report, apply_changes=True)
            elif "## Subfolders" not in router_text:
                errors.append(
                    f"{type_folder}/{type_folder}.md: not in router format — agent must rewrite it as a router"
                )
        claude_md_pending.append(
            {
                "file": str(type_dir / "CLAUDE.md"),
                "row": f"| `{subfolder}/` | `{kind}` | — |",
            }
        )
    report.detected["subdivision"] = {
        "moved": moved,
        "rows_moved": rows_moved,
        "claude_md_pending": claude_md_pending,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# C6 — broken-link bucket-A fix executor (user-gated)
# ---------------------------------------------------------------------------


def execute_link_fixes(wiki_root: Path, plan_path: Path, report: Report) -> None:
    """Rewrite accepted bucket-A wikilink fixes. USER-GATED (step 9 accept).

    Plan rows `{file, old, new}` — `file` is wiki-root-relative, `old`/`new`
    are exact filenames (e.g. `Foo.md`). Rewrites `[[old…]]` -> `[[new…]]`
    preserving any `#anchor`/`|alias` tail and the embed `!` prefix. Scoped to
    `wiki/**` only — NEVER edits `raw/` (raw-immutability contract).
    """
    plan = json.loads(read_text(plan_path))
    rewritten: list[dict[str, object]] = []
    skipped: list[str] = []
    errors: list[str] = []
    for row in plan:
        file_rel, old, new = row["file"], row["old"], row["new"]
        parts = Path(file_rel).parts
        if not parts or parts[0] != "wiki" or ".." in parts:
            errors.append(f"{file_rel}: outside wiki/ scope — row skipped")
            continue
        page = wiki_root / file_rel
        if excluded_dir(page.relative_to(wiki_root)):
            errors.append(f"{file_rel}: excluded path — row skipped")
            continue
        if not os.path.exists(_fspath(page)):
            errors.append(f"{file_rel}: file missing — row skipped")
            continue
        text = read_text(page)  # re-read immediately before writing (pitfall 6)
        pattern = re.compile(
            r"(!?\[\[)" + re.escape(old) + r"((?:#[^\]|]*)?(?:\|[^\]]*)?\]\])"
        )
        updated, count = pattern.subn(lambda m: m.group(1) + new + m.group(2), text)
        if count == 0:
            skipped.append(f"{file_rel}: [[{old}]] not found")
            continue
        write_text(page, updated, report, apply_changes=True)
        rewritten.append({"file": file_rel, "old": old, "new": new, "count": count})
    report.detected["link_fixes"] = {
        "rewritten": rewritten,
        "skipped": skipped,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# U3 Stage-2 — human-gated `update-links` sub-mode (append-only apply)
# ---------------------------------------------------------------------------
# Reads accepted missing-link proposals and appends `[[target.md]]` to the
# source page's `related:` frontmatter (append-only) PLUS the reverse link
# `[[source.md]]` to the target page's `related:`. NEVER auto-links: this runs
# ONLY when the lint Step-9 `update-links` handler invokes it on an explicit
# owner accept (mirrors `--execute-link-fixes`). Append-only — it adds list
# items to an existing-or-created `related:` block and touches nothing else.

def append_related_link(text: str, link_name: str) -> tuple[str, bool]:
    """Append `- "[[link_name]]"` to a page's `related:` frontmatter, append-only.

    Returns (new_text, changed). Idempotent: if the target is already present in
    `related:` (any quote/`.md` form), returns unchanged. Handles three shapes:
    a block list (`related:\n  - "[[x.md]]"`), an inline-empty list
    (`related: []`), and a missing `related:` key (inserts a block before the
    closing frontmatter `---`). Never edits body or any other field.
    """
    fm_match = re.match(r"^(---\s*\n)(.*?)(\n---\s*\n)", text, flags=re.S)
    if not fm_match:
        return text, False
    head, fm_body, tail = fm_match.group(1), fm_match.group(2), fm_match.group(3)
    rest = text[fm_match.end():]
    item = f'  - "[[{link_name}]]"'

    # Idempotence: already linked in related: -> no-op.
    rel_block_match = re.search(r"^related:\s*(.*)$", fm_body, flags=re.M)
    existing_targets: set[str] = set()
    for tgt in re.findall(r"\[\[([^\]|#]+?\.md)", fm_body):
        existing_targets.add(Path(tgt.strip()).name)
    if link_name in existing_targets:
        return text, False

    lines = fm_body.split("\n")
    if rel_block_match is None:
        # No related: key — insert a fresh block at the end of frontmatter.
        new_fm = fm_body.rstrip("\n") + f"\nrelated:\n{item}"
        return head + new_fm + tail + rest, True

    # Locate the related: line and its (possibly empty) item block.
    rel_idx = None
    for i, ln in enumerate(lines):
        if re.match(r"^related:\s*(.*)$", ln):
            rel_idx = i
            break
    rel_line = lines[rel_idx]
    inline = re.match(r"^related:\s*(\S.*)$", rel_line)
    if inline and inline.group(1).strip() in ("[]", "[ ]"):
        # related: [] -> convert to a block list with the new item.
        lines[rel_idx] = "related:"
        lines.insert(rel_idx + 1, item)
        return head + "\n".join(lines) + tail + rest, True
    # Block list: find the end of the existing `  - ` item run after rel_idx.
    insert_at = rel_idx + 1
    while insert_at < len(lines) and re.match(r"^\s*-\s", lines[insert_at]):
        insert_at += 1
    lines.insert(insert_at, item)
    return head + "\n".join(lines) + tail + rest, True


def update_missing_links(wiki_root: Path, plan_path: Path, report: Report) -> None:
    """Apply accepted missing-link proposals. USER-GATED (lint step 9 accept).

    Plan rows `{source, target}` — `source` wiki-root-relative path of the page
    that mentions the target; `target` the bare `target.md` filename. For each
    accepted row: append `[[target]]` to the source's `related:` (forward link)
    AND `[[source.md]]` to the target's `related:` (reverse link). Append-only;
    idempotent; never auto-links (only fires on an explicit owner accept).
    """
    plan = json.loads(read_text(plan_path))
    applied: list[dict[str, object]] = []
    skipped: list[str] = []
    errors: list[str] = []
    for row in plan:
        source_rel, target_name = row["source"], Path(row["target"]).name
        sparts = Path(source_rel).parts
        if not sparts or sparts[0] != "wiki" or ".." in sparts:
            errors.append(f"{source_rel}: outside wiki/ scope — row skipped")
            continue
        source_page = wiki_root / source_rel
        if not os.path.exists(_fspath(source_page)):
            errors.append(f"{source_rel}: source file missing — row skipped")
            continue
        # Resolve the target page by bare filename anywhere under wiki/ (excl. assets).
        target_matches = [
            p for p in (wiki_root / "wiki").rglob(target_name)
            if not excluded_dir(p.relative_to(wiki_root))
        ]
        if not target_matches:
            errors.append(f"{target_name}: target page not found under wiki/ — row skipped")
            continue
        if len(target_matches) > 1:
            errors.append(f"{target_name}: ambiguous ({len(target_matches)} matches) — row skipped")
            continue
        target_page = target_matches[0]
        if target_page.resolve() == source_page.resolve():
            errors.append(f"{source_rel}: self-link refused — row skipped")
            continue
        source_name = source_page.name

        # Forward: append [[target]] to source.related (re-read immediately).
        s_text = read_text(source_page)
        s_new, s_changed = append_related_link(s_text, target_name)
        # Reverse: append [[source]] to target.related.
        t_text = read_text(target_page)
        t_new, t_changed = append_related_link(t_text, source_name)

        if not s_changed and not t_changed:
            skipped.append(f"{source_rel} <-> {target_name}: both directions already linked")
            continue
        if s_changed:
            write_text(source_page, s_new, report, apply_changes=True)
        if t_changed:
            write_text(target_page, t_new, report, apply_changes=True)
        applied.append(
            {
                "source": source_rel,
                "target": target_name,
                "forward_added": s_changed,
                "reverse_added": t_changed,
            }
        )
    report.detected["missing_link_updates"] = {
        "applied": applied,
        "skipped": skipped,
        "errors": errors,
    }


def cmd_update_links(args_list: list[str]) -> int:
    """`update-links` sub-command — Stage-2 human-gated apply of accepted
    missing-link proposals. Invoked ONLY by the lint Step-9 update-links handler
    after an explicit owner accept. NEVER part of the read-mostly detection pass.
    """
    parser = argparse.ArgumentParser(
        description="Apply accepted missing-link proposals (append-only, owner-gated)."
    )
    parser.add_argument("--vault-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--plan", type=Path, required=True,
        metavar="PLAN_JSON",
        help="JSON list of accepted rows {source, target} from the missing-links report",
    )
    args = parser.parse_args(args_list)
    wiki_root = resolve_wiki_root(args.vault_root.resolve())
    report = Report(mode="execute")
    update_missing_links(wiki_root, args.plan, report)
    print(json.dumps(report.detected["missing_link_updates"], indent=2, ensure_ascii=False))
    return 0


def extract_topic_open_questions(text: str) -> list[str]:
    """Extract non-struck ``Open questions`` lines from a topic page.

    Returns the verbatim question text (list marker stripped) for every
    line under ``## Open questions`` that starts with ``- `` and does NOT
    contain struck markers (``~~``).
    """
    body = body_after_frontmatter(text)
    sections = split_h2_sections(body)
    open_qs_body = sections.get("Open questions", "")
    questions: list[str] = []
    for line in open_qs_body.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") and "~~" not in stripped:
            questions.append(stripped[2:].strip())
    return questions


_QUESTION_H2_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\]\s*(.+)$")


def parse_questions_md_entries(text: str) -> tuple[list[dict], list[str]]:
    """Parse ``questions.md`` into entries and warnings.

    Returns ``(entries, warnings)``.  An entry is ``open`` when it has no
    ``answer:`` block or zero ``answer:`` bullets.  Warnings name malformed
    entries (heading without ``[YYYY-MM-DD]`` prefix).
    """
    entries: list[dict] = []
    warnings: list[str] = []
    h2_pattern = re.compile(r"^##\s+(.+?)\s*$", re.M)
    matches = list(h2_pattern.finditer(text))

    for i, match in enumerate(matches):
        heading = match.group(1)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]

        date_match = _QUESTION_H2_RE.match(heading)
        if not date_match:
            warnings.append(f"Malformed entry (no [YYYY-MM-DD] prefix): {heading[:120]}")
            continue

        entry: dict = {
            "heading": heading,
            "date": date_match.group(1),
            "question": date_match.group(2).strip(),
            "relates": [],
            "seeded_by": None,
            "answer_bullets": [],
            "is_open": True,
        }

        # relates: block (0..n quoted wikilinks)
        relates_match = re.search(
            r"^relates:\s*\n((?:[ \t]*-[ \t]*\"?\[\[.+?\]\]\"?[ \t]*\n?)*)",
            body, re.M,
        )
        if relates_match:
            for line in relates_match.group(1).splitlines():
                for link in re.findall(r'\[\[([^\]]+?)\]\]', line):
                    entry["relates"].append(link)

        # seeded-by: single quoted wikilink
        seeded_match = re.search(r'^seeded-by:\s*"?\[\[([^\]]+?)\]\]"?', body, re.M)
        if seeded_match:
            entry["seeded_by"] = seeded_match.group(1)

        # answer: block — count bullets
        answer_match = re.search(
            r"^answer:\s*\n((?:[ \t]*-[ \t]*[^\n]*\n?)*)", body, re.M
        )
        if answer_match:
            bullets: list[str] = []
            for line in answer_match.group(1).splitlines():
                bullet_match = re.match(r"^[ \t]*-[ \t]*(.*)$", line)
                if bullet_match:
                    bullets.append(bullet_match.group(1).strip())
            entry["answer_bullets"] = bullets
            entry["is_open"] = len(bullets) == 0
        else:
            entry["is_open"] = True

        entries.append(entry)

    return entries, warnings


def cmd_open_gaps(args_list: list[str]) -> int:
    """Emit the ``open-gaps`` aggregate (Step 8.5).

    Gathers topic-home open-questions plus ``questions.md`` open entries
    and emits the lint-standard markdown aggregate.  When the questions
    layer is OFF and no topic has open questions, emits the defined empty
    state (both sections show ``_No open questions._``).
    """
    parser = argparse.ArgumentParser(description="Emit the open-gaps aggregate.")
    parser.add_argument("--vault-root", type=Path, default=Path.cwd())
    args = parser.parse_args(args_list)
    wiki_root = resolve_wiki_root(args.vault_root.resolve())

    topic_rows: list[tuple[str, str]] = []  # (question_text, stem)
    topics_dir = wiki_root / "wiki" / "topics"
    if topics_dir.exists():
        for page in sorted(topics_dir.glob("*.md")):
            if page.name == "topics.md":
                continue
            text = read_text(page)
            for q in extract_topic_open_questions(text):
                topic_rows.append((q, page.stem))

    md_entries: list[dict] = []
    md_warnings: list[str] = []
    questions_path = wiki_root / "questions.md"
    questions_layer_on = questions_path.exists()
    if questions_layer_on:
        entries, warnings = parse_questions_md_entries(read_text(questions_path))
        md_warnings.extend(warnings)
        md_entries = [e for e in entries if e["is_open"]]

    today_str = today().isoformat()
    lines = [
        "---",
        "type: questions-index",
        f"last-touched: {today_str}",
        "---",
        "",
        "# Open gaps",
        "",
        "> Lint-generated, READ-ONLY — regenerated in full on every `/sb-wiki-lint` run. Do NOT hand-edit; edits are overwritten. Aggregates every OPEN question across both homes (topic pages + `questions.md`). Resolve a question in its home; it drops off this view on the next lint.",
        "",
        f"## Topic-home open questions ({len(topic_rows)})",
        "",
        "| Question | Topic |",
        "|----------|-------|",
    ]
    for q_text, stem in topic_rows:
        safe = q_text.replace("|", "\\|")
        lines.append(f"| {safe} | [[{stem}.md]] |")
    if not topic_rows:
        lines.append("_No open questions._")

    lines.extend([
        "",
        f"## `questions.md` open questions ({len(md_entries)})",
        "",
        "| Question | Home | Relates |",
        "|----------|------|---------|",
    ])
    for entry in md_entries:
        safe_heading = entry["heading"].replace("|", "\\|")
        relates_str = ", ".join(f"[[{r}]]" for r in entry["relates"]) if entry["relates"] else "—"
        lines.append(f"| {safe_heading} | [[questions.md]] | {relates_str} |")
    if not md_entries:
        lines.append("_No open questions._")

    output = "\n".join(lines) + "\n"
    print(output, end="")
    for w in md_warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    return 0


def cmd_sweep_gather(args_list: list[str]) -> int:
    """Emit the substantive open-questions collection (Step 7.7a).

    Gathers every open question from both homes and emits a JSON object.
    The ``questions`` array carries the question text, home, and source
    path so the sweep's match judgment (LLM or hybrid search) can run
    over it.
    """
    parser = argparse.ArgumentParser(description="Emit the open-questions collection for answer-sweep.")
    parser.add_argument("--vault-root", type=Path, default=Path.cwd())
    args = parser.parse_args(args_list)
    wiki_root = resolve_wiki_root(args.vault_root.resolve())

    results: list[dict] = []
    warnings: list[str] = []

    topics_dir = wiki_root / "wiki" / "topics"
    if topics_dir.exists():
        for page in sorted(topics_dir.glob("*.md")):
            if page.name == "topics.md":
                continue
            text = read_text(page)
            for q in extract_topic_open_questions(text):
                rel = str(page.relative_to(wiki_root)).replace("\\", "/")
                results.append({
                    "home": "topic",
                    "question": q,
                    "source": rel,
                })

    questions_path = wiki_root / "questions.md"
    if questions_path.exists():
        entries, w = parse_questions_md_entries(read_text(questions_path))
        warnings.extend(w)
        for entry in entries:
            if entry["is_open"]:
                results.append({
                    "home": "questions.md",
                    "question": entry["question"],
                    "heading": entry["heading"],
                    "source": "questions.md",
                    "relates": entry["relates"],
                })

    payload = {
        "questions": results,
        "warnings": warnings,
        "count": len(results),
    }
    output = json.dumps(payload, indent=2, ensure_ascii=False)
    print(output)
    return 0


def cmd_update_backfill_gather(args_list: list[str]) -> int:
    """Retroactive backfill gather — firm sweep + tier-gated semantic probe loop.

    Read-only, stateless subcommand (mirrors open-gaps / sweep-gather).
    Evaluates every source page against current topic pages:
    (a) firm-mechanical corpus sweep (slug match + grep wikilink overlap),
    (b) per-source semantic probes via the search helper (--type topic --k 5),
    (c) citation-dedupe + rejected-ledger suppression.

    Emits JSON: candidate pairs + signals + counts + tier availability.
    Writes nothing — the LLM confirmation bar and proposal-set drafting
    happen in the /sb-wiki-update-backfill command (scan mode).
    """
    parser = argparse.ArgumentParser(
        description="Retroactive backfill gather — firm + semantic candidate pairs."
    )
    parser.add_argument("--vault-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON to this file instead of stdout.",
    )
    parser.add_argument(
        "--skip-semantic",
        action="store_true",
        help="Firm-only gather — skip the per-source semantic probe loop. Use for "
             "cheap incremental testing or when Voyage is intentionally not consulted.",
    )
    parser.add_argument(
        "--weak-threshold",
        type=int,
        default=FIRM_RELEVANCE_WEAK_T,
        help="Firm-match relevance: a firm row is flagged `weak` (hub-concept, "
             "advisory) when its rarest shared concept appears in >= this many "
             f"source pages. Default {FIRM_RELEVANCE_WEAK_T} (p75 calibration, "
             "2026-06-10 run). NEVER drops a row — total-coverage invariant.",
    )
    args = parser.parse_args(args_list)
    wiki_root = resolve_wiki_root(args.vault_root.resolve())

    # --- Check semantic tier availability ---
    # --skip-semantic forces the firm-only path regardless of tier readiness.
    tier_available = False if args.skip_semantic else _check_search_tier(wiki_root)

    # --- Load rejected ledger ---
    rejected_pairs: set[tuple[str, str]] = set()
    pending_file = wiki_root / "pending-topic-updates.md"
    if pending_file.exists():
        rejected_pairs = _parse_rejected_ledger(read_text(pending_file))

    # --- Load citation map (topic -> set of cited source filenames) ---
    citation_map: dict[str, set[str]] = _build_topic_citation_map(wiki_root)

    # --- Enumerate topic pages (the firm sweep reads each matched page on demand;
    #     the semantic confirmation bar is the LLM's job in scan mode, so the
    #     gather needs no Scope cache here) ---
    topics_dir = wiki_root / "wiki" / "topics"
    topic_pages: list[Path] = []
    if topics_dir.exists():
        for page in sorted(topics_dir.glob("*.md")):
            if page.name == "topics.md":
                continue
            topic_pages.append(page)

    # --- Build source pages list ---
    sources_root = wiki_root / "wiki" / "sources"
    source_pages: list[Path] = []
    if sources_root.exists():
        for origin_dir in sorted(p for p in sources_root.iterdir() if p.is_dir()):
            for src in sorted(origin_dir.glob("*.md")):
                if src.name == f"{origin_dir.name}.md":
                    continue
                source_pages.append(src)

    # --- Firm-mechanical sweep ---
    # Detection matches the forward firm-tier authority EXACTLY (schema §
    # "Existing topic updates" Firm tier; ingest Step 3·7 match table) — the
    # backfill never forks a second confidence bar. The three (and only three)
    # firm match types:
    #   (1) slug-match              — topic slug in the source title OR a Substance bullet
    #   (2) key-concept-overlap     — Substance wikilink ∩ topic's Key concepts/Key entities links
    #   (3) related-frontmatter-overlap — Substance wikilink ∩ topic's related: frontmatter links
    # Wikilinks anywhere ELSE on the topic page (Sources, Timeline, prose) are
    # grep false-positives the forward authority DROPS — there is no bare
    # "wikilink-overlap" arm. Iterate sorted slugs for deterministic row order.
    firm_candidates: list[dict] = []
    topic_slugs_sorted: list[str] = sorted(p.stem for p in topic_pages)

    # Relevance-scoring caches, accumulated DURING the firm sweep (no second
    # corpus walk). `src_df` counts SOURCE document frequency for every concept
    # any source's `## Substance` wikilinks — across ALL source pages, including
    # sources that produce no firm candidate (the sweep visits every source, so
    # the count is corpus-complete). `src_substance_links` / `topic_key_links`
    # cache the exact link sets a firm row's overlap is recomputed from. Links
    # are stored normalized (lowercased, `.md`-stripped) so DF counting and
    # overlap are stable under case/extension drift. See `_compute_firm_relevance`.
    src_df: Counter = Counter()
    src_substance_links: dict[str, set[str]] = {}
    topic_key_links: dict[str, set[str]] = {}

    for src_page in source_pages:
        src_text = read_text(src_page)
        src_fm = frontmatter(src_text)
        src_title = src_fm.get("title", "") or first_h1(src_text)
        src_rel = str(src_page.relative_to(wiki_root)).replace("\\", "/")
        src_filename = src_page.name

        substance = section_body(src_text, "Substance")
        substance_links = set(re.findall(r"\[\[([^\]|]+?\.md)\]\]", substance)) if substance else set()
        substance_text_lower = substance.lower() if substance else ""
        src_title_lower = src_title.lower()

        # Accumulate relevance caches (once per source). Normalize links so the
        # DF map and per-row overlap are computed in one canonical space.
        substance_links_norm = {_norm_link(l) for l in substance_links}
        src_substance_links[src_rel] = substance_links_norm
        for link in substance_links_norm:
            src_df[link] += 1

        for topic_stem in topic_slugs_sorted:
            # Citation-dedupe applies to ALL tiers (spec row 6 names it in the
            # gather chain): if the topic page already cites this source, the
            # information is already there — suppress before any match work.
            if src_filename in citation_map.get(topic_stem, set()):
                continue

            match_types: list[str] = []
            # (1) Slug match
            if topic_stem.lower() in src_title_lower or topic_stem.lower() in substance_text_lower:
                match_types.append("slug-match")

            # (2)/(3) Wikilink overlap — ONLY against qualifying locations
            # (Key concepts/Key entities sections and related: frontmatter),
            # never the whole page body. Mirrors the forward authority's
            # "drop wikilink hits outside the qualifying locations".
            if substance_links:
                topic_path = topics_dir / f"{topic_stem}.md"
                if topic_path.exists():
                    topic_text = read_text(topic_path)
                    topic_fm = frontmatter(topic_text)
                    related_links = _parse_related_frontmatter(topic_fm)
                    key_sections = _extract_key_section_links(topic_text)
                    # Cache the normalized Key-section links for relevance
                    # recompute (related: links are NOT scored — relevance is a
                    # key-concept-overlap signal, matching the reference).
                    if topic_stem not in topic_key_links:
                        topic_key_links[topic_stem] = {_norm_link(l) for l in key_sections}
                    if substance_links & key_sections:
                        match_types.append("key-concept-overlap")
                    if substance_links & related_links:
                        match_types.append("related-frontmatter-overlap")

            if match_types:
                firm_candidates.append({
                    "source": src_rel,
                    "source_title": src_title,
                    "topic": f"{topic_stem}.md",
                    "signal": "firm:" + ",".join(match_types),
                    "match_types": match_types,
                })

    # --- Firm-match relevance (advisory; never drops a row) ---
    # Recompute each firm row's overlap concept(s) and score by source DF. The
    # `Match`/`Rel` columns + strongest->weakest sort the artifact assembler
    # renders read from this `relevance` field. WEAK_T is the `--weak-threshold`.
    _compute_firm_relevance(
        firm_candidates, src_df, src_substance_links, topic_key_links,
        weak_t=args.weak_threshold,
    )
    weak_firm = sum(1 for c in firm_candidates if c["relevance"]["weak"])

    # --- Semantic probe loop (tier-gated) ---
    semantic_candidates: list[dict] = []
    firm_pairs = {(c["source"], c["topic"]) for c in firm_candidates}

    if tier_available:
        for src_page in source_pages:
            src_text = read_text(src_page)
            src_fm = frontmatter(src_text)
            src_title = src_fm.get("title", "") or first_h1(src_text)
            src_rel = str(src_page.relative_to(wiki_root)).replace("\\", "/")
            substance = section_body(src_text, "Substance")

            # Build substance digest (≤2 sentences)
            digest = _make_substance_digest(substance)
            query = f"{src_title} — {digest}" if digest else src_title

            # Call search helper
            search_result = _call_search_helper(wiki_root, query, k=5, topic_only=True)
            if search_result is None:
                continue

            # Per-source semantic candidates AFTER the dedupe chain. The gather
            # applies NO confirmation bar and NO token pre-filter (D11 + design
            # Q1: the semantic arm carries no token-overlap signal; a deterministic
            # pre-filter would both reintroduce the banned signal and silently drop
            # candidates the LLM never sees). The authorized narrowing here is ONLY
            # the dedupe chain: firm-wins -> rejected-ledger -> citation-dedupe.
            # The LLM confirmation bar (citable factual claim extending topic scope)
            # runs in /sb-wiki-update-backfill scan mode, not here.
            src_filename = src_page.name
            # One probe can return the same topic page multiple times (different
            # chunk anchors). Collapse to one entry per topic, keeping the highest
            # score, BEFORE the cap — so a (source, topic) pair is never emitted
            # twice and the cap counts distinct topics.
            best_by_topic: dict[str, dict] = {}
            for hit in search_result.get("results", []):
                hit_rel = hit.get("path", "")
                hit_stem = Path(hit_rel).stem
                hit_score = hit.get("score", 0)
                topic_key = f"{hit_stem}.md"
                pair = (src_rel, topic_key)

                # Dedupe chain (the only authorized narrowing)
                if pair in firm_pairs:
                    continue  # firm wins
                if pair in rejected_pairs:
                    continue  # rejected ledger
                if src_filename in citation_map.get(hit_stem, set()):
                    continue  # citation-dedupe
                # The topic must still exist as a page (defensive — k-hits should
                # already be topic pages under --type topic).
                if not (topics_dir / f"{hit_stem}.md").exists():
                    continue

                prev = best_by_topic.get(topic_key)
                if prev is None or hit_score > prev["score"]:
                    best_by_topic[topic_key] = {
                        "source": src_rel,
                        "source_title": src_title,
                        "topic": topic_key,
                        "signal": f"semantic:{hit_score}",
                        "score": hit_score,
                    }

            # Cap 2 PER SOURCE, ranked by helper score (descending), tie-broken by
            # topic key for determinism — mirrors the forward per-ingest cap
            # (design Q1 / schema "Semantic tier"): each source's probe is the
            # ingest-equivalent unit, so the per-ingest cap of 2 applies per source
            # here, never a single global cap. Overflow drops silently (re-detected
            # by future ingests or a later backfill).
            src_hits = sorted(
                best_by_topic.values(),
                key=lambda c: (-c["score"], c["topic"]),
            )
            semantic_candidates.extend(src_hits[:2])

    # --- Build output ---
    result = {
        "firm_candidates": firm_candidates,
        "semantic_candidates": semantic_candidates,
        "firm_count": len(firm_candidates),
        "semantic_count": len(semantic_candidates),
        "firm_weak_count": weak_firm,
        "firm_relevance_weak_threshold": args.weak_threshold,
        "total_sources_scanned": len(source_pages),
        "total_topics_evaluated": len(topic_pages),
        "tier_available": tier_available,
        "semantic_skipped": bool(args.skip_semantic),
        "rejected_pairs_suppressed": len(rejected_pairs),
        "note": _gather_note(tier_available, args.skip_semantic),
    }

    output = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    return 0


def _gather_note(tier_available: bool, skip_semantic: bool) -> str:
    """Honest one-line note for the gather output — never claims a confirmation
    bar ran (the LLM applies that in scan mode, not the gather)."""
    base = "Propose-only — no wiki writes. Run /sb-wiki-update-backfill scan for the LLM confirmation bar and proposal-set drafting."
    if skip_semantic:
        return base + " Semantic arm SKIPPED (--skip-semantic): firm-only gather."
    if tier_available:
        return base + " Semantic tier available; candidates emitted post-dedupe, UNconfirmed (LLM confirms in scan mode)."
    return base + " Semantic tier unavailable: firm-only gather (no token fallback, per D11)."


def _check_search_tier(wiki_root: Path) -> bool:
    """Check if the search helper is available and can run.

    `--vault-root` is a GLOBAL option on sb-wiki-search.py — it MUST precede the
    `status` subcommand (argparse rejects it after the subcommand with exit 2).
    The search script resolves wiki_root internally from the VAULT root, so pass
    the vault root, never the wiki root.
    """
    vault_root = wiki_root.parent.parent
    sb_os_path = _resolve_sb_os_path(wiki_root)
    search_script = sb_os_path / "wiki" / "scripts" / "sb-wiki-search.py"
    if not search_script.exists():
        return False
    try:
        result = subprocess.run(
            [sys.executable, str(search_script), "--vault-root", str(vault_root), "status"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15,
        )
        if result.returncode != 0:
            print(
                f"[update-backfill] search-tier probe exited {result.returncode}: "
                f"{result.stderr.strip()}",
                file=sys.stderr,
            )
            return False
        status = json.loads(result.stdout)
        # status emits {"ready": bool, "mode": "hybrid"|"fts-only", ...}.
        # The semantic (vector) tier is ON only in hybrid mode; fts-only means
        # no Voyage embedder — the backfill must run firm-only (D11: no token
        # fallback). "unavailable" is not a real mode value; ready=False covers
        # the no-index case.
        return bool(status.get("ready")) and status.get("mode") == "hybrid"
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as err:
        print(f"[update-backfill] search-tier probe failed: {err}", file=sys.stderr)
        return False


def _resolve_sb_os_path(wiki_root: Path) -> Path:
    """Resolve sb_os_path from sb-os.json at vault root."""
    vault_root = wiki_root.parent.parent  # wiki_root is under vault root
    manifest = json.loads(read_text(vault_root / "sb-os.json"))
    return vault_root / manifest.get("sb_os_path", "3-resources/tools/sb-os")


def _parse_rejected_ledger(text: str) -> set[tuple[str, str]]:
    """Parse the rejected ledger section from pending-topic-updates.md."""
    pairs: set[tuple[str, str]] = set()
    in_ledger = False
    for line in text.splitlines():
        if line.startswith("## Rejected") or line.startswith("## rejected"):
            in_ledger = True
            continue
        if in_ledger and line.startswith("## "):
            in_ledger = False
            continue
        if in_ledger and line.strip().startswith("|") and not line.strip().startswith("|-"):
            cells = split_row_cells(line)
            if len(cells) >= 2:
                source = cells[0].strip().strip("[]")
                topic = cells[1].strip().strip("[]")
                if source and topic:
                    pairs.add((source, topic))
    return pairs


def _build_topic_citation_map(wiki_root: Path) -> dict[str, set[str]]:
    """Build a map of topic stem -> set of cited source filenames."""
    citation_map: dict[str, set[str]] = {}
    topics_dir = wiki_root / "wiki" / "topics"
    if not topics_dir.exists():
        return citation_map
    for page in sorted(topics_dir.glob("*.md")):
        if page.name == "topics.md":
            continue
        text = read_text(page)
        sources_section = section_body(text, "Sources")
        cited: set[str] = set()
        for match in re.findall(r"\[\[([^\]|]+?\.md)\]\]", sources_section):
            cited.add(match)
        # Also scan full text for footnote definitions
        for match in re.findall(r"\[\^\d+\]:\s*\[\[([^\]|]+?\.md)\]\]", text):
            cited.add(match)
        citation_map[page.stem] = cited
    return citation_map


def _parse_related_frontmatter(fm: dict) -> set[str]:
    """Parse related: frontmatter into a set of linked filenames."""
    raw = fm.get("related", "")
    if not raw:
        return set()
    # related: can be a YAML list or inline [...]
    if raw.startswith("["):
        return set(re.findall(r"\[\[([^\]|]+?\.md)\]\]", raw))
    return set()


def _extract_key_section_links(text: str) -> set[str]:
    """Extract wikilinks from a topic's Key concepts / Key entities sections.

    These are the ONLY qualifying locations for the forward firm-tier
    "key-concept/entity overlap" match (schema § "Existing topic updates" Firm
    tier; ingest Step 3·7 match table). `Key positions / Angles` and `Timeline`
    are apply-ROUTING targets in the Update-behavior table, NOT firm-detection
    locations — including them here would fork a looser bar than the forward
    authority, so they are excluded.
    """
    links: set[str] = set()
    for heading in ["Key concepts", "Key entities"]:
        body = section_body(text, heading)
        if body:
            links.update(re.findall(r"\[\[([^\]|]+?\.md)\]\]", body))
    return links


def _make_substance_digest(substance: str | None) -> str:
    """Extract ≤2 sentences from substance as a search digest."""
    if not substance:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", substance.strip())
    return " ".join(sentences[:2])


def _norm_link(link: str) -> str:
    """Normalize a wikilink target for relevance DF counting / overlap.

    Lowercase, strip a trailing `.md`, and fold smart quotes / en/em dashes to
    their ASCII twins so the same concept counts once across case/quote drift
    (mirrors the reference `firm-match-relevance.py` `norm` + the quote fold the
    corpus carries in curly-quote filenames). Pure string op — no I/O.
    """
    s = unicodedata.normalize("NFC", link).strip()
    s = (s.replace("’", "'").replace("‘", "'")
          .replace("“", '"').replace("”", '"')
          .replace("–", "-").replace("—", "-"))
    return s.lower().removesuffix(".md")


def _compute_firm_relevance(
    firm_candidates: list[dict],
    src_df: "Counter",
    src_substance_links: dict[str, set[str]],
    topic_key_links: dict[str, set[str]],
    weak_t: int,
) -> None:
    """Annotate each firm candidate IN PLACE with a `relevance` field.

    A firm row fires because the source's `## Substance` wikilinks a concept the
    topic lists in `## Key concepts` / `## Key entities`. Score each row by the
    SOURCE DOCUMENT FREQUENCY of its overlap concept(s) — a match on a hub
    concept (appears in many sources) is incidental; a match on a rare,
    topic-specific concept is strong:

        overlap   = source.substance_links ∩ topic.key_section_links
        min_df    = min(src_df[c] for c in overlap)     # rarest shared concept's DF
        best      = the overlap concept with that min DF (the `Match` concept)
        weak      = min_df >= weak_t                     # rarest shared still common

    ADVISORY ONLY — never drops a row (total-coverage invariant). Each annotation
    carries everything the artifact assembler needs for the `Match`/`Rel` columns
    and the strongest->weakest sort: the `Match` concept, its DF, the full
    overlap set, the `min_df` sort key, and the `weak` flag. A firm row with NO
    recomputed overlap (a pure slug-match row, or a related-frontmatter-only row)
    has no key-concept signal to score: it gets `overlap: []`, `min_df: None`,
    `weak: False` (an unscored row is NEVER auto-weak), and sorts LAST within its
    topic (treated as min_df = +inf by the assembler's documented sort rule).
    """
    for cand in firm_candidates:
        sub_links = src_substance_links.get(cand["source"], set())
        key_links = topic_key_links.get(Path(cand["topic"]).stem, set())
        overlap = sorted(sub_links & key_links)
        if overlap:
            best = min(overlap, key=lambda c: src_df.get(c, 0))
            min_df = src_df.get(best, 0)
            weak = min_df >= weak_t
            cand["relevance"] = {
                "overlap": overlap,
                "match_concept": best,
                "match_df": min_df,
                "min_df": min_df,
                "weak": weak,
            }
        else:
            # No key-concept overlap to score (slug-only / related-only row).
            cand["relevance"] = {
                "overlap": [],
                "match_concept": None,
                "match_df": None,
                "min_df": None,
                "weak": False,
            }


def _call_search_helper(wiki_root: Path, query: str, k: int = 5, topic_only: bool = False) -> dict | None:
    """Call the search helper for a semantic probe.

    `--vault-root` is a GLOBAL option — it MUST precede the `search` subcommand
    (argparse rejects it after the subcommand). `--k`, `--type`, and `--json` are
    subcommand options and follow the query.
    """
    vault_root = wiki_root.parent.parent
    sb_os_path = _resolve_sb_os_path(wiki_root)
    search_script = sb_os_path / "wiki" / "scripts" / "sb-wiki-search.py"
    if not search_script.exists():
        return None
    cmd = [
        sys.executable, str(search_script),
        "--vault-root", str(vault_root),
        "search", query,
        "--k", str(k), "--json", "--no-sync",
        # --no-rerank: the gather harvests by top-k MEMBERSHIP (cap 2/source)
        # and the LLM confirmation bar supplies precision, so the rerank
        # stage's precision reordering only costs harvest recall here
        # (p4-11 pilot: confirmed-class candidates inside the cap-2 window
        # fell 81/95 -> 75/95 under rerank). Rerank stays default-on for
        # every other search consumer.
        "--no-rerank",
    ]
    if topic_only:
        cmd.extend(["--type", "topic"])
    try:
        # Force UTF-8 decode: the search script emits UTF-8 (ensure_ascii=False),
        # but subprocess defaults to the locale codec (cp1252 on Windows), which
        # crashes the stdout reader on smart quotes / accented chars.
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        if result.returncode != 0:
            print(
                f"[update-backfill] semantic probe exited {result.returncode}: "
                f"{result.stderr.strip()}",
                file=sys.stderr,
            )
            return None
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as err:
        print(f"[update-backfill] semantic probe failed: {err}", file=sys.stderr)
        return None


def resolve_wiki_root(vault_root: Path) -> Path:
    manifest = json.loads(read_text(vault_root / "sb-os.json"))
    return vault_root / manifest["wiki_root"]


def _parse_artifact_pending_pairs(text: str) -> set[tuple[str, str]]:
    """Parse drafted (source, topic) pairs from a pending-topic-updates.md table.

    Reads ONLY the `## Pending topic updates` section's table rows (stops at the
    next `##` heading — the rejected ledger is a different section with a
    different shape). A pending row is `| source page | target topic | signal |
    ...`. The source/topic cells are folded with `_norm_link`-equivalent
    normalization for stable matching against the gather's pair set (smart-quote
    / case / `.md` drift). Returns the set of (folded source-rel, folded
    topic-name) pairs. Code-fence backticks around a cell are stripped.
    """
    pairs: set[tuple[str, str]] = set()
    in_pending = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("##"):
            in_pending = stripped.lower().startswith("## pending topic updates")
            continue
        if not in_pending or not stripped.startswith("|"):
            continue
        cells = [c.strip().strip("`").strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        src, topic = cells[0], cells[1]
        if not src or src.lower() in ("source page", "---") or set(src) <= {"-"}:
            continue  # header / separator row
        pairs.add((_norm_pair_cell(src), _norm_pair_cell(topic)))
    return pairs


def _norm_pair_cell(cell: str) -> str:
    """Normalize a source/topic cell for pair identity (case/quote/dash fold)."""
    s = unicodedata.normalize("NFC", cell).strip()
    s = (s.replace("’", "'").replace("‘", "'")
          .replace("“", '"').replace("”", '"')
          .replace("–", "-").replace("—", "-"))
    return s.lower()


def cmd_update_backfill_reconcile(args_list: list[str]) -> int:
    """Coverage gate — reconcile a drafted artifact against the gather's firm set.

    The firm tier is TOTAL-COVERAGE: every firm (source, topic) pair the gather
    emitted MUST be drafted in the artifact, OR accounted for as already-cited
    (citation staleness between gather and draft). A firm pair that is neither is
    an UNEXPLAINED GAP — the silent-drop defect class this gate exists to catch
    (2026-06-10: ~107 of 351 firm rows silently dropped under large per-subagent
    source lists). Deterministic, pair-keyed — does NOT depend on the drafting
    agent remembering to chunk or self-count.

    Inputs: --gather <gather JSON>, --artifact <drafted pending-topic-updates.md>.
    Emits a JSON coverage report (counts + the explicit gap/staleness lists).
    Exit 1 if ANY firm pair is an unexplained gap; exit 0 when coverage is total.
    Read-only — writes nothing under wiki/ and never touches the artifact.
    """
    parser = argparse.ArgumentParser(
        description="Backfill coverage gate — drafted ∪ accounted == gather firm set."
    )
    parser.add_argument("--vault-root", type=Path, default=Path.cwd())
    parser.add_argument("--gather", type=Path, required=True,
                        help="gather JSON (from update-backfill-gather --output)")
    parser.add_argument("--artifact", type=Path, required=True,
                        help="drafted pending-topic-updates.md to reconcile")
    parser.add_argument("--output", type=Path, default=None,
                        help="write the coverage report JSON here instead of stdout")
    args = parser.parse_args(args_list)
    wiki_root = resolve_wiki_root(args.vault_root.resolve())

    gather = json.loads(read_text(args.gather))
    firm = gather.get("firm_candidates", [])
    # Expected firm pair set, normalized to the artifact's pair space.
    expected: dict[tuple[str, str], dict] = {}
    for c in firm:
        key = (_norm_pair_cell(c["source"]), _norm_pair_cell(c["topic"]))
        expected[key] = c

    drafted = _parse_artifact_pending_pairs(read_text(args.artifact))

    # Citation map for staleness accounting: a firm pair absent from the draft is
    # JUSTIFIED only if the topic page now cites the source (the information is
    # already on the page — citation-dedupe would suppress it on a fresh gather).
    citation_map = _build_topic_citation_map(wiki_root)

    drafted_firm: list[list[str]] = []
    staleness_accounted: list[list[str]] = []
    unexplained_gaps: list[list[str]] = []
    for key, cand in sorted(expected.items()):
        if key in drafted:
            drafted_firm.append(list(key))
            continue
        # Not drafted — is it justified by staleness (topic now cites source)?
        topic_stem = Path(cand["topic"]).stem
        src_filename = Path(cand["source"]).name
        if src_filename in citation_map.get(topic_stem, set()):
            staleness_accounted.append(list(key))
        else:
            unexplained_gaps.append([cand["source"], cand["topic"]])

    report = {
        "firm_expected": len(expected),
        "firm_drafted": len(drafted_firm),
        "staleness_accounted": len(staleness_accounted),
        "unexplained_gaps": len(unexplained_gaps),
        "coverage_total": not unexplained_gaps,
        "gap_pairs": unexplained_gaps,
        "staleness_pairs": staleness_accounted,
    }
    output = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    if unexplained_gaps:
        print(
            f"[update-backfill-reconcile] COVERAGE GATE FAILED: "
            f"{len(unexplained_gaps)} firm pair(s) neither drafted nor "
            f"citation-accounted — re-draft these before writing the artifact.",
            file=sys.stderr,
        )
        return 1
    return 0


# ---------------------------------------------------------------------------
# normalize-filenames subcommand (p4-9)
# ---------------------------------------------------------------------------
# ASCII-slugify all non-ASCII wiki filenames. Fold map:
#   – typographic quotes/dashes: ' ' → ' | ' ' → drop | " " → - | — – ‑ → -
#   – ellipsis: … → drop | bullet: • → -
#   – accents (PT + other): NFKD + strip non-ASCII combining marks
#   – mojibake ├Â (= UTF-8 ö mis-decoded): repair to ö BEFORE NFKD fold
#   – emoji / surrogate pairs: drop
#   – post-fold: collapse consecutive hyphens, strip leading/trailing hyphens
# Collision gate: emitted rename map verified collision-free BEFORE any
# execute path exists. A collision halts with the colliding set (exit 2).
# Modes:
#   --dry-run (default): scan → emit JSON rename map + reference-class counts
#   --execute:           perform renames + heal all reference classes
#                        + re-key lint state-file stamps (never wipe)
# State-file re-key: when --state-report is given, re-key (old_rel→new_rel)
# in the JSON stamps dict, preserving runs_completed and all other fields.
# The Voyage search index (index.db) stores paths; document the re-key step
# here — the conductor runs a full --sync after migration to rebuild it.

_MOJIBAKE_PAIRS: list[tuple[str, str]] = [
    # Each entry is (mojibake_sequence, intended_unicode_char).
    # Source: UTF-8 multi-byte sequences decoded as individual Latin-1 chars.
    # ├Â = U+251C U+00C2 = the UTF-8 bytes C3 B6 (ö) decoded as CP437/Latin-1
    # produces E2 94 9C (├, U+251C) + C3 (Ã) B6... actually the observed
    # pair from the live corpus is ├Â (U+251C + U+00C2), documented in task
    # dispatch as the known mojibake class for ö in these filenames.
    ("├Â", "ö"),  # ├Â → ö (Swedish/German o-umlaut)
]


def _slug_fold(name: str) -> str:
    """Fold a filename stem to pure ASCII per the p4-9 design.

    Steps:
    1. Repair mojibake sequences (byte-exact substitutions).
    2. Fold typographic punctuation: curly quotes, em/en dashes, bullet,
       ellipsis.
    3. Drop emoji / surrogate-pair characters.
    4. NFKD-decompose and strip non-ASCII (accent fold).
    5. Whitespace → hyphen, then collapse hyphen runs, strip leading/trailing.
    6. Lowercase the result.

    The `.md` extension is stripped before calling and re-appended by the
    caller — pass the stem only.
    """
    s = name

    # Step 1: mojibake repair (order matters — apply before any Unicode fold).
    for mojibake, intended in _MOJIBAKE_PAIRS:
        s = s.replace(mojibake, intended)

    # Step 2: typographic punctuation fold.
    # RIGHT SINGLE QUOTATION MARK ' → apostrophe ' (kept as a separator signal).
    # LEFT SINGLE QUOTATION MARK ' → drop (decorative open-quote).
    # LEFT/RIGHT DOUBLE QUOTATION MARKS " " → - (title separator).
    # EM DASH — → -.
    # EN DASH – → -.
    # NON-BREAKING HYPHEN ‑ → -.
    # HORIZONTAL ELLIPSIS … → drop.
    # BULLET • → -.
    s = (
        s
        .replace("’", "'")   # RIGHT SINGLE QUOTATION MARK → apostrophe
        .replace("‘", "")    # LEFT SINGLE QUOTATION MARK → drop
        .replace("“", "-")   # LEFT DOUBLE QUOTATION MARK → -
        .replace("”", "-")   # RIGHT DOUBLE QUOTATION MARK → -
        .replace("—", "-")   # EM DASH → -
        .replace("–", "-")   # EN DASH → -
        .replace("‑", "-")   # NON-BREAKING HYPHEN → -
        .replace("…", "")    # HORIZONTAL ELLIPSIS → drop
        .replace("•", "-")   # BULLET → -
    )

    # Step 3: drop emoji and surrogate-pair characters.
    # Emoji occupy the Supplementary Multilingual Plane (U+1F000 and above),
    # represented as surrogate pairs in Python str when built from UTF-16.
    # Also drop any remaining high-plane chars (U+10000+) and surrogates.
    cleaned: list[str] = []
    for ch in s:
        cp = ord(ch)
        if cp >= 0xD800 and cp <= 0xDFFF:
            continue   # surrogate — drop
        if cp >= 0x10000:
            continue   # supplementary plane (emoji etc.) — drop
        cleaned.append(ch)
    s = "".join(cleaned)

    # Step 4: NFKD decomposition + strip non-ASCII.
    # Decomposes accented chars into base + combining marks, then drops
    # any remaining non-ASCII character (the combining marks and any char
    # that has no ASCII base).
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if ord(c) < 128)

    # Step 5: normalise hyphens (the apostrophe from step 2 also folds here).
    # Replace apostrophe with nothing (it appears mid-word, not as separator).
    s = s.replace("'", "")
    # Whitespace → hyphen: a kebab filename never contains a space. This also
    # powers the case/space normalisation of not-yet-ingested raw files
    # (see `_is_case_space_candidate`); for non-ASCII renames it rides along
    # harmlessly (references are always healed).
    s = re.sub(r"\s+", "-", s)
    # Collapse consecutive hyphens produced by chained folds.
    s = re.sub(r"-{2,}", "-", s)
    # Strip leading/trailing hyphens.
    s = s.strip("-")

    # Step 6: lowercase guard.
    s = s.lower()

    return s


def _all_wiki_files(wiki_root: Path) -> list[Path]:
    """Return ALL files under wiki_root that may need renaming.

    Scope: raw/ + wiki/ subtrees — ALL file types (not just .md), because
    raw/ contains PDFs too. Excludes only binary-dump asset folders (``_assets``
    / ``*-assets``); a semantic ``assets/`` content folder stays in scope so its
    pages rename consistently with how their references are healed.
    """
    result: list[Path] = []
    for subtree in ("raw", "wiki"):
        d = wiki_root / subtree
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if p.is_file() and not excluded_dir(p.relative_to(wiki_root)):
                result.append(p)
    return result


def _is_case_space_candidate(p: Path, wiki_root: Path) -> bool:
    """True if ``p`` is a not-yet-ingested raw source file eligible for
    case/space filename normalisation (owner ruling 2026-06-14).

    Scope is deliberately narrow so the rename can NEVER break a live
    reference:

    - under ``raw/`` (never ``wiki/``), a DIRECT child of an origin folder
      (``raw/{origin}/{file}``), and NOT in a binary-dump asset folder
      (``_assets`` / ``*-assets``, already filtered by ``excluded_dir``);
    - a real source candidate: a ``.md``/``.pdf`` whose name is neither a
      ``NON_SOURCE_FILES`` sentinel (``CLAUDE.md`` etc.) nor the origin index
      (``{origin}.md``);
    - NOT yet ingested: no source page exists at
      ``wiki/sources/{origin}/{stem}.md`` (mirrors the ingest "ingested"
      definition in ``sb-wiki-ingest-all-manifest.py``).

    An un-ingested raw file has no source page and nothing links to it, so a
    case/space rename is reference-safe — that is exactly why ALREADY-ingested
    files are excluded here (the owner's stated fear of breaking links).
    """
    try:
        rel = p.relative_to(wiki_root)
    except ValueError:
        return False
    parts = rel.parts
    # raw/{origin}/{file} — direct origin child only (mirrors the manifest's
    # iterdir scope; deeper nesting like legacy raw/{origin}/assets/ is out).
    if len(parts) != 3 or parts[0] != "raw":
        return False
    if excluded_dir(rel):
        return False
    if p.suffix not in (".md", ".pdf"):
        return False
    origin = parts[1]
    if p.name in NON_SOURCE_FILES or p.name == f"{origin}.md":
        return False
    source_page = wiki_root / "wiki" / "sources" / origin / f"{p.stem}.md"
    return not source_page.exists()


def _build_rename_map(
    wiki_root: Path, files: list[Path] | None = None
) -> tuple[list[tuple[Path, Path]], list[dict[str, str]]]:
    """Scan wiki_root and return (renames, collisions).

    renames: list of (old_path, new_path) for files whose folded name differs.
    collisions: list of dicts describing any fold-map collisions.

    Collision = two different old names fold to the same new name, OR a
    folded name clashes with an EXISTING file that is NOT itself being renamed.

    ``files``: when provided, evaluate ONLY these paths instead of rglob-ing the
    whole ``raw/`` + ``wiki/`` corpus (bounded-rescan path — owner ruling
    2026-06-14). The caller (e.g. the ingest A11 step) passes just the
    file(s) it touched, so a clean incoming file no longer triggers a
    whole-corpus scan. ``None`` = scan the whole corpus (default / migration).
    """
    all_files = files if files is not None else _all_wiki_files(wiki_root)

    # Map from (parent_dir, new_stem+ext) → list of old Path objects.
    fold_map: dict[tuple[Path, str], list[Path]] = {}
    # Files that keep their name (fold produces identical stem).
    unchanged: set[Path] = set()

    for p in all_files:
        stem = p.stem
        ext = p.suffix  # e.g. ".md" or ".pdf"
        # SCOPE GATE (p4-9 contract, Q1b ruling 2026-06-11): the migration is
        # bounded to NON-ASCII-NAMED files only. Uppercase, spaces, and ASCII
        # punctuation are all ASCII and are OUT of scope for the migration.
        # EXTENSION (owner ruling 2026-06-14): a pure-ASCII file ALSO becomes a
        # rename candidate when it is a not-yet-ingested raw file — its case and
        # spaces are normalised to canonical kebab via _slug_fold. Reference-safe
        # because nothing links to an un-ingested raw file (see
        # _is_case_space_candidate). Every other pure-ASCII file keeps its name.
        if all(ord(c) < 128 for c in stem):
            if not _is_case_space_candidate(p, wiki_root):
                unchanged.add(p)
                continue
        folded_stem = _slug_fold(stem)
        new_name = folded_stem + ext
        if new_name == p.name:
            unchanged.add(p)
            continue
        key = (p.parent, new_name)
        fold_map.setdefault(key, []).append(p)

    renames: list[tuple[Path, Path]] = []
    collisions: list[dict[str, str]] = []

    for (parent, new_name), old_paths in fold_map.items():
        new_path = parent / new_name
        # Collision type A: two different old files fold to the same new name.
        if len(old_paths) > 1:
            collisions.append({
                "new_name": str(new_path.relative_to(wiki_root)).replace("\\", "/"),
                "sources": [
                    str(p.relative_to(wiki_root)).replace("\\", "/")
                    for p in old_paths
                ],
                "reason": "multiple-sources-fold-to-same-name",
            })
            continue
        # Collision type B: target name is already taken by a file NOT itself
        # being renamed (i.e., it is in `unchanged` OR was not visited at all).
        if new_path.exists() and new_path not in {p for p, _ in renames}:
            old_path = old_paths[0]
            if new_path != old_path:  # not renaming to itself
                collisions.append({
                    "new_name": str(new_path.relative_to(wiki_root)).replace("\\", "/"),
                    "sources": [str(old_path.relative_to(wiki_root)).replace("\\", "/")],
                    "existing": str(new_path.relative_to(wiki_root)).replace("\\", "/"),
                    "reason": "target-name-already-exists",
                })
                continue
        renames.append((old_paths[0], new_path))

    return sorted(renames, key=lambda t: str(t[0])), collisions


def _count_reference_classes(wiki_root: Path, rename_map: list[tuple[Path, Path]]) -> dict:
    """Count how many references of each class need healing (dry-run only).

    Reference classes:
    1. wikilinks — [[old-stem.md]] or [[old-stem.pdf]] in wiki/ files
    2. raw-index File cells — | [[old-stem.md]] | rows in raw/{origin}/{origin}.md
    3. raw: backlinks — raw: "[[old-stem.md]]" frontmatter in source pages
    4. questions.md / logs entries — string occurrences in those files
    5. pending-topic-updates.md source-path cells (read-only count)
    6. lint state-file stamps — path-keyed entries that need re-key
    """
    # Bounded-rescan short-circuit (owner ruling 2026-06-14): no renames means
    # nothing to heal — return zeroed counts WITHOUT rglob-ing the corpus. This
    # is what makes a scoped, clean incoming file O(scope), not O(corpus).
    if not rename_map:
        return {
            "wikilinks": 0,
            "raw_index_file_cells": 0,
            "raw_backlinks": 0,
            "questions_logs_entries": 0,
            "pending_topic_updates_rows": 0,
            "root_level_files": 0,
            "state_file_stamps": 0,
        }

    # Build a set of (old_rel, new_rel) for fast lookup.
    old_to_new: dict[str, str] = {}
    for old_p, new_p in rename_map:
        old_rel = str(old_p.relative_to(wiki_root)).replace("\\", "/")
        new_rel = str(new_p.relative_to(wiki_root)).replace("\\", "/")
        old_to_new[old_rel] = new_rel

    # We also need old-stem lookup (without path context) for wikilink patterns.
    old_stems: set[str] = set()
    for old_p, _ in rename_map:
        old_stems.add(old_p.stem + old_p.suffix)

    counts = {
        "wikilinks": 0,
        "raw_index_file_cells": 0,
        "raw_backlinks": 0,
        "questions_logs_entries": 0,
        "pending_topic_updates_rows": 0,
        "root_level_files": 0,
        "state_file_stamps": 0,
    }

    # Count wikilinks in wiki/ files.
    # NOTE: source pages under wiki/sources/ carry a `raw: "[[stem.md]]"`
    # frontmatter backlink. The bare-prefix count below (`[[old`) would absorb
    # those into `wikilinks`, leaving the `raw_backlinks` class falsely 0 — the
    # heal IS performed at execute time (every wiki/ file is healed for both the
    # body `[[old…]]` and the quoted frontmatter pattern), so the defect is in
    # attribution, not coverage. Tally the quoted frontmatter occurrences under
    # `raw_backlinks` and EXCLUDE them from the `wikilinks` total so the dry-run
    # count matches what the conductor verifies post-migration.
    wiki_dir = wiki_root / "wiki"
    if wiki_dir.exists():
        for p in wiki_dir.rglob("*.md"):
            if excluded_dir(p.relative_to(wiki_root)):
                continue
            try:
                text = read_text(p)
            except OSError:
                continue
            for old_name in old_stems:
                fm_backlinks = text.count(f'"[[{old_name}]]"')
                if fm_backlinks:
                    counts["raw_backlinks"] += fm_backlinks
                if f"[[{old_name}" in text:
                    # bare-prefix total minus the quoted-frontmatter occurrences
                    counts["wikilinks"] += text.count(f"[[{old_name}") - fm_backlinks

    # Count raw-index File cells and raw: backlinks under raw/ (legacy location).
    raw_dir = wiki_root / "raw"
    if raw_dir.exists():
        for p in raw_dir.rglob("*.md"):
            if excluded_dir(p.relative_to(wiki_root)):
                continue
            try:
                text = read_text(p)
            except OSError:
                continue
            for old_name in old_stems:
                # Raw index File cells: | [[slug.md]] |
                if f"[[{old_name}]]" in text:
                    counts["raw_index_file_cells"] += text.count(f"[[{old_name}]]")
                # raw: frontmatter backlinks
                if f'"[[{old_name}]]"' in text:
                    counts["raw_backlinks"] += text.count(f'"[[{old_name}]]"')

    # Count questions.md and logs/*.md occurrences.
    for special in [wiki_root / "questions.md"]:
        if special.exists():
            try:
                text = read_text(special)
            except OSError:
                continue
            for old_name in old_stems:
                if old_name in text:
                    counts["questions_logs_entries"] += text.count(old_name)
    logs_dir = wiki_root / "logs"
    if logs_dir.exists():
        for p in logs_dir.glob("*.md"):
            try:
                text = read_text(p)
            except OSError:
                continue
            for old_name in old_stems:
                if old_name in text:
                    counts["questions_logs_entries"] += text.count(old_name)

    # Count pending-topic-updates.md source-path cells (read-only).
    pending = wiki_root / "pending-topic-updates.md"
    if pending.exists():
        try:
            text = read_text(pending)
        except OSError:
            text = ""
        for old_name in old_stems:
            if old_name in text:
                counts["pending_topic_updates_rows"] += text.count(old_name)

    # Count root-level wiki files ({wiki_root}/*.md, e.g. tecer-relevant.md).
    # These sit OUTSIDE the wiki/ and raw/ subtrees the loops above scan, so
    # their [[file.md]] references were silently uncounted (stray-healer gap,
    # shape 2). NON_SOURCE_FILES (CLAUDE.md etc.) are not wiki content; questions
    # and pending are tallied in their own classes above — exclude all three.
    for p in sorted(wiki_root.glob("*.md")):
        if p.name in NON_SOURCE_FILES or p.name in ("questions.md", "pending-topic-updates.md"):
            continue
        try:
            text = read_text(p)
        except OSError:
            continue
        for old_name in old_stems:
            if f"[[{old_name}" in text:
                counts["root_level_files"] += text.count(f"[[{old_name}")

    # Count lint state-file stamps that need re-key.
    state_path = wiki_root / "lint-deterministic-report.json"
    if state_path.exists():
        try:
            state = json.loads(read_text(state_path))
            stamps = state.get("stamps", {})
            for key in stamps:
                base = Path(key).name
                if base in old_stems:
                    counts["state_file_stamps"] += 1
        except (json.JSONDecodeError, OSError):
            pass

    return counts


def _execute_normalize(
    wiki_root: Path,
    rename_map: list[tuple[Path, Path]],
    state_path: Path | None = None,
    output: Path | None = None,
) -> dict:
    """Execute renames + heal all reference classes + re-key state stamps.

    MIGRATION IS CONDUCTOR-EXECUTED. This function is called by the executor
    (cmd_normalize_filenames --execute). In the plan, the conductor runs this
    after reviewer certification.

    Returns a result dict with counts of renames performed and references healed.
    """
    result: dict = {
        "renames_performed": [],
        "wikilinks_healed": 0,
        "raw_index_cells_healed": 0,
        "raw_backlinks_healed": 0,
        "questions_logs_healed": 0,
        "pending_topic_updates_healed": 0,
        "root_level_files_healed": 0,
        "state_stamps_rekeyed": 0,
        "errors": [],
    }

    # Bounded-rescan short-circuit (owner ruling 2026-06-14): an empty rename map
    # means nothing to heal or re-key — return the zeroed result WITHOUT rglob-ing
    # the whole corpus. Mirrors the same guard in _count_reference_classes.
    if not rename_map:
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            with open(_fspath(output), "w", encoding="utf-8") as fh:
                fh.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return result

    # Build old→new mapping indexed by (stem+ext) for text healing.
    old_to_new_name: dict[str, str] = {}  # old_filename → new_filename
    old_to_new_rel: dict[str, str] = {}   # old_rel_path → new_rel_path
    for old_p, new_p in rename_map:
        old_to_new_name[old_p.name] = new_p.name
        old_rel = str(old_p.relative_to(wiki_root)).replace("\\", "/")
        new_rel = str(new_p.relative_to(wiki_root)).replace("\\", "/")
        old_to_new_rel[old_rel] = new_rel

    # Step A: Heal all TEXT references BEFORE renaming files.
    # This ensures we can still read files at their old paths.

    def _heal_file(p: Path) -> int:
        """Rewrite wikilink references in a file. Returns count of subs made."""
        try:
            text = read_text(p)
        except OSError as e:
            result["errors"].append(f"READ-FAIL {p}: {e}")
            return 0
        updated = text
        for old_name, new_name in old_to_new_name.items():
            # Heal [[old-stem.ext…]] patterns preserving anchors/aliases.
            pattern = re.compile(
                r"(!?\[\[)" + re.escape(old_name) + r"((?:#[^\]|]*)?(?:\|[^\]]*)?\]\])"
            )
            updated = pattern.sub(lambda m, n=new_name: m.group(1) + n + m.group(2), updated)
            # Heal "[[old-stem.ext]]" frontmatter patterns.
            updated = updated.replace(f'"[[{old_name}]]"', f'"[[{new_name}]]"')
        if updated != text:
            try:
                with open(_fspath(p), "w", encoding="utf-8") as fh:
                    fh.write(updated)
            except OSError as e:
                result["errors"].append(f"WRITE-FAIL {p}: {e}")
                return 0
            return len(re.findall(re.compile(
                r"(!?\[\[)(?:" + "|".join(re.escape(n) for n in old_to_new_name) + r")",
            ), text))
        return 0

    # Heal wiki/ files.
    wiki_dir = wiki_root / "wiki"
    if wiki_dir.exists():
        for p in wiki_dir.rglob("*.md"):
            if excluded_dir(p.relative_to(wiki_root)):
                continue
            n = _heal_file(p)
            result["wikilinks_healed"] += n

    # Heal raw/ files (index + raw: frontmatter).
    raw_dir = wiki_root / "raw"
    if raw_dir.exists():
        for p in raw_dir.rglob("*.md"):
            if excluded_dir(p.relative_to(wiki_root)):
                continue
            n = _heal_file(p)
            result["raw_index_cells_healed"] += n

    # Heal questions.md and logs/*.md.
    for special in [wiki_root / "questions.md"]:
        if special.exists():
            n = _heal_file(special)
            result["questions_logs_healed"] += n
    logs_dir = wiki_root / "logs"
    if logs_dir.exists():
        for p in logs_dir.glob("*.md"):
            n = _heal_file(p)
            result["questions_logs_healed"] += n

    # Heal root-level wiki files ({wiki_root}/*.md, e.g. tecer-relevant.md) —
    # outside the wiki/ and raw/ subtrees above (stray-healer gap, shape 2).
    # NON_SOURCE_FILES are not wiki content; questions/pending are healed in
    # their own blocks — exclude all three to avoid touching or double-healing.
    for p in sorted(wiki_root.glob("*.md")):
        if p.name in NON_SOURCE_FILES or p.name in ("questions.md", "pending-topic-updates.md"):
            continue
        n = _heal_file(p)
        result["root_level_files_healed"] += n

    # Heal pending-topic-updates.md (read: designed here, executed by conductor).
    # _heal_file rewrites the column-5 [[file.md]] citation cells; the column-1
    # source-path cells are bare `wiki/sources/{origin}/{file}.md` paths the
    # wikilink regex never matches (stray-healer gap, shape 3). Heal those by
    # full rel-path substitution after the wikilink pass.
    pending = wiki_root / "pending-topic-updates.md"
    if pending.exists():
        n = _heal_file(pending)
        result["pending_topic_updates_healed"] += n
        try:
            text = read_text(pending)
            updated = text
            path_subs = 0
            for old_rel, new_rel in old_to_new_rel.items():
                occurrences = updated.count(old_rel)
                if occurrences:
                    updated = updated.replace(old_rel, new_rel)
                    path_subs += occurrences
            if updated != text:
                with open(_fspath(pending), "w", encoding="utf-8") as fh:
                    fh.write(updated)
            result["pending_topic_updates_healed"] += path_subs
        except OSError as e:
            result["errors"].append(f"PENDING-PATH-HEAL-FAIL {pending}: {e}")

    # Step B: Re-key lint state-file stamps.
    effective_state = state_path if state_path else wiki_root / "lint-deterministic-report.json"
    if effective_state.exists():
        try:
            state = json.loads(read_text(effective_state))
            stamps = state.get("stamps", {})
            new_stamps: dict[str, str] = {}
            rekeyed = 0
            for rel, stamp_val in stamps.items():
                # rel is a wiki-root-relative path like "wiki/sources/origin/file.md"
                if rel in old_to_new_rel:
                    new_stamps[old_to_new_rel[rel]] = stamp_val
                    rekeyed += 1
                else:
                    new_stamps[rel] = stamp_val
            state["stamps"] = new_stamps
            result["state_stamps_rekeyed"] = rekeyed
            # Write back preserving all other fields including runs_completed.
            with open(_fspath(effective_state), "w", encoding="utf-8") as fh:
                fh.write(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
        except (json.JSONDecodeError, OSError) as e:
            result["errors"].append(f"STATE-REKEY-FAIL: {e}")

    # Step C: Perform the actual renames.
    for old_p, new_p in rename_map:
        if not old_p.exists():
            result["errors"].append(f"RENAME-SKIP-MISSING: {old_p.relative_to(wiki_root)}")
            continue
        if new_p.exists() and new_p != old_p:
            result["errors"].append(
                f"RENAME-SKIP-COLLISION: {old_p.relative_to(wiki_root)} → "
                f"{new_p.relative_to(wiki_root)} (target exists)"
            )
            continue
        try:
            os.replace(_fspath(old_p), _fspath(new_p))
            result["renames_performed"].append({
                "old": str(old_p.relative_to(wiki_root)).replace("\\", "/"),
                "new": str(new_p.relative_to(wiki_root)).replace("\\", "/"),
            })
        except OSError as e:
            result["errors"].append(
                f"RENAME-FAIL: {old_p.relative_to(wiki_root)} → {new_p.relative_to(wiki_root)}: {e}"
            )

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(_fspath(output), "w", encoding="utf-8") as fh:
            fh.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def cmd_normalize_filenames(args_list: list[str]) -> int:
    """ASCII-slugify all non-ASCII filenames in the wiki corpus.

    Fold map (p4-9 design, Q1b owner ruling 2026-06-11):
    - Typographic quotes/dashes: ' → ' (apostrophe, then dropped in post-fold)
      ' → drop | " " → - | — – ‑ → -
    - Ellipsis … → drop | Bullet • → -
    - Accents (PT + other): NFKD + strip non-ASCII combining marks
    - Mojibake ├Â (UTF-8 ö mis-decoded): repair to ö BEFORE fold
    - Emoji / supplementary-plane chars: drop
    - Post-fold: collapse consecutive hyphens, strip leading/trailing

    Also normalises CASE and SPACE for not-yet-ingested raw files (owner ruling
    2026-06-14): a pure-ASCII raw file with no source page yet (nothing links to
    it) is folded to canonical kebab (lowercase, spaces → hyphens). Already-
    ingested files are never touched by this rule — see _is_case_space_candidate.

    Modes:
      Default (--dry-run):  scan → emit JSON rename map + reference counts;
                            exit 0 when no collisions, exit 2 on collision.
      --execute:            renames + reference-class heals + state re-key.
                            MIGRATION IS CONDUCTOR-EXECUTED — run only after
                            reviewer certification and before Phase-5 lint.
      --scope PATH ...:     BOUNDED RESCAN — evaluate only the given file(s)
                            instead of the whole corpus; a clean incoming file
                            does no whole-corpus scan. Combine with --execute
                            for the per-ingest stray-heal (A11 wiring).

    Voyage search index note: index.db stores document paths. After --execute,
    the conductor must run:
        python sb-wiki-search.py --vault-root <vault> index
    to rebuild the index against the renamed paths. Stale paths in index.db
    produce dead search results for any renamed file until that sync runs.
    The clipper writes raws OUTSIDE sb-os governance — the normalize-filenames
    subcommand doubles as the recurring stray-healer for any non-ASCII files
    introduced by the clipper after the one-time corpus migration. Run it
    periodically (or on ingest post-commit) to catch stragglers. Document
    this seam so operators know: the creation-time rule governs ingest, the
    normalize subcommand governs everything else.
    """
    parser = argparse.ArgumentParser(
        description="ASCII-slugify non-ASCII filenames in the wiki corpus."
    )
    parser.add_argument("--vault-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "CONDUCTOR-EXECUTED: perform renames, heal all reference classes, "
            "re-key lint state-file stamps. Requires --output for the result log."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="write the rename map / result JSON here instead of stdout",
    )
    parser.add_argument(
        "--state-report",
        type=Path,
        default=None,
        help="path to the lint state JSON for stamp re-key (default: canonical path)",
    )
    parser.add_argument(
        "--scope",
        type=Path,
        action="append",
        default=None,
        metavar="PATH",
        help=(
            "BOUNDED RESCAN: evaluate ONLY these file(s) for renaming instead of "
            "scanning the whole corpus (repeatable). Paths resolve against the "
            "current dir or absolute; any path outside wiki_root or inside a "
            "binary-dump asset folder is ignored. Omit to scan the whole corpus "
            "(default / migration). Used by the ingest A11 step to pass just the "
            "incoming raw file so a clean file triggers no whole-corpus scan."
        ),
    )
    args = parser.parse_args(args_list)
    vault_root = args.vault_root.resolve()
    wiki_root = resolve_wiki_root(vault_root)

    scoped_files: list[Path] | None = None
    if args.scope:
        scoped_files = []
        for raw_path in args.scope:
            sp = raw_path.resolve()
            try:
                rel = sp.relative_to(wiki_root)
            except ValueError:
                continue  # outside the wiki corpus — ignore
            if sp.is_file() and not excluded_dir(rel):
                scoped_files.append(sp)

    renames, collisions = _build_rename_map(wiki_root, files=scoped_files)

    if collisions:
        payload = {
            "status": "COLLISION",
            "collision_count": len(collisions),
            "collisions": collisions,
            "rename_count": 0,
            "renames": [],
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with open(_fspath(args.output), "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
        print(text)
        print(
            f"\nCOLLISION GATE: {len(collisions)} collision(s) detected. "
            "Resolve before --execute. See 'collisions' field above.",
            file=sys.stderr,
        )
        return 2

    rename_list = [
        {
            "old": str(old_p.relative_to(wiki_root)).replace("\\", "/"),
            "new": str(new_p.relative_to(wiki_root)).replace("\\", "/"),
        }
        for old_p, new_p in renames
    ]

    if not args.execute:
        # Dry-run: emit rename map + reference-class counts.
        ref_counts = _count_reference_classes(wiki_root, renames)
        payload = {
            "status": "DRY_RUN",
            "rename_count": len(renames),
            "renames": rename_list,
            "reference_class_counts": ref_counts,
            "voyage_index_note": (
                "After --execute the conductor must run: "
                "python sb-wiki-search.py --vault-root <vault> index "
                "to rebuild the Voyage index against the renamed paths."
            ),
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with open(_fspath(args.output), "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
        print(text)
        return 0

    # Execute mode.
    result = _execute_normalize(
        wiki_root,
        renames,
        state_path=args.state_report,
        output=args.output,
    )
    return 1 if result.get("errors") else 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    if len(sys.argv) > 1 and sys.argv[1] == "update-backfill-gather":
        return cmd_update_backfill_gather(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "update-backfill-reconcile":
        return cmd_update_backfill_reconcile(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "open-gaps":
        return cmd_open_gaps(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "sweep-gather":
        return cmd_sweep_gather(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "check-pages":
        return cmd_check_pages(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "normalize-filenames":
        return cmd_normalize_filenames(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "update-links":
        return cmd_update_links(sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true", help="write deterministic changes")
    parser.add_argument("--report", type=Path, help="optional JSON report path")
    parser.add_argument(
        "--prune-log",
        action="store_true",
        help="delete spent/retired logs/*.md entries (lint-contract-authorized prune)",
    )
    parser.add_argument(
        "--prune-source-queue",
        action="store_true",
        help=(
            "delete resolved source-queue.md entries whose wiki source page now "
            "exists (finance lint rule 3; owner-gated — irreversible delete)"
        ),
    )
    parser.add_argument(
        "--candidate-age-floor",
        type=int,
        default=CANDIDATE_AGE_FLOOR_DAYS,
        metavar="DAYS",
        help=(
            "age floor (days) at/above which an unpromoted candidate-topic "
            "surfaces as aged (0 = every pending candidate)"
        ),
    )
    parser.add_argument(
        "--execute-renames",
        type=Path,
        metavar="PLAN_JSON",
        help="USER-GATED: execute PDF title-conformance renames from a step-9 plan",
    )
    parser.add_argument(
        "--execute-subdivision",
        type=Path,
        metavar="PLAN_JSON",
        help="USER-GATED: execute folder-subdivision moves from a step-9 plan",
    )
    parser.add_argument(
        "--execute-link-fixes",
        type=Path,
        metavar="PLAN_JSON",
        help="USER-GATED: apply accepted bucket-A broken-link fixes from a step-9 plan",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="force full-corpus dirty set (all pages treated as changed)",
    )
    parser.add_argument(
        "--token-overlap-a",
        metavar="TEXT",
        help="first text for token-overlap check",
    )
    parser.add_argument(
        "--token-overlap-b",
        metavar="TEXT",
        help="second text for token-overlap check",
    )
    args = parser.parse_args()

    if args.token_overlap_a is not None and args.token_overlap_b is not None:
        shared, verdict = token_overlap(args.token_overlap_a, args.token_overlap_b)
        payload = {
            "tokens_a": sorted(tokenize(args.token_overlap_a)),
            "tokens_b": sorted(tokenize(args.token_overlap_b)),
            "shared_tokens": sorted(shared),
            "shared_count": len(shared),
            "verdict": verdict,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    wiki_root = resolve_wiki_root(args.vault_root.resolve())

    # State file resolution: explicit --report flag takes precedence; otherwise
    # fall back to the canonical path under wiki_root.
    state_path = args.report if args.report else wiki_root / "lint-deterministic-report.json"

    # Guard: --prune-log combined with --report at the canonical state path is
    # forbidden.  The prune-only flow (Step 8) must NEVER carry --report at the
    # canonical path: doing so re-snapshots state in check-mode, bumps
    # runs_completed a second time, and overwrites the --full report from the
    # mandatory pre-Step-1 apply run (live incident p2-7 RUN-1; D10 ruling).
    # Scratch-path --report is still allowed; prune without --report is unchanged.
    # Mirrors the p2-1 execute-mode write-guard (report.mode != "execute").
    canonical_state_path = wiki_root / "lint-deterministic-report.json"
    if (args.prune_log or args.prune_source_queue) and args.report and args.report.resolve() == canonical_state_path.resolve():
        print(
            "ERROR: a prune flag (--prune-log / --prune-source-queue) combined with --report at the\n"
            "canonical state path is forbidden. The Step-8 prune invocation must NOT carry --report\n"
            "<canonical path>: it re-snapshots state in check-mode, double-bumps runs_completed, and\n"
            "overwrites the --apply report.\n"
            "Fix: run the prune flag WITHOUT --report (prune only), or use a scratch path for --report.",
            file=sys.stderr,
        )
        return 1

    prev_stamps, fallback_reason, prev_runs_completed = load_state(state_path)

    if args.execute_renames or args.execute_subdivision or args.execute_link_fixes:
        # Executor mode: run ONLY the requested user-gated executor(s).
        report = Report(mode="execute")
        if args.execute_renames:
            execute_renames(wiki_root, args.execute_renames, report)
        if args.execute_subdivision:
            execute_subdivision(wiki_root, args.execute_subdivision, report)
        if args.execute_link_fixes:
            execute_link_fixes(wiki_root, args.execute_link_fixes, report)
    else:
        full_mode = args.full or fallback_reason is not None
        report = Report(
            mode="apply" if args.apply else "check",
            full_mode=full_mode,
            state_fallback_reason=fallback_reason,
        )
        # Collapse legacy 4-col/3-col raw indexes to the 2-col `| File | Wiki |`
        # FIRST (ADX-9/ADX-10), so sync_raw_indexes then sizes any newly-added row
        # to the migrated 2-col header and heal flips the Wiki cell at its 2-col
        # position — keeping the whole raw-index pass idempotent on a second run.
        migrate_raw_indexes_to_file_wiki(wiki_root, report, args.apply)
        sync_raw_indexes(wiki_root, report, args.apply)
        heal_raw_wiki_cells(wiki_root, report, args.apply)
        sync_wiki_leaf_headers_and_queue(wiki_root, report, args.apply)
        sync_type_tags(wiki_root, report, args.apply)
        migrate_sources_index_to_description(wiki_root, report, args.apply)
        detect_broken_wikilinks(wiki_root, report)
        detect_disputed_callouts(wiki_root, report)
        detect_subdivision(wiki_root, report)
        scan_log(
            wiki_root,
            report,
            prune=args.prune_log,
            candidate_age_floor=args.candidate_age_floor,
        )
        scan_source_queue(wiki_root, report, prune=args.prune_source_queue)
        check_questions_links(wiki_root, report)
        structural_walk(wiki_root, report, args.apply)
        detect_pdf_title_conformance(wiki_root, report)
        detect_md_duplicate_raws(wiki_root, report)
        detect_missing_links(wiki_root, report, args.apply)

        # --- Dirty-set computation (incremental lint state spine) ---
        tracked = collect_tracked_pages(wiki_root)
        current_stamps: dict[str, str] = {}
        dirty: list[str] = []
        for page in tracked:
            rel = str(page.relative_to(wiki_root)).replace("\\", "/")
            stamp = compute_stamp(page)
            current_stamps[rel] = stamp
            if full_mode or prev_stamps.get(rel) != stamp:
                dirty.append(rel)
        report.stamps = current_stamps
        report.dirty_set = dirty

    payload = {
        "mode": report.mode,
        "writes": report.writes,
        "judgment_needed": report.judgment_needed,
        "detected": report.detected,
        "dirty_set": report.dirty_set,
        "stamps": report.stamps,
        "state_schema_version": report.state_schema_version,
        "full_mode": report.full_mode,
        "state_fallback_reason": report.state_fallback_reason,
        "stamp_commit_policy": report.stamp_commit_policy,
    }
    if report.mode != "execute":
        payload["runs_completed"] = prev_runs_completed + 1
    output = json.dumps(payload, indent=2, ensure_ascii=False)
    # Executor mode computes no stamps; writing its report would CLOBBER the
    # state file (the report IS the state file) with empty stamps, silently
    # forcing the next run into a full sweep. Executor detail (detected.renames
    # / .subdivision / .link_fixes, claude_md_pending) is consumed from stdout,
    # which is always printed below — so never persist an execute-mode report.
    if args.report and report.mode != "execute":
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
