#!/usr/bin/env python3
"""Collision-safe appends to shared wiki files (lock-guarded).

`/sb-wiki-ingest-all` dispatches up to 5 cross-origin subagents per wave in
PARALLEL. Each runs `/sb-wiki-ingest silent` and appends to GLOBAL targets that
two workers can touch at once — the candidate logs (`logs/mentions.md`,
`logs/topics.md`, Step 9) and the semantic-update queue
(`pending-topic-updates.md`, silent Step 10). Two parallel read-modify-write
appends to one file can clobber. This helper serializes every such write behind
a per-file lock so no append is ever lost.

Two operations:
- ``append-block`` — append a standalone text block (an H2 log entry) at EOF of
  an append-only log file, blank-line separated.
- ``append-row``   — insert a markdown table row at the end of a named section's
  table (the pending-topic-updates queue), optionally deduped by key columns.

Both take a per-file lock (an ``O_CREAT|O_EXCL`` lockfile with bounded retry and
age-based stale-lock recovery), then read-modify-write with read-back
verification — mirroring ``sb-wiki-index-transaction.py``'s atomic-write
discipline. Single-writer callers (interactive ingest, the research auto-ingest)
behave identically: the lock simply never contends, and the file result is byte
-identical to a direct append.

Stdlib-only. ``--vault-root`` isolates every path resolution (test seam). The
caller composes the entry/row text per the wiki schema; this helper owns ONLY
the atomic placement.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


LOCK_TIMEOUT_SECONDS = 30.0
LOCK_STALE_SECONDS = 30.0
LOCK_POLL_SECONDS = 0.05


class AppendError(Exception):
    pass


class LockTimeout(AppendError):
    pass


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text_verified(path: Path, content: str) -> None:
    # Under the per-file lock. Retry transient OS errors (AV / the OS indexer can
    # briefly hold a file on Windows); a content mismatch is a real failure and
    # raises immediately — never masked by a retry.
    for attempt in range(10):
        try:
            path.write_text(content, encoding="utf-8", newline="")
            roundtrip = read_text(path)
        except OSError:
            if attempt == 9:
                raise
            time.sleep(0.02)
            continue
        if roundtrip != content:
            raise AppendError(f"write verification failed: {path}")
        return
    raise AppendError(f"write failed after retries: {path}")


def resolve_wiki_root(vault_root: Path) -> Path:
    manifest_path = vault_root / "sb-os.json"
    if not manifest_path.is_file():
        raise AppendError(f"missing manifest: {manifest_path}")
    manifest = json.loads(read_text(manifest_path))
    wiki_root = manifest.get("wiki_root")
    if not wiki_root:
        raise AppendError(f"missing wiki_root in: {manifest_path}")
    return (vault_root / wiki_root).resolve()


def resolve_target(vault_root: Path, rel_file: str) -> Path:
    wiki_root = resolve_wiki_root(vault_root)
    target = (wiki_root / rel_file).resolve()
    # Containment guard — never resolve a target outside the wiki root.
    if os.path.commonpath([str(wiki_root), str(target)]) != str(wiki_root):
        raise AppendError(f"target escapes wiki_root: {target}")
    return target


# --- lock -----------------------------------------------------------------

def _lock_path(target: Path) -> Path:
    return target.with_name(target.name + ".lock")


def acquire_lock(lock_path: Path,
                 timeout: float = LOCK_TIMEOUT_SECONDS,
                 stale: float = LOCK_STALE_SECONDS,
                 poll: float = LOCK_POLL_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, f"{os.getpid()} {time.time()}".encode("ascii"))
            finally:
                os.close(fd)
            return
        except FileExistsError:
            # Held by another worker. Steal only a stale lock (a crashed holder);
            # the append is sub-second, so a lock older than `stale` is orphaned.
            try:
                age = time.time() - lock_path.stat().st_mtime
            except FileNotFoundError:
                continue  # released between our create-attempt and stat — retry
            except OSError:
                age = 0.0  # transient stat failure — treat as fresh, just wait
            if age > stale:
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                continue  # re-contend via O_EXCL; the winner creates it
            if time.monotonic() >= deadline:
                raise LockTimeout(
                    f"could not acquire lock within {timeout:.0f}s: {lock_path}"
                )
            time.sleep(poll)
        except PermissionError:
            # Windows delete-pending race: another worker is releasing the
            # lockfile (unlinked but not yet gone), or AV/the indexer holds it
            # for an instant. This is NOT a held lock — wait briefly, re-contend.
            if time.monotonic() >= deadline:
                raise LockTimeout(
                    f"lock contention did not clear within {timeout:.0f}s: {lock_path}"
                )
            time.sleep(poll)


def release_lock(lock_path: Path) -> None:
    # Never raise from release (it runs in a finally). Retry a transient hold;
    # if it ultimately fails, the lingering lock is stolen as stale by the next
    # acquirer — degraded but never a lost append.
    for _ in range(20):
        try:
            lock_path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.02)


# --- append-block ---------------------------------------------------------

def plan_append_block(before: str, entry: str, init_header: str | None,
                      exists: bool) -> str:
    entry_text = entry.strip("\n")
    if not entry_text.strip():
        raise AppendError("refusing to append an empty entry")
    if not exists:
        base = (init_header.rstrip("\n") if init_header else "").strip("\n")
        if base:
            return f"{base}\n\n{entry_text}\n"
        return f"{entry_text}\n"
    base = before.rstrip("\n")
    if not base:
        return f"{entry_text}\n"
    return f"{base}\n\n{entry_text}\n"


# --- append-row -----------------------------------------------------------

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


def _is_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def _is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(set(c) <= set("-: ") and "-" in c for c in cells)


def _dedupe_key(row: str, columns: list[int]) -> tuple[str, ...]:
    cells = split_row(row)
    key: list[str] = []
    for idx in columns:
        cell = cells[idx] if idx < len(cells) else ""
        key.append(" ".join(cell.split()).lower())
    return tuple(key)


def _find_section(lines: list[str], section: str) -> int | None:
    wanted = section.strip().lower()
    for index, line in enumerate(lines):
        if line.startswith("## ") and line[3:].strip().lower() == wanted:
            return index
    return None


def plan_append_row(before: str, section: str, row: str, dedupe_cols: list[int],
                    init_header: str | None, exists: bool) -> tuple[str, bool]:
    """Return (new_content, skipped). skipped=True → row already present (dedupe)."""
    row_text = row.strip()
    if not row_text.startswith("|"):
        raise AppendError(f"row is not a markdown table row: {row_text!r}")

    if not exists:
        if not init_header:
            raise AppendError("target missing and no --init-header given")
        base = init_header.rstrip("\n")
        return f"{base}\n{row_text}\n", False

    lines = before.split("\n")
    trailing_nl = before.endswith("\n")
    if trailing_nl:
        lines = lines[:-1]  # drop the empty element from the final newline

    section_index = _find_section(lines, section)
    if section_index is None:
        raise AppendError(f"section not found: ## {section}")

    # Bound the search to this section (until the next H2 or EOF).
    end = len(lines)
    for i in range(section_index + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break

    # Locate the contiguous table block inside the section: header row,
    # separator row, then data rows.
    header_idx = None
    for i in range(section_index + 1, end):
        if _is_table_line(lines[i]):
            header_idx = i
            break
    if header_idx is None or header_idx + 1 >= end or not _is_table_line(lines[header_idx + 1]):
        raise AppendError(f"no table found under section: ## {section}")

    last_row_idx = header_idx + 1  # the separator row, at minimum
    data_rows: list[str] = []
    for i in range(header_idx + 2, end):
        if not _is_table_line(lines[i]):
            break
        last_row_idx = i
        data_rows.append(lines[i])

    if dedupe_cols:
        new_key = _dedupe_key(row_text, dedupe_cols)
        for existing in data_rows:
            if _dedupe_key(existing, dedupe_cols) == new_key:
                return before, True  # already present — no-op

    lines.insert(last_row_idx + 1, row_text)
    new_content = "\n".join(lines)
    if trailing_nl:
        new_content += "\n"
    return new_content, False


# --- read entry / row text ------------------------------------------------

def load_payload(inline: str | None, payload_file: str | None) -> str:
    if payload_file:
        return Path(payload_file).read_text(encoding="utf-8")
    if inline is not None:
        return inline
    return sys.stdin.read()


# --- CLI ------------------------------------------------------------------

def run_append_block(args: argparse.Namespace) -> int:
    vault_root = Path(args.vault_root).resolve()
    target = resolve_target(vault_root, args.file)
    entry = load_payload(args.entry, args.entry_file)
    lock_path = _lock_path(target)
    acquire_lock(lock_path)
    try:
        exists = target.is_file()
        before = read_text(target) if exists else ""
        after = plan_append_block(before, entry, args.init_header, exists)
        changed = after != before
        print(f"MODE: {'DRY-RUN' if args.dry_run else 'APPLY'}")
        print(f"{target}: append-block; changed={str(changed).lower()}")
        if not args.dry_run and changed:
            target.parent.mkdir(parents=True, exist_ok=True)
            write_text_verified(target, after)
    finally:
        release_lock(lock_path)
    if not args.dry_run and args.consume and args.entry_file:
        try:
            Path(args.entry_file).unlink()
        except FileNotFoundError:
            pass
    return 0


def run_append_row(args: argparse.Namespace) -> int:
    vault_root = Path(args.vault_root).resolve()
    target = resolve_target(vault_root, args.file)
    row = load_payload(args.row, args.row_file).strip("\n")
    dedupe_cols = [int(c) for c in args.dedupe_cols.split(",")] if args.dedupe_cols else []
    lock_path = _lock_path(target)
    acquire_lock(lock_path)
    try:
        exists = target.is_file()
        before = read_text(target) if exists else ""
        after, skipped = plan_append_row(
            before, args.section, row, dedupe_cols, args.init_header, exists
        )
        changed = after != before
        print(f"MODE: {'DRY-RUN' if args.dry_run else 'APPLY'}")
        if skipped:
            print(f"{target}: append-row; SKIPPED (duplicate key); changed=false")
        else:
            print(f"{target}: append-row under '## {args.section}'; changed={str(changed).lower()}")
        if not args.dry_run and changed:
            target.parent.mkdir(parents=True, exist_ok=True)
            write_text_verified(target, after)
    finally:
        release_lock(lock_path)
    if not args.dry_run and args.consume and args.row_file:
        try:
            Path(args.row_file).unlink()
        except FileNotFoundError:
            pass
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--vault-root", default=str(Path.cwd()))
    common.add_argument("--file", required=True,
                        help="target path relative to wiki_root, e.g. logs/mentions.md")
    common.add_argument("--init-header",
                        help="header text written only when the target is created")
    common.add_argument("--consume", action="store_true",
                        help="delete --entry-file / --row-file after a successful write")
    common.add_argument("--dry-run", action="store_true")

    pb = sub.add_parser("append-block", parents=[common],
                        help="append an H2 log entry at EOF (blank-line separated)")
    pb.add_argument("--entry", help="entry text (inline)")
    pb.add_argument("--entry-file", help="file holding the entry text")
    pb.set_defaults(func=run_append_block)

    pr = sub.add_parser("append-row", parents=[common],
                        help="insert a table row at the end of a section's table")
    pr.add_argument("--section", required=True,
                    help="H2 section title whose table receives the row")
    pr.add_argument("--row", help="markdown table row (inline)")
    pr.add_argument("--row-file", help="file holding the table row")
    pr.add_argument("--dedupe-cols", default="",
                    help="comma-separated column indices forming the dedupe key")
    pr.set_defaults(func=run_append_row)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except LockTimeout as exc:
        print(f"ERROR: lock timeout: {exc}", file=sys.stderr)
        return 2
    except AppendError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — surface any unexpected failure cleanly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
