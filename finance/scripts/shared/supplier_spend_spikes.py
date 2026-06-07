"""supplier-spend-spikes: month-over-month supplier spending spikes (read/audit-diagnostic).

Lists every supplier whose monthly spending total increased by more than a
threshold (default >20%) versus the immediately preceding calendar month, across
the fechamento transactions.csv ledgers.

This tool is READ-ONLY. It NEVER writes to any ledger.

Spending model:
  - A supplier's monthly spend = sum of (-amount) over that supplier's rows in
    the month, i.e. expenses count positive, refunds/credits net it down.
  - Rows in non-expense categories (receitas, intercontas, ignorar, venda) are
    excluded (same exclusion set as gate_coverage.py).
  - Supplier identity = the `supplier_canonical` column; rows with an empty
    supplier_canonical are grouped under "(unmapped)" and reported, never dropped.
  - The month a row belongs to is taken from the chosen --axis date column
    (data_competencia by default), NOT the folder name, so CC installments
    collapse to their attribution month correctly.

Comparison:
  - Each month is compared against the immediately preceding CALENDAR month
    (e.g. 2026-05 vs 2026-04). A pair is emitted only when both months have data.
  - A supplier is flagged when prior_total > 0 AND
    (current - prior) / prior > threshold, and (when --min-base > 0) the prior
    total is at least --min-base (suppresses tiny-base percentage blowups).
  - Suppliers that spent in the current month but had no prior-month spend are
    listed in a separate "appeared (no prior month spend)" section — surfaced,
    not counted in the >threshold list (no prior = no percentage).

Usage:
    python supplier_spend_spikes.py [options]

Options:
    --axis {competencia,caixa}  Date axis defining the spend month (default: competencia)
    --threshold FLOAT           Increase threshold as a fraction (default: 0.20 = 20%)
    --min-base FLOAT            Minimum prior-month total to flag a supplier (default: 100.0)
    --month YYYY-MM             Restrict to this month vs its prior month only
    --ledger-dir PATH           Override the fechamento dir (default: resolved from vault)

Exit codes:
    0  Ran successfully (whether or not spikes were found)
    1  No fechamento transactions.csv data found
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

# Same non-expense exclusion set as gate_coverage.py.
_EXCLUDED_CATEGORIES = {"receitas", "intercontas", "ignorar", "venda"}
_UNMAPPED = "(unmapped)"
_AXIS_COLUMN = {"competencia": "data_competencia", "caixa": "data_caixa"}


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "sb-os.json").exists() or (parent / ".obsidian").exists():
            return parent
    raise RuntimeError("Vault root not found (looking for sb-os.json or .obsidian)")


def _resolve_fechamento_dir(override: str | None) -> Path:
    if override:
        return Path(override)
    env = os.environ.get("BOOKKEEPER_LEDGER_DIR")
    base = Path(env) if env else (
        _find_vault_root() / ".user" / "finance" / "bookkeeper" / "ledgers"
    )
    return base / "fechamento"


def _prior_month(ym: str) -> str:
    """Return the immediately preceding calendar month for 'YYYY-MM'."""
    year, month = int(ym[:4]), int(ym[5:7])
    if month == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"


def aggregate_spend(
    fechamento_dir: Path,
    axis: str = "competencia",
) -> dict[str, dict[str, float]]:
    """Aggregate net spend per (month, supplier) across all transactions.csv files.

    Returns {month 'YYYY-MM': {supplier_canonical: net_spend_float}}.
    Net spend = sum of (-amount) over included rows. Months come from the axis
    date column value, not the folder name. Pure aside from reading the CSVs.
    """
    axis_col = _AXIS_COLUMN[axis]
    totals: dict[str, dict[str, float]] = {}
    if not fechamento_dir.exists():
        return totals
    for month_dir in sorted(fechamento_dir.iterdir()):
        tx = month_dir / "transactions.csv"
        if not tx.is_file():
            continue
        with open(tx, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                category = (row.get("category") or "").strip().lower()
                if category in _EXCLUDED_CATEGORIES:
                    continue
                axis_val = (row.get(axis_col) or "").strip()
                if len(axis_val) < 7:
                    continue
                month = axis_val[:7]
                try:
                    amount = float(row.get("amount") or "0")
                except ValueError:
                    continue
                supplier = (row.get("supplier_canonical") or "").strip() or _UNMAPPED
                totals.setdefault(month, {})[supplier] = (
                    totals.setdefault(month, {}).get(supplier, 0.0) + (-amount)
                )
    return totals


def find_spikes(
    totals: dict[str, dict[str, float]],
    threshold: float = 0.20,
    min_base: float = 100.0,
    only_month: str | None = None,
) -> dict[str, dict]:
    """Compute month-over-month supplier spikes.

    Returns {current_month: {'prior': str, 'spikes': [...], 'appeared': [...]}}
    where each spike is a dict (supplier, prior, current, delta, pct) sorted by
    pct descending, and each appeared entry is (supplier, current).
    Pure: input -> output, no I/O.
    """
    result: dict[str, dict] = {}
    current_months = [only_month] if only_month else sorted(totals.keys())
    for month in current_months:
        cur = totals.get(month)
        if not cur:
            continue
        prior_m = _prior_month(month)
        prev = totals.get(prior_m)
        if not prev:
            continue
        spikes = []
        appeared = []
        for supplier, cur_total in cur.items():
            if cur_total <= 0:
                continue
            prev_total = prev.get(supplier, 0.0)
            if prev_total <= 0:
                appeared.append({"supplier": supplier, "current": cur_total})
                continue
            if min_base > 0 and prev_total < min_base:
                continue
            pct = (cur_total - prev_total) / prev_total
            if pct > threshold:
                spikes.append({
                    "supplier": supplier,
                    "prior": prev_total,
                    "current": cur_total,
                    "delta": cur_total - prev_total,
                    "pct": pct,
                })
        spikes.sort(key=lambda s: s["pct"], reverse=True)
        appeared.sort(key=lambda a: a["current"], reverse=True)
        result[month] = {"prior": prior_m, "spikes": spikes, "appeared": appeared}
    return result


def _fmt_brl(v: float) -> str:
    return f"R${v:,.2f}"


def _print_report(spikes: dict[str, dict], threshold: float, min_base: float, axis: str) -> None:
    pct_label = f"{threshold * 100:.0f}%"
    print(f"=== Supplier spend spikes (> {pct_label} MoM, axis={axis}, "
          f"min-base={_fmt_brl(min_base)}) ===")
    if not spikes:
        print("No comparable month pairs in the data.")
        return
    for month in sorted(spikes.keys()):
        block = spikes[month]
        print(f"\n--- {month} vs {block['prior']} ---")
        rows = block["spikes"]
        if rows:
            cols = ["supplier", "prior", "current", "delta", "pct"]
            display = [{
                "supplier": r["supplier"],
                "prior": _fmt_brl(r["prior"]),
                "current": _fmt_brl(r["current"]),
                "delta": "+" + _fmt_brl(r["delta"]),
                "pct": f"+{r['pct'] * 100:.1f}%",
            } for r in rows]
            widths = {c: max(len(c), max(len(d[c]) for d in display)) for c in cols}
            print("  ".join(c.ljust(widths[c]) for c in cols))
            print("  ".join("-" * widths[c] for c in cols))
            for d in display:
                print("  ".join(d[c].ljust(widths[c]) for c in cols))
        else:
            print("(no suppliers above threshold)")
        if block["appeared"]:
            names = ", ".join(f"{a['supplier']} ({_fmt_brl(a['current'])})"
                              for a in block["appeared"])
            print(f"appeared (no prior month spend): {names}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List suppliers whose monthly spend rose more than a "
                    "threshold (default >20%) vs the prior calendar month."
    )
    parser.add_argument("--axis", choices=["competencia", "caixa"], default="competencia",
                        help="Date axis defining the spend month (default: competencia)")
    parser.add_argument("--threshold", type=float, default=0.20,
                        help="Increase threshold as a fraction (default: 0.20 = 20%%)")
    parser.add_argument("--min-base", type=float, default=100.0,
                        help="Minimum prior-month total to flag a supplier (default: 100.0)")
    parser.add_argument("--month", help="Restrict to this month (YYYY-MM) vs its prior month")
    parser.add_argument("--ledger-dir", help="Override the fechamento directory")
    args = parser.parse_args()

    fechamento_dir = _resolve_fechamento_dir(args.ledger_dir)
    totals = aggregate_spend(fechamento_dir, axis=args.axis)
    if not totals:
        print(f"ERROR: No fechamento transactions.csv data found under {fechamento_dir}",
              file=sys.stderr)
        sys.exit(1)

    spikes = find_spikes(totals, threshold=args.threshold,
                         min_base=args.min_base, only_month=args.month)
    _print_report(spikes, args.threshold, args.min_base, args.axis)
    sys.exit(0)


if __name__ == "__main__":
    main()
