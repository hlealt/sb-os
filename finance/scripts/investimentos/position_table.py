"""position_table: tabular CLI dump of portfolio positions (p4-7).

Reads portfolio.json and prints an ASCII table of active positions,
filtered by optional flags. Equivalent to reading the dashboard table
offline — eliminates repeated ad-hoc portfolio.json iteration.

Default columns: id, qty, avg_cost, current_price, pnl_pct,
                 cost_brl, value_brl, pnl_brl, irr, irr_quality

This tool is READ-ONLY. It NEVER writes to any ledger.

Usage:
    python position_table.py [--bucket rv_eua] [--currency USD] [--type cra]
                             [--portfolio-path PATH]

Filters:
    --bucket    IRR class bucket: rv_br | rv_eua | rf_balcao | fundos | crypto
    --currency  Position currency (USD or BRL)
    --type      Position type (cra, deb, acao, stock_us, …)

Exit codes:
    0  Table printed (even if empty after filters)
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


# IRR bucket mapping matches calculate.py _irr_class_bucket
_LISTED_TYPES = {"acao", "fii", "bdr", "opcao", "etf", "stock_us", "etf_us",
                 "direito_subscricao"}
_RF_TYPES = {"cra", "deb", "lca", "lci", "cdb", "cdb_mp", "tesouro", "lc", "cri", "rf"}
_FUND_TYPES = {"fia_br", "fia_usa", "fim_br", "firf_br", "fidc", "coe", "di"}


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


def _safe_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _fmt_pct(v) -> str:
    if v is None:
        return "  n/a"
    return f"{v * 100:+.1f}%"


def _fmt_brl(v) -> str:
    if v is None:
        return "n/a"
    return f"{v:,.0f}"


def _fmt_qty(v) -> str:
    if v is None:
        return ""
    f = float(v)
    if f == int(f):
        return str(int(f))
    return f"{f:.4f}".rstrip("0").rstrip(".")


def _fmt_price(v) -> str:
    if v is None:
        return "n/a"
    return f"{float(v):.2f}"


def _fmt_irr(v) -> str:
    if v is None:
        return "  n/a"
    return f"{v * 100:.2f}%"


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def filter_positions(
    positions: list[dict],
    bucket: str | None,
    currency: str | None,
    asset_type: str | None,
) -> list[dict]:
    out = []
    for pos in positions:
        if bucket and _irr_bucket(pos) != bucket:
            continue
        if currency and (pos.get("currency") or "BRL").upper() != currency.upper():
            continue
        if asset_type and (pos.get("type") or "").lower() != asset_type.lower():
            continue
        out.append(pos)
    return out


def print_table(positions: list[dict]) -> None:
    if not positions:
        print("  (no positions match the given filters)")
        return

    # Determine column set based on valuation_method
    has_price = any(pos.get("valuation_method") in ("price", "crypto") for pos in positions)
    has_balcao = any(pos.get("valuation_method") == "balcao" for pos in positions)

    # Build rows
    rows = []
    total_cost_brl = 0.0
    total_value_brl = 0.0
    total_pnl_brl = 0.0

    for pos in positions:
        vm = pos.get("valuation_method", "")
        if vm in ("price", "crypto"):
            qty = _fmt_qty(pos.get("quantity"))
            avg = _fmt_price(pos.get("avg_cost"))
            cur_price = _fmt_price(pos.get("current_price"))
            pnl_pct = _fmt_pct(pos.get("pnl_pct"))
        else:
            qty = ""
            avg = ""
            cur_price = ""
            pnl_pct = _fmt_pct(pos.get("pnl_pct"))

        cost_brl = _safe_float(pos.get("cost_basis_brl") or pos.get("cost_basis"))
        value_brl = _safe_float(pos.get("current_value_brl") or pos.get("current_value") or 0)
        pnl_brl = _safe_float(pos.get("pnl_absolute_brl") or pos.get("pnl_absolute") or 0)
        irr_str = _fmt_irr(pos.get("irr"))
        quality = pos.get("irr_quality") or ""
        bucket_str = _irr_bucket(pos)

        total_cost_brl += cost_brl
        total_value_brl += value_brl
        total_pnl_brl += pnl_brl

        rows.append({
            "id": pos.get("id", ""),
            "bucket": bucket_str,
            "qty": qty,
            "avg_cost": avg,
            "cur_price": cur_price,
            "pnl_pct": pnl_pct,
            "cost_brl": _fmt_brl(cost_brl),
            "value_brl": _fmt_brl(value_brl),
            "pnl_brl": _fmt_brl(pnl_brl),
            "irr": irr_str,
            "quality": quality,
        })

    # Column widths
    cols = ["id", "bucket", "qty", "avg_cost", "cur_price", "pnl_pct",
            "cost_brl", "value_brl", "pnl_brl", "irr", "quality"]
    headers = ["id", "bucket", "qty", "avg_cost", "price", "pnl%",
               "cost(R$)", "value(R$)", "pnl(R$)", "irr", "quality"]

    widths = {c: len(h) for c, h in zip(cols, headers)}
    for row in rows:
        for c in cols:
            widths[c] = max(widths[c], len(str(row[c])))

    sep = "  ".join("-" * widths[c] for c in cols)
    header_line = "  ".join(h.ljust(widths[c]) for c, h in zip(cols, headers))
    print(f"\n  {header_line}")
    print(f"  {sep}")
    for row in rows:
        print("  " + "  ".join(str(row[c]).ljust(widths[c]) for c in cols))

    # Totals row
    print(f"  {sep}")
    totals = {c: "" for c in cols}
    totals["id"] = "TOTAL"
    totals["cost_brl"] = _fmt_brl(total_cost_brl)
    totals["value_brl"] = _fmt_brl(total_value_brl)
    totals["pnl_brl"] = _fmt_brl(total_pnl_brl)
    print("  " + "  ".join(str(totals[c]).ljust(widths[c]) for c in cols))

    print(f"\n  {len(positions)} position(s) shown.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tabular CLI dump of portfolio positions from portfolio.json."
    )
    parser.add_argument("--bucket", help="Filter by IRR class bucket (rv_br|rv_eua|rf_balcao|fundos|crypto)")
    parser.add_argument("--currency", help="Filter by currency (USD|BRL)")
    parser.add_argument("--type", dest="asset_type", help="Filter by type (acao|stock_us|cra|…)")
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
    print(f"\n  portfolio.json — cut_date: {meta.get('cut_date', 'unknown')}  "
          f"positions: {len(positions)}")

    filtered = filter_positions(positions, args.bucket, args.currency, args.asset_type)
    print_table(filtered)


if __name__ == "__main__":
    main()
