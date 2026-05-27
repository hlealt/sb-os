"""bucket_sanity_check: per-class IRR divergence detector (p4-8).

For each IRR bucket (rv_br, rv_eua, rf_balcao, fundos, crypto), lists the
per-asset IRRs and compares their simple average against the portfolio's
stored bucket IRR. Flags divergence with a `>>> DIVERGENCE <<<` marker if
|actual_bucket_irr - simple_avg| > threshold (default 5%).

Note: a legitimate divergence is expected (time-weighted IRR is NOT a simple
average of per-asset IRRs). This tool is informational — it catches large
unexpected mismatches, not the normal time-weighting delta.

This tool is READ-ONLY. It NEVER writes to any ledger.

Usage:
    python bucket_sanity_check.py [--bucket rv_eua] [--threshold 0.05]
                                  [--portfolio-path PATH]

Exit codes:
    0  No divergences found (or running in informational mode)
    1  portfolio.json not found
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


# Bucket classification matching calculate.py
_RF_TYPES = {"cra", "deb", "lca", "lci", "cdb", "cdb_mp", "tesouro", "lc", "cri", "rf"}
_FUND_TYPES = {"fia_br", "fia_usa", "fim_br", "firf_br", "fidc", "coe", "di"}
_ALL_BUCKETS = ("rv_br", "rv_eua", "rf_balcao", "fundos", "crypto")


def _irr_bucket(pos: dict) -> str:
    typ = (pos.get("type") or "").lower()
    currency = (pos.get("currency") or "BRL").upper()
    asset_class = (pos.get("asset_class") or "").lower()
    if asset_class == "crypto" or typ == "crypto":
        return "crypto"
    if typ in _FUND_TYPES:
        return "fundos"
    if typ in _RF_TYPES:
        return "rf_balcao"
    if asset_class == "variable_income":
        return "rv_eua" if currency == "USD" else "rv_br"
    return "other"


def _fmt_pct(v) -> str:
    if v is None:
        return "  n/a"
    return f"{v * 100:+.2f}%"


def _fmt_brl(v) -> str:
    if v is None:
        return "n/a"
    try:
        return f"R$ {float(v):,.0f}"
    except (TypeError, ValueError):
        return str(v)


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def check_buckets(portfolio: dict, target_bucket: str | None, threshold: float) -> int:
    """Print per-bucket divergence report. Returns count of divergences found."""
    irr_summary = portfolio.get("summary", {}).get("irr", {})
    per_class = irr_summary.get("per_class") or {}
    positions = portfolio.get("positions", [])
    meta = portfolio.get("meta", {})

    # Group positions by bucket
    buckets: dict[str, list[dict]] = {b: [] for b in _ALL_BUCKETS}
    for pos in positions:
        b = _irr_bucket(pos)
        if b in buckets:
            buckets[b].append(pos)

    print(f"\n{'='*70}")
    print(f"  bucket_sanity_check — cut_date: {meta.get('cut_date', 'unknown')}")
    print(f"  threshold: {threshold * 100:.1f}%  (|simple_avg - bucket_irr| > threshold → flag)")
    print("=" * 70)

    divergences = 0
    buckets_to_check = [target_bucket] if target_bucket else list(_ALL_BUCKETS)

    for bucket in buckets_to_check:
        if bucket not in _ALL_BUCKETS:
            print(f"\n  WARN: unknown bucket '{bucket}' — skip")
            continue

        pos_list = buckets.get(bucket, [])
        stored = per_class.get(bucket, {})
        stored_irr = stored.get("irr")
        stored_tv = stored.get("terminal_value")
        stored_flows = stored.get("flow_count")

        print(f"\n  {'─'*60}")
        print(f"  Bucket: {bucket}  "
              f"(stored_irr={_fmt_pct(stored_irr)}, "
              f"terminal={_fmt_brl(stored_tv)}, "
              f"flows={stored_flows})")

        if not pos_list:
            print("    (no active positions in this bucket)")
            continue

        # Collect per-asset IRRs
        irr_values = []
        print(f"\n    {'id':<28}  {'irr':>8}  {'quality':<14}  {'value_brl':>12}")
        print(f"    {'-'*28}  {'-'*8}  {'-'*14}  {'-'*12}")
        for pos in sorted(pos_list, key=lambda p: p.get("id", "")):
            irr = pos.get("irr")
            if irr is not None:
                irr_values.append(irr)
            val_brl = pos.get("current_value_brl") or pos.get("current_value") or 0
            print(
                f"    {pos.get('id',''):<28}  {_fmt_pct(irr):>8}  "
                f"{(pos.get('irr_quality') or ''):.<14}  {_fmt_brl(val_brl):>12}"
            )

        if not irr_values:
            print("    (no per-asset IRR values available — cannot compute simple avg)")
            continue

        simple_avg = sum(irr_values) / len(irr_values)
        print(f"\n    simple average IRR : {_fmt_pct(simple_avg)}")
        print(f"    stored bucket IRR  : {_fmt_pct(stored_irr)}")

        if stored_irr is not None:
            delta = abs(simple_avg - stored_irr)
            print(f"    delta              : {delta * 100:.2f}pp")
            if delta > threshold:
                divergences += 1
                print(f"\n    >>> DIVERGENCE <<< |delta| ({delta * 100:.2f}pp) > threshold "
                      f"({threshold * 100:.1f}pp)")
            else:
                print(f"    → within threshold (ok)")
        else:
            print("    (no stored bucket IRR — cannot check divergence)")

    print(f"\n{'='*70}")
    if divergences:
        print(f"  {divergences} divergence(s) found.")
    else:
        print("  All checked buckets within threshold.")
    print("=" * 70)
    return divergences


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Per-class IRR divergence check against portfolio.json bucket IRRs."
    )
    parser.add_argument(
        "--bucket",
        choices=list(_ALL_BUCKETS),
        help="Narrow to one bucket (default: check all)"
    )
    parser.add_argument(
        "--threshold", type=float, default=0.05,
        help="Divergence threshold as decimal (default 0.05 = 5%%)"
    )
    parser.add_argument("--portfolio-path", help="Override portfolio.json path")
    args = parser.parse_args()

    portfolio_path = Path(args.portfolio_path) if args.portfolio_path else _default_portfolio_path()
    if not portfolio_path.exists():
        print(f"ERROR: portfolio.json not found: {portfolio_path}", file=sys.stderr)
        sys.exit(1)

    with open(portfolio_path, encoding="utf-8") as f:
        portfolio = json.load(f)

    check_buckets(portfolio, args.bucket, args.threshold)
    # Always exit 0 — this tool is informational; divergence is expected (time-weighting)
    sys.exit(0)


if __name__ == "__main__":
    main()
