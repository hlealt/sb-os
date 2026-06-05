"""audit_balcao_dups: cross-source duplicate detection in balcao.csv (p4-11).

Scans balcao.csv for rows that share the same (date, operation, |amount|) triple
across different source values — indicating cross-source duplication (e.g., both
b3_manual and safra_movimentacoes recorded the same amortization event).

Groups made of exactly one safra_movimentacoes row plus b3/b3_manual rows are
neutralized at read time by `_dedup_cross_source_balcao` (position_calculator.py,
applied via `load_balcao`) and are reported as informational. Ledger rows are
NEVER deleted — append-only + consumer-side filter convention
(config/corrections/CONVENTION.md).

Without --product-id, scans all assets. With --product-id, narrows to that asset.

This tool is READ-ONLY. It NEVER writes to any ledger.

Usage:
    python audit_balcao_dups.py [--product-id ID] [--ledger-dir PATH]

Exit codes:
    0  No duplicates, or every group is covered by the read-time dedup
    1  Uncovered duplicates detected (or balcao.csv not found)
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from pathlib import Path


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "sb-os.json").exists() or (parent / ".obsidian").exists():
            return parent
    raise RuntimeError("Vault root not found")


def _default_ledger_dir() -> Path:
    override = os.environ.get("BOOKKEEPER_INVESTIMENTOS_DIR")
    if override:
        return Path(override)
    return _find_vault_root() / ".user" / "finance" / "bookkeeper" / "ledgers" / "investimentos"


def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def find_duplicate_groups(rows: list[dict], product_id: str | None) -> dict[str, list[list[dict]]]:
    """Return {product_id: [group, ...]} for cross-source duplicates.

    A duplicate group is a set of rows sharing (date, operation, |amount|)
    across at least 2 distinct sources.
    """
    if product_id:
        rows = [r for r in rows if r.get("product_id") == product_id]

    # Group by product_id first
    by_product: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        pid = r.get("product_id", "")
        by_product[pid].append(r)

    result: dict[str, list[list[dict]]] = {}
    for pid, prod_rows in by_product.items():
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for r in prod_rows:
            try:
                amt = round(abs(float(r.get("amount") or 0)), 2)
            except (TypeError, ValueError):
                continue
            key = (r.get("date", ""), (r.get("operation") or "").lower(), amt)
            groups[key].append(r)
        dup_groups = [g for g in groups.values() if len({r.get("source", "") for r in g}) > 1]
        if dup_groups:
            result[pid] = dup_groups
    return result


def group_covered_by_read_time_dedup(group: list[dict]) -> bool:
    """True if `_dedup_cross_source_balcao` collapses this group to one row.

    The read-time filter (position_calculator.py, applied via `load_balcao`)
    drops b3 / b3_manual rows whose key matches a safra_movimentacoes row.
    A group is fully neutralized when it has exactly one safra_movimentacoes
    row and every other row is b3 / b3_manual.
    """
    sources = [(r.get("source") or "").strip() for r in group]
    others = [s for s in sources if s != "safra_movimentacoes"]
    return (sources.count("safra_movimentacoes") == 1 and bool(others)
            and all(s in ("b3", "b3_manual") for s in others))


def print_report(dup_groups: dict[str, list[list[dict]]], product_id: str | None) -> int:
    """Print the duplicate report. Returns count of groups NOT covered by read-time dedup."""
    scope = f"product_id={product_id}" if product_id else "all assets"
    total_groups = sum(len(groups) for groups in dup_groups.values())

    print(f"\n{'='*70}")
    print(f"  audit_balcao_dups — scope: {scope}")
    print("=" * 70)

    if not dup_groups:
        print(f"\n  No cross-source duplicates found.")
        print("=" * 70)
        return 0

    print(f"\n  Found {total_groups} duplicate group(s) across {len(dup_groups)} asset(s).")
    print(f"  Read-time dedup precedence: safra_movimentacoes > b3 > b3_manual\n")

    uncovered_total = 0
    for pid in sorted(dup_groups.keys()):
        groups = dup_groups[pid]
        print(f"  ── {pid} ({len(groups)} duplicate group(s)) ──")
        for i, grp in enumerate(groups, start=1):
            sample = grp[0]
            amt = abs(float(sample.get("amount") or 0))
            covered = group_covered_by_read_time_dedup(grp)
            if not covered:
                uncovered_total += 1
            marker = "handled at read time" if covered else "NOT covered — investigate"
            print(f"    Group {i}: date={sample.get('date')}  "
                  f"op={sample.get('operation')}  amount={amt:.2f}  [{marker}]")
            for r in grp:
                print(f"      source={r.get('source'):<30}  amount={r.get('amount')}")
        print()

    if uncovered_total:
        print(f"  Action: {uncovered_total} group(s) NOT covered by `_dedup_cross_source_balcao` —")
        print("  resolve via a corrections entry (config/corrections/, consumer-side filter).")
        print("  NEVER delete ledger rows (append-only convention).")
    else:
        print("  All groups are neutralized at read time by `_dedup_cross_source_balcao`")
        print("  (position_calculator.py). Ledger rows stay — append-only convention.")
    print("=" * 70)
    return uncovered_total


def audit(ledger_dir: Path, product_id: str | None) -> int:
    """Run the audit. Returns exit code (0=clean or all covered, 1=uncovered duplicates or file missing)."""
    balcao_path = ledger_dir / "balcao.csv"
    if not balcao_path.exists():
        print(f"ERROR: balcao.csv not found: {balcao_path}", file=sys.stderr)
        return 1

    rows = _load_csv(balcao_path)
    dup_groups = find_duplicate_groups(rows, product_id)
    count = print_report(dup_groups, product_id)
    return 1 if count > 0 else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect cross-source duplicates in balcao.csv."
    )
    parser.add_argument("--product-id", help="Narrow scan to one product_id")
    parser.add_argument("--ledger-dir", help="Override investimentos ledger directory")
    args = parser.parse_args()

    ledger_dir = Path(args.ledger_dir) if args.ledger_dir else _default_ledger_dir()
    sys.exit(audit(ledger_dir, args.product_id))


if __name__ == "__main__":
    main()
