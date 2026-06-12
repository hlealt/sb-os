#!/usr/bin/env python3
"""Deterministic support pass for sb-wiki-lint.

This script handles only mechanical wiki maintenance. It never writes
judgment-bearing index cells such as Description, Scope, or What it says.
Those gaps are emitted as a JSON queue for the LLM lint workflow.

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


RAW_HEADER = "| File | Title | Date | Wiki |\n|------|-------|------|------|\n"
CONCEPT_HEADER = "| File | Description |\n|------|-------------|\n"
ENTITY_HEADER = "| File | Description |\n|------|-------------|\n"
TOPIC_HEADER = "| File | Scope |\n|------|-------|\n"
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
    """Asset-folder exclusion: any path segment named `assets` or `*-assets`."""
    return any(part == "assets" or part.endswith("-assets") for part in path.parts)


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


def derive_raw_title_and_date(path: Path) -> tuple[str, str]:
    text = read_text(path)
    fm = frontmatter(text)
    title = fm.get("title", "") or first_h1(text)
    date = fm.get("date", "") or fm.get("created", "")
    if not date:
        match = re.match(r"^(\d{4})[-_](\d{2})[-_](\d{2})", path.name)
        if match:
            date = "-".join(match.groups())
    return title, date


def sync_raw_indexes(wiki_root: Path, report: Report, apply_changes: bool) -> None:
    raw_root = wiki_root / "raw"
    if not raw_root.exists():
        return
    for origin_dir in sorted(p for p in raw_root.iterdir() if p.is_dir() and p.name != "assets"):
        index_path = origin_dir / f"{origin_dir.name}.md"
        index_text = read_text(index_path) if index_path.exists() else RAW_HEADER
        if not index_path.exists():
            write_text(index_path, index_text, report, apply_changes)
        links = table_links(index_text)
        lines = index_text.rstrip("\n").splitlines() if index_text.strip() else RAW_HEADER.rstrip("\n").splitlines()
        changed = False
        for raw_file in sorted(origin_dir.glob("*.md")):
            if raw_file.name == index_path.name or raw_file.name in NON_SOURCE_FILES or raw_file.name in links:
                continue
            title, date = derive_raw_title_and_date(raw_file)
            if title and date:
                lines.append(make_row([f"[[{raw_file.name}]]", title, date, "No"]))
                changed = True
            else:
                report.judgment_needed.append(
                    {
                        "index": str(index_path),
                        "file": str(raw_file),
                        "cell": "Title/Date",
                        "reason": "raw index row missing and title/date are not fully deterministic",
                    }
                )
        if changed:
            write_text(index_path, "\n".join(lines) + "\n", report, apply_changes)


def ingested_raw_filenames(wiki_root: Path) -> tuple[set[str], dict[str, set[str]]]:
    """Inventory which raws have a 1:1 source page, by two union signals.

    A raw is "ingested" when EITHER signal fires — both keyed on the raw
    FILENAME / stem so .md and .pdf raws are handled uniformly:

      - ``raw:`` backlink — the source page's ``raw:`` frontmatter wikilinks
        the raw filename (the canonical 1:1 link per the wiki schema). Returned
        as a set of raw filenames across ALL source pages, any origin.
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
            raw_val = frontmatter(read_text(page)).get("raw", "")
            for target in re.findall(r"\[\[([^\]|#]+?)\]\]", raw_val):
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
            if not cells or cells[0] == "File" or len(cells) != 4:
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
            if cells[3].strip() != "No":
                continue
            backlink_hit = raw_filename in backlink_targets
            mirror_hit = Path(raw_filename).stem in origin_stems
            if backlink_hit or mirror_hit:
                cells[3] = "Yes"
                lines[idx] = make_row(cells)
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
            # Post-rewrite shape guard: every modified row must still split into
            # exactly 4 cells. A violation is a script bug — refuse the write.
            broken = [lines[i] for i in modified_rows if len(split_row_cells(lines[i])) != 4]
            if broken:
                report.detected.setdefault("row_shape_errors", []).extend(
                    f"{index_path}: {row}" for row in broken
                )
            else:
                write_text(index_path, "\n".join(lines) + "\n", report, apply_changes)
    report.detected["raw_wiki_healed"] = healed
    report.detected["raw_wiki_dangling"] = dangling


def sync_wiki_leaf_headers_and_queue(wiki_root: Path, report: Report, apply_changes: bool) -> None:
    specs = [
        ("concepts", "concepts.md", CONCEPT_HEADER, "Description"),
        ("entities", "entities.md", ENTITY_HEADER, "Description"),
        ("topics", "topics.md", TOPIC_HEADER, "Scope"),
    ]
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


