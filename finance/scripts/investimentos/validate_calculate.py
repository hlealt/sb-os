"""validate_calculate: portfolio.json sanity checker (p4-6).

Default (verbose) mode: reads portfolio.json and pretty-prints:
  - Total IRR and total value
  - Per-class IRR table (irr, terminal_value, flow_count)
  - irr_quality histogram (complete/seed_only/short_window/unverified/missing)
  - Any positions with |irr| > 200% or irr_quality != complete flagged

--strict mode: exits non-zero if any sanity violation is found.
  Violations:
    - |irr| > 200% for any position or class bucket
    - irr_quality missing on a balcão position that has a current_value

This tool is READ-ONLY. It NEVER writes to any ledger.

Usage:
    python validate_calculate.py [--portfolio-path PATH] [--strict]

Exit codes (verbose):  0 always (informational report)
Exit codes (--strict): 0 = no violations, 1 = one or more violations
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "sb-os.json").exists() or (parent / ".obsidian").exists():
            return parent
    raise RuntimeError("Vault root not found")


def _default_portfolio_path() -> Path:
    override = os.environ.get("BOOKKEEPER_PORTFOLIO_PATH")
    if override:
        return Path(override)
    return (
        _find_vault_root()
        / ".user" / "finance" / "bookkeeper" / "ledgers" / "investimentos" / "portfolio.json"
    )


def load_portfolio(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"portfolio.json not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _fmt_pct(v) -> str:
    if v is None:
        return "  n/a"
    return f"{v * 100:+.2f}%"


def _fmt_brl(v) -> str:
    if v is None:
        return "n/a"
    return f"R$ {v:,.2f}"


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def _irr_violations(portfolio: dict) -> list[str]:
    """Return one string per IRR violation found (|irr| > 200%)."""
    violations: list[str] = []
    irr_data = portfolio.get("summary", {}).get("irr", {})
    total_irr = irr_data.get("total")
    if total_irr is not None and abs(total_irr) > 2.0:
        violations.append(f"Portfolio total IRR {_fmt_pct(total_irr)} exceeds ±200% band")
    for cls, v in (irr_data.get("per_class") or {}).items():
        cls_irr = v.get("irr")
        if cls_irr is not None and abs(cls_irr) > 2.0:
            violations.append(f"Class bucket '{cls}': IRR {_fmt_pct(cls_irr)} exceeds ±200% band")
    # Current (open-positions-only) variant — same ±200% band (D12).
    current = irr_data.get("current") or {}
    cur_total = current.get("total")
    if cur_total is not None and abs(cur_total) > 2.0:
        violations.append(f"Portfolio current IRR {_fmt_pct(cur_total)} exceeds ±200% band")
    for cls, v in (current.get("per_class") or {}).items():
        cls_irr = v.get("irr")
        if cls_irr is not None and abs(cls_irr) > 2.0:
            violations.append(
                f"Class bucket '{cls}' (current): IRR {_fmt_pct(cls_irr)} exceeds ±200% band"
            )
    for pos in portfolio.get("positions", []):
        pid = pos.get("id", "?")
        irr = pos.get("irr")
        if irr is not None and abs(irr) > 2.0:
            violations.append(f"Position '{pid}': IRR {_fmt_pct(irr)} exceeds ±200% band")
    return violations


def _quality_violations(portfolio: dict) -> list[str]:
    """Return one string per irr_quality violation (missing on valued balcão position)."""
    violations: list[str] = []
    for pos in portfolio.get("positions", []):
        if pos.get("valuation_method") != "balcao":
            continue
        if pos.get("current_value") is None:
            continue
        q = pos.get("irr_quality", "")
        if not q:
            violations.append(
                f"Position '{pos.get('id', '?')}': balcão position with current_value "
                f"has no irr_quality set"
            )
    return violations


def _quality_histogram(portfolio: dict) -> dict[str, int]:
    hist: dict[str, int] = {}
    for pos in portfolio.get("positions", []):
        q = pos.get("irr_quality") or "missing"
        hist[q] = hist.get(q, 0) + 1
    return hist


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_report(portfolio: dict) -> None:
    meta = portfolio.get("meta", {})
    summary = portfolio.get("summary", {})
    irr_data = summary.get("irr", {})

    print(f"\n{'='*65}")
    print(f"  portfolio.json validation report")
    print(f"  generated_at : {meta.get('generated_at', 'unknown')}")
    print(f"  cut_date     : {meta.get('cut_date', 'unknown')}")
    print(f"{'='*65}")

    # Total IRR + value
    total_irr = irr_data.get("total")
    total_value = summary.get("total_value")
    total_pnl = summary.get("total_pnl")
    current = irr_data.get("current") or {}
    print(f"\n  Total value  : {_fmt_brl(total_value)}")
    print(f"  Total P&L    : {_fmt_brl(total_pnl)}")
    print(f"  Portfolio IRR: {_fmt_pct(total_irr)}")
    if current.get("total") is not None:
        print(f"  Current IRR  : {_fmt_pct(current.get('total'))} (open positions only)")

    # Per-class IRR table — all-time + current variant columns (D12).
    # Legacy portfolios without the `current` block print n/a in those columns.
    per_class = irr_data.get("per_class") or {}
    cur_per_class = current.get("per_class") or {}
    if per_class:
        print(f"\n  {'Bucket':<12}  {'IRR':>8}  {'IRR cur':>8}  {'Terminal Value':>16}  {'Flows':>6}  {'F cur':>6}")
        print(f"  {'-'*12}  {'-'*8}  {'-'*8}  {'-'*16}  {'-'*6}  {'-'*6}")
        for cls, v in per_class.items():
            cur_v = cur_per_class.get(cls) or {}
            irr_s = _fmt_pct(v.get("irr"))
            cur_irr_s = _fmt_pct(cur_v.get("irr"))
            tv_s = _fmt_brl(v.get("terminal_value"))
            fc = v.get("flow_count", 0)
            fc_cur = cur_v.get("flow_count", "n/a")
            print(f"  {cls:<12}  {irr_s:>8}  {cur_irr_s:>8}  {tv_s:>16}  {fc:>6}  {fc_cur:>6}")

    # irr_quality histogram
    hist = _quality_histogram(portfolio)
    if hist:
        print(f"\n  irr_quality distribution:")
        for q_val, count in sorted(hist.items()):
            bar = "█" * min(count, 30)
            print(f"    {q_val:<16}  {count:>4}  {bar}")

    # IRR violations
    irr_v = _irr_violations(portfolio)
    qual_v = _quality_violations(portfolio)
    all_v = irr_v + qual_v
    if all_v:
        print(f"\n  VIOLATIONS ({len(all_v)}):")
        for msg in all_v:
            print(f"    WARN  {msg}")
    else:
        print("\n  No violations found.")

    print(f"\n{'='*65}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def validate(portfolio_path: Path, strict: bool) -> int:
    """Run validation. Returns exit code (0=clean, 1=violations in strict mode)."""
    portfolio = load_portfolio(portfolio_path)
    print_report(portfolio)
    if strict:
        irr_v = _irr_violations(portfolio)
        qual_v = _quality_violations(portfolio)
        if irr_v or qual_v:
            return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="portfolio.json sanity checker — IRR and irr_quality validation."
    )
    parser.add_argument("--portfolio-path", help="Override portfolio.json path")
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit non-zero if any sanity band is violated (CI gate mode)"
    )
    args = parser.parse_args()

    portfolio_path = Path(args.portfolio_path) if args.portfolio_path else _default_portfolio_path()
    try:
        sys.exit(validate(portfolio_path, args.strict))
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
