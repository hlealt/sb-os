"""find_phantom_application: phantom income stream detector (p4-12).

Scans balcao.csv joined with assets.csv for positions where:
  juros_amort_total > 0 but aplicado_total = 0

This pattern indicates a phantom income stream with no recorded principal investment —
common when a parser's data window starts AFTER the actual investment date, so the
initial aplicação is missing.

This tool is READ-ONLY. It NEVER writes to any ledger.

Usage:
    python find_phantom_application.py [--ledger-dir PATH] [--assets-path PATH]

Exit codes:
    0  No phantom positions found
    1  One or more phantom positions detected (or required files not found)
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
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


def compute_per_product_totals(balcao_rows: list[dict]) -> dict[str, dict]:
    """Aggregate aplicado and juros_amort totals per product_id."""
    totals: dict[str, dict] = defaultdict(lambda: {
        "aplicado_total": 0.0,
        "juros_amort_total": 0.0,
        "first_date": None,
        "row_count": 0,
    })
    for r in balcao_rows:
        pid = r.get("product_id", "")
        if not pid:
            continue
        op = (r.get("operation") or "").lower()
        try:
            amt = float(r.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        t = totals[pid]
        t["row_count"] += 1
        # Track first row date
        row_date = r.get("date", "")
        if row_date and (t["first_date"] is None or row_date < t["first_date"]):
            t["first_date"] = row_date
        if op == "aplicacao":
            t["aplicado_total"] += abs(amt)
        elif op in ("juros", "amortizacao"):
            t["juros_amort_total"] += amt
    return dict(totals)


def detect_phantoms(
    totals: dict[str, dict],
    assets: dict[str, dict],
) -> list[dict]:
    """Return list of phantom positions (juros_amort>0, aplicado=0)."""
    phantoms = []
    for pid, t in totals.items():
        if t["aplicado_total"] == 0.0 and t["juros_amort_total"] > 0.0:
            asset_meta = assets.get(pid, {})
            phantoms.append({
                "product_id": pid,
                "aplicado_total": t["aplicado_total"],
                "juros_amort_total": t["juros_amort_total"],
                "first_balcao_date": t["first_date"] or "(unknown)",
                "application_date": asset_meta.get("application_date") or "(not in assets.csv)",
                "asset_name": asset_meta.get("name") or "(not in assets.csv)",
                "active": asset_meta.get("active") or "(unknown)",
            })
    return sorted(phantoms, key=lambda p: p["product_id"])


def _fmt_brl(v: float) -> str:
    return f"R$ {v:,.2f}"


def print_report(phantoms: list[dict]) -> int:
    """Print the phantom application report. Returns count of phantom positions."""
    total_phantom_income = sum(p["juros_amort_total"] for p in phantoms)

    print(f"\n{'='*70}")
    print(f"  find_phantom_application")
    print(f"  Flags: juros_amort_total > 0 AND aplicado_total = 0")
    print("=" * 70)

    if not phantoms:
        print(f"\n  No phantom positions found.")
        print("=" * 70)
        return 0

    print(f"\n  Found {len(phantoms)} phantom position(s) "
          f"— total phantom income: {_fmt_brl(total_phantom_income)}\n")

    # Header
    print(f"  {'product_id':<32}  {'juros_amort':>13}  "
          f"{'first_balcao':>12}  {'app_date':>12}  {'active':>6}")
    print(f"  {'-'*32}  {'-'*13}  {'-'*12}  {'-'*12}  {'-'*6}")

    for p in phantoms:
        print(f"  {p['product_id']:<32}  "
              f"{_fmt_brl(p['juros_amort_total']):>13}  "
              f"{p['first_balcao_date']:>12}  "
              f"{p['application_date']:>12}  "
              f"{p['active']:>6}")

    print(f"\n  Recommended fix: inject a manual seed row (operation=aplicacao) with the")
    print(f"  estimated principal for each flagged asset.")
    print("=" * 70)
    return len(phantoms)


def audit(ledger_dir: Path, assets_path: Path) -> int:
    """Run the audit. Returns exit code (0=clean, 1=phantoms or files missing)."""
    balcao_path = ledger_dir / "balcao.csv"
    if not balcao_path.exists():
        print(f"ERROR: balcao.csv not found: {balcao_path}", file=sys.stderr)
        return 1

    balcao_rows = _load_csv(balcao_path)
    assets_rows = _load_csv(assets_path)
    assets = {r["id"]: r for r in assets_rows if r.get("id")}

    totals = compute_per_product_totals(balcao_rows)
    phantoms = detect_phantoms(totals, assets)
    count = print_report(phantoms)
    return 1 if count > 0 else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect phantom income streams in balcao.csv (juros_amort>0, aplicado=0)."
    )
    parser.add_argument("--ledger-dir", help="Override investimentos ledger directory")
    parser.add_argument("--assets-path", help="Override assets.csv path")
    args = parser.parse_args()

    ledger_dir = Path(args.ledger_dir) if args.ledger_dir else _default_ledger_dir()
    assets_path = Path(args.assets_path) if args.assets_path else _default_assets_path()
    sys.exit(audit(ledger_dir, assets_path))


if __name__ == "__main__":
    main()