def preview(text: str) -> str:
    """One-line, table-safe preview (<=280 chars before pipe escaping).

    Wikilinks are flattened to display text BEFORE truncation (a cut
    mid-wikilink leaks a raw `|` that splits the table row), then any
    remaining literal pipes are escaped. Normalize-then-escape keeps the
    result idempotent across re-sync passes.
    """
    one_line = re.sub(r"\s+", " ", flatten_wikilinks(text)).strip()
    if len(one_line) > 280:
        one_line = one_line[:277].rstrip() + "..."
    return one_line.replace("\\|", "|").replace("|", "\\|")


def split_row_cells(line: str) -> list[str]:
    """Split a Markdown table row on UNESCAPED pipes only (`\\|` stays in-cell)."""
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", inner)]


def sync_source_my_take_and_queue(wiki_root: Path, report: Report, apply_changes: bool) -> None:
    sources_root = wiki_root / "wiki" / "sources"
    if not sources_root.exists():
        return
    for origin_dir in sorted(p for p in sources_root.iterdir() if p.is_dir()):
        index_path = origin_dir / f"{origin_dir.name}.md"
        if not index_path.exists():
            continue
        lines = read_text(index_path).splitlines()
        changed = False
        modified_rows: list[int] = []
        linked = table_links("\n".join(lines))
        for source_page in sorted(origin_dir.glob("*.md")):
            if source_page.name == index_path.name or source_page.name in linked:
                continue
            report.judgment_needed.append(
                {
                    "index": str(index_path),
                    "file": str(source_page),
                    "cell": "What it says",
                    "reason": "wiki sources row missing; factual summary requires LLM judgment",
                }
            )
        for idx, line in enumerate(lines):
            if not line.strip().startswith("|") or re.match(r"^\s*\|\s*-+", line):
                continue
            cells = split_row_cells(line)
            if not cells or cells[0] == "File":
                continue
            match = re.search(r"\[\[([^\]]+?\.md)\]\]", cells[0])
            if not match:
                continue
            if len(cells) != 3:
                # Malformed data row (e.g. prior unescaped-pipe corruption):
                # never process it — re-syncing would perpetuate the damage.
                report.judgment_needed.append(
                    {
                        "index": str(index_path),
                        "file": str(origin_dir / match.group(1)),
                        "cell": "row-shape",
                        "reason": f"row has {len(cells)} cells, expected 3 — malformed; repair manually",
                    }
                )
                continue
            source_path = origin_dir / match.group(1)
            if not os.path.exists(_fspath(source_path)):
                continue
            body = section_body(read_text(source_path), "My take")
            if body:
                new_value = preview(body)
            elif cells[2] in {DASH, "pending"}:
                new_value = cells[2]
            else:
                new_value = "pending"
            if new_value != cells[2]:
                cells[2] = new_value
                lines[idx] = make_row(cells)
                modified_rows.append(idx)
                changed = True
        if changed:
            # Post-rewrite shape guard: every row this pass modified must still
            # split into exactly 3 cells. A violation is a script bug — refuse
            # the write and surface it rather than persist a broken table.
            broken = [lines[i] for i in modified_rows if len(split_row_cells(lines[i])) != 3]
            if broken:
                report.detected.setdefault("row_shape_errors", []).extend(
                    f"{index_path}: {row}" for row in broken
                )
                continue
            write_text(index_path, "\n".join(lines) + "\n", report, apply_changes)


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
    inline_all = re.findall(r"\[\^(\d+)\](?!:)", text)
    order: list[str] = []
    for marker in inline_all:
        if marker not in order:
            order.append(marker)
    return {"defs": defs, "inline": inline_all, "order": order}


