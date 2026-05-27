"""Validation gate #6 — Ledger upsert match tolerance = 0 (p4-16).

Tier: P0. Fail-loud if ANY fuzzy match appears in the update_ledgers report.

Wraps update_ledgers.py's dedup report as a pass/fail exit-code gate.
The gate reads a serialized upsert report JSON (one report per ledger, same
structure as `update_ledgers.dedup_and_insert` returns) and fails if any
entry has non-empty `skipped_fuzzy` — a fuzzy match at tolerance=0 is a bug.

Report file schema (written by the investimentos workflow step-03 or
produced by running update_ledgers.py with --report-out):
  {
    "orders.csv":   {"inserted": N, "skipped_exact": N, "skipped_fuzzy": [...]},
    "proventos.csv": {...},
    ...
  }

Usage:
    python gate_ledger_tolerance.py --report PATH

Exit codes:
    0   Pass — no fuzzy matches found (all matches are exact or inserts)
    1   Fail — one or more fuzzy matches found (bug: tolerance must be 0)
    2   Error — report file missing or malformed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import audit


_GATE_NAME = "gate_6_ledger_tolerance"


def check_report(report: dict) -> tuple[bool, int, list[dict]]:
    """Return (passed, fuzzy_count, fuzzy_details).

    passed=True  → no fuzzy matches in any ledger.
    passed=False → fuzzy matches found; detail lists them.
    """
    fuzzy_details: list[dict] = []
    for ledger_name, ledger_report in report.items():
        if not isinstance(ledger_report, dict):
            continue
        fuzzy = ledger_report.get("skipped_fuzzy", [])
        if not isinstance(fuzzy, list):
            continue
        for entry in fuzzy:
            fuzzy_details.append({"ledger": ledger_name, **entry})

    passed = len(fuzzy_details) == 0
    return passed, len(fuzzy_details), fuzzy_details


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate #6: Ledger upsert match tolerance must be 0 (no fuzzy matches)."
    )
    parser.add_argument(
        "--report",
        metavar="PATH",
        required=True,
        help="Path to upsert report JSON (from update_ledgers.py).",
    )
    args = parser.parse_args()

    report_path = Path(args.report)
    if not report_path.exists():
        print(f"ERROR: report file not found: {report_path}", file=sys.stderr)
        return 2

    try:
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: could not read report file: {exc}", file=sys.stderr)
        return 2

    if not isinstance(report, dict):
        print("ERROR: report must be a JSON object mapping ledger names to reports", file=sys.stderr)
        return 2

    passed, fuzzy_count, fuzzy_details = check_report(report)

    audit.emit(
        "gate_pass" if passed else "gate_fail",
        source_function="gate_ledger_tolerance.main",
        gate={
            "name": _GATE_NAME,
            "metric": "fuzzy_match_count",
            "value": float(fuzzy_count),
            "threshold": 0.0,
            "passed": passed,
        },
        trigger_context={"report_path": str(report_path)},
    )

    if passed:
        print(f"gate_6 PASS — no fuzzy matches found (tolerance=0 enforced)")
        return 0
    else:
        print(f"gate_6 FAIL — {fuzzy_count} fuzzy match(es) found at tolerance=0:", file=sys.stderr)
        for entry in fuzzy_details:
            ledger = entry.get("ledger", "?")
            date = entry.get("date", "?")
            asset = entry.get("asset", "?")
            deltas = entry.get("deltas", {})
            print(f"  [{ledger}] {date} {asset}: {deltas}", file=sys.stderr)
        print("Fuzzy matches at tolerance=0 indicate a parser or data bug — investigate before committing.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
