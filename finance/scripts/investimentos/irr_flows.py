"""irr_flows: per-asset IRR flow decomposition reader.

For each requested asset id, prints the synthetic XIRR cash-flow ladder that
calculate.py builds, the terminal anchoring, and the recomputed XIRR vs the
value stored in portfolio.json -- so IRR divergences can be diagnosed without
reading raw CSVs by hand.

Mirrors calculate.py EXACTLY:
  - Calls _build_position_flows (which applies _filter_balcao_for_irr +
    code-migration seeds) to build flow lists.
  - Uses irr_calculator.compute_xirr for rates.
  - Loads ledgers via position_calculator.load_csv / load_balcao with
    meta.cut_date as cut.
  - Applies the same per-valuation-method terminal anchoring as
    _build_position_entry (D9): balcao positions anchor at price_date;
    listed/crypto anchor at meta.cut_date.

Split-id handling: when the same id appears in multiple portfolio positions
(e.g. BTC at two exchanges), each position gets its own terminal row, PLUS a
combined row that sums both terminals and recomputes XIRR(merged_flows, combined).
For crypto, each exchange has its own partitioned flow key ({asset}@{exchange}),
so each position's stored irr is computed against that exchange's OWN flow
partition -- not the full cross-exchange flow set.  The combined row merges all
exchange-partitioned flows to show the aggregate picture.

This tool is READ-ONLY. It NEVER writes to any file.

Usage:
    python irr_flows.py ID [ID ...] [--portfolio-path PATH] [--ledger-dir PATH]

Environment overrides (mirror bucket_sanity_check.py):
    BOOKKEEPER_PORTFOLIO_PATH   -- overrides --portfolio-path default
    BOOKKEEPER_INVESTIMENTOS_DIR -- overrides --ledger-dir default

Exit codes:
    0  Always (pure read tool); only exit 1 if portfolio.json is missing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return parent
    raise RuntimeError(f"Vault root not found from {__file__}")


def _default_portfolio_path() -> Path:
    override = os.environ.get("BOOKKEEPER_PORTFOLIO_PATH")
    if override:
        return Path(override)
    return (
        _find_vault_root()
        / ".user" / "finance" / "bookkeeper" / "ledgers" / "investimentos" / "portfolio.json"
    )


def _default_ledger_dir() -> Path:
    override = os.environ.get("BOOKKEEPER_INVESTIMENTOS_DIR")
    if override:
        return Path(override)
    return (
        _find_vault_root()
        / ".user" / "finance" / "bookkeeper" / "ledgers" / "investimentos"
    )


# ---------------------------------------------------------------------------
# Import calculate.py machinery
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).parent))
sys.path.append(str(Path(__file__).resolve().parents[1] / "shared"))

from position_calculator import load_csv, load_balcao, LEDGER_DIR  # noqa: E402
from calculate import _build_position_flows  # noqa: E402
from irr_calculator import compute_xirr  # noqa: E402


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_brl(v: float) -> str:
    return f"R$ {v:>14,.2f}"


def _fmt_irr(v) -> str:
    if v is None:
        return "None"
    return f"{v * 100:+.4f}%"


def _print_sep(char: str = "=", width: int = 72) -> None:
    print(char * width)


def _print_section(title: str) -> None:
    print()
    _print_sep()
    print(f"  {title}")
    _print_sep()


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _load_portfolio(portfolio_path: Path) -> dict:
    if not portfolio_path.exists():
        print(f"ERROR: portfolio.json not found at {portfolio_path}", file=sys.stderr)
        sys.exit(1)
    with open(portfolio_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _collect_positions_by_id(portfolio: dict) -> dict[str, list[dict]]:
    """Group portfolio position entries by id (there may be multiple per id)."""
    result: dict[str, list[dict]] = {}
    for pos in portfolio.get("positions", []):
        pid = pos.get("id", "")
        if pid:
            result.setdefault(pid, []).append(pos)
    return result


def _get_flow_key(pos_entry: dict) -> str:
    """Derive the flow dict key used by _build_position_flows for this position."""
    if pos_entry.get("valuation_method") == "crypto":
        return f"{pos_entry['id']}@{pos_entry['broker']}"
    return pos_entry["id"]


def _get_terminal_for_position(pos_entry: dict, cut_date: str) -> tuple[float, str]:
    """Return (terminal_value, terminal_date) matching calculate.py's _build_position_entry."""
    vm = pos_entry.get("valuation_method", "")
    if vm in ("price", "crypto"):
        # Listed / crypto: terminal at cut_date, value = current_value
        val = pos_entry.get("current_value") or 0.0
        return float(val), cut_date
    else:
        # balcao: terminal at price_date (D9)
        val = pos_entry.get("current_value") or 0.0
        price_date = pos_entry.get("price_date") or cut_date
        return float(val), price_date


