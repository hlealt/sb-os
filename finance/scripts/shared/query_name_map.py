"""query-name-map: read tool over the investimentos name-map ledger (p4-4).

Surfaces the ticker/instrument name-map entries from
.user/finance/bookkeeper/ledgers/investimentos/name_map.csv in human-readable
form so bookkeeper can inspect canonical mappings without reading the raw CSV.

This tool is READ-ONLY. It NEVER writes to name_map.csv.

Usage:
    python query_name_map.py [options]

Options:
    --source SOURCE        Filter by parser source (b3, safra, bipa, etc.)
    --field FIELD          Filter by field name (fundo, produto, etc.)
    --raw PATTERN          Filter by raw_value containing PATTERN (case-insensitive)
    --canonical PATTERN    Filter by canonical_value containing PATTERN
    --asset-type TYPE      Filter by asset_type
    --limit N              Max rows to return (default: 30, hard cap: 200)
    --name-map-path PATH   Override path to name_map.csv (for testing)

Exit codes:
    0  Rows found and printed
    1  No rows matched or name_map.csv not found
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

_SLICE_CAP = 200
_SLICE_DEFAULT = 30


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "sb-os.json").exists() or (parent / ".obsidian").exists():
            return parent
    raise RuntimeError("Vault root not found (looking for sb-os.json or .obsidian)")


def _default_name_map_path() -> Path:
    override = os.environ.get("BOOKKEEPER_NAME_MAP_PATH")
    if override:
        return Path(override)
    return (
        _find_vault_root()
        / ".user" / "finance" / "bookkeeper"
        / "ledgers" / "investimentos" / "name_map.csv"
    )


def query_name_map(
    filepath: Path,
    source: str | None = None,
    field: str | None = None,
    raw_pattern: str | None = None,
    canonical_pattern: str | None = None,
    asset_type: str | None = None,
    limit: int = _SLICE_DEFAULT,
) -> list[dict]:
    """Return matching rows from name_map.csv.

    Returns empty list if the file does not exist (fail-soft).
    Expected CSV columns: source, field, raw_value, canonical_value, asset_type
    """
    limit = min(limit, _SLICE_CAP)
    if not filepath.exists():
        return []
    rows: list[dict] = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if source and row.get("source", "").strip().lower() != source.lower():
                continue
            if field and row.get("field", "").strip().lower() != field.lower():
                continue
            if raw_pattern:
                if raw_pattern.lower() not in row.get("raw_value", "").strip().lower():
                    continue
            if canonical_pattern:
                if canonical_pattern.lower() not in row.get("canonical_value", "").strip().lower():
                    continue
            if asset_type:
                if row.get("asset_type", "").strip().lower() != asset_type.lower():
                    continue
            rows.append(dict(row))
            if len(rows) >= limit:
                break
    return rows


def _print_table(rows: list[dict]) -> None:
    if not rows:
        return
    cols = ["source", "field", "raw_value", "canonical_value", "asset_type"]
    cols = [c for c in cols if c in rows[0]]
    widths = {}
    for c in cols:
        max_val = max((len(str(r.get(c, ""))) for r in rows), default=0)
        widths[c] = min(max(len(c), max_val), 50)
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    sep = "  ".join("-" * widths[c] for c in cols)
    print(header)
    print(sep)
    for row in rows:
        print("  ".join(str(row.get(c, ""))[:widths[c]].ljust(widths[c]) for c in cols))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query the investimentos name-map (read-only)."
    )
    parser.add_argument("--source", help="Filter by source (b3, safra, bipa, …)")
    parser.add_argument("--field", help="Filter by field name (fundo, produto, …)")
    parser.add_argument("--raw", dest="raw_pattern", help="Filter raw_value containing PATTERN")
    parser.add_argument("--canonical", dest="canonical_pattern",
                        help="Filter canonical_value containing PATTERN")
    parser.add_argument("--asset-type", help="Filter by asset_type")
    parser.add_argument(
        "--limit", type=int, default=_SLICE_DEFAULT,
        help=f"Max rows (default {_SLICE_DEFAULT}, hard cap {_SLICE_CAP})",
    )
    parser.add_argument(
        "--name-map-path",
        help="Override path to name_map.csv (absolute or relative to cwd)",
    )
    args = parser.parse_args()

    if args.name_map_path:
        filepath = Path(args.name_map_path)
    else:
        filepath = _default_name_map_path()

    if not filepath.exists():
        print(f"ERROR: name_map.csv not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    rows = query_name_map(
        filepath,
        source=args.source,
        field=args.field,
        raw_pattern=args.raw_pattern,
        canonical_pattern=args.canonical_pattern,
        asset_type=args.asset_type,
        limit=args.limit,
    )

    if not rows:
        print("No name-map entries matched the given filters.")
        sys.exit(1)

    effective_limit = min(args.limit, _SLICE_CAP)
    print(f"=== name_map.csv — {len(rows)} entry/entries (limit={effective_limit}) ===")
    _print_table(rows)
    print(f"\n[{len(rows)} row(s) shown. Use --limit / --source / --field to narrow.]")


if __name__ == "__main__":
    main()
