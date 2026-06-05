"""position_summary: all-in-one diagnostic for a single investment position (p4-5).

Given a product_id, prints:
  - Asset metadata (name, type, active, application_date, maturity_date)
  - Balcão summary (aplicado_total, resgates_total, juros_amort_total,
    net_flow, flow_count, irr, irr_quality)
  - Balance-snapshot trajectory (last 6 entries)
  - Inline sub-detector results:
      find_phantom_application  — aplicado=0 and juros_amort>0
      audit_active_vs_maturity  — active=true but maturity_date < today
      audit_balcao_dups         — (date, op, |amount|) cross-source duplicates
                                  (groups covered by the read-time dedup are
                                  reported as INFO, not anomalies)

This tool is READ-ONLY. It NEVER writes to any ledger.

Usage:
    python position_summary.py PRODUCT_ID [--ledger-dir PATH] [--assets-path PATH]

Exit codes:
    0  No anomalies found
    1  One or more anomalies detected (or product_id not found)
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "sb-os.json").exists() or (parent / ".obsidian").exists():
            return parent
    raise RuntimeError("Vault root not found")


def _ledger_dir() -> Path:
    override = os.environ.get("BOOKKEEPER_INVESTIMENTOS_DIR")
    if override:
        return Path(override)
    return _find_vault_root() / ".user" / "finance" / "bookkeeper" / "ledgers" / "investimentos"


def _assets_path() -> Path:
    override = os.environ.get("BOOKKEEPER_ASSETS_PATH")
    if override:
        return Path(override)
    return _find_vault_root() / ".user" / "finance" / "bookkeeper" / "data" / "assets.csv"


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_assets(assets_path: Path) -> dict[str, dict]:
    rows = _load_csv(assets_path)
    return {r["id"]: r for r in rows if r.get("id")}


def load_balcao_for_product(balcao_path: Path, product_id: str) -> list[dict]:
    rows = _load_csv(balcao_path)
    return [r for r in rows if r.get("product_id") == product_id]


def load_snapshots_for_product(snap_path: Path, product_id: str) -> list[dict]:
    rows = _load_csv(snap_path)
    return sorted(
        [r for r in rows if r.get("product_id") == product_id],
        key=lambda r: r.get("date", ""),
    )


# ---------------------------------------------------------------------------
# Sub-detectors
# ---------------------------------------------------------------------------

def detect_phantom_application(rows: list[dict]) -> dict:
    """Flag aplicado_total=0 but juros_amort_total>0."""
    aplicado = sum(
        abs(float(r.get("amount") or 0))
        for r in rows if (r.get("operation") or "").lower() in ("aplicacao",)
    )
    juros_amort = sum(
        float(r.get("amount") or 0)
        for r in rows
        if (r.get("operation") or "").lower() in ("juros", "amortizacao")
    )
    is_phantom = aplicado == 0.0 and juros_amort > 0.0
    return {"is_phantom": is_phantom, "aplicado_total": aplicado, "juros_amort_total": juros_amort}


def detect_active_vs_maturity(asset_meta: dict) -> dict:
    """Flag active=true but maturity_date < today."""
    active_str = (asset_meta.get("active") or "").lower()
    is_active = active_str == "true"
    maturity_str = (asset_meta.get("maturity_date") or "").strip()
    today = date.today()
    if not is_active or not maturity_str:
        return {"stale_active": False, "maturity_date": maturity_str, "days_past": None}
    try:
        mat = datetime.strptime(maturity_str, "%Y-%m-%d").date()
        days_past = (today - mat).days
        return {"stale_active": days_past > 0, "maturity_date": maturity_str, "days_past": days_past}
    except ValueError:
        return {"stale_active": False, "maturity_date": maturity_str, "days_past": None}


def detect_balcao_dups(rows: list[dict]) -> list[dict]:
    """Flag (date, operation, |amount|) duplicates across different sources."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        try:
            amt = round(abs(float(r.get("amount") or 0)), 2)
        except (TypeError, ValueError):
            continue
        key = (r.get("date", ""), (r.get("operation") or "").lower(), amt)
        groups[key].append(r)
    return [g for g in groups.values() if len({r.get("source", "") for r in g}) > 1]


