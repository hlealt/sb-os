"""Validation gate #7 — Spot-check coverage: mandatory source classes (p4-18).

Tier: P1. Auto-halt before step-05 if any mandatory spot-check class was skipped.

Mandatory classes (per step-04-validate.md "Cobertura mínima"):
  - B3 orders         (required always)
  - B3 proventos      (required always)
  - Safra balcao      (required always)
  - Avenue orders     (required if avenue files are present)
  - Avenue fx         (required if avenue files are present)
  - Crypto exchange   (required if crypto files are present; any 1 exchange)

Reads a coverage record JSON written by the bookkeeper workflow step-04 after
spot-checking.  The record lists which classes were checked.

Coverage record schema:
  {
    "checked": ["b3_orders", "b3_proventos", "safra_balcao", ...],
    "present_sources": ["b3", "safra_balcao", "avenue", "crypto"]  // optional
  }

present_sources determines which classes are required.  If absent, all mandatory
classes are required.

Usage:
    python gate_spot_check_coverage.py --coverage-record PATH

Exit codes:
    0   Pass — all mandatory classes are covered
    1   Fail — one or more mandatory classes were not spot-checked
    2   Error — coverage record missing or malformed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import audit


_GATE_NAME = "gate_7_spot_check_coverage"

# All classes always required.
_ALWAYS_REQUIRED: set[str] = {"b3_orders", "b3_proventos", "safra_balcao"}

# Classes required only when the corresponding source is present.
_CONDITIONAL: dict[str, str] = {
    "avenue_orders": "avenue",
    "avenue_fx": "avenue",
    "crypto_exchange": "crypto",
}


def check_coverage(record: dict) -> tuple[bool, list[str]]:
    """Return (passed, missing_classes).

    passed=True  → all mandatory classes for the present sources are covered.
    passed=False → one or more mandatory classes skipped.
    """
    if not isinstance(record, dict):
        return False, ["coverage record is not a JSON object"]

    checked: set[str] = set(record.get("checked", []) or [])
    present_sources: set[str] = set(record.get("present_sources", []) or [])

    required: set[str] = set(_ALWAYS_REQUIRED)
    for cls, source in _CONDITIONAL.items():
        # If present_sources was provided, use it to determine conditionality.
        # If not provided, assume all conditional classes are required (conservative).
        if not present_sources or source in present_sources:
            required.add(cls)

    missing = sorted(required - checked)
    return len(missing) == 0, missing


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate #7: Mandatory spot-check source classes must all be covered."
    )
    parser.add_argument(
        "--coverage-record",
        metavar="PATH",
        required=True,
        help="Path to coverage record JSON (written by bookkeeper step-04).",
    )
    args = parser.parse_args()

    record_path = Path(args.coverage_record)
    if not record_path.exists():
        print(f"ERROR: coverage record not found: {record_path}", file=sys.stderr)
        return 2

    try:
        with open(record_path, "r", encoding="utf-8") as f:
            record = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: could not read coverage record: {exc}", file=sys.stderr)
        return 2

    passed, missing = check_coverage(record)

    checked_list = record.get("checked", []) if isinstance(record, dict) else []

    audit.emit(
        "gate_pass" if passed else "gate_fail",
        source_function="gate_spot_check_coverage.main",
        gate={
            "name": _GATE_NAME,
            "metric": "unchecked_mandatory_classes",
            "value": float(len(missing)),
            "threshold": 0.0,
            "passed": passed,
        },
        trigger_context={
            "coverage_record_path": str(record_path),
            "checked": checked_list,
            "missing": missing,
        },
    )

    if passed:
        print(f"gate_7 PASS — all mandatory spot-check classes covered: {sorted(checked_list)}")
        return 0
    else:
        print(f"gate_7 FAIL — {len(missing)} mandatory class(es) not spot-checked:", file=sys.stderr)
        for cls in missing:
            print(f"  MISSING: {cls}", file=sys.stderr)
        print("Run spot-checks for the missing classes before proceeding to step-05.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
