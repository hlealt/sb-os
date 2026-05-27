"""Validation gate #8 — Portfolio delta anomaly detector (p4-19).

Tier: P1. Auto-halt if any UNFLAGGED anomaly exists.

NOTE: The 20% threshold in this gate is this gate's own evidence-based value
(from step-06-review.md "Anomalias detectadas" examples).  It is NOT the S7
regression-delta value (also 20%, recorded in shape.md, applied at p6-4
pre-close validation).

Anomaly conditions (per step-06-review.md):
  1. Per-position variacao > 20% (absolute pct change in current_value_brl vs prior snapshot)
  2. Position zeroed unexpectedly (quantity was >0 in prior snapshot; now 0)
  3. New unknown ticker (present in current portfolio but absent from prior snapshot)

Reads two portfolio.json files (current and prior snapshot) and computes the
deltas.  Any anomaly that is NOT in the flagged_anomalies list causes a FAIL.

Flagged anomalies (user-acknowledged): passed via --flagged FILE or
--flagged-ids "id1,id2" (comma-separated position IDs).

Usage:
    python gate_portfolio_delta.py \\
        --portfolio PATH \\
        --prior-snapshot PATH \\
        [--flagged-ids "TICKER1,TICKER2"] \\
        [--flagged FILE]

Exit codes:
    0   Pass — no unflagged anomalies
    1   Fail — unflagged anomalies exist; surface to user before snapshot
    2   Error — portfolio or prior-snapshot file missing or malformed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import audit


_GATE_NAME = "gate_8_portfolio_delta"
_VARIACAO_THRESHOLD = 0.20  # 20% — gate #8's own evidence value (NOT S7)


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return parent
    raise RuntimeError(f"Vault root not found from {__file__}")


def _load_portfolio(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    positions = data.get("positions", [])
    if not isinstance(positions, list):
        raise ValueError(f"portfolio.json at {path} has non-list 'positions'")
    return positions


def compute_anomalies(
    current_positions: list[dict],
    prior_positions: list[dict],
) -> list[dict]:
    """Return list of anomaly dicts.

    Each anomaly: {id, anomaly_type, detail}
    anomaly_type: 'variacao_gt_20pct' | 'position_zeroed' | 'new_unknown_ticker'
    """
    prior_by_id: dict[str, dict] = {p["id"]: p for p in prior_positions if "id" in p}
    current_by_id: dict[str, dict] = {p["id"]: p for p in current_positions if "id" in p}

    anomalies: list[dict] = []

    for pos_id, cur in current_by_id.items():
        if pos_id not in prior_by_id:
            anomalies.append({
                "id": pos_id,
                "anomaly_type": "new_unknown_ticker",
                "detail": f"New position {pos_id!r} not in prior snapshot",
            })
            continue

        prior = prior_by_id[pos_id]

        # Check for position zeroed unexpectedly.
        prior_qty = prior.get("quantity", 0) or 0
        cur_qty = cur.get("quantity", 0) or 0
        if prior_qty > 0 and cur_qty == 0:
            anomalies.append({
                "id": pos_id,
                "anomaly_type": "position_zeroed",
                "detail": f"Position {pos_id!r} zeroed (was qty={prior_qty})",
            })
            continue  # zeroed position — no point checking variacao

        # Check variacao in current_value_brl.
        prior_val = float(prior.get("current_value_brl", 0) or 0)
        cur_val = float(cur.get("current_value_brl", 0) or 0)

        if prior_val == 0:
            # Can't compute pct change from zero — skip variacao check.
            continue

        variacao = abs(cur_val - prior_val) / abs(prior_val)
        if variacao > _VARIACAO_THRESHOLD:
            anomalies.append({
                "id": pos_id,
                "anomaly_type": "variacao_gt_20pct",
                "detail": (
                    f"Position {pos_id!r} variacao={variacao:.1%} "
                    f"(prior_brl={prior_val:.2f}, current_brl={cur_val:.2f})"
                ),
            })

    return anomalies


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate #8: Portfolio delta anomaly detector."
    )
    parser.add_argument(
        "--portfolio",
        metavar="PATH",
        help="Path to current portfolio.json. Defaults to .user/.../portfolio.json.",
    )
    parser.add_argument(
        "--prior-snapshot",
        metavar="PATH",
        help="Path to prior snapshot portfolio-{date}.json for comparison.",
    )
    parser.add_argument(
        "--flagged-ids",
        metavar="IDS",
        default="",
        help="Comma-separated list of position IDs that the user has already flagged/acknowledged.",
    )
    parser.add_argument(
        "--flagged",
        metavar="FILE",
        help="Path to JSON file containing list of already-flagged position IDs.",
    )
    args = parser.parse_args()

    vault_root = _find_vault_root()
    inv_dir = vault_root / ".user" / "finance" / "bookkeeper" / "ledgers" / "investimentos"

    # Resolve portfolio path.
    portfolio_path = Path(args.portfolio) if args.portfolio else inv_dir / "portfolio.json"
    if not portfolio_path.exists():
        print(f"ERROR: portfolio.json not found: {portfolio_path}", file=sys.stderr)
        return 2

    # Resolve prior snapshot.
    if args.prior_snapshot:
        prior_path = Path(args.prior_snapshot)
    else:
        # Pick the most recent dated snapshot (not portfolio.json itself).
        snapshot_files = sorted(inv_dir.glob("portfolio-*.json"))
        if not snapshot_files:
            # No prior snapshot — can't check deltas; vacuous pass.
            audit.emit(
                "gate_pass",
                source_function="gate_portfolio_delta.main",
                gate={
                    "name": _GATE_NAME,
                    "metric": "unflagged_anomaly_count",
                    "value": 0.0,
                    "threshold": 0.0,
                    "passed": True,
                },
                trigger_context={"reason": "no_prior_snapshot"},
            )
            print("gate_8 PASS — no prior snapshot available; delta check skipped")
            return 0
        prior_path = snapshot_files[-1]

    if not prior_path.exists():
        print(f"ERROR: prior snapshot not found: {prior_path}", file=sys.stderr)
        return 2

    # Load flagged IDs.
    flagged_ids: set[str] = set()
    if args.flagged_ids:
        flagged_ids.update(x.strip() for x in args.flagged_ids.split(",") if x.strip())
    if args.flagged:
        flagged_file = Path(args.flagged)
        if flagged_file.exists():
            try:
                with open(flagged_file, "r", encoding="utf-8") as f:
                    ids = json.load(f)
                if isinstance(ids, list):
                    flagged_ids.update(str(x) for x in ids)
            except (json.JSONDecodeError, OSError) as exc:
                print(f"WARNING: could not read flagged file: {exc}", file=sys.stderr)

    # Load portfolios.
    try:
        current_positions = _load_portfolio(portfolio_path)
        prior_positions = _load_portfolio(prior_path)
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        print(f"ERROR: could not load portfolio files: {exc}", file=sys.stderr)
        return 2

    anomalies = compute_anomalies(current_positions, prior_positions)
    unflagged = [a for a in anomalies if a["id"] not in flagged_ids]

    audit.emit(
        "gate_pass" if not unflagged else "gate_fail",
        source_function="gate_portfolio_delta.main",
        gate={
            "name": _GATE_NAME,
            "metric": "unflagged_anomaly_count",
            "value": float(len(unflagged)),
            "threshold": 0.0,
            "passed": not unflagged,
        },
        trigger_context={
            "portfolio_path": str(portfolio_path),
            "prior_snapshot_path": str(prior_path),
            "total_anomalies": len(anomalies),
            "flagged_ids": sorted(flagged_ids),
        },
    )

    if anomalies:
        print(f"Anomalies detected ({len(anomalies)} total, {len(flagged_ids)} flagged):")
        for a in anomalies:
            flag_str = " [FLAGGED]" if a["id"] in flagged_ids else " [UNFLAGGED]"
            print(f"  {flag_str} {a['detail']}")

    if not unflagged:
        print(f"\ngate_8 PASS — {len(anomalies)} anomaly(ies) found, all flagged by user")
        return 0
    else:
        print(f"\ngate_8 FAIL — {len(unflagged)} unflagged anomaly(ies) require user resolution:", file=sys.stderr)
        for a in unflagged:
            print(f"  {a['anomaly_type']}: {a['detail']}", file=sys.stderr)
        print("Flag each anomaly (pass --flagged-ids) or investigate before creating snapshot.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
