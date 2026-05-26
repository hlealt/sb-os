"""Snapshot contamination detector (p1-5).

For each dated snapshot in the investimentos ledger directory, compares
every position's price_date against meta.cut_date.  A snapshot is
CONTAMINATED if any position has price_source='api' AND
price_date != meta.cut_date (mixed-date contamination per p2-24).

Usage:
    python detect_snapshot_contamination.py [--snapshots-dir PATH]

Exit codes:
    0  No contamination found
    1  One or more snapshots are contaminated
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return parent
    raise RuntimeError(f"Vault root not found from {__file__}")


_DEFAULT_SNAPSHOTS_DIR = (
    _find_vault_root()
    / ".user" / "finance" / "bookkeeper" / "ledgers" / "investimentos"
)


def check_snapshot(snapshot_path: Path) -> dict:
    """Check a single snapshot file for mixed-date contamination.

    Returns a result dict with keys:
        snapshot     - filename
        cut_date     - meta.cut_date
        contaminated - bool
        offenders    - list of {id, price_source, price_date} for mismatched positions
        clean_priced - count of api-priced positions with correct date
        missing      - count of positions with price_source='missing'
    """
    with open(snapshot_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cut_date = data.get("meta", {}).get("cut_date", "")
    positions = data.get("positions", [])

    offenders = []
    clean_priced = 0
    missing_count = 0

    for pos in positions:
        price_source = pos.get("price_source", "")
        price_date = pos.get("price_date", "")

        if price_source == "missing":
            missing_count += 1
            continue

        if price_source != "api":
            # balcao / snapshot source — not subject to the API contamination check
            continue

        # price_source == 'api': date must match cut_date
        if price_date != cut_date:
            offenders.append({
                "id": pos.get("id"),
                "price_source": price_source,
                "price_date": price_date,
                "cut_date": cut_date,
            })
        else:
            clean_priced += 1

    return {
        "snapshot": snapshot_path.name,
        "cut_date": cut_date,
        "contaminated": len(offenders) > 0,
        "offenders": offenders,
        "clean_priced": clean_priced,
        "missing": missing_count,
    }


def detect_contamination(snapshots_dir: Path) -> list[dict]:
    """Check all portfolio-{date}.json files in snapshots_dir.

    Returns list of result dicts (one per snapshot), sorted by cut_date.
    """
    snapshot_files = sorted(snapshots_dir.glob("portfolio-????-??-??.json"))
    return [check_snapshot(p) for p in snapshot_files]


def _print_report(results: list[dict]) -> None:
    any_contaminated = any(r["contaminated"] for r in results)

    print(f"Contamination report — {len(results)} snapshot(s) checked")
    print("-" * 60)
    for r in results:
        status = "CONTAMINATED" if r["contaminated"] else "CLEAN"
        print(f"  {r['snapshot']}  [{status}]")
        print(f"    cut_date     : {r['cut_date']}")
        print(f"    api-priced   : {r['clean_priced']} clean, {len(r['offenders'])} mismatched")
        print(f"    missing      : {r['missing']}")
        if r["offenders"]:
            for o in r["offenders"]:
                print(
                    f"    MISMATCH  id={o['id']}  price_date={o['price_date']}  "
                    f"cut_date={o['cut_date']}"
                )
    print("-" * 60)
    if any_contaminated:
        contaminated = [r["snapshot"] for r in results if r["contaminated"]]
        print(f"RESULT: CONTAMINATION DETECTED in {contaminated}")
    else:
        print("RESULT: No contamination — all api-priced positions have price_date == cut_date")


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect mixed-date snapshot contamination")
    parser.add_argument(
        "--snapshots-dir",
        type=Path,
        default=_DEFAULT_SNAPSHOTS_DIR,
        help="Directory containing portfolio-{date}.json files",
    )
    args = parser.parse_args()

    if not args.snapshots_dir.is_dir():
        print(f"ERROR: snapshots directory not found: {args.snapshots_dir}", file=sys.stderr)
        raise SystemExit(2)

    results = detect_contamination(args.snapshots_dir)

    if not results:
        print("No dated snapshots found.")
        raise SystemExit(0)

    _print_report(results)

    any_contaminated = any(r["contaminated"] for r in results)
    raise SystemExit(1 if any_contaminated else 0)


if __name__ == "__main__":
    main()
