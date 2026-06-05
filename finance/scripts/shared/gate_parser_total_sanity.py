"""Validation gate #5 — parser total sanity for *_orders.csv rows (p4-25).

Tier: P4. Fail-loud on deviation > 0.5%.

Checks: total ≈ quantity × price ± fees (sign depends on side), tolerance 0.5%
of row total.
  fees = fees_exchange + fees_brokerage + fees_irrf

Side-aware fee convention:
  Buy (side "C"):  expected = abs(qty * price) + fees  (fees add to cost)
  Sell (side "V"): expected = abs(qty * price) - fees  (fees deducted from proceeds)
  Unknown/missing side: falls back to + fees (conservative, no crash)

Corrections-aware: loads manual_adjust/quantity corrections from per-asset-type
correction files under {vault_root}/.user/finance/bookkeeper/config/corrections/
(intl.csv, stocks.csv, fii.csv, rf.csv, crypto.csv, funds.csv). When a row
matches a correction (ticker + date + from_value == stored qty), the check is
recomputed with to_value as quantity. Missing corrections dir/file = no
corrections (fail-soft). Override the corrections dir via BOOKKEEPER_CORRECTIONS_DIR.

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

# Per-asset-type corrections files that may contain manual_adjust/quantity rows.
_CORRECTIONS_FILENAMES = [
    "intl.csv",
    "stocks.csv",
    "fii.csv",
    "rf.csv",
    "crypto.csv",
    "funds.csv",
]


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


def _default_corrections_dir() -> Path:
    override = os.environ.get("BOOKKEEPER_CORRECTIONS_DIR")
    if override:
        return Path(override)
    return (
        _find_vault_root()
        / ".user" / "finance" / "bookkeeper" / "config" / "corrections"
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


def _floats_equal(a: float, b: float, rel_tol: float = 1e-6) -> bool:
    """Float equality with relative tolerance (for corrections from_value guard)."""
    if a == b:
        return True
    denom = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / denom < rel_tol


# ---------------------------------------------------------------------------
# Corrections loader
# ---------------------------------------------------------------------------

def load_qty_corrections(corrections_dir: Path) -> dict[tuple[str, str], list[dict]]:
    """Load manual_adjust/quantity corrections from all per-asset-type files.

    Returns a dict keyed by (ticker, iso_date) → list of correction dicts.
    Each dict has 'from_value' (float) and 'to_value' (float).

    Fail-soft: missing dir or file → no corrections, never raises.
    """
    result: dict[tuple[str, str], list[dict]] = {}
    if not corrections_dir.is_dir():
        return result

    for filename in _CORRECTIONS_FILENAMES:
        path = corrections_dir / filename
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    if row.get("correction_type") != "manual_adjust":
                        continue
                    if row.get("field") != "quantity":
                        continue
                    ticker = row.get("target_key", "").strip()
                    date = row.get("correction_date", "").strip()
                    from_v = _safe_float(row.get("from_value"))
                    to_v = _safe_float(row.get("to_value"))
                    if not ticker or not date or from_v is None or to_v is None:
                        continue
                    key = (ticker, date)
                    result.setdefault(key, []).append({
                        "from_value": from_v,
                        "to_value": to_v,
                    })
        except (OSError, UnicodeDecodeError):
            # Fail-soft per CONVENTION.md
            continue

    return result


def _find_correction(
    corrections: dict[tuple[str, str], list[dict]],
    ticker: str,
    date: str,
    qty: float,
) -> float | None:
    """Return corrected quantity if a matching correction exists, else None.

    Join key: (ticker, date) AND from_value == qty (float-normalized).
    The from_value guard prevents misbinding when a ticker has multiple
    same-day rows.
    """
    entries = corrections.get((ticker, date))
    if not entries:
        return None
    for entry in entries:
        if _floats_equal(entry["from_value"], qty):
            return entry["to_value"]
    return None


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

def check_orders_file(
    path: Path,
    corrections: dict[tuple[str, str], list[dict]] | None = None,
) -> tuple[list[dict], int]:
    """Return (violations, corrections_applied_count).

    violations: one dict per row that violates the total sanity check.
    corrections_applied_count: number of rows that passed only via a correction.

    Dict keys: row_num, date, ticker, side, quantity, price, fees, total_stored,
    total_expected, deviation_pct.

    Rows where any of quantity/price/total are missing/unparseable are skipped
    (not violations — missing data is a different check).
    """
    if corrections is None:
        corrections = {}

    violations: list[dict] = []
    corrections_applied = 0

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

                side = (row.get("side") or "").strip().upper()
                ticker = (row.get("ticker") or "").strip()
                date = (row.get("date") or "").strip()

                stored = abs(total)
                if stored == 0.0:
                    # Zero total row is a separate anomaly; skip.
                    continue

                def _compute_expected(effective_qty: float) -> float:
                    """Side-aware expected total magnitude."""
                    gross = abs(effective_qty * price)
                    if side == "V":
                        return gross - fees  # sell: fees deducted from proceeds
                    else:
                        return gross + fees  # buy (C) or unknown: fees added to cost

                expected = _compute_expected(qty)
                deviation = abs(stored - expected) / stored

                # If still outside tolerance, try corrections-join.
                corrected_qty: float | None = None
                if deviation > _TOLERANCE and corrections:
                    corrected_qty = _find_correction(corrections, ticker, date, qty)
                    if corrected_qty is not None:
                        expected_corrected = _compute_expected(corrected_qty)
                        deviation_corrected = abs(stored - expected_corrected) / stored
                        if deviation_corrected <= _TOLERANCE:
                            corrections_applied += 1
                            continue  # row passes via correction

                if deviation > _TOLERANCE:
                    violations.append({
                        "row_num": row_num,
                        "date": date,
                        "ticker": ticker,
                        "side": side,
                        "quantity": qty,
                        "price": price,
                        "fees": fees,
                        "total_stored": total,
                        "total_expected": expected if total >= 0 else -expected,
                        "deviation_pct": deviation * 100,
                    })
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"Could not read {path}: {exc}") from exc
    return violations, corrections_applied


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Gate #5: parser total sanity — total ≈ qty×price±fees (tol 0.5%)."
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

    # Load corrections once (fail-soft).
    corrections_dir = _default_corrections_dir()
    corrections = load_qty_corrections(corrections_dir)

    all_violations: list[dict] = []
    total_corrections_applied = 0
    error_files: list[str] = []

    for path in files:
        try:
            violations, corrections_applied = check_orders_file(path, corrections)
            all_violations.extend(violations)
            total_corrections_applied += corrections_applied
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
            "corrections_applied": total_corrections_applied,
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

    msg = (
        f"gate_5 PASS — all rows within {_TOLERANCE * 100:.1f}% tolerance "
        f"({len(files)} file(s) checked"
    )
    if total_corrections_applied:
        msg += f", {total_corrections_applied} row(s) passed via quantity correction"
    msg += ")"
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
