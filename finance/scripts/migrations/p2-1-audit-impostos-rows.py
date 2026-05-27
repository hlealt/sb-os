"""p2-1 audit: enumerate all ledger rows where category="impostos".

Scans all transactions.csv files under ledgers/fechamento/ and prints a
structured report of every row carrying category="impostos".

Run:
    python p2-1-audit-impostos-rows.py           # tabular report
    python p2-1-audit-impostos-rows.py --json    # machine-readable JSON
"""

import argparse
import csv
import json
import sys
from pathlib import Path


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "sb-os.json").exists() or (parent / ".obsidian").exists():
            return parent
    raise RuntimeError("Vault root not found (looking for sb-os.json or .obsidian)")


def find_impostos_rows(ledger_base: Path) -> list[dict]:
    """Return all rows with category='impostos' across all fechamento months."""
    rows = []
    for month_dir in sorted(ledger_base.iterdir()):
        txfile = month_dir / "transactions.csv"
        if not txfile.exists():
            continue
        with open(txfile, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("category", "").strip() == "impostos":
                    rows.append({
                        "month": month_dir.name,
                        "date": row.get("date", ""),
                        "description": row.get("description", ""),
                        "amount": row.get("amount", ""),
                        "bank": row.get("bank", ""),
                        "supplier_canonical": row.get("supplier_canonical", ""),
                        "tags": row.get("tags", ""),
                        "match_confidence": row.get("match_confidence", ""),
                        "source_file": str(txfile),
                    })
    return rows


def print_report(rows: list[dict]) -> None:
    print(f"impostos-category audit — {len(rows)} row(s) found")
    print("-" * 80)
    for r in rows:
        print(
            f"  [{r['month']}] {r['date']}  bank={r['bank']}  "
            f"amount={r['amount']:>10}  supplier={r['supplier_canonical']!r}  "
            f"tags={r['tags']!r}"
        )
        print(f"           desc: {r['description']}")
    print("-" * 80)
    if not rows:
        print("  CLEAN — no category='impostos' rows in any ledger.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit category='impostos' ledger rows (p2-1)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    vault = _find_vault_root()
    ledger_base = vault / ".user" / "finance" / "bookkeeper" / "ledgers" / "fechamento"

    if not ledger_base.exists():
        print(f"ERROR: ledger base not found: {ledger_base}", file=sys.stderr)
        return 1

    rows = find_impostos_rows(ledger_base)

    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        print_report(rows)

    return 0


if __name__ == "__main__":
    sys.exit(main())
