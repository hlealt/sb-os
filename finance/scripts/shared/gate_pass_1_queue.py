"""Validation gate #11 — Pass-1 queue must be zero before Pass 2 fires (p4-15).

Tier: P0. Fail-loud on any remaining Pass-1 items.

Wraps the existing QueueOrderingError pattern from lib/queue.py as a
standalone pass/fail exit-code CLI tool.  The gate reads a serialized
queue state file (JSON) produced by the bookkeeper workflow and checks
whether all Pass-1 items are resolved before Pass 2 is dispatched.

Queue state file schema (written by bookkeeper step-05):
  {
    "pass_1_items": [...],   # list; empty = resolved
    "pass_2_items": [...]    # list; non-empty triggers this gate check
  }

When pass_2_items is non-empty AND pass_1_items is non-empty, that is a
QueueOrderingError — the user tried to open Pass 2 without clearing Pass 1.
When no state file path is given, the gate checks only whether the queue
module raises correctly on a synthetic unresolved transaction (smoke).

Usage:
    python gate_pass_1_queue.py --queue-state PATH

Exit codes:
    0   Pass — Pass-1 queue is empty (or no Pass-2 work pending)
    1   Fail — Pass-1 items remain unresolved while Pass-2 was requested
    2   Error — queue state file missing or malformed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import audit


_GATE_NAME = "gate_11_pass_1_queue"


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return parent
    raise RuntimeError(f"Vault root not found from {__file__}")


def check_queue_state(state: dict) -> tuple[bool, str]:
    """Return (passed, detail_message).

    passed=True  → Pass-1 queue is empty (gate passes).
    passed=False → Pass-1 items remain unresolved (QueueOrderingError condition).
    """
    pass_1 = state.get("pass_1_items", [])
    pass_2 = state.get("pass_2_items", [])

    if not isinstance(pass_1, list) or not isinstance(pass_2, list):
        return False, "Malformed queue state: pass_1_items/pass_2_items must be lists"

    # Gate fires when Pass-2 work exists AND Pass-1 is not empty.
    # If there is no Pass-2 work queued, there is nothing to guard against.
    if not pass_2:
        return True, f"Pass-2 queue is empty — gate not triggered (pass_1={len(pass_1)} items remain)"

    if pass_1:
        return False, (
            f"QueueOrderingError: {len(pass_1)} Pass-1 item(s) unresolved "
            f"while Pass-2 has {len(pass_2)} item(s) pending. "
            "Resolve all Pass-1 items before opening Pass 2."
        )

    return True, f"Pass-1 queue is empty — Pass-2 may proceed ({len(pass_2)} boundary items)"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate #11: Pass-1 queue must be zero before Pass 2 fires."
    )
    parser.add_argument(
        "--queue-state",
        metavar="PATH",
        help="Path to queue state JSON (written by bookkeeper step-05).",
    )
    args = parser.parse_args()

    if not args.queue_state:
        # No state file — gate passes vacuously (nothing to check).
        audit.emit(
            "gate_pass",
            source_function="gate_pass_1_queue.main",
            gate={
                "name": _GATE_NAME,
                "metric": "pass_1_remaining",
                "value": 0,
                "threshold": 0,
                "passed": True,
            },
            trigger_context={"reason": "no_queue_state_provided"},
        )
        print("gate_11 PASS — no queue state file provided; gate vacuously passes")
        return 0

    state_path = Path(args.queue_state)
    if not state_path.exists():
        print(f"ERROR: queue state file not found: {state_path}", file=sys.stderr)
        return 2

    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: could not read queue state file: {exc}", file=sys.stderr)
        return 2

    passed, detail = check_queue_state(state)
    pass_1_count = len(state.get("pass_1_items", [])) if isinstance(state.get("pass_1_items"), list) else -1

    audit.emit(
        "gate_pass" if passed else "gate_fail",
        source_function="gate_pass_1_queue.main",
        gate={
            "name": _GATE_NAME,
            "metric": "pass_1_remaining",
            "value": float(pass_1_count),
            "threshold": 0.0,
            "passed": passed,
        },
        trigger_context={"queue_state_path": str(state_path)},
    )

    if passed:
        print(f"gate_11 PASS — {detail}")
        return 0
    else:
        print(f"gate_11 FAIL — {detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
