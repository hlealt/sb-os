"""Validation gate #4 — Transaction-count sanity per bank (p4-17).

Tier: P1. Auto-halt if count=0 for any present bank file, or if >10% of
rows have dates outside the expected month ±5 days.

Reads normalized expense CSVs from the expenses ledger directory and checks:
  1. No file has zero transaction rows (count=0 for a present file = bug).
  2. Date range: all dates are within expected_month ± 5 days.
     - If >10% of rows fall outside this window → FAIL.
     - expected_month defaults to the most-common year-month in the file.

Usage:
    python gate_transaction_count.py --expenses-dir PATH [--month YYYY-MM]

Exit codes:
    0   Pass — all files have rows; all within date tolerance
    1   Fail — count=0 for a present file OR >10% of rows outside date window
    2   Error — expenses directory not found
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import audit


_GATE_NAME = "gate_4_transaction_count"
_DATE_TOLERANCE_DAYS = 5
_OUTSIDE_WINDOW_THRESHOLD = 0.10  # 10%


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return parent
    raise RuntimeError(f"Vault root not found from {__file__}")


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return None


def check_file(
    csv_path: Path,
    expected_month: date | None,
) -> dict:
    """Check a single normalized CSV file.

    Returns dict with keys:
        file, row_count, outside_window, outside_pct, passed, issues
    """
    issues: list[str] = []

    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    except OSError as exc:
        return {
            "file": csv_path.name,
            "row_count": 0,
            "outside_window": 0,
            "outside_pct": 0.0,
            "passed": False,
            "issues": [f"Could not read file: {exc}"],
        }

    row_count = len(rows)

    if row_count == 0:
        return {
            "file": csv_path.name,
            "row_count": 0,
            "outside_window": 0,
            "outside_pct": 0.0,
            "passed": False,
            "issues": ["Zero transactions — file is present but empty"],
        }

    # Determine the window.  If no expected_month given, derive from most-common month.
    if expected_month is None:
        from collections import Counter
        month_counts: Counter = Counter()
        for row in rows:
            d = _parse_date(row.get("date", ""))
            if d is not None:
                month_counts[(d.year, d.month)] += 1
        if month_counts:
            (yr, mo), _ = month_counts.most_common(1)[0]
            expected_month = date(yr, mo, 1)
        else:
            # No parseable dates — skip window check.
            return {
                "file": csv_path.name,
                "row_count": row_count,
                "outside_window": 0,
                "outside_pct": 0.0,
                "passed": True,
                "issues": [],
            }

    # Build the allowed window: [first_of_month - 5 days, last_of_month + 5 days].
    import calendar
    last_day = calendar.monthrange(expected_month.year, expected_month.month)[1]
    window_start = date(expected_month.year, expected_month.month, 1) - timedelta(days=_DATE_TOLERANCE_DAYS)
    window_end = date(expected_month.year, expected_month.month, last_day) + timedelta(days=_DATE_TOLERANCE_DAYS)

    outside_window = 0
    for row in rows:
        d = _parse_date(row.get("date", ""))
        if d is not None and not (window_start <= d <= window_end):
            outside_window += 1

    outside_pct = outside_window / row_count if row_count > 0 else 0.0

    passed = True
    if outside_pct > _OUTSIDE_WINDOW_THRESHOLD:
        issues.append(
            f"{outside_window}/{row_count} rows ({outside_pct:.1%}) outside "
            f"window {window_start}..{window_end} (threshold: {_OUTSIDE_WINDOW_THRESHOLD:.0%})"
        )
        passed = False

    return {
        "file": csv_path.name,
        "row_count": row_count,
        "outside_window": outside_window,
        "outside_pct": outside_pct,
        "passed": passed,
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate #4: Transaction-count sanity per bank file."
    )
    parser.add_argument(
        "--expenses-dir",
        metavar="PATH",
        help=(
            "Path to the expenses/{YYYY-MM}/ directory containing normalized CSVs. "
            "Defaults to .user/finance/bookkeeper/ledgers/expenses/{latest-month}/"
        ),
    )
    parser.add_argument(
        "--month",
        metavar="YYYY-MM",
        help="Expected month (YYYY-MM). Derived from file contents if not given.",
    )
    args = parser.parse_args()

    # Resolve expenses directory.
    if args.expenses_dir:
        expenses_dir = Path(args.expenses_dir)
    else:
        vault_root = _find_vault_root()
        expenses_base = vault_root / ".user" / "finance" / "bookkeeper" / "ledgers" / "expenses"
        # Pick the most-recently-modified month directory.
        month_dirs = [d for d in expenses_base.iterdir() if d.is_dir() and d.name != "months.json"]
        if not month_dirs:
            print(f"ERROR: no month directories under {expenses_base}", file=sys.stderr)
            return 2
        expenses_dir = max(month_dirs, key=lambda p: p.name)

    if not expenses_dir.exists():
        print(f"ERROR: expenses directory not found: {expenses_dir}", file=sys.stderr)
        return 2

    # Parse expected month if provided.
    expected_month: date | None = None
    if args.month:
        try:
            yr, mo = args.month.split("-")
            expected_month = date(int(yr), int(mo), 1)
        except (ValueError, TypeError):
            print(f"ERROR: invalid --month value: {args.month!r} (expected YYYY-MM)", file=sys.stderr)
            return 2

    # Find all CSV files.
    csv_files = sorted(expenses_dir.glob("*.csv"))
    if not csv_files:
        # No files present — vacuous pass (the gate only fires when files are present).
        audit.emit(
            "gate_pass",
            source_function="gate_transaction_count.main",
            gate={
                "name": _GATE_NAME,
                "metric": "files_with_violations",
                "value": 0.0,
                "threshold": 0.0,
                "passed": True,
            },
            trigger_context={"expenses_dir": str(expenses_dir), "reason": "no_csv_files"},
        )
        print(f"gate_4 PASS — no CSV files in {expenses_dir} (vacuous pass)")
        return 0

    results = []
    for csv_path in csv_files:
        result = check_file(csv_path, expected_month)
        results.append(result)

    failed = [r for r in results if not r["passed"]]
    violations = len(failed)

    audit.emit(
        "gate_pass" if not failed else "gate_fail",
        source_function="gate_transaction_count.main",
        gate={
            "name": _GATE_NAME,
            "metric": "files_with_violations",
            "value": float(violations),
            "threshold": 0.0,
            "passed": not failed,
        },
        trigger_context={"expenses_dir": str(expenses_dir), "files_checked": len(results)},
    )

    # Always print summary.
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"  [{status}] {r['file']}: {r['row_count']} rows")
        for issue in r["issues"]:
            print(f"         ! {issue}")

    if not failed:
        print(f"\ngate_4 PASS — {len(results)} file(s) checked, all within tolerance")
        return 0
    else:
        print(f"\ngate_4 FAIL — {violations} file(s) failed:", file=sys.stderr)
        for r in failed:
            print(f"  {r['file']}: {'; '.join(r['issues'])}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
