"""
Orphan Detection — sb-os vault utility.

Finds .md files with zero incoming wiki-links — files not reachable from
any other vault file via [[wiki-link]] traversal.

Usage:
    python orphan-detection.py [--vault-path PATH] [--entry-points FILES] [--json]

Options:
    --vault-path PATH       Vault root (default: current directory).
    --entry-points FILES    Comma-separated list of filenames that are entry
                            points and must never be reported as orphans
                            (default: Home.md).
    --json                  Emit machine-readable JSON instead of grouped text.

Output: orphans grouped by folder, or JSON when --json is set.
"""

import os
import re
import json
import argparse
from pathlib import Path
from collections import defaultdict

# Directories to completely ignore (not scanned, not reported).
# These follow sb-os PARA conventions — users with custom layouts can fork.
IGNORE_DIRS = {".obsidian", ".claude", "Templates", "Files", "node_modules", ".git",
               ".venv", "4-archives", "5-workbench"}

# Default entry points — files that are never orphans (overridable via --entry-points).
DEFAULT_ENTRY_POINTS = {"Home.md"}

# Patterns for files that are never orphans by convention.
CONVENTION_PATTERNS = [
    re.compile(r"^\d{4}-\d{2}-\d{2}\.md$"),      # Daily notes:     2026-03-30.md
    re.compile(r"^\d{4}-W\d{2}\.md$"),            # Weekly notes:    2026-W13.md
    re.compile(r"^\d{4}-\d{2}\.md$"),             # Monthly notes:   2026-03.md
    re.compile(r"^\d{4}-Q\d\.md$"),               # Quarterly notes: 2026-Q1.md
    re.compile(r"^CLAUDE\.md$"),                   # Agent-facing file maps
    re.compile(r"^README\.md$"),                   # READMEs from external repos
]

# Wiki-link pattern: [[target]] or [[target|alias]] or [[target#heading]].
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")


def is_index_file(filepath: str, vault_root: str) -> bool:
    """Index file = filename matches its parent directory name (e.g. farm/farm.md)."""
    p = Path(filepath)
    return p.stem == p.parent.name


def should_ignore_dir(dirpath: str, vault_root: str) -> bool:
    rel = os.path.relpath(dirpath, vault_root)
    parts = Path(rel).parts
    return any(p in IGNORE_DIRS for p in parts)


def is_convention_file(filename: str) -> bool:
    return any(pat.match(filename) for pat in CONVENTION_PATTERNS)


def scan_vault(vault_path: str) -> tuple[list[str], dict[str, set[str]]]:
    """Scan vault, return (all_files, links_from_file)."""
    all_files = []
    links_from = defaultdict(set)

    vault_root_abs = os.path.abspath(vault_path)

    for dirpath, dirnames, filenames in os.walk(vault_path):
        # Prune ignored directories.
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]

        # Prune nested git repositories (any dir below vault root that contains .git).
        if os.path.abspath(dirpath) != vault_root_abs and ".git" in os.listdir(dirpath):
            dirnames[:] = []
            continue

        if should_ignore_dir(dirpath, vault_path):
            continue

        for fname in filenames:
            if not fname.endswith(".md"):
                continue

            filepath = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(filepath, vault_path).replace("\\", "/")
            all_files.append(rel_path)

            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
            except (OSError, UnicodeDecodeError):
                continue

            for match in WIKILINK_RE.finditer(content):
                target = match.group(1).strip()
                links_from[rel_path].add(target)

    return all_files, links_from


def resolve_link(target: str, all_files_map: dict[str, str]) -> str | None:
    """Resolve a wiki-link target to a file path. Obsidian matches by filename."""
    target_md = target if target.endswith(".md") else target + ".md"
    target_name = Path(target_md).name
    return all_files_map.get(target_name)


def find_orphans(vault_path: str, entry_points: set[str]) -> list[dict]:
    all_files, links_from = scan_vault(vault_path)

    # Build filename -> path map (for resolving wiki-links).
    files_by_name = {}
    for fp in all_files:
        name = Path(fp).name
        # If duplicate names, keep the first (Obsidian resolves by shortest path).
        if name not in files_by_name:
            files_by_name[name] = fp

    # Build set of all files that are linked TO by at least one other file.
    linked_to = set()
    for source, targets in links_from.items():
        for target in targets:
            resolved = resolve_link(target, files_by_name)
            if resolved:
                linked_to.add(resolved)

    orphans = []
    for fp in sorted(all_files):
        filename = Path(fp).name

        if filename in entry_points:
            continue
        if is_convention_file(filename):
            continue
        if is_index_file(fp, vault_path):
            continue
        if fp in linked_to:
            continue

        folder = str(Path(fp).parent)
        orphans.append({
            "path": fp,
            "folder": folder,
            "filename": filename,
        })

    return orphans


def parse_entry_points(value: str) -> set[str]:
    """Parse a comma-separated list of filenames into a set, stripping whitespace."""
    return {name.strip() for name in value.split(",") if name.strip()}


def main():
    parser = argparse.ArgumentParser(description="Detect orphan files in an Obsidian vault.")
    parser.add_argument("--vault-path", default=".", help="Path to vault root (default: current directory)")
    parser.add_argument(
        "--entry-points",
        default=",".join(sorted(DEFAULT_ENTRY_POINTS)),
        help="Comma-separated filenames that are never orphans (default: Home.md)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    vault_path = os.path.abspath(args.vault_path)
    entry_points = parse_entry_points(args.entry_points)
    orphans = find_orphans(vault_path, entry_points)

    if args.json:
        print(json.dumps({"orphans": orphans, "count": len(orphans)}, indent=2, ensure_ascii=False))
        return

    if not orphans:
        print("No orphan files found.")
        return

    print(f"\n{'='*60}")
    print(f"  {len(orphans)} orphan file(s) found")
    print(f"{'='*60}\n")

    by_folder = defaultdict(list)
    for o in orphans:
        by_folder[o["folder"]].append(o["filename"])

    for folder in sorted(by_folder.keys()):
        files = by_folder[folder]
        print(f"  {folder}/")
        for f in sorted(files):
            print(f"    - {f}")
        print()


if __name__ == "__main__":
    main()