def cmd_check_pages(args_list: list[str]) -> int:
    """Citation-integrity gate (``check-pages``) — ingest post-commit check.

    Validates the footnote state of the named pages only: every inline
    ``[^N]`` marker has a definition, every definition has at least one
    inline marker, and no definition number is duplicated.  Ordering is
    NOT checked — the C3 renumber pass owns normalization.  Exits 1 on
    any issue so workflow callers can hard-gate on the result.
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
            for target in set(re.findall(r"\[\[([^\]|#]+?\.md)\]\]", text)):
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
    slug = re.sub(r"[?!,.\"'()\[\]‘’“”]", "", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


def raw_index_titles(origin_dir: Path) -> dict[str, str]:
    """Map raw filename -> index Title cell (empty when no row)."""
    index_path = origin_dir / f"{origin_dir.name}.md"
    titles: dict[str, str] = {}
    if not index_path.exists():
        return titles
    for line in read_text(index_path).splitlines():
        if not line.strip().startswith("|") or re.match(r"^\s*\|\s*-+", line):
            continue
        cells = split_row_cells(line)
        if len(cells) < 2 or cells[0] == "File":
            continue
        match = re.search(r"\[\[([^\]|#]+?)\]\]", cells[0])
        if match:
            titles[Path(match.group(1)).name] = cells[1]
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
        titles = raw_index_titles(origin_dir)
        slug_groups: dict[str, list[tuple[str, str]]] = {}
        for pdf in sorted(origin_dir.glob("*.pdf")):
            title = titles.get(pdf.name, "")
            if not title:
                continue  # no index Title — step 7 / judgment pass owns the row first
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
    5. Normalise hyphens: collapse runs, strip leading/trailing.
    6. Lowercase the result (names are already lowercase; this is a guard).

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
    raw/ contains PDFs too. Excludes asset folders.
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


def _build_rename_map(wiki_root: Path) -> tuple[
    list[tuple[Path, Path]], list[dict[str, str]]
]:
    """Scan wiki_root and return (renames, collisions).

    renames: list of (old_path, new_path) for files whose folded name differs.
    collisions: list of dicts describing any fold-map collisions.

    Collision = two different old names fold to the same new name, OR a
    folded name clashes with an EXISTING file that is NOT itself being renamed.
    """
    all_files = _all_wiki_files(wiki_root)

    # Map from (parent_dir, new_stem+ext) → list of old Path objects.
    fold_map: dict[tuple[Path, str], list[Path]] = {}
    # Files that keep their name (fold produces identical stem).
    unchanged: set[Path] = set()

    for p in all_files:
        stem = p.stem
        ext = p.suffix  # e.g. ".md" or ".pdf"
        # SCOPE GATE (p4-9 contract, Q1b ruling 2026-06-11): the migration is
        # bounded to NON-ASCII-NAMED files only. Uppercase, spaces, and ASCII
        # punctuation are all ASCII and are OUT of scope — folding them inflates
        # the migration far beyond the ruled scope. A file whose stem is already
        # pure ASCII keeps its name even if _slug_fold would alter it (e.g.
        # case/space normalisation). Only a stem carrying a byte above 0x7F is a
        # rename candidate.
        if all(ord(c) < 128 for c in stem):
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
        "state_stamps_rekeyed": 0,
        "errors": [],
    }

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

    # Heal pending-topic-updates.md (read: designed here, executed by conductor).
    pending = wiki_root / "pending-topic-updates.md"
    if pending.exists():
        n = _heal_file(pending)
        result["pending_topic_updates_healed"] += n

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

    Modes:
      Default (--dry-run):  scan → emit JSON rename map + reference counts;
                            exit 0 when no collisions, exit 2 on collision.
      --execute:            renames + reference-class heals + state re-key.
                            MIGRATION IS CONDUCTOR-EXECUTED — run only after
                            reviewer certification and before Phase-5 lint.

    Voyage search index note: index.db stores document paths. After --execute,
    the conductor must run:
        python sb-wiki-search.py --vault-root <vault> sync
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
    args = parser.parse_args(args_list)
    vault_root = args.vault_root.resolve()
    wiki_root = resolve_wiki_root(vault_root)

    renames, collisions = _build_rename_map(wiki_root)

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
                "python sb-wiki-search.py --vault-root <vault> sync "
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
    if args.prune_log and args.report and args.report.resolve() == canonical_state_path.resolve():
        print(
            "ERROR: --prune-log combined with --report at the canonical state path is forbidden.\n"
            "The Step-8 prune invocation must NOT carry --report <canonical path>: it re-snapshots\n"
            "state in check-mode, double-bumps runs_completed, and overwrites the --apply report.\n"
            "Fix: run --prune-log WITHOUT --report (prune only), or use a scratch path for --report.",
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
        sync_raw_indexes(wiki_root, report, args.apply)
        heal_raw_wiki_cells(wiki_root, report, args.apply)
        sync_wiki_leaf_headers_and_queue(wiki_root, report, args.apply)
        sync_type_tags(wiki_root, report, args.apply)
        sync_source_my_take_and_queue(wiki_root, report, args.apply)
        detect_broken_wikilinks(wiki_root, report)
        detect_disputed_callouts(wiki_root, report)
        detect_subdivision(wiki_root, report)
        scan_log(
            wiki_root,
            report,
            prune=args.prune_log,
            candidate_age_floor=args.candidate_age_floor,
        )
        check_questions_links(wiki_root, report)
        structural_walk(wiki_root, report, args.apply)
        detect_pdf_title_conformance(wiki_root, report)

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
