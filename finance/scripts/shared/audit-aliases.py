"""audit-aliases: duplicate alias detector across suppliers.json (p4-14).

Scans suppliers.json for alias strings that appear under more than one supplier entry.
Duplicate aliases are a silent ambiguity: categorize.py's first-match-wins lookup
resolves to different suppliers depending on iteration order.

Real example found 2026-05-03:
  'PAGAMENTO DE CONTA BANCO SANTANDER' → both entre-contas AND cartao-de-credito
  'PAGAMENTO DE CONTA ITAÚ UNIBANCO'   → both condominio AND care-plus

This tool is READ-ONLY. It NEVER writes to suppliers.json.

Usage:
    python audit-aliases.py [--suppliers-path PATH] [--duplicates-only]

Flags:
    --duplicates-only   Print only the duplicate aliases (default: also show stats)
    --suppliers-path    Override path to suppliers.json

Exit codes:
    0  No duplicate aliases found
    1  One or more duplicate aliases detected (suitable for pre-commit hook)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "sb-os.json").exists() or (parent / ".obsidian").exists():
            return parent
    raise RuntimeError("Vault root not found")


def _default_suppliers_path() -> Path:
    override = os.environ.get("BOOKKEEPER_SUPPLIERS_PATH")
    if override:
        return Path(override)
    return (
        _find_vault_root()
        / ".user" / "finance" / "bookkeeper" / "config" / "suppliers.json"
    )


def load_alias_map(suppliers: dict) -> dict[str, list[str]]:
    """Build {alias_upper: [slug, ...]} map from suppliers.json.

    aliases are compared case-insensitively (uppercased) matching categorize.py behavior.
    """
    alias_to_slugs: dict[str, list[str]] = defaultdict(list)
    for slug, supplier in suppliers.get("suppliers", {}).items():
        for alias in supplier.get("aliases", []):
            if not alias:
                continue
            alias_to_slugs[alias.upper()].append(slug)
    return dict(alias_to_slugs)


def find_duplicates(alias_map: dict[str, list[str]]) -> list[dict]:
    """Return entries where an alias appears under more than one slug."""
    dups = []
    for alias_upper, slugs in alias_map.items():
        unique_slugs = list(dict.fromkeys(slugs))  # preserve order, deduplicate
        if len(unique_slugs) > 1:
            dups.append({
                "alias": alias_upper,
                "slugs": unique_slugs,
                "count": len(unique_slugs),
            })
    return sorted(dups, key=lambda d: d["alias"])


def print_report(dups: list[dict], suppliers_path: Path, duplicates_only: bool) -> int:
    """Print the alias audit report. Returns count of duplicate aliases."""
    print(f"\n{'='*70}")
    print(f"  audit-aliases — source: {suppliers_path.name}")
    print("=" * 70)

    if not duplicates_only:
        print(f"\n  Total duplicate aliases found: {len(dups)}")

    if not dups:
        print(f"\n  No duplicate aliases found. suppliers.json is clean.")
        print("=" * 70)
        return 0

    affected_suppliers = set()
    for d in dups:
        affected_suppliers.update(d["slugs"])

    print(f"\n  {len(dups)} duplicate alias(es) across {len(affected_suppliers)} supplier(s).\n")

    # Table header
    print(f"  {'alias':<55}  {'suppliers'}")
    print(f"  {'-'*55}  {'-'*30}")

    for d in dups:
        alias_display = d["alias"]
        if len(alias_display) > 53:
            alias_display = alias_display[:50] + "..."
        slugs_str = ", ".join(d["slugs"])
        print(f"  {alias_display:<55}  {slugs_str}")

    print(f"\n  Recommended actions:")
    print(f"  1. Remove the alias from the lower-priority supplier entry.")
    print(f"  2. If genuinely ambiguous, use value_based_mappings in categories.json instead.")
    print("=" * 70)
    return len(dups)


def audit(suppliers_path: Path, duplicates_only: bool) -> int:
    """Run the audit. Returns exit code (0=clean, 1=duplicates or file missing)."""
    if not suppliers_path.exists():
        print(f"ERROR: suppliers.json not found: {suppliers_path}", file=sys.stderr)
        return 1

    with open(suppliers_path, encoding="utf-8") as f:
        suppliers = json.load(f)

    alias_map = load_alias_map(suppliers)
    dups = find_duplicates(alias_map)
    count = print_report(dups, suppliers_path, duplicates_only)
    return 1 if count > 0 else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect duplicate aliases across suppliers in suppliers.json."
    )
    parser.add_argument("--suppliers-path", help="Override path to suppliers.json")
    parser.add_argument(
        "--duplicates-only", action="store_true",
        help="Print only duplicate aliases (no stats header)"
    )
    args = parser.parse_args()

    suppliers_path = (
        Path(args.suppliers_path) if args.suppliers_path else _default_suppliers_path()
    )
    sys.exit(audit(suppliers_path, args.duplicates_only))


if __name__ == "__main__":
    main()
