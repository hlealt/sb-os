"""Validation gates #1, #2, #3 — tagged despesas coverage before commit.

Gates are ANDed — all three must pass for exit 0.

Gate #1 (P2, S7=90% R$): R$-coverage of tagged despesas >= 90%.
Gate #2 (P2, S7=90% rows): row-coverage of tagged despesas >= 90%.
Gate #3 (P2, S7=R$100): no untagged despesa with abs(amount) > R$100.

Per p2-15: gates #2 and #3 run in the same loop as gate #1. All three
conditions are ANDed — a single call enforces all three.

Exclusions (per p2-15 gate #1 scope):
  - receitas      (income)
  - intercontas   (transfers between own accounts)
  - ignorar       (explicitly ignored rows)
  - venda         (investment sales)

Auto-loop: if any gate fails, auto-loops back to Step 4b (max 3 iterations).
Max-loop guard: after 3 iterations, surfaces a user prompt instead.

Config sources:
  gates.step_5_5_coverage.threshold (0.90) — R$ and row coverage threshold.
  tag_coverage.gate.untagged_amount_threshold_brl (100) — CANONICAL (and only) floor key.

Usage:
    python gate_coverage.py \\
        --transactions PATH \\
        [--loop-count N]    \\
        [--config-dir PATH]

Exit codes:
    0   Pass — all three gates pass
    1   Fail — one or more gates fail
    2   Error — transactions file missing or malformed; config missing
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import audit, standing_rules as sr


_GATE_NAME = "gate_1_coverage"

_EXCLUDED_CATEGORIES = {"receitas", "intercontas", "ignorar", "venda"}

# Fallback threshold if config is unreachable (fail-safe: use resolved value).
_COVERAGE_THRESHOLD_FALLBACK = 0.90

# Fallback untagged-amount floor (gate #3) — canonical source is config.
_UNTAGGED_FLOOR_FALLBACK = 100.0

# Max auto-loop iterations before surfacing user prompt.
_MAX_LOOP = 3


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return parent
    raise RuntimeError(f"Vault root not found from {__file__}")


def _load_threshold(config_dir: Path) -> float:
    """Read the coverage threshold from standing-rules.yaml.

    Returns the resolved 0.90 value (or fallback if config is unavailable).
    """
    try:
        rules = sr.load_standing_rules(config_dir)
        gates_cfg = sr.load_gates(rules)
        step_5_5 = gates_cfg.get("step_5_5_coverage", {})
        threshold = step_5_5.get("threshold")
        if threshold is not None and isinstance(threshold, (int, float)):
            return float(threshold)
    except sr.StandingRulesError:
        pass
    return _COVERAGE_THRESHOLD_FALLBACK


def _load_untagged_floor(config_dir: Path) -> float:
    """Read the untagged-amount floor from standing-rules.yaml.

    Canonical (and only) source: tag_coverage.gate.untagged_amount_threshold_brl.
    p5-8 removed the former gates.step_5_5_coverage.untagged_amount_threshold alias,
    so this reads the single canonical key. Returns _UNTAGGED_FLOOR_FALLBACK if
    config is unavailable.
    """
    try:
        rules = sr.load_standing_rules(config_dir)
        tag_cov = rules.get("tag_coverage", {})
        gate_section = tag_cov.get("gate", {}) if isinstance(tag_cov, dict) else {}
        canonical = gate_section.get("untagged_amount_threshold_brl")
        if canonical is not None and isinstance(canonical, (int, float)):
            return float(canonical)
    except sr.StandingRulesError:
        pass
    return _UNTAGGED_FLOOR_FALLBACK


def compute_coverage(rows: list[dict]) -> tuple[float, float, float]:
    """Return (coverage_pct, tagged_amount_brl, total_despesas_brl).

    A row is a "despesa" if:
      - category is not in _EXCLUDED_CATEGORIES
      - amount is negative (expense convention: negative = outflow)

    A despesa is "tagged" if its tags column is non-empty.
    """
    total_brl = 0.0
    tagged_brl = 0.0

    for row in rows:
        category = (row.get("category") or "").strip().lower()
        if category in _EXCLUDED_CATEGORIES:
            continue

        try:
            amount = float(row.get("amount", 0) or 0)
        except (ValueError, TypeError):
            continue

        if amount >= 0:
            # Only expense rows (negative amounts) count.
            continue

        abs_amount = abs(amount)
        total_brl += abs_amount

        tags = (row.get("tags") or "").strip()
        if tags:
            tagged_brl += abs_amount

    coverage = tagged_brl / total_brl if total_brl > 0 else 1.0
    return coverage, tagged_brl, total_brl


def compute_row_coverage(rows: list[dict]) -> tuple[float, int, int]:
    """Return (row_coverage_pct, tagged_row_count, total_despesa_row_count).

    Gate #2: row-coverage of tagged despesas >= threshold.
    Same exclusions as compute_coverage.
    """
    total_rows = 0
    tagged_rows = 0

    for row in rows:
        category = (row.get("category") or "").strip().lower()
        if category in _EXCLUDED_CATEGORIES:
            continue

        try:
            amount = float(row.get("amount", 0) or 0)
        except (ValueError, TypeError):
            continue

        if amount >= 0:
            continue

        total_rows += 1
        tags = (row.get("tags") or "").strip()
        if tags:
            tagged_rows += 1

    coverage = tagged_rows / total_rows if total_rows > 0 else 1.0
    return coverage, tagged_rows, total_rows


def find_large_untagged(rows: list[dict], floor_brl: float) -> list[dict]:
    """Return despesa rows that are untagged AND abs(amount) > floor_brl.

    Gate #3: none of these must exist after coverage threshold is reached.
    """
    violations: list[dict] = []
    for row in rows:
        category = (row.get("category") or "").strip().lower()
        if category in _EXCLUDED_CATEGORIES:
            continue

        try:
            amount = float(row.get("amount", 0) or 0)
        except (ValueError, TypeError):
            continue

        if amount >= 0:
            continue

        tags = (row.get("tags") or "").strip()
        if tags:
            continue  # tagged — fine

        if abs(amount) > floor_brl:
            violations.append(row)

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gates #1/#2/#3 (ANDed): tagged despesas coverage before commit."
    )
    parser.add_argument(
        "--transactions",
        metavar="PATH",
        help="Path to transactions.csv (fechamento/{YYYY-MM}/transactions.csv).",
    )
    parser.add_argument(
        "--loop-count",
        type=int,
        default=0,
        metavar="N",
        help="Current auto-loop iteration count (0 = first run). Max 3 before user prompt.",
    )
    parser.add_argument(
        "--config-dir",
        metavar="PATH",
        help="Path to bookkeeper config dir containing standing-rules.yaml.",
    )
    args = parser.parse_args()

    vault_root = _find_vault_root()

    # Resolve config dir.
    if args.config_dir:
        config_dir = Path(args.config_dir)
    else:
        config_dir = vault_root / ".user" / "finance" / "bookkeeper" / "config"

    # Resolve transactions path.
    if args.transactions:
        tx_path = Path(args.transactions)
    else:
        # Default to most-recent fechamento month.
        fechamento_base = vault_root / ".user" / "finance" / "bookkeeper" / "ledgers" / "fechamento"
        month_dirs = sorted(
            [d for d in fechamento_base.iterdir() if d.is_dir()],
            key=lambda p: p.name,
        )
        if not month_dirs:
            print(f"ERROR: no fechamento month directories under {fechamento_base}", file=sys.stderr)
            return 2
        tx_path = month_dirs[-1] / "transactions.csv"

    if not tx_path.exists():
        print(f"ERROR: transactions.csv not found: {tx_path}", file=sys.stderr)
        return 2

    # Load thresholds from config.
    threshold = _load_threshold(config_dir)
    floor_brl = _load_untagged_floor(config_dir)

    # Load transactions.
    try:
        with open(tx_path, "r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    except (OSError, UnicodeDecodeError) as exc:
        print(f"ERROR: could not read transactions file: {exc}", file=sys.stderr)
        return 2

    # Gate #1 — R$ coverage.
    coverage_brl, tagged_brl, total_brl = compute_coverage(rows)
    gate1_pass = coverage_brl >= threshold

    # Gate #2 — row coverage.
    coverage_rows, tagged_rows, total_rows = compute_row_coverage(rows)
    gate2_pass = coverage_rows >= threshold

    # Gate #3 — no large untagged despesas.
    large_untagged = find_large_untagged(rows, floor_brl)
    gate3_pass = len(large_untagged) == 0

    all_pass = gate1_pass and gate2_pass and gate3_pass

    # Emit coverage_progress event (gate #1 metric).
    audit.emit_coverage(
        metric="despesas_tagged_brl_pct",
        value=coverage_brl,
        source_function="gate_coverage.main",
        threshold=threshold,
        trigger_context={
            "transactions_path": str(tx_path),
            "tagged_brl": round(tagged_brl, 2),
            "total_brl": round(total_brl, 2),
            "loop_count": args.loop_count,
        },
    )

    # Emit coverage_progress event (gate #2 metric).
    audit.emit_coverage(
        metric="despesas_tagged_row_pct",
        value=coverage_rows,
        source_function="gate_coverage.main",
        threshold=threshold,
        trigger_context={
            "tagged_rows": tagged_rows,
            "total_rows": total_rows,
            "loop_count": args.loop_count,
        },
    )

    # Emit combined gate pass/fail event.
    audit.emit_gate(
        _GATE_NAME,
        metric="despesas_tagged_brl_pct",
        value=coverage_brl,
        threshold=threshold,
        passed=all_pass,
        source_function="gate_coverage.main",
        trigger_context={
            "loop_count": args.loop_count,
            "gate2_row_coverage": round(coverage_rows, 4),
            "gate3_large_untagged_count": len(large_untagged),
            "gate3_floor_brl": floor_brl,
        },
    )

    print(
        f"R$ coverage:  {coverage_brl:.1%} "
        f"(R${tagged_brl:.2f} tagged / R${total_brl:.2f} total expenses)"
    )
    print(
        f"Row coverage: {coverage_rows:.1%} "
        f"({tagged_rows} tagged / {total_rows} total expenses)"
    )
    if large_untagged:
        print(
            f"Untagged expenses > R${floor_brl:.0f}: {len(large_untagged)} item(s)",
            file=sys.stderr,
        )
        for r in large_untagged:
            print(
                f"  {r.get('date','')}  {r.get('description','')[:40]}  "
                f"R${abs(float(r.get('amount', 0))):.2f}",
                file=sys.stderr,
            )

    if all_pass:
        print(
            f"gate_1/2/3 PASS — R$ {coverage_brl:.1%} >= {threshold:.0%}, "
            f"rows {coverage_rows:.1%} >= {threshold:.0%}, "
            f"no untagged > R${floor_brl:.0f}"
        )
        return 0

    # FAIL path.
    loop_count = args.loop_count

    if loop_count >= _MAX_LOOP:
        # Max-loop guard: surface user prompt instead of auto-looping.
        print(
            f"\nInsufficient coverage after {_MAX_LOOP} Step 4b iterations.",
            file=sys.stderr,
        )
        if not gate1_pass:
            print(
                f"R$ tagged: {coverage_brl:.1%} (target: {threshold:.0%}). "
                f"Total untagged expenses: R${total_brl - tagged_brl:.2f}",
                file=sys.stderr,
            )
        if not gate2_pass:
            print(
                f"Rows tagged: {coverage_rows:.1%} (target: {threshold:.0%}). "
                f"Untagged expenses: {total_rows - tagged_rows}",
                file=sys.stderr,
            )
        if not gate3_pass:
            print(
                f"Untagged expenses above R${floor_brl:.0f}: {len(large_untagged)} item(s)",
                file=sys.stderr,
            )
        print("Proceed anyway? [S/N]", file=sys.stderr)
        print(
            f"gate_1/2/3 FAIL — max_loop={_MAX_LOOP} reached; surfacing user prompt",
            file=sys.stderr,
        )
    else:
        next_loop = loop_count + 1
        reasons = []
        if not gate1_pass:
            reasons.append(f"R$ {coverage_brl:.1%} < {threshold:.0%}")
        if not gate2_pass:
            reasons.append(f"rows {coverage_rows:.1%} < {threshold:.0%}")
        if not gate3_pass:
            reasons.append(f"{len(large_untagged)} untagged > R${floor_brl:.0f}")
        print(
            f"gate_1/2/3 FAIL — {'; '.join(reasons)} "
            f"(iteration {next_loop}/{_MAX_LOOP}); return to Step 4b",
            file=sys.stderr,
        )

    return 1


if __name__ == "__main__":
    sys.exit(main())
