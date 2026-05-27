"""audit_active_vs_maturity: stale-active and stale-inactive asset detector (p4-13).

Scans assets.csv for two anomaly types:

  STALE-ACTIVE: active=true but maturity_date < today
    These assets continue to appear in portfolio.json with their last snapshot
    value, inflating current_value and IRR bucket aggregates.

  STALE-INACTIVE (converse): active=false but balcao.csv has recent rows
    If optionally provided, balcao.csv is used to check recency of activity.

This tool is READ-ONLY. It NEVER writes to any ledger.

Usage:
    python audit_active_vs_maturity.py [--assets-path PATH] [--ledger-dir PATH]
                                       [--activity-days N]

Exit codes:
    0  No anomalies found
    1  One or more anomalies detected (or assets.csv not found)
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "sb-os.json").exists() or (parent / ".obsidian").exists():
            return parent
    raise RuntimeError("Vault root not found")


def _default_ledger_dir() -> Path:
    override = os.environ.get("BOOKKEEPER_INVESTIMENTOS_DIR")
    if override:
        return Path(override)
    return _find_vault_root() / ".user" / "finance" / "bookkeeper" / "ledgers" / "investimentos"


def _default_assets_path() -> Path:
    override = os.environ.get("BOOKKEEPER_ASSETS_PATH")
    if override:
        return Path(override)
    return _find_vault_root() / ".user" / "finance" / "bookkeeper" / "data" / "assets.csv"


def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _parse_date(s: str) -> date | None:
    if not s or not s.strip():
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _last_balcao_date(balcao_rows: list[dict], product_id: str) -> date | None:
    """Return the latest date in balcao.csv for this product_id, or None."""
    dates = []
    for r in balcao_rows:
        if r.get("product_id") == product_id:
            d = _parse_date(r.get("date", ""))
            if d:
                dates.append(d)
    return max(dates) if dates else None


def detect_stale_active(assets: list[dict], today: date) -> list[dict]:
    """Find assets where active=true but maturity_date < today."""
    result = []
    for a in assets:
        active_str = (a.get("active") or "").lower()
        if active_str != "true":
            continue
        mat = _parse_date(a.get("maturity_date", ""))
        if mat is None:
            continue  # No maturity date — not applicable (e.g. equities)
        if mat < today:
            days_past = (today - mat).days
            result.append({
                "product_id": a.get("id", ""),
                "name": a.get("name", ""),
                "maturity_date": str(mat),
                "days_past_maturity": days_past,
                "last_balcao_date": None,  # filled later if balcao loaded
            })
    return sorted(result, key=lambda r: r["days_past_maturity"], reverse=True)


def detect_stale_inactive(
    assets: list[dict],
    balcao_rows: list[dict],
    today: date,
    activity_days: int,
) -> list[dict]:
    """Find assets where active=false but balcao has recent rows (within activity_days)."""
    if not balcao_rows:
        return []
    cutoff = today - timedelta(days=activity_days)
    result = []
    for a in assets:
        active_str = (a.get("active") or "").lower()
        if active_str != "false":
            continue
        pid = a.get("id", "")
        last_date = _last_balcao_date(balcao_rows, pid)
        if last_date and last_date >= cutoff:
            result.append({
                "product_id": pid,
                "name": a.get("name", ""),
                "last_balcao_date": str(last_date),
                "days_since_last_activity": (today - last_date).days,
            })
    return sorted(result, key=lambda r: r["last_balcao_date"], reverse=True)


def print_report(
    stale_active: list[dict],
    stale_inactive: list[dict],
    today: date,
    activity_days: int,
) -> int:
    """Print the audit report. Returns total anomaly count."""
    total = len(stale_active) + len(stale_inactive)

    print(f"\n{'='*70}")
    print(f"  audit_active_vs_maturity — reference date: {today}")
    print("=" * 70)

    # --- Stale-active ---
    print(f"\n  STALE-ACTIVE (active=true, maturity_date < today): {len(stale_active)}")
    if stale_active:
        print(f"\n  {'product_id':<32}  {'maturity_date':>13}  {'days_past':>10}  "
              f"{'last_balcao':>12}")
        print(f"  {'-'*32}  {'-'*13}  {'-'*10}  {'-'*12}")
        for r in stale_active:
            lb = str(r["last_balcao_date"]) if r.get("last_balcao_date") else "(not loaded)"
            print(f"  {r['product_id']:<32}  {r['maturity_date']:>13}  "
                  f"{r['days_past_maturity']:>10}  {lb:>12}")
        print(f"\n  Recommended fix: set active=false and record a final vencimento row.")
    else:
        print(f"  None found.")

    # --- Stale-inactive ---
    print(f"\n  STALE-INACTIVE (active=false, balcao activity within {activity_days}d): "
          f"{len(stale_inactive)}")
    if stale_inactive:
        print(f"\n  {'product_id':<32}  {'last_balcao':>12}  {'days_since':>10}")
        print(f"  {'-'*32}  {'-'*12}  {'-'*10}")
        for r in stale_inactive:
            print(f"  {r['product_id']:<32}  {r['last_balcao_date']:>12}  "
                  f"{r['days_since_last_activity']:>10}")
        print(f"\n  Recommended fix: verify if these assets are truly closed; "
              f"set active=true or add a closing row.")
    elif not stale_inactive and len(stale_active) == 0:
        print(f"  None found.")
    else:
        print(f"  None found.")

    # Summary
    print(f"\n  Total anomalies: {total}")
    print("=" * 70)
    return total


def audit(
    assets_path: Path,
    ledger_dir: Path,
    activity_days: int,
) -> int:
    """Run the audit. Returns exit code (0=clean, 1=anomalies or files missing)."""
    if not assets_path.exists():
        print(f"ERROR: assets.csv not found: {assets_path}", file=sys.stderr)
        return 1

    assets = _load_csv(assets_path)
    # balcao is optional — used only for stale-inactive check
    balcao_path = ledger_dir / "balcao.csv"
    balcao_rows = _load_csv(balcao_path)

    today = date.today()
    stale_active = detect_stale_active(assets, today)

    # Populate last_balcao_date for stale-active entries
    if balcao_rows:
        for entry in stale_active:
            entry["last_balcao_date"] = str(
                _last_balcao_date(balcao_rows, entry["product_id"]) or ""
            )

    stale_inactive = detect_stale_inactive(assets, balcao_rows, today, activity_days)
    count = print_report(stale_active, stale_inactive, today, activity_days)
    return 1 if count > 0 else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect stale-active and stale-inactive assets in assets.csv."
    )
    parser.add_argument("--assets-path", help="Override assets.csv path")
    parser.add_argument("--ledger-dir", help="Override investimentos ledger directory")
    parser.add_argument(
        "--activity-days", type=int, default=90,
        help="Window (days) for stale-inactive check (default: 90)"
    )
    args = parser.parse_args()

    assets_path = Path(args.assets_path) if args.assets_path else _default_assets_path()
    ledger_dir = Path(args.ledger_dir) if args.ledger_dir else _default_ledger_dir()
    sys.exit(audit(assets_path, ledger_dir, args.activity_days))


if __name__ == "__main__":
    main()
