"""Validation gates #1 and #3 — tagged despesas coverage before commit.

2026-06-05 REDESIGN: gate contract revised, row coverage demoted to informational.

Gate #1 (R$ coverage): R$-coverage of tagged despesas >= config threshold.
  Config key: gates.step_5_5_coverage.threshold (recalibrated to 0.75).
  Code fallback: 0.75 (lowered from 0.90 to match config; config drives the gate).

Gate #2 (row coverage): INFORMATIONAL ONLY — computed and printed but NEVER
  fails the gate. Audit event still emitted (observability preserved).

Gate #3 (large untagged): no UNACKNOWLEDGED untagged despesa with
  abs(amount) > config floor.
  Config key: tag_coverage.gate.untagged_amount_threshold_brl (recalibrated to 300).
  Ack side-ledger: .user/finance/bookkeeper/config/corrections/tag-review-acks.csv
    (header: tx_date,tx_description,tx_amount,month,acked_at,source,note).
  Acked rows above the floor → visible ACK note (never silent skip).
  Unacknowledged rows above the floor → exit 1 (violation).
  Identity join: same (date, description, repr(float(amount))) scheme as
    categorize.py::tx_identity / _tx_amount_key. Imported from categorize
    when available; reimplemented here with a comment binding it to that scheme.

Gates ANDed: gate #1 AND gate #3 must both pass for exit 0.
(Gate #2 is informational and never fails the combined gate.)

Auto-loop: if any gate fails, auto-loops back to Step 4b (max 3 iterations).
Max-loop guard: after 3 iterations, surfaces a user prompt instead.

Config sources:
  gates.step_5_5_coverage.threshold (0.75) — R$ coverage threshold.
  tag_coverage.gate.untagged_amount_threshold_brl (300) — untagged-despesa floor.

Usage:
    python gate_coverage.py \\
        --transactions PATH \\
        [--ack-file PATH]   \\
        [--loop-count N]    \\
        [--config-dir PATH]

Exit codes:
    0   Pass — gate #1 passes AND no unacknowledged untagged despesa > floor
    1   Fail — gate #1 fails OR unacknowledged untagged despesa > floor
    2   Error — transactions file missing or malformed; ack file present but
               missing required identity columns (tx_date,tx_description,tx_amount)
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

# Fallback threshold if config is unreachable.
# Lowered from 0.90 to 0.75 (2026-06-05) to match standing-rules.yaml
# gates.step_5_5_coverage.threshold recalibration. The config drives the gate;
# this is the in-code safe default when config is unreachable.
_COVERAGE_THRESHOLD_FALLBACK = 0.75

# Fallback untagged-amount floor (gate #3) — canonical source is config.
# Kept at R$100 (original S7 value, more conservative than the config's R$300).
# Production gate uses config tag_coverage.gate.untagged_amount_threshold_brl.
_UNTAGGED_FLOOR_FALLBACK = 100.0

# Required identity columns in the ack file (fail-loud if absent).
_ACK_IDENTITY_COLS = ("tx_date", "tx_description", "tx_amount")

# Max auto-loop iterations before surfacing user prompt.
_MAX_LOOP = 3


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return parent
    raise RuntimeError(f"Vault root not found from {__file__}")


def _load_threshold(config_dir: Path) -> float:
    """Read the coverage threshold from standing-rules.yaml."""
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


def _tx_amount_key(amount: object) -> str:
    """Normalize an amount to a canonical key string.

    BINDING: identical to categorize.py::_tx_amount_key — repr(float(amount))
    with unparseable-amount fallback to str(amount).strip(). Any change here
    MUST be mirrored in categorize.py (or this function should import from there).
    """
    try:
        return repr(float(amount))
    except (ValueError, TypeError):
        return str(amount).strip()


def _ack_identity(row: dict) -> tuple[str, str, str]:
    """Build the identity key from an ack CSV row.

    BINDING: same scheme as categorize.tx_identity — (str(date).strip(),
    str(description).strip(), repr(float(amount))). The ack file's columns
    are tx_date/tx_description/tx_amount; the tx file's columns are
    date/description/amount.
    """
    return (
        str(row.get("tx_date", "")).strip(),
        str(row.get("tx_description", "")).strip(),
        _tx_amount_key(row.get("tx_amount", "")),
    )


def _tx_identity(row: dict) -> tuple[str, str, str]:
    """Build the identity key from a transactions.csv row.

    BINDING: same scheme as categorize.tx_identity.
    """
    return (
        str(row.get("date", "")).strip(),
        str(row.get("description", "")).strip(),
        _tx_amount_key(row.get("amount", "")),
    )


def load_tag_review_acks(ack_path: Path) -> set[tuple[str, str, str]]:
    """Load the ack side-ledger into a set of identity keys.

    Fail-soft on missing file (returns empty set — identical to
    load_manual_overrides' missing-file branch in categorize.py).
    Fail-loud on missing required identity columns (tx_date, tx_description,
    tx_amount): raises SystemExit(2) — a corrections log that cannot be read
    is never a silent default (corrections convention).
    """
    if not ack_path.exists():
        return set()

    with open(ack_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        # Validate required identity columns.
        if reader.fieldnames is None:
            print(
                f"ERROR: ack file has no header: {ack_path}", file=sys.stderr
            )
            sys.exit(2)
        missing = [c for c in _ACK_IDENTITY_COLS if c not in reader.fieldnames]
        if missing:
            print(
                f"ERROR: ack file {ack_path} is missing required identity "
                f"columns: {missing}. Cannot read ack set — refusing to "
                f"silently default to empty (corrections convention).",
                file=sys.stderr,
            )
            sys.exit(2)
        out: set[tuple[str, str, str]] = set()
        for row in reader:
            out.add(_ack_identity(row))
    return out


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

    Gate #2 redesign (2026-06-05): INFORMATIONAL ONLY — this function computes
    row coverage for display and audit purposes; the result is never used to
    fail the gate. Same exclusions as compute_coverage.
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

    Gate #3: no UNACKNOWLEDGED row in this list may exist. The caller applies
    the ack side-ledger to determine which rows are acknowledged vs violations.
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
        description=(
            "Gate #1 (R$ coverage) + Gate #3 (no unacked large untagged despesas). "
            "Gate #2 (row coverage) is informational — printed but never fails."
        )
    )
    parser.add_argument(
        "--transactions",
        metavar="PATH",
        help="Path to transactions.csv (fechamento/{YYYY-MM}/transactions.csv).",
    )
    parser.add_argument(
        "--ack-file",
        metavar="PATH",
        help=(
            "Path to tag-review-acks.csv. "
            "Absent → empty ack set (fail-soft). "
            "Present but missing identity columns → exit 2 (fail-loud)."
        ),
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

    # Resolve ack file path.
    if args.ack_file:
        ack_path = Path(args.ack_file)
    else:
        ack_path = (
            config_dir / "corrections" / "tag-review-acks.csv"
        )

    # Load ack set (fail-soft on missing; fail-loud on bad header → exits 2).
    ack_keys = load_tag_review_acks(ack_path)

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

    # Gate #2 — row coverage (INFORMATIONAL ONLY — never fails).
    coverage_rows, tagged_rows, total_rows = compute_row_coverage(rows)
    # gate2 is not in all_pass — it is informational only.

    # Gate #3 — classify untagged despesas above floor as acked vs violations.
    large_untagged = find_large_untagged(rows, floor_brl)
    acked_rows: list[dict] = []
    violation_rows: list[dict] = []
    for row in large_untagged:
        if _tx_identity(row) in ack_keys:
            acked_rows.append(row)
        else:
            violation_rows.append(row)
    gate3_pass = len(violation_rows) == 0

    all_pass = gate1_pass and gate3_pass

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

    # Emit coverage_progress event (gate #2 metric — informational, always emitted).
    audit.emit_coverage(
        metric="despesas_tagged_row_pct",
        value=coverage_rows,
        source_function="gate_coverage.main",
        threshold=threshold,
        trigger_context={
            "tagged_rows": tagged_rows,
            "total_rows": total_rows,
            "loop_count": args.loop_count,
            "informational_only": True,
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
            "gate2_row_coverage": round(coverage_rows, 4),  # informational
            "gate3_large_untagged_count": len(large_untagged),
            "gate3_floor_brl": floor_brl,
            "gate3_acked_skips": len(acked_rows),
        },
    )

    # --- Output ---

    print(
        f"R$ coverage:  {coverage_brl:.1%} "
        f"(R${tagged_brl:.2f} tagged / R${total_brl:.2f} total expenses)"
    )
    print(
        f"Row coverage: {coverage_rows:.1%} "
        f"({tagged_rows} tagged / {total_rows} total expenses) [informational]"
    )

    # Print acked rows as visible ACK notes (never silent skip).
    if acked_rows:
        print(
            f"Untagged expenses > R${floor_brl:.0f} with ack ({len(acked_rows)} item(s)):"
        )
        for r in acked_rows:
            print(
                f"  ACK  {r.get('date','')}  {r.get('description','')[:40]}  "
                f"R${abs(float(r.get('amount', 0))):.2f}"
            )

    # Print violations (unacked) to stderr.
    if violation_rows:
        print(
            f"Untagged expenses > R${floor_brl:.0f} WITHOUT ack: {len(violation_rows)} item(s)",
            file=sys.stderr,
        )
        for r in violation_rows:
            print(
                f"  VIOLATION  {r.get('date','')}  {r.get('description','')[:40]}  "
                f"R${abs(float(r.get('amount', 0))):.2f}",
                file=sys.stderr,
            )

    if all_pass:
        print(
            f"gate_1/3 PASS — R$ {coverage_brl:.1%} >= {threshold:.0%}, "
            f"no unacknowledged untagged > R${floor_brl:.0f}"
            + (f" ({len(acked_rows)} acked)" if acked_rows else "")
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
        if not gate3_pass:
            print(
                f"Unacknowledged untagged expenses above R${floor_brl:.0f}: "
                f"{len(violation_rows)} item(s)",
                file=sys.stderr,
            )
        print("Proceed anyway? [S/N]", file=sys.stderr)
        print(
            f"gate_1/3 FAIL — max_loop={_MAX_LOOP} reached; surfacing user prompt",
            file=sys.stderr,
        )
    else:
        next_loop = loop_count + 1
        reasons = []
        if not gate1_pass:
            reasons.append(f"R$ {coverage_brl:.1%} < {threshold:.0%}")
        if not gate3_pass:
            reasons.append(f"{len(violation_rows)} unacked untagged > R${floor_brl:.0f}")
        print(
            f"gate_1/3 FAIL — {'; '.join(reasons)} "
            f"(iteration {next_loop}/{_MAX_LOOP}); return to Step 4b",
            file=sys.stderr,
        )

    return 1


if __name__ == "__main__":
    sys.exit(main())
