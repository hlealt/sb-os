"""query-corrections: read tool over the corrections side-ledgers (p4-3).

Queries the append-only corrections side-ledgers under
.user/finance/bookkeeper/config/corrections/ and returns human-readable rows
answering "what corrections exist for this tx / month / category / identity key?"

Covered corrections files:
  - manual-overrides.csv        (category/tags override per transaction)
  - competencia-overrides.csv   (data_competencia override per transaction)
  - category-migrations.csv     (retroactive category recoding)
  - code_migrations.csv         (broker recode for cross-asset edge cases)
  - vendor-canonicals.csv       (canonical vendor mapping)
  - tag-renames.csv             (tag rename mapping)
  - stocks.csv, fii.csv, rf.csv, crypto.csv, intl.csv, funds.csv
    (per-asset-type generic corrections)
  Any additional *.csv files present in the corrections directory.

This tool is READ-ONLY. It NEVER writes to any corrections file.

Usage:
    python query_corrections.py [--file NAME] [--month YYYY-MM]
                                [--category CAT] [--identity KEY]
                                [--pattern PATTERN] [--limit N]

Options:
    --file NAME        Only query this corrections file (base name, e.g.
                       manual-overrides or manual-overrides.csv). Omit to
                       query all files.
    --month YYYY-MM    Filter rows where any column starts with YYYY-MM.
    --category CAT     Filter rows where any column equals CAT (case-insensitive).
    --identity KEY     Filter rows where tx_date|tx_description|tx_amount matches
                       KEY (pipe-separated composite identity).
    --pattern PATTERN  Filter rows where any column contains PATTERN (case-insensitive).
    --limit N          Max rows per file (default: 30, hard cap: 100).

Exit codes:
    0  Rows found
    1  No rows matched or corrections directory not found
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

_SLICE_CAP = 100
_SLICE_DEFAULT = 30

# Corrections files listed in CONVENTION.md — checked first, then any extra *.csv
_KNOWN_FILES = [
    "manual-overrides.csv",
    "competencia-overrides.csv",
    "category-migrations.csv",
    "code_migrations.csv",
    "vendor-canonicals.csv",
    "tag-renames.csv",
    "stocks.csv",
    "fii.csv",
    "rf.csv",
    "crypto.csv",
    "intl.csv",
    "funds.csv",
]


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "sb-os.json").exists() or (parent / ".obsidian").exists():
            return parent
    raise RuntimeError("Vault root not found (looking for sb-os.json or .obsidian)")


def _resolve_corrections_dir() -> Path:
    """Resolve corrections directory.

    Override for test isolation: set BOOKKEEPER_CONFIG_DIR to a path and this
    function derives the corrections dir from it.
    """
    override = os.environ.get("BOOKKEEPER_CONFIG_DIR")
    if override:
        return Path(override) / "corrections"
    return (
        _find_vault_root()
        / ".user" / "finance" / "bookkeeper" / "config" / "corrections"
    )


def _matches(row: dict, month: str | None, category: str | None,
             identity: str | None, pattern: str | None) -> bool:
    values = list(row.values())
    if month:
        if not any(str(v).startswith(month) for v in values):
            return False
    if category:
        if not any(str(v).lower() == category.lower() for v in values):
            return False
    if identity:
        parts = [p.strip() for p in identity.split("|")]
        row_vals = [str(v).strip() for v in values]
        if not all(p in row_vals for p in parts):
            return False
    if pattern:
        if not any(pattern.lower() in str(v).lower() for v in values):
            return False
    return True


def query_corrections_file(
    filepath: Path,
    month: str | None = None,
    category: str | None = None,
    identity: str | None = None,
    pattern: str | None = None,
    limit: int = _SLICE_DEFAULT,
) -> list[dict]:
    """Return matching rows from a single corrections CSV.

    Returns empty list if the file does not exist (fail-soft per CONVENTION.md).
    """
    limit = min(limit, _SLICE_CAP)
    if not filepath.exists():
        return []
    rows: list[dict] = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            if not _matches(row, month, category, identity, pattern):
                continue
            rows.append(dict(row))
            if len(rows) >= limit:
                break
    return rows


def _corrections_files(corrections_dir: Path, target_file: str | None) -> list[Path]:
    """List corrections files to query."""
    if target_file:
        name = target_file if target_file.endswith(".csv") else target_file + ".csv"
        return [corrections_dir / name]

    # Known files first (in CONVENTION.md order), then any extra *.csv files
    known = [corrections_dir / f for f in _KNOWN_FILES]
    extra = sorted(
        p for p in corrections_dir.glob("*.csv")
        if p.name not in _KNOWN_FILES
    )
    return known + extra


def _print_table(rows: list[dict]) -> None:
    if not rows:
        return
    cols = list(rows[0].keys())
    widths = {c: max(len(c), max((len(str(r.get(c, ""))) for r in rows), default=0)) for c in cols}
    widths = {c: min(w, 40) for c, w in widths.items()}  # cap column width at 40
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    sep = "  ".join("-" * widths[c] for c in cols)
    print(header)
    print(sep)
    for row in rows:
        print("  ".join(str(row.get(c, ""))[:widths[c]].ljust(widths[c]) for c in cols))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query corrections side-ledgers (read-only)."
    )
    parser.add_argument(
        "--file",
        help="Query only this corrections file (base name or with .csv). Omit for all.",
    )
    parser.add_argument("--month", help="Filter rows containing YYYY-MM in any column")
    parser.add_argument("--category", help="Filter rows where any column equals CAT")
    parser.add_argument(
        "--identity",
        help="Filter by composite key tx_date|tx_description|tx_amount",
    )
    parser.add_argument("--pattern", help="Filter rows where any column contains PATTERN")
    parser.add_argument(
        "--limit", type=int, default=_SLICE_DEFAULT,
        help=f"Max rows per file (default {_SLICE_DEFAULT}, hard cap {_SLICE_CAP})",
    )
    args = parser.parse_args()

    corrections_dir = _resolve_corrections_dir()
    if not corrections_dir.exists():
        print(f"ERROR: Corrections directory not found: {corrections_dir}", file=sys.stderr)
        sys.exit(1)

    files = _corrections_files(corrections_dir, args.file)
    total_found = 0

    for filepath in files:
        rows = query_corrections_file(
            filepath,
            month=args.month,
            category=args.category,
            identity=args.identity,
            pattern=args.pattern,
            limit=args.limit,
        )
        if not rows:
            continue
        total_found += len(rows)
        print(f"\n=== {filepath.name} — {len(rows)} row(s) ===")
        _print_table(rows)

    if total_found == 0:
        print("No correction rows matched the given filters.")
        sys.exit(1)

    print(f"\n[Total: {total_found} row(s) across all queried files]")


if __name__ == "__main__":
    main()