def report_for_id(
    asset_id: str,
    all_flows: dict[str, list[tuple[str, float]]],
    positions_by_id: dict[str, list[dict]],
    cut_date: str,
) -> None:
    """Print the full IRR flow decomposition for one asset id."""
    pos_entries = positions_by_id.get(asset_id, [])

    _print_section(f"ASSET: {asset_id}")

    # Collect all flow keys for this id (one per exchange for crypto, one for others)
    flow_keys: list[str] = []
    for pos in pos_entries:
        k = _get_flow_key(pos)
        if k not in flow_keys:
            flow_keys.append(k)

    # Determine the "bare id" flow key for non-split assets
    # For non-crypto, all positions share the same flow key = id
    if not pos_entries:
        # id not in portfolio.json -- still show flows if any
        flow_keys = [asset_id]

    # --- Print flow ladders per key ---
    for fk in flow_keys:
        raw_flows = all_flows.get(fk, [])
        sorted_flows = sorted(raw_flows, key=lambda x: x[0])

        label = f"FLOW LADDER: {fk}" if fk != asset_id else "FLOW LADDER"
        print(f"\n  [{label}]  ({len(sorted_flows)} flows)")
        if not sorted_flows:
            print("    (no flows found)")
            continue

        print(f"  {'#':>4}  {'date':<12}  {'amount':>16}  {'cumulative':>16}")
        print(f"  {'-'*4}  {'-'*12}  {'-'*16}  {'-'*16}")
        cumulative = 0.0
        for i, (date_s, amount) in enumerate(sorted_flows, 1):
            cumulative += amount
            print(f"  {i:>4}  {date_s:<12}  {amount:>16,.2f}  {cumulative:>16,.2f}")

    # --- Per-position terminal anchoring and XIRR ---
    print(f"\n  TERMINAL ANCHORING AND XIRR")
    print(f"  {'key':<28}  {'terminal_date':<14}  {'terminal_val':>14}  {'recomputed_xirr':>16}  {'stored_irr':>16}  {'drift':>10}")
    print(f"  {'-'*28}  {'-'*14}  {'-'*14}  {'-'*16}  {'-'*16}  {'-'*10}")

    combined_terminal = 0.0
    combined_terminal_date = cut_date  # default; all crypto use cut_date
    has_combined = len(pos_entries) > 1

    # For balcao positions with different price_dates, use the latest for combined
    # (this is informational -- combined xirr is always anchored at cut_date for
    # consistency when split positions have different price_dates)
    combined_anchor = cut_date

    for pos in pos_entries:
        fk = _get_flow_key(pos)
        raw_flows = all_flows.get(fk, [])
        terminal_val, terminal_date = _get_terminal_for_position(pos, cut_date)
        combined_terminal += terminal_val

        recomputed = compute_xirr(
            raw_flows,
            terminal_value=terminal_val,
            terminal_date=terminal_date,
            label=None,  # silence internal warnings; we report results directly
        )
        stored = pos.get("irr")

        drift = None
        if recomputed is not None and stored is not None:
            drift = recomputed - stored

        drift_str = f"{drift * 100:+.4f}%" if drift is not None else "n/a"
        print(
            f"  {fk:<28}  {terminal_date:<14}  {terminal_val:>14,.2f}"
            f"  {_fmt_irr(recomputed):>16}  {_fmt_irr(stored):>16}  {drift_str:>10}"
        )

    # Combined row for split-id assets
    if has_combined:
        # Use the first flow key that is NOT exchange-split (or the first key)
        # For crypto splits, flows are per-exchange so we need to merge
        # Gather all unique flow keys for this id
        combined_flows_merged: list[tuple[str, float]] = []
        seen_flow_keys: set[str] = set()
        for pos in pos_entries:
            fk = _get_flow_key(pos)
            if fk not in seen_flow_keys:
                seen_flow_keys.add(fk)
                combined_flows_merged.extend(all_flows.get(fk, []))

        # For crypto, each position has its own exchange-keyed flows, so merging
        # all of them gives the full picture. For balcao/listed, all positions
        # share the same flow key -- de-duplication handles that above.
        combined_xirr = compute_xirr(
            combined_flows_merged,
            terminal_value=combined_terminal,
            terminal_date=combined_anchor,
            label=None,
        )
        combined_str = _fmt_irr(combined_xirr)
        print(
            f"  {'[COMBINED]':<28}  {combined_anchor:<14}  {combined_terminal:>14,.2f}"
            f"  {combined_str:>16}  {'(n/a)':>16}  {'':>10}"
        )
        print(
            f"\n  NOTE: per-position stored irr uses that exchange's OWN partitioned"
            f"\n        flow set ({'{asset}@{exchange}'} key) against its partial terminal."
            f"\n        Combined row: all exchange-partitioned flows merged + combined terminal @ {combined_anchor}."
        )

    # --- Summary: position metadata ---
    if pos_entries:
        print(f"\n  POSITION METADATA")
        for pos in pos_entries:
            fk = _get_flow_key(pos)
            vm = pos.get("valuation_method", "")
            print(f"  flow_key={fk}")
            print(f"    valuation_method = {vm}")
            print(f"    broker           = {pos.get('broker', '')}")
            print(f"    type             = {pos.get('type', '')}")
            if vm == "balcao":
                print(f"    price_date       = {pos.get('price_date', '')}")
                print(f"    current_value    = {pos.get('current_value')}")
                print(f"    irr_quality      = {pos.get('irr_quality', '')}")
            else:
                print(f"    price_date       = {pos.get('price_date', '')}")
                print(f"    current_value    = {pos.get('current_value')}")
                print(f"    quantity         = {pos.get('quantity')}")
    else:
        print(f"\n  WARNING: '{asset_id}' not found in portfolio.json positions.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Per-asset IRR flow decomposition reader. Mirrors calculate.py exactly."
    )
    parser.add_argument(
        "ids",
        nargs="+",
        metavar="ID",
        help="One or more asset ids (product_id / ticker)",
    )
    parser.add_argument(
        "--portfolio-path",
        help="Override portfolio.json path (env: BOOKKEEPER_PORTFOLIO_PATH)",
    )
    parser.add_argument(
        "--ledger-dir",
        help="Override ledger directory (env: BOOKKEEPER_INVESTIMENTOS_DIR)",
    )
    args = parser.parse_args()

    portfolio_path = Path(args.portfolio_path) if args.portfolio_path else _default_portfolio_path()
    ledger_dir = Path(args.ledger_dir) if args.ledger_dir else _default_ledger_dir()

    # Load portfolio
    portfolio = _load_portfolio(portfolio_path)
    cut_date: str = portfolio["meta"]["cut_date"]
    positions_by_id = _collect_positions_by_id(portfolio)

    # Build all flows using the exact same pipeline as calculate.py
    all_flows = _build_position_flows(
        load_csv(ledger_dir / "orders.csv", cut_date),
        load_csv(ledger_dir / "proventos.csv", cut_date),
        load_balcao(cut_date),
        load_csv(ledger_dir / "crypto.csv", cut_date),
        load_csv(ledger_dir / "corporate_actions.csv", cut_date),
    )

    print(f"IRR Flow Decomposition  |  cut_date={cut_date}  |  portfolio={portfolio_path.name}")
    _print_sep()

    requested_not_found = []
    for asset_id in args.ids:
        # Check: id must appear in portfolio positions OR in flow keys
        in_portfolio = asset_id in positions_by_id
        in_flows = any(
            fk == asset_id or fk.startswith(f"{asset_id}@")
            for fk in all_flows
        )
        if not in_portfolio and not in_flows:
            requested_not_found.append(asset_id)
            print(f"\nWARNING: '{asset_id}' not found in portfolio.json or flow keys.")
            continue
        report_for_id(asset_id, all_flows, positions_by_id, cut_date)

    print()
    _print_sep()
    print(f"  Total ids requested: {len(args.ids)}  |  Not found: {len(requested_not_found)}")
    _print_sep()


if __name__ == "__main__":
    main()