def group_covered_by_read_time_dedup(group: list[dict]) -> bool:
    """True if `_dedup_cross_source_balcao` collapses this group to one row.

    The read-time filter (position_calculator.py, applied via `load_balcao`)
    drops b3 / b3_manual rows whose key matches a safra_movimentacoes row.
    A group is fully neutralized when it has exactly one safra_movimentacoes
    row and every other row is b3 / b3_manual. Ledger rows are NEVER deleted
    (append-only + consumer-side filter convention).
    """
    sources = [(r.get("source") or "").strip() for r in group]
    others = [s for s in sources if s != "safra_movimentacoes"]
    return (sources.count("safra_movimentacoes") == 1 and bool(others)
            and all(s in ("b3", "b3_manual") for s in others))


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_brl(v: float) -> str:
    return f"R$ {v:,.2f}"


def _print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


def _print_kv_table(rows: list[tuple[str, str]]) -> None:
    if not rows:
        return
    key_w = max(len(k) for k, _ in rows)
    for k, v in rows:
        print(f"  {k.ljust(key_w)}  {v}")


# ---------------------------------------------------------------------------
# Main report builder
# ---------------------------------------------------------------------------

def build_report(
    product_id: str,
    ledger_dir: Path,
    assets_path: Path,
) -> int:
    """Print the position summary report. Returns exit code (0=clean, 1=anomaly)."""
    balcao_path = ledger_dir / "balcao.csv"
    snap_path = ledger_dir / "balance-snapshots.csv"

    assets = load_assets(assets_path)
    balcao_rows = load_balcao_for_product(balcao_path, product_id)
    snap_rows = load_snapshots_for_product(snap_path, product_id)

    if not balcao_rows and product_id not in assets:
        print(f"ERROR: product_id '{product_id}' not found in balcao.csv or assets.csv.",
              file=sys.stderr)
        return 1

    asset_meta = assets.get(product_id, {})
    anomalies: list[str] = []

    # ---- Asset metadata ----
    _print_section(f"POSITION: {product_id}")
    _print_kv_table([
        ("name", asset_meta.get("name") or "(not in assets.csv)"),
        ("type", asset_meta.get("type") or ""),
        ("asset_class", asset_meta.get("asset_class") or ""),
        ("active", asset_meta.get("active") or ""),
        ("broker", asset_meta.get("current_broker") or ""),
        ("currency", asset_meta.get("currency") or ""),
        ("application_date", asset_meta.get("application_date") or ""),
        ("maturity_date", asset_meta.get("maturity_date") or ""),
        ("indexer", asset_meta.get("indexer") or ""),
        ("rate", asset_meta.get("rate") or ""),
    ])

    # ---- Balcão summary ----
    _print_section("BALCÃO SUMMARY")
    ops = [(r.get("operation") or "").lower() for r in balcao_rows]
    aplicado = sum(
        abs(float(r.get("amount") or 0))
        for r in balcao_rows if (r.get("operation") or "").lower() == "aplicacao"
    )
    juros_amort = sum(
        float(r.get("amount") or 0)
        for r in balcao_rows
        if (r.get("operation") or "").lower() in ("juros", "amortizacao")
    )
    resgates = sum(
        abs(float(r.get("amount") or 0))
        for r in balcao_rows
        if (r.get("operation") or "").lower() in ("resgate", "vencimento")
    )
    impostos = sum(
        abs(float(r.get("amount") or 0))
        for r in balcao_rows
        if (r.get("operation") or "").lower() in ("irrf", "iof")
    )
    net_flow = sum(float(r.get("amount") or 0) for r in balcao_rows)
    sources = sorted({r.get("source", "") for r in balcao_rows if r.get("source")})
    _print_kv_table([
        ("aplicado_total", _fmt_brl(aplicado)),
        ("juros_amort_total", _fmt_brl(juros_amort)),
        ("resgates_total", _fmt_brl(resgates)),
        ("impostos_total", _fmt_brl(impostos)),
        ("net_flow", _fmt_brl(net_flow)),
        ("flow_count", str(len(balcao_rows))),
        ("sources", ", ".join(sources) if sources else "(none)"),
    ])

    # ---- Balance-snapshot trajectory (last 6) ----
    _print_section("BALANCE-SNAPSHOT TRAJECTORY (last 6)")
    recent_snaps = snap_rows[-6:]
    if recent_snaps:
        print(f"  {'date':<12}  {'balance':>14}  {'source'}")
        print(f"  {'-'*12}  {'-'*14}  {'-'*20}")
        for s in recent_snaps:
            bal = float(s.get("balance") or 0)
            print(f"  {s.get('date', ''):<12}  {_fmt_brl(bal):>14}  {s.get('source', '')}")
    else:
        print("  (no balance snapshots found)")

    # ---- Sub-detector: phantom application ----
    phantom = detect_phantom_application(balcao_rows)
    if phantom["is_phantom"]:
        anomalies.append("PHANTOM_APPLICATION")
        print("\n=== [ANOMALY] PHANTOM APPLICATION ===")
        print(f"  aplicado_total = R$ 0 but juros_amort_total = {_fmt_brl(phantom['juros_amort_total'])}")
        print("  Recommended fix: inject a manual seed row with the estimated principal.")

    # ---- Sub-detector: stale active vs maturity ----
    maturity_check = detect_active_vs_maturity(asset_meta)
    if maturity_check["stale_active"]:
        anomalies.append("STALE_ACTIVE_PAST_MATURITY")
        print("\n=== [ANOMALY] STALE ACTIVE PAST MATURITY ===")
        print(f"  active=true but maturity_date={maturity_check['maturity_date']} "
              f"({maturity_check['days_past']} days ago)")
        print("  Recommended fix: set active=false and record a final vencimento row.")

    # ---- Sub-detector: balcão duplicates ----
    dup_groups = detect_balcao_dups(balcao_rows)
    if dup_groups:
        def _print_groups(groups: list[list[dict]]) -> None:
            for grp in groups:
                print(f"  date={grp[0].get('date')}  op={grp[0].get('operation')}  "
                      f"amount={grp[0].get('amount')}")
                for r in grp:
                    print(f"    source={r.get('source')}")

        uncovered = [g for g in dup_groups if not group_covered_by_read_time_dedup(g)]
        covered = [g for g in dup_groups if group_covered_by_read_time_dedup(g)]
        if uncovered:
            anomalies.append("BALCAO_CROSS_SOURCE_DUPLICATES")
            print(f"\n=== [ANOMALY] BALCÃO CROSS-SOURCE DUPLICATES ({len(uncovered)} group(s)) ===")
            _print_groups(uncovered)
            print("  NOT covered by the read-time dedup (`_dedup_cross_source_balcao`).")
            print("  Resolve via a corrections entry (config/corrections/) — NEVER delete ledger rows.")
        if covered:
            print(f"\n=== [INFO] CROSS-SOURCE DUPLICATES HANDLED AT READ TIME ({len(covered)} group(s)) ===")
            _print_groups(covered)
            print("  Neutralized by `_dedup_cross_source_balcao` (position_calculator.py);")
            print("  rows stay in the ledger — append-only + consumer-side filter convention.")

    # ---- Summary ----
    print(f"\n{'=' * 60}")
    if anomalies:
        print(f"  RESULT: {len(anomalies)} anomaly(ies) found — {', '.join(anomalies)}")
    else:
        print("  RESULT: clean — no anomalies detected")
    print("=" * 60)

    return 1 if anomalies else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="All-in-one diagnostic for a single investment position."
    )
    parser.add_argument("product_id", help="product_id from balcao.csv / assets.csv")
    parser.add_argument("--ledger-dir", help="Override ledger directory path")
    parser.add_argument("--assets-path", help="Override assets.csv path")
    args = parser.parse_args()

    ledger_dir = Path(args.ledger_dir) if args.ledger_dir else _ledger_dir()
    assets_path = Path(args.assets_path) if args.assets_path else _assets_path()

    sys.exit(build_report(args.product_id, ledger_dir, assets_path))


if __name__ == "__main__":
    main()
