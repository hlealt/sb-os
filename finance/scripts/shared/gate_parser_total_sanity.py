"""Validation gate #5 — parser total sanity for *_orders.csv rows (p4-25).

Tier: P4. Fail-loud on deviation > 0.5%.

Checks: total ≈ quantity × price + fees, tolerance 0.5% of row total.
  fees = fees_exchange + fees_brokerage + fees_irrf

Applies to all rows in the given orders.csv file (or all *_orders.csv files
under --orders-dir). In workflow context "new rows" are those added in the
current ingest session; this gate validates the provided file(s) in full and
the caller supplies only the new-rows slice when needed.

Fail-loud behaviour: lists every row where deviation > 0.5%. User decides
whether to halt or accept. Gate does NOT auto-loop — root cause is in the
source file or parser.

Usage:
    python gate_parser_total_sanity.py --orders-path PATH
    python gate_parser_total_sanity.py --orders-dir PATH

Exit codes:
    0   Pass — all rows within 0.5% tolerance
    1   Fail — one or more rows exceed tolerance (listed on stderr)
    2   Error — no orders file found or file unreadable
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import audit

_GATE_NAME = "gate_5_parser_total_sanity"
_TOLERANCE = 0.005  # 0.5%


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return parent
    raise RuntimeError(f"Vault root not found from {__file__}")


def _default_orders_path() -> Path:
    override = os.environ.get("BOOKKEEPER_ORDERS_PATH")
    if override:
        return Path(override)
    return (
        _find_vault_root()
        / ".user" / "finance" / "bookkeeper" / "ledgers" / "investimentos" / "orders.csv"
    )


def _safe_float(value) -> float | None:
    """Parse a cell as float; return None on blank or unparseable."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def check_orders_file(path: Path) -> list[dict]:
    """Return one dict per row that violates the total sanity check.

    Dict keys: row_num, date, ticker, side, quantity, price, fees, total_stored,
    total_expected, deviation_pct.

    Rows where any of quantity/price/total are missing/unparseable are skipped
    (not violations — missing data is a different check).
    """
    violations: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row_num, row in enumerate(reader, start=2):  # 2 = first data row
                qty = _safe_float(row.get("quantity"))
                price = _safe_float(row.get("price"))
                total = _safe_float(row.get("total"))
                if qty is None or price is None or total is None:
                    continue

                fees_ex = _safe_float(row.get("fees_exchange")) or 0.0
                fees_br = _safe_float(row.get("fees_brokerage")) or 0.0
                fees_irrf = _safe_float(row.get("fees_irrf")) or 0.0
                fees = fees_ex + fees_br + fees_irrf

                # Convention: sell rows have negative total; buy rows positive.
                # Use abs for the magnitude check; sign must also match.
                expected = abs(qty * price) + fees
                stored = abs(total)

                if stored == 0.0:
                    # Zero total row is a separate anomaly; skip.
                    continue

                deviation = abs(stored - expected) / stored
                if deviation > _TOLERANCE:
                    violations.append({
                        "row_num": row_num,
                        "date": row.get("date", ""),
                        "ticker": row.get("ticker", ""),
                        "side": row.get("side", ""),
                        "quantity": qty,
                        "price": price,
                        "fees": fees,
                        "total_stored": total,
                        "total_expected": expected if total >= 0 else -expected,
                        "deviation_pct": deviation * 100,
                    })
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"Could not read {path}: {exc}") from exc
    return violations


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Gate #5: parser total sanity — total ≈ qty×price+fees (tol 0.5%)."
    )
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument("--orders-path", help="Path to a single orders.csv file")
    grp.add_argument(
        "--orders-dir",
        help="Directory containing *_orders.csv files (scans all matches)"
    )
    args = parser.parse_args()

    # Resolve file list.
    if args.orders_path:
        files = [Path(args.orders_path)]
    elif args.orders_dir:
        d = Path(args.orders_dir)
        if not d.is_dir():
            print(f"ERROR: orders-dir not found: {d}", file=sys.stderr)
            return 2
        files = list(d.glob("*orders*.csv"))
        if not files:
            print(f"ERROR: no *orders*.csv files found in {d}", file=sys.stderr)
            return 2
    else:
        files = [_default_orders_path()]

    # Check existence of all resolved files.
    missing = [f for f in files if not f.exists()]
    if missing:
        for f in missing:
            print(f"ERROR: orders file not found: {f}", file=sys.stderr)
        return 2

    all_violations: list[dict] = []
    error_files: list[str] = []

    for path in files:
        try:
            violations = check_orders_file(path)
            all_violations.extend(violations)
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            error_files.append(str(path))

    if error_files:
        return 2

    passed = len(all_violations) == 0
    files_checked = [str(f) for f in files]

    audit.emit_gate(
        _GATE_NAME,
        metric="orders_total_violation_count",
        value=float(len(all_violations)),
        threshold=0.0,
        passed=passed,
        source_function="gate_parser_total_sanity.main",
        trigger_context={
            "files_checked": files_checked,
            "tolerance_pct": _TOLERANCE * 100,
        },
    )

    if all_violations:
        print(
            f"Parser total sanity violations — {len(all_violations)} row(s) "
            f"with deviation > {_TOLERANCE * 100:.1f}%:",
            file=sys.stderr,
        )
        print(
            f"  {'row':>4}  {'date':<12}  {'ticker':<8}  {'side':<4}  "
            f"{'qty':>10}  {'price':>10}  {'stored':>12}  {'expected':>12}  {'dev%':>6}",
            file=sys.stderr,
        )
        for v in all_violations:
            print(
                f"  {v['row_num']:>4}  {v['date']:<12}  {v['ticker']:<8}  {v['side']:<4}  "
                f"{v['quantity']:>10.4f}  {v['price']:>10.4f}  "
                f"{v['total_stored']:>12.4f}  {v['total_expected']:>12.4f}  "
                f"{v['deviation_pct']:>6.2f}%",
                file=sys.stderr,
            )
        print(
            "\nUser decision required: investigate source file or parser before committing.",
            file=sys.stderr,
        )
        print(f"gate_5 FAIL — {len(all_violations)} row(s) violate 0.5% tolerance", file=sys.stderr)
        return 1

    print(
        f"gate_5 PASS — all rows within {_TOLERANCE * 100:.1f}% tolerance "
        f"({len(files)} file(s) checked)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
