"""sample-from-ledger: spot-checkable row slices from ledger CSVs (p4-2).

Returns a small, bounded slice of rows from a normalized per-bank extrato CSV
or a fechamento transactions.csv so `bookkeeper` can validate by judgment
WITHOUT reading raw CSVs/JSONs directly — closing the P0 gap for tools-only
access during Pass 1.

This tool is READ-ONLY. It NEVER writes to any ledger.

Usage:
    python sample_from_ledger.py <ledger> [options]

Arguments:
    ledger       One of:
                   expenses/<YYYY-MM>/<bank>_extrato.csv  — per-bank extrato
                   expenses/<YYYY-MM>/<bank>_fatura.csv   — per-bank fatura
                   fechamento/<YYYY-MM>/transactions.csv  — rolled-up ledger
                 Path is relative to .user/finance/bookkeeper/ledgers/.
                 May also be an absolute path.

Options:
    --month YYYY-MM        Filter rows by month (date column starts with YYYY-MM)
    --category CAT         Filter rows by category (transactions.csv only)
    --vendor PATTERN       Filter rows by description containing PATTERN (case-insensitive)
    --amount-min FLOAT     Filter rows where abs(amount) >= FLOAT
    --amount-max FLOAT     Filter rows where abs(amount) <= FLOAT
    --limit N              Max rows to return (default: 20, hard cap: 50)
    --offset N             Skip first N matching rows (pagination)

Slice-size guardrail: --limit is capped at 50. The full ledger is NEVER
returned by this tool regardless of arguments.

Exit codes:
    0  Rows found and printed
    1  No rows matched filters or file not found
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

_SLICE_CAP = 50
_SLICE_DEFAULT = 20


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "sb-os.json").exists() or (parent / ".obsidian").exists():
            return parent
    raise RuntimeError("Vault root not found (looking for sb-os.json or .obsidian)")


def _resolve_ledger_path(ledger_arg: str) -> Path:
    """Resolve ledger path: absolute, or relative to .user/finance/bookkeeper/ledgers/."""
    p = Path(ledger_arg)
    if p.is_absolute():
        return p
    override = os.environ.get("BOOKKEEPER_LEDGER_DIR")
    if override:
        return Path(override) / p
    return _find_vault_root() / ".user" / "finance" / "bookkeeper" / "ledgers" / p


def _matches(row: dict, month: str | None, category: str | None,
             vendor: str | None, amount_min: float | None,
             amount_max: float | None) -> bool:
    if month:
        date_val = row.get("date", "")
        if not date_val.startswith(month):
            return False
    if category:
        if row.get("category", "").lower() != category.lower():
            return False
    if vendor:
        desc = row.get("description", "")
        if vendor.lower() not in desc.lower():
            return False
    if amount_min is not None or amount_max is not None:
        try:
            amt = abs(float(row.get("amount", "0") or "0"))
        except ValueError:
            return False
        if amount_min is not None and amt < amount_min:
            return False
        if amount_max is not None and amt > amount_max:
            return False
    return True


def sample_ledger(
    ledger_path: Path,
    month: str | None = None,
    category: str | None = None,
    vendor: str | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    limit: int = _SLICE_DEFAULT,
    offset: int = 0,
) -> list[dict]:
    """Return a bounded slice of rows from a ledger CSV.

    Always respects the SLICE_CAP guardrail — never returns more than 50 rows.
    """
    limit = min(limit, _SLICE_CAP)
    if not ledger_path.exists():
        return []
    results: list[dict] = []
    skipped = 0
    with open(ledger_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not _matches(row, month, category, vendor, amount_min, amount_max):
                continue
            if skipped < offset:
                skipped += 1
                continue
            results.append(dict(row))
            if len(results) >= limit:
                break
    return results


def _print_table(rows: list[dict], columns: list[str] | None = None) -> None:
    if not rows:
        return
    cols = columns or list(rows[0].keys())
    # Compute column widths
    widths = {c: max(len(c), max((len(str(r.get(c, ""))) for r in rows), default=0)) for c in cols}
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    sep = "  ".join("-" * widths[c] for c in cols)
    print(header)
    print(sep)
    for row in rows:
        print("  ".join(str(row.get(c, "")).ljust(widths[c]) for c in cols))


# Key columns to show for each ledger type (keeps output readable)
_EXTRATO_COLS = ["date", "description", "amount", "balance", "bank", "source_type"]
_TRANSACTIONS_COLS = ["date", "description", "amount", "category", "supplier_canonical",
                      "tags", "data_competencia", "manual_override"]


def _detect_columns(rows: list[dict]) -> list[str]:
    if not rows:
        return []
    keys = list(rows[0].keys())
    if "category" in keys:
        # transactions.csv
        return [c for c in _TRANSACTIONS_COLS if c in keys]
    return [c for c in _EXTRATO_COLS if c in keys]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Return a bounded spot-checkable slice of ledger rows."
    )
    parser.add_argument(
        "ledger",
        help="Ledger path, relative to .user/finance/bookkeeper/ledgers/ or absolute.",
    )
    parser.add_argument("--month", help="Filter by month prefix (YYYY-MM)")
    parser.add_argument("--category", help="Filter by category (transactions.csv)")
    parser.add_argument("--vendor", help="Filter by description pattern (case-insensitive)")
    parser.add_argument("--amount-min", type=float, help="Filter abs(amount) >= value")
    parser.add_argument("--amount-max", type=float, help="Filter abs(amount) <= value")
    parser.add_argument(
        "--limit", type=int, default=_SLICE_DEFAULT,
        help=f"Max rows (default {_SLICE_DEFAULT}, hard cap {_SLICE_CAP})",
    )
    parser.add_argument("--offset", type=int, default=0, help="Skip first N matching rows")
    args = parser.parse_args()

    ledger_path = _resolve_ledger_path(args.ledger)
    if not ledger_path.exists():
        print(f"ERROR: Ledger not found: {ledger_path}", file=sys.stderr)
        sys.exit(1)

    rows = sample_ledger(
        ledger_path,
        month=args.month,
        category=args.category,
        vendor=args.vendor,
        amount_min=args.amount_min,
        amount_max=args.amount_max,
        limit=args.limit,
        offset=args.offset,
    )

    if not rows:
        print("No rows matched the given filters.")
        sys.exit(1)

    effective_limit = min(args.limit, _SLICE_CAP)
    print(f"=== {ledger_path.name} — {len(rows)} row(s) (limit={effective_limit}, offset={args.offset}) ===")
    cols = _detect_columns(rows)
    _print_table(rows, cols)
    print(f"\n[Slice guardrail: max {_SLICE_CAP} rows per call. Use --offset to paginate.]")


if __name__ == "__main__":
    main()
