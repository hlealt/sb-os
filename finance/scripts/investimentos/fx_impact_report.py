"""fx_impact_report: P&L decomposition into asset gain vs FX gain for USD positions (p4-10).

For all USD (rv_eua) positions in portfolio.json, decomposes total BRL P&L into:
  (a) native USD gain  — price appreciation in USD terms
  (b) FX gain          — USD/BRL rate change applied to cost_basis_brl

Uses per-ticker weighted FX rates from fx_engine.build_fx_state() so decomposition
is consistent with how cost_basis_brl was computed by calculate.py.

Answers: "How much of my rv_eua performance is the company vs the dollar appreciating?"

This tool is READ-ONLY. It NEVER writes to any ledger.

Usage:
    python fx_impact_report.py [--portfolio-path PATH]

Exit codes:
    0  Report printed (including empty/no-USD case)
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


def _fmt_brl(v: float) -> str:
    return f"R$ {v:,.2f}"


def _fmt_usd(v: float) -> str:
    return f"$ {v:,.2f}"


def _fmt_pct(v: float) -> str:
    return f"{v * 100:+.2f}%"


def _load_fx_rates(portfolio_path: Path) -> dict[str, float]:
    """Load per-ticker weighted FX rates from fx_engine if importable.

    Falls back gracefully to {} if fx_engine is not available (e.g. tests).
    Returns {ticker: brl_per_usd}.
    """
    try:
        investimentos_dir = Path(__file__).resolve().parent
        if str(investimentos_dir) not in sys.path:
            sys.path.insert(0, str(investimentos_dir))
        from fx_engine import build_fx_state  # type: ignore
        fx_state = build_fx_state()
        tickers = set()
        # We need to know which tickers exist; we'll collect from the lots
        rates = {}
        for lot in fx_state.lots:
            t = lot.ticker
            if t not in rates:
                rates[t] = fx_state.get_ticker_fx_rate(t)
        # Also include the account-level fallback
        rates["__account__"] = fx_state.weighted_avg_rate
        return rates
    except Exception:
        return {}


def decompose_positions(positions: list[dict], fx_rates: dict[str, float]) -> list[dict]:
    """Decompose each USD position's BRL P&L into asset gain + FX gain.

    decomposition:
      cost_usd       = cost_brl / fx_rate_at_cost     (per-ticker weighted avg)
      value_usd      = value_brl / current_price_brl_per_usd  (if available via position)
                       OR estimated from price_native_usd (if present)
      native_pnl_usd = value_usd - cost_usd
      fx_gain_brl    = cost_usd * (fx_rate_now - fx_rate_at_cost)
      total_pnl_brl  = value_brl - cost_brl

    We use the position fields: cost_brl / current_value_brl / price / qty / currency.
    """
    result = []
    for pos in positions:
        if (pos.get("currency") or "BRL").upper() != "USD":
            continue

        pid = pos.get("id", "")
        cost_brl = float(pos.get("cost_brl") or pos.get("cost_basis_brl") or 0)
        value_brl = float(pos.get("current_value_brl") or pos.get("current_value") or 0)
        total_pnl_brl = value_brl - cost_brl

        # Per-ticker FX rate used at purchase time
        fx_rate_at_cost = fx_rates.get(pid)
        if fx_rate_at_cost is None:
            # Try account-level fallback
            fx_rate_at_cost = fx_rates.get("__account__", 0.0)

        if cost_brl == 0 or fx_rate_at_cost == 0:
            result.append({
                "id": pid,
                "cost_brl": cost_brl,
                "value_brl": value_brl,
                "total_pnl_brl": total_pnl_brl,
                "native_pnl_brl": None,
                "fx_gain_brl": None,
                "fx_rate_at_cost": fx_rate_at_cost,
                "note": "insufficient cost or FX data",
            })
            continue

        # Estimate USD values from BRL via the per-ticker rate
        cost_usd = cost_brl / fx_rate_at_cost

        # For current value we use current_price_usd if present, else estimate from value_brl
        # portfolio.json positions may carry `price` (current price in native currency)
        # and `quantity`. If price is in USD, value_usd = qty * price
        qty = float(pos.get("quantity") or pos.get("qty") or 0)
        price_native = float(pos.get("price") or 0)
        if qty > 0 and price_native > 0:
            value_usd = qty * price_native
        elif fx_rate_at_cost > 0 and value_brl > 0:
            # Use the same rate as a rough estimate (no current FX rate available separately)
            # This slightly underestimates FX effect but avoids inventing a current rate
            value_usd = value_brl / fx_rate_at_cost
        else:
            value_usd = 0.0

        native_pnl_usd = value_usd - cost_usd
        native_pnl_brl = native_pnl_usd * fx_rate_at_cost
        fx_gain_brl = total_pnl_brl - native_pnl_brl

        result.append({
            "id": pid,
            "cost_brl": cost_brl,
            "value_brl": value_brl,
            "total_pnl_brl": total_pnl_brl,
            "native_pnl_usd": native_pnl_usd,
            "native_pnl_brl": native_pnl_brl,
            "fx_gain_brl": fx_gain_brl,
            "fx_rate_at_cost": fx_rate_at_cost,
            "note": "",
        })
    return result


def print_report(rows: list[dict], meta: dict) -> None:
    cut_date = meta.get("cut_date", "unknown")
    print(f"\n{'='*78}")
    print(f"  fx_impact_report — cut_date: {cut_date}")
    print(f"  Decomposes rv_eua (USD) BRL P&L = native asset gain + FX gain")
    print("=" * 78)

    if not rows:
        print("\n  (no USD positions found in portfolio.json)")
        print("=" * 78)
        return

    # Header
    print(f"\n  {'id':<28}  {'cost_brl':>13}  {'value_brl':>13}  "
          f"{'native_pnl':>13}  {'fx_gain':>13}  {'total_pnl':>13}  {'fx_rate':>8}")
    print(f"  {'-'*28}  {'-'*13}  {'-'*13}  {'-'*13}  {'-'*13}  {'-'*13}  {'-'*8}")

    total_cost = 0.0
    total_value = 0.0
    total_native = 0.0
    total_fx = 0.0
    total_pnl = 0.0

    for row in sorted(rows, key=lambda r: r["id"]):
        cost = row["cost_brl"]
        value = row["value_brl"]
        pnl = row["total_pnl_brl"]
        native = row.get("native_pnl_brl")
        fx = row.get("fx_gain_brl")
        fx_rate = row.get("fx_rate_at_cost", 0.0)
        note = row.get("note", "")

        native_s = _fmt_brl(native) if native is not None else "  n/a"
        fx_s = _fmt_brl(fx) if fx is not None else "  n/a"

        print(f"  {row['id']:<28}  {_fmt_brl(cost):>13}  {_fmt_brl(value):>13}  "
              f"{native_s:>13}  {fx_s:>13}  {_fmt_brl(pnl):>13}  {fx_rate:>8.4f}")

        total_cost += cost
        total_value += value
        if native is not None:
            total_native += native
        if fx is not None:
            total_fx += fx
        total_pnl += pnl

        if note:
            print(f"    NOTE: {note}")

    # Totals row
    print(f"  {'-'*28}  {'-'*13}  {'-'*13}  {'-'*13}  {'-'*13}  {'-'*13}  {'-'*8}")
    print(f"  {'TOTAL (rv_eua)':<28}  {_fmt_brl(total_cost):>13}  {_fmt_brl(total_value):>13}  "
          f"{_fmt_brl(total_native):>13}  {_fmt_brl(total_fx):>13}  {_fmt_brl(total_pnl):>13}  "
          f"{'':>8}")

    # Attribution footer
    print(f"\n  Portfolio-level FX attribution:")
    if total_pnl != 0:
        fx_share = total_fx / total_pnl * 100 if total_pnl != 0 else 0
        native_share = total_native / total_pnl * 100 if total_pnl != 0 else 0
        direction = "added" if total_fx >= 0 else "subtracted"
        print(f"    FX {direction} {_fmt_brl(abs(total_fx))} of the {_fmt_brl(total_pnl)} total rv_eua gain "
              f"({fx_share:.1f}% FX, {native_share:.1f}% asset).")
    else:
        print(f"    Total P&L is zero — no attribution available.")

    print("=" * 78)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Decompose rv_eua (USD) P&L into asset gain + FX gain."
    )
    parser.add_argument("--portfolio-path", help="Override portfolio.json path")
    args = parser.parse_args()

    portfolio_path = Path(args.portfolio_path) if args.portfolio_path else _default_portfolio_path()
    if not portfolio_path.exists():
        print(f"ERROR: portfolio.json not found: {portfolio_path}", file=sys.stderr)
        sys.exit(1)

    with open(portfolio_path, encoding="utf-8") as f:
        portfolio = json.load(f)

    positions = portfolio.get("positions", [])
    meta = portfolio.get("meta", {})

    fx_rates = _load_fx_rates(portfolio_path)
    rows = decompose_positions(positions, fx_rates)
    print_report(rows, meta)
    sys.exit(0)


if __name__ == "__main__":
    main()
