#!/usr/bin/env python3
"""Atomically record one ingested raw source across the wiki indexes."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


# ADX-9/ADX-10: the raw index is reduced to `| File | Wiki |` — the human-readable
# summary column (Title/Description) AND the Date column are both dropped (zero
# programmatic readers; Date duplicated the filename's YYYY-MM-DD prefix). Legacy
# 4-col `File|Title|Date|Wiki` and 3-col `File|Description|Wiki` are still RECOGNIZED
# (read + migrated by lint), but the canonical written form is 2-col.
RAW_HEADER = "| File | Wiki |"
RAW_SEPARATOR = "|------|------|"
# U11: the wiki sources index is the unified 2-col `| File | Description |`
# (the `My take` column was dropped — it lives canonically in the source-page
# body; `What it says` was renamed to `Description`).
SOURCES_HEADER = "| File | Description |"
SOURCES_SEPARATOR = "|------|-------------|"


class TransactionError(Exception):
    pass


@dataclass
class Edit:
    path: Path
    before: str
    after: str
    action: str


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def resolve_wiki_root(vault_root: Path) -> Path:
    manifest_path = vault_root / "sb-os.json"
    if not manifest_path.is_file():
        raise TransactionError(f"missing manifest: {manifest_path}")
    manifest = json.loads(read_text(manifest_path))
    wiki_root = manifest.get("wiki_root")
    if not wiki_root:
        raise TransactionError(f"missing wiki_root in: {manifest_path}")
    return (vault_root / wiki_root).resolve()


def escape_cell(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip())
    return value.replace("|", r"\|")


def split_row(row: str) -> list[str]:
    text = row.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in text:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            current.append(char)
            escaped = True
            continue
        if char == "|":
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    cells.append("".join(current).strip())
    return cells


def row_from_cells(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def link_target(cell: str) -> str | None:
    match = re.search(r"\[\[([^\]|#]+)", cell)
    if not match:
        return None
    return match.group(1).rsplit("/", 1)[-1]


def find_table(lines: list[str], required_columns: list[str]) -> tuple[int, list[str]]:
    """Locate the table whose header carries every required column (by name).

    Per the spec's row-format-drift edge case, the script reads the target
    header to position columns rather than assuming a fixed column set. An
    exact header match wins; failing that, the first header that CONTAINS all
    required columns (a legacy raw index such as ``| File | Description | Wiki |``
    that predates the ``| File | Title | Date | Wiki |`` canonical form) is
    accepted so the ``Wiki`` flip still lands. Column values are placed by name,
    never by fixed index, so a wider-or-narrower table is never mis-filled.
    """
    wanted = [column.lower() for column in required_columns]
    fallback: tuple[int, list[str]] | None = None
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        actual = [cell.strip() for cell in split_row(line)]
        lowered = [cell.lower() for cell in actual]
        if lowered == wanted:
            return index, actual
        if fallback is None and all(column in lowered for column in wanted):
            fallback = (index, actual)
    if fallback is not None:
        return fallback
    raise TransactionError(f"table header not found: {' | '.join(required_columns)}")


def find_row_by_link(lines: list[str], header_index: int, file_column: int, filename: str) -> int | None:
    for index in range(header_index + 2, len(lines)):
        line = lines[index]
        if not line.lstrip().startswith("|"):
            break
        cells = split_row(line)
        if file_column >= len(cells):
            continue
        if link_target(cells[file_column]) == filename:
            return index
    return None


def normalize_source_filename(filename: str) -> str:
    return filename if filename.endswith(".md") else f"{filename}.md"


# ---------------------------------------------------------------------------
# Consolidated raw-index writer (U2b — the ONE name-keyed authority)
# ---------------------------------------------------------------------------
# Every raw-index structural mutation routes through this module. The three
# historical writers (``build_raw_edit`` here; ``sync_raw_indexes`` and
# ``heal_raw_wiki_cells`` in sb-wiki-lint-deterministic.py) call these helpers
# instead of building rows independently, and the two matchers
# (``find_row_by_link`` here, ``ingested_raw_filenames`` in lint) read the same
# layout authority. The writer is SCHEMA-PARAMETERIZED: it places a value into
# the column its NAME owns, sized to the ACTUAL table it is editing, and refuses
# to misfire into a wider row's cell.
#
# Raw-row layout authority. A raw row is recognized when its width is one of the
# three raw layouts, and the ``Wiki`` flag is ALWAYS the final cell of a raw row
# (true for all):
#   - 2-col canonical: ``| File | Wiki |``               (ADX-9/ADX-10 — current)
#   - 4-col legacy:    ``| File | Title | Date | Wiki |``
#   - 3-col legacy:    ``| File | Description | Wiki |``
# Locating ``Wiki`` as the final cell of the MATCHED ROW (not by the header's
# ``index("Wiki")``) is the 5B fix: a 4-col data row appended under a 3-col
# legacy header no longer takes the header's Wiki index (2 = the Date cell of the
# wider row) — the flag lands in the row's own last cell. A row whose width is
# none of 2/3/4 is UNRECOGNIZED: the writer refuses to flip it and reports it,
# never guessing a Wiki position.

RAW_RECOGNIZED_WIDTHS = (2, 3, 4)


def raw_row_wiki_index(cells: list[str]) -> int | None:
    """Return the index of the ``Wiki`` cell in a raw DATA row, by the row's own
    layout — or ``None`` when the row width is not a recognized raw layout.

    The ``Wiki`` flag is the final cell of every recognized raw row (2-col
    canonical ``File|Wiki``, 3-col legacy ``File|Description|Wiki``, 4-col legacy
    ``File|Title|Date|Wiki``). This keys off the matched ROW, never the header, so
    a 4-col row appended under a 3-col header is flipped at index 3 (its real last
    cell), never index 2 (the header's Wiki position, which is the Date cell of
    the wider row); a 2-col canonical row flips at index 1.
    """
    if len(cells) not in RAW_RECOGNIZED_WIDTHS:
        return None
    return len(cells) - 1


def set_raw_row_wiki(cells: list[str], value: str) -> tuple[list[str], str | None]:
    """Set the ``Wiki`` cell of a raw data row by the row's own layout.

    Returns ``(new_cells, previous_value)``; ``previous_value`` is ``None`` when
    the row is an unrecognized width (refuse — the caller reports it). Never pads
    or reshapes the row; only the Wiki cell is touched.
    """
    wiki_idx = raw_row_wiki_index(cells)
    if wiki_idx is None:
        return cells, None
    new_cells = list(cells)
    previous = new_cells[wiki_idx]
    new_cells[wiki_idx] = value
    return new_cells, previous


def build_raw_row(columns: list[str], raw_filename: str, title: str, date: str, wiki: str) -> str:
    """Build a raw-index row sized to the ACTUAL header ``columns`` (Rule 2/3).

    Values are placed by column NAME, never by fixed index, so a non-canonical
    table is never given a wrong-width row: a 2-col canonical ``File|Wiki`` header
    gets ``File + Wiki`` (Title/Date are dropped — not in the column set);
    a 4-col legacy header gets File/Title/Date/Wiki; a 3-col legacy
    ``File|Description|Wiki`` header gets a 3-col row (File + blank Description +
    Wiki). The producer does NOT manufacture a wider row under a narrower header.
    The ``Wiki`` cell is always the row's final cell.
    """
    lowered = [c.lower() for c in columns]
    cells = [""] * len(columns)
    if "file" in lowered:
        cells[lowered.index("file")] = f"[[{escape_cell(raw_filename)}]]"
    if "title" in lowered:
        cells[lowered.index("title")] = escape_cell(title)
    if "date" in lowered:
        cells[lowered.index("date")] = escape_cell(date)
    # Wiki is the row's final cell for every recognized raw layout.
    cells[len(columns) - 1] = wiki
    return row_from_cells(cells)


def repair_raw_row_width(cells: list[str], header_width: int) -> tuple[list[str], bool]:
    """Merge a row spilled WIDER than its header back to the header width (Rule:
    broken 5-col repair). Returns ``(repaired_cells, changed)``.

    Cause of the live breakage: a source filename / Title containing an
    unescaped subtitle separator (``--`` slug → ``Title | Subtitle``) split the
    Title across two cells, yielding a 5-col row under a 4-col header. The repair
    MERGES the spilled middle cells back into ONE Title cell (joined with a
    literal ``--`` — the separator the slug encodes), preserving File at the
    front and the trailing Date/Wiki cells. Only fires when the row is exactly
    ONE cell wider than a 4-col header (the verified break shape); any other
    over-width is left for report (bespoke — never guessed).
    """
    if header_width != 4 or len(cells) != header_width + 1:
        return cells, False
    # cells: [File, Title_part1, Title_part2, Date, Wiki]
    file_cell = cells[0]
    title = f"{cells[1]} -- {cells[2]}"
    date_cell = cells[3]
    wiki_cell = cells[4]
    return [file_cell, title, date_cell, wiki_cell], True


def build_raw_edit(path: Path, raw_filename: str, title: str | None, date: str | None) -> Edit:
    if not path.is_file():
        raise TransactionError(f"missing target: {path}")
    before = read_text(path)
    lines = before.splitlines()
    header_index, columns = find_table(lines, ["File", "Wiki"])
    file_column = columns.index("File")
    row_index = find_row_by_link(lines, header_index, file_column, raw_filename)
    if row_index is None:
        if not title or not date:
            raise TransactionError(
                f"raw row missing and --raw-title/--raw-date not provided: {path} :: {raw_filename}"
            )
        # ADD branch — build the row sized to the ACTUAL header via the
        # consolidated writer (Rule 2/3): placed by column NAME, never a fixed
        # 4-col row under a non-canonical header.
        lines.insert(header_index + 2, build_raw_row(columns, raw_filename, title, date, "Yes"))
        action = f"ADD raw row + set Wiki=Yes for {raw_filename}"
    else:
        # UPDATE branch — flip Wiki by the MATCHED ROW's own layout (5B fix),
        # NOT by the header's Wiki index. A 4-col data row under a 3-col legacy
        # header is flipped at its own last cell (index 3), never the header's
        # Wiki index (2 = the wider row's Date cell). An unrecognized-width row
        # is REFUSED + reported, never misfired into.
        cells = split_row(lines[row_index])
        new_cells, previous = set_raw_row_wiki(cells, "Yes")
        if previous is None:
            raise TransactionError(
                f"raw row width {len(cells)} unrecognized (not 3 or 4) — refusing to "
                f"set Wiki to avoid misfire: {path} :: {raw_filename} :: {lines[row_index]!r}"
            )
        lines[row_index] = row_from_cells(new_cells)
        action = (
            f"ENSURE raw Wiki=Yes for {raw_filename}"
            if previous == "Yes"
            else f"SET raw Wiki: {previous or '<blank>'} -> Yes for {raw_filename}"
        )
    after = "\n".join(lines) + ("\n" if before.endswith("\n") else "")
    return Edit(path=path, before=before, after=after, action=action)


def build_sources_edit(path: Path, source_filename: str, summary: str) -> Edit:
    """Add the unified 2-col `| File | Description |` wiki-sources row (U11).

    The `My take` index column was dropped (it lives canonically in the
    source-page body); `What it says` was renamed to `Description`. The
    Description cell carries the LLM-derived factual summary. If the index FILE
    is absent, it is created with the 2-col header + separator (ingest step 8
    contract: "Wiki sources index file missing → create it with header row").
    A legacy 3-col `| File | What it says | My take |` header is still LOCATED
    (so an ADD lands correctly) — the row is appended in the 2-col shape; lint
    migrates the legacy header + existing rows to the 2-col form.
    """
    if not path.is_file():
        before = ""
        lines: list[str] = []
    else:
        before = read_text(path)
        lines = before.splitlines()
    # Locate the index table by the `File` column (tolerates a not-yet-migrated
    # legacy 3-col header). Absent any table → write the unified header.
    try:
        header_index, columns = find_table(lines, ["File"])
        file_column = columns.index("File")
    except TransactionError:
        if not lines:
            lines = [SOURCES_HEADER, SOURCES_SEPARATOR]
        else:
            lines += [SOURCES_HEADER, SOURCES_SEPARATOR]
        header_index = len(lines) - 2
        file_column = 0
    row_index = find_row_by_link(lines, header_index, file_column, source_filename)
    row = [
        f"[[{escape_cell(source_filename)}]]",
        escape_cell(summary),
    ]
    if row_index is None:
        insert_at = header_index + 2
        while insert_at < len(lines) and lines[insert_at].lstrip().startswith("|"):
            insert_at += 1
        lines.insert(insert_at, row_from_cells(row))
        action = f"ADD wiki-sources row for {source_filename}"
    else:
        action = f"ALREADY recorded wiki-sources row for {source_filename}"
    after = "\n".join(lines) + ("\n" if (before == "" or before.endswith("\n")) else "")
    return Edit(path=path, before=before, after=after, action=action)


# ---------------------------------------------------------------------------
# Wiki leaf-index writer (U4 — concept / entity / topic stub rows)
# ---------------------------------------------------------------------------
# Writes ONE row into a ``| File | Description |`` or ``| File | Scope |``
# wiki leaf index.  The Description/Scope cell is judgment-bearing (must be
# supplied by the calling LLM workflow — scripts MUST NOT derive it from a
# slug or heading guess).  The writer is intentionally NARROW: it appends a
# missing row and is a no-op when the row already exists.  It does NOT
# create the index file when it is absent (log a WARNING and exit 0 — lint
# creates and owns leaf indexes; this writer only fills a gap at self-heal
# time so the stub appears immediately).

LEAF_INDEX_DESCRIPTION_COLUMNS = ("description",)
LEAF_INDEX_SCOPE_COLUMNS = ("scope",)
LEAF_INDEX_VALUE_COLUMNS = LEAF_INDEX_DESCRIPTION_COLUMNS + LEAF_INDEX_SCOPE_COLUMNS


def build_leaf_index_edit(path: Path, page_filename: str, description: str) -> Edit:
    """Insert a ``| File | Description |`` (or ``| File | Scope |``) row for
    *page_filename* into the leaf index at *path*.

    Rules:
    - ``description`` MUST be a non-blank LLM-derived sentence; the caller is
      responsible for supplying it (this function refuses a blank string).
    - If the index file does not exist, return a no-op Edit and print a
      WARNING — lint creates leaf-index files; this writer only augments them.
    - If the row is already present, return a no-op Edit (idempotent).
    - Row is appended at the end of the table (after the last existing row).
    - Supports both ``| File | Description |`` and ``| File | Scope |``
      tables; the value column name is detected from the header.
    """
    page_filename = normalize_source_filename(page_filename)
    if not description or not description.strip():
        raise TransactionError(
            f"description must not be blank for leaf-index row: {page_filename}"
        )
    if not path.is_file():
        print(
            f"WARNING: leaf index not found — skipping row for {page_filename}: {path}",
            file=sys.stderr,
        )
        # Return a no-op edit so the caller can continue without aborting.
        return Edit(path=path, before="", after="", action=f"SKIP (index absent) leaf row for {page_filename}")
    before = read_text(path)
    lines = before.splitlines()
    # Detect which value column the table uses: Description or Scope.
    try:
        header_index, columns = find_table(lines, ["File", "Description"])
        value_col_name = "Description"
    except TransactionError:
        try:
            header_index, columns = find_table(lines, ["File", "Scope"])
            value_col_name = "Scope"
        except TransactionError:
            raise TransactionError(
                f"leaf index has no File|Description or File|Scope table: {path}"
            )
    file_column = columns.index("File")
    row_index = find_row_by_link(lines, header_index, file_column, page_filename.removesuffix(".md"))
    if row_index is None:
        # Also check with .md suffix in the link target.
        row_index = find_row_by_link(lines, header_index, file_column, page_filename)
    if row_index is not None:
        return Edit(
            path=path,
            before=before,
            after=before,
            action=f"ALREADY recorded leaf row for {page_filename}",
        )
    row = [
        f"[[{escape_cell(page_filename)}]]",
        escape_cell(description.strip()),
    ]
    insert_at = header_index + 2
    while insert_at < len(lines) and lines[insert_at].lstrip().startswith("|"):
        insert_at += 1
    lines.insert(insert_at, row_from_cells(row))
    action = f"ADD leaf-index ({value_col_name}) row for {page_filename}"
    after = "\n".join(lines) + ("\n" if before.endswith("\n") else "")
    return Edit(path=path, before=before, after=after, action=action)


def validate_targets(edits: list[Edit]) -> None:
    seen = set()
    for edit in edits:
        if edit.path in seen:
            raise TransactionError(f"duplicate target path: {edit.path}")
        seen.add(edit.path)
        parent = edit.path.parent
        if not parent.is_dir():
            raise TransactionError(f"missing parent directory: {parent}")
        if edit.path.exists() and not edit.path.is_file():
            raise TransactionError(f"not a file target: {edit.path}")
        if edit.path.exists() and not os.access(edit.path, os.W_OK):
            raise TransactionError(f"unwritable target: {edit.path}")


def write_atomically(edits: list[Edit]) -> None:
    written: list[Edit] = []
    try:
        for edit in edits:
            if edit.before == edit.after:
                continue
            edit.path.write_text(edit.after, encoding="utf-8", newline="")
            if read_text(edit.path) != edit.after:
                raise TransactionError(f"write verification failed: {edit.path}")
            written.append(edit)
    except Exception:
        for edit in reversed(written):
            edit.path.write_text(edit.before, encoding="utf-8", newline="")
        raise


def print_plan(edits: list[Edit], dry_run: bool) -> None:
    print(f"MODE: {'DRY-RUN' if dry_run else 'APPLY'}")
    for edit in edits:
        changed = edit.before != edit.after
        print(f"{edit.path}: {edit.action}; changed={str(changed).lower()}")
    if all(edit.before == edit.after for edit in edits):
        print("NOTE: already recorded; no file changes needed")


def _add_global_args(p: argparse.ArgumentParser) -> None:
    """Add flags shared by every parser/sub-parser: --vault-root and --dry-run."""
    p.add_argument("--vault-root", type=Path, default=Path.cwd())
    p.add_argument("--dry-run", action="store_true")


def _add_ingest_args(p: argparse.ArgumentParser, *, required: bool) -> None:
    """Add ingest-specific flags.

    ``required=True`` for the ``ingest`` sub-command (callers MUST supply
    all four core flags); ``required=False`` for the legacy flat-arg parser
    (detected at runtime via ``if not args.origin`` in ``main()``).
    """
    p.add_argument("--origin", required=required)
    p.add_argument("--raw-file", required=required, help="raw filename including extension")
    p.add_argument("--source-file", required=required, help="source page filename, .md optional")
    p.add_argument("--what-it-says", required=required, help="wiki-sources Description (factual summary)")
    p.add_argument("--raw-title", help="required only when the raw-index row is missing")
    p.add_argument("--raw-date", help="required only when the raw-index row is missing")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")

    # ------------------------------------------------------------------
    # Sub-command: ingest  (default / legacy flat-arg mode)
    # Record a raw-index row + wiki-sources row for one ingested source.
    # ------------------------------------------------------------------
    ingest = subparsers.add_parser(
        "ingest",
        help="Record raw-index Wiki=Yes and wiki-sources row (default for backwards compat).",
    )
    _add_global_args(ingest)
    _add_ingest_args(ingest, required=True)

    # ------------------------------------------------------------------
    # Sub-command: leaf-index  (U4 — self-heal stub indexing)
    # Write ONE row into a concept/entity/topic wiki leaf index.
    # The description cell is judgment-bearing — the caller supplies it.
    # ------------------------------------------------------------------
    leaf = subparsers.add_parser(
        "leaf-index",
        help="Add a File|Description row to a wiki leaf index (U4 — self-heal stub indexing).",
    )
    _add_global_args(leaf)
    leaf.add_argument(
        "--leaf-index-path",
        required=True,
        type=Path,
        help="Workspace-root-absolute path to the leaf index .md file.",
    )
    leaf.add_argument(
        "--page-file",
        required=True,
        help="Stub page filename (e.g. attention-mechanism.md). .md is added if missing.",
    )
    leaf.add_argument(
        "--description",
        required=True,
        help="LLM-derived 1-sentence Description or Scope cell (must not be blank).",
    )

    # ------------------------------------------------------------------
    # Legacy flat-arg mode: no sub-command → behave as "ingest"
    # All original callers (sb-wiki-ingest.md Steps 7–8) pass --origin
    # directly without a sub-command; keep them working unchanged.
    # ------------------------------------------------------------------
    _add_global_args(parser)
    _add_ingest_args(parser, required=False)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    # Determine effective command: explicit sub-command or legacy flat-args.
    command = getattr(args, "command", None)
    if command is None:
        # Legacy flat-arg invocation: treat as "ingest" when --origin is present.
        if not args.origin:
            print("ERROR: provide a sub-command (ingest / leaf-index) or supply --origin for legacy mode.", file=sys.stderr)
            return 1
        command = "ingest"

    try:
        vault_root = args.vault_root.resolve()

        if command == "ingest":
            wiki_root = resolve_wiki_root(vault_root)
            raw_index = wiki_root / "raw" / args.origin / f"{args.origin}.md"
            sources_index = wiki_root / "wiki" / "sources" / args.origin / f"{args.origin}.md"
            source_filename = normalize_source_filename(args.source_file)
            edits = [
                build_raw_edit(raw_index, args.raw_file, args.raw_title, args.raw_date),
                build_sources_edit(sources_index, source_filename, args.what_it_says),
            ]
            validate_targets([e for e in edits if e.path.exists()])
            print_plan(edits, args.dry_run)
            if not args.dry_run:
                write_atomically(edits)
            return 0

        if command == "leaf-index":
            leaf_path = args.leaf_index_path.resolve()
            edit = build_leaf_index_edit(leaf_path, args.page_file, args.description)
            validate_targets([edit] if edit.path.exists() else [])
            print_plan([edit], args.dry_run)
            if not args.dry_run:
                write_atomically([edit])
            return 0

        print(f"ERROR: unknown command: {command}", file=sys.stderr)
        return 1

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
