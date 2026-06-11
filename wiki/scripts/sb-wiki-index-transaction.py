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


RAW_HEADER = "| File | Title | Date | Wiki |"
RAW_SEPARATOR = "|------|-------|------|------|"
SOURCES_HEADER = "| File | What it says | My take |"
SOURCES_SEPARATOR = "|------|--------------|---------|"


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


def build_raw_edit(path: Path, raw_filename: str, title: str | None, date: str | None) -> Edit:
    if not path.is_file():
        raise TransactionError(f"missing target: {path}")
    before = read_text(path)
    lines = before.splitlines()
    header_index, columns = find_table(lines, ["File", "Wiki"])
    file_column = columns.index("File")
    wiki_column = columns.index("Wiki")
    row_index = find_row_by_link(lines, header_index, file_column, raw_filename)
    if row_index is None:
        if not title or not date:
            raise TransactionError(
                f"raw row missing and --raw-title/--raw-date not provided: {path} :: {raw_filename}"
            )
        # Size the new row to the ACTUAL header width (canonical 4-col or a
        # legacy variant), placing values only into columns that exist by name
        # so a non-canonical table is never given a wrong-width row.
        cells = [""] * len(columns)
        cells[file_column] = f"[[{escape_cell(raw_filename)}]]"
        if "Title" in columns:
            cells[columns.index("Title")] = escape_cell(title)
        if "Date" in columns:
            cells[columns.index("Date")] = escape_cell(date)
        cells[wiki_column] = "Yes"
        lines.insert(header_index + 2, row_from_cells(cells))
        action = f"ADD raw row + set Wiki=Yes for {raw_filename}"
    else:
        cells = split_row(lines[row_index])
        while len(cells) < len(columns):
            cells.append("")
        previous = cells[wiki_column]
        cells[wiki_column] = "Yes"
        lines[row_index] = row_from_cells(cells)
        action = (
            f"ENSURE raw Wiki=Yes for {raw_filename}"
            if previous == "Yes"
            else f"SET raw Wiki: {previous or '<blank>'} -> Yes for {raw_filename}"
        )
    after = "\n".join(lines) + ("\n" if before.endswith("\n") else "")
    return Edit(path=path, before=before, after=after, action=action)


def build_sources_edit(path: Path, source_filename: str, summary: str, my_take: str) -> Edit:
    if not path.is_file():
        raise TransactionError(f"missing target: {path}")
    before = read_text(path)
    lines = before.splitlines()
    header_index, columns = find_table(lines, ["File", "What it says", "My take"])
    file_column = columns.index("File")
    row_index = find_row_by_link(lines, header_index, file_column, source_filename)
    row = [
        f"[[{escape_cell(source_filename)}]]",
        escape_cell(summary),
        escape_cell(my_take),
    ]
    if row_index is None:
        insert_at = header_index + 2
        while insert_at < len(lines) and lines[insert_at].lstrip().startswith("|"):
            insert_at += 1
        lines.insert(insert_at, row_from_cells(row))
        action = f"ADD wiki-sources row for {source_filename}"
    else:
        action = f"ALREADY recorded wiki-sources row for {source_filename}"
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", type=Path, default=Path.cwd())
    parser.add_argument("--origin", required=True)
    parser.add_argument("--raw-file", required=True, help="raw filename including extension")
    parser.add_argument("--source-file", required=True, help="source page filename, .md optional")
    parser.add_argument("--what-it-says", required=True, help="wiki-sources factual summary")
    parser.add_argument("--my-take", default="pending")
    parser.add_argument("--raw-title", help="required only when the raw-index row is missing")
    parser.add_argument("--raw-date", help="required only when the raw-index row is missing")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        vault_root = args.vault_root.resolve()
        wiki_root = resolve_wiki_root(vault_root)
        raw_index = wiki_root / "raw" / args.origin / f"{args.origin}.md"
        sources_index = wiki_root / "wiki" / "sources" / args.origin / f"{args.origin}.md"
        source_filename = normalize_source_filename(args.source_file)
        edits = [
            build_raw_edit(raw_index, args.raw_file, args.raw_title, args.raw_date),
            build_sources_edit(sources_index, source_filename, args.what_it_says, args.my_take),
        ]
        validate_targets(edits)
        print_plan(edits, args.dry_run)
        if not args.dry_run:
            write_atomically(edits)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
