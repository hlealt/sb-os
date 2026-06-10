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
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


RAW_HEADER = "| File | Title | Date | Wiki |\n|------|-------|------|------|\n"
CONCEPT_HEADER = "| File | Description |\n|------|-------------|\n"
ENTITY_HEADER = "| File | Description |\n|------|-------------|\n"
TOPIC_HEADER = "| File | Scope |\n|------|-------|\n"
LEAF_INDEX_FRONTMATTER = "---\ntype: index\n---\n\n"
STATE_SCHEMA_VERSION = "1.0"


def compute_stamp(path: Path) -> str:
    """Return a SHA256 hex digest of the file content as a content stamp."""
    return hashlib.sha256(read_text(path).encode("utf-8")).hexdigest()


def load_state(state_path: Path) -> tuple[dict[str, str], str | None]:
    """Load previous stamps from the state file.

    Returns (stamps, fallback_reason).  fallback_reason is None on success,
    or a string explaining why full-mode fallback was triggered.
    """
    if not state_path.exists():
        return {}, "first-run"
    try:
        data = json.loads(read_text(state_path))
        version = data.get("state_schema_version", "")
        if version != STATE_SCHEMA_VERSION:
            return {}, f"schema-mismatch (expected {STATE_SCHEMA_VERSION}, got {version!r})"
        stamps = data.get("stamps", {})
        if not isinstance(stamps, dict):
            return {}, "corrupt-state"
        return stamps, None
    except Exception:
        return {}, "corrupt-state"


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
SOURCE_AGENT_HALF = {"Substance", "Notable quotes", "Connections"}


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


def scan_log(wiki_root: Path, report: Report, prune: bool) -> None:
    """Prune-test every entry across the split logs under {wiki_root}/logs/.

    Each entry carries its type in its own H2 header, so the scanner walks every
    file in logs/ and resolves per type (resolution = page exists):
      - candidate-topic       -> topic pages
      - candidate-mention     -> ALL page names
      - proposed-new-thesis   -> theses pages (like candidate-topic)
      - speculative-thesis-update -> NEVER auto-pruned; aged + surfaced as
        "awaiting investor decision" (the page already exists, so there is no
        "page exists" resolution signal — DEC-2).
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
                    if age > STUB_AGE_FLOOR_DAYS:
                        aging.append({"slug": brief, "logged": date_match.group(1), "age_days": age})
            keep.append(block)
        if prune and (file_spent or file_retired):
            write_text(log_path, preamble + "".join(keep), report, apply_changes=True)
            pruned_spent += file_spent
            pruned_retired += file_retired
    report.detected["log_spent_entries"] = spent
    report.detected["log_retired_entries"] = retired
    report.detected["log_unknown_type_entries"] = unknown
    report.detected["log_aging_candidate_topics"] = aging
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


def resolve_wiki_root(vault_root: Path) -> Path:
    manifest = json.loads(read_text(vault_root / "sb-os.json"))
    return vault_root / manifest["wiki_root"]


def main() -> int:
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
    args = parser.parse_args()

    wiki_root = resolve_wiki_root(args.vault_root.resolve())

    # State file resolution: explicit --report flag takes precedence; otherwise
    # fall back to the canonical path under wiki_root.
    state_path = args.report if args.report else wiki_root / "lint-deterministic-report.json"
    prev_stamps, fallback_reason = load_state(state_path)

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
        sync_wiki_leaf_headers_and_queue(wiki_root, report, args.apply)
        sync_type_tags(wiki_root, report, args.apply)
        sync_source_my_take_and_queue(wiki_root, report, args.apply)
        detect_broken_wikilinks(wiki_root, report)
        detect_disputed_callouts(wiki_root, report)
        detect_subdivision(wiki_root, report)
        scan_log(wiki_root, report, prune=args.prune_log)
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
