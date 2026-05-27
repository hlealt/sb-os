"""p2-7: Value-based config invariant test.

For every value_based_mappings entry, assert that every supplier whose aliases
include a substring match of the vendor pattern has a default_category that
agrees with the value-based entry's category.

Background (p2-5 fragility note / p2-5-ordering.md §9):
  The value-based layer fires before supplier resolution. When two suppliers
  share an alias, the value-based rule is the amount-based disambiguator. If
  a supplier's default_category ever diverges from the value-based category,
  the invariant breaks silently — any row outside the amount band will fall
  through to supplier resolution and get the wrong category.

  This test converts that silent-wrong risk into a loud-fail gate.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _find_live_config() -> tuple[Path, Path] | None:
    """Return (categories.json path, suppliers.json path) from the live vault config."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        cats = parent / ".user" / "finance" / "bookkeeper" / "config" / "categories.json"
        sups = parent / ".user" / "finance" / "bookkeeper" / "config" / "suppliers.json"
        if cats.exists() and sups.exists():
            return cats, sups
    return None


def _alias_matches_vendor_pattern(alias: str, vendor_pattern: str) -> bool:
    """Return True when vendor_pattern is a substring of alias (case-insensitive)."""
    return vendor_pattern.upper() in alias.upper()


def test_value_based_supplier_default_category_agreement():
    """Every alias-sharing supplier's default_category must agree with value-based entry.

    For each value_based_mappings entry (vendor, amount, category):
      For each supplier whose aliases include a substring match of vendor:
        assert supplier.default_category == value_based_entry.category

    A mismatch means a row at an amount OUTSIDE the ±5% band would be classified
    by the supplier layer and get the wrong category silently.

    KNOWN DOCUMENTED EXCEPTIONS (p2-5-ordering.md §9, p2-5 fragility note):
    The condominio and care-plus suppliers both declare the alias
    "PAGAMENTO DE CONTA ITAÚ UNIBANCO" with different default_category values
    (casa vs saude). This is intentional and structural — the value-based layer
    exists precisely to disambiguate these two. Their disagreement is expected
    and must not trigger a failure. Only NEW undocumented disagreements fail.
    """
    # Known exceptions: (vendor_pattern_upper, supplier_slug) pairs that are
    # documented in p2-5-ordering.md §9 as intentional shared-alias collisions
    # resolved by value-based disambiguation. Add new entries here ONLY when
    # a new shared-alias collision is documented in an inventory artifact.
    KNOWN_EXCEPTIONS: set[tuple[str, str]] = {
        ("PAGAMENTO DE CONTA ITAÚ UNIBANCO", "condominio"),
        ("PAGAMENTO DE CONTA ITAÚ UNIBANCO", "care-plus"),
    }

    paths = _find_live_config()
    if paths is None:
        pytest.skip("Live config not found — skipping invariant test")

    cats_path, sups_path = paths

    categories_config = json.loads(cats_path.read_text(encoding="utf-8"))
    suppliers_config = json.loads(sups_path.read_text(encoding="utf-8"))

    value_based_mappings: list[dict] = categories_config.get("value_based_mappings", [])
    suppliers: dict = suppliers_config.get("suppliers", {})

    failures: list[str] = []

    for vb_entry in value_based_mappings:
        vendor_pattern: str = vb_entry.get("vendor", "")
        vb_category: str = vb_entry.get("category", "")
        if not vendor_pattern or not vb_category:
            continue

        for slug, supplier in suppliers.items():
            # Skip documented exceptions
            if (vendor_pattern.upper(), slug) in {
                (vp.upper(), s) for vp, s in KNOWN_EXCEPTIONS
            }:
                continue

            aliases: list[str] = supplier.get("aliases", [])
            matching_aliases = [
                a for a in aliases
                if _alias_matches_vendor_pattern(a, vendor_pattern)
            ]
            if not matching_aliases:
                continue

            sup_category: str = supplier.get("default_category", "")
            if sup_category != vb_category:
                failures.append(
                    f"INVARIANT BROKEN: value_based_mappings vendor={vendor_pattern!r} "
                    f"category={vb_category!r} | supplier slug={slug!r} "
                    f"canonical={supplier.get('canonical')!r} "
                    f"default_category={sup_category!r} (via alias {matching_aliases[0]!r}). "
                    f"Rows at amounts outside ±5% of {vb_entry.get('amount')} "
                    f"will be silently classified as {sup_category!r} instead of {vb_category!r}. "
                    f"If this collision is intentional (disambiguated by value-based), "
                    f"add it to KNOWN_EXCEPTIONS in this test with an inventory artifact citation."
                )

    assert not failures, (
        "Value-based/supplier default_category invariant violated:\n"
        + "\n".join(failures)
    )


def test_value_based_vendor_patterns_match_supplier_aliases():
    """Every value_based_mappings vendor pattern must match at least one supplier alias.

    A vendor pattern that matches no supplier alias is an orphan — the
    value-based rule fires for matched amounts but has no supplier layer
    fallback, producing 'a_identificar' for out-of-band rows. This is a
    fragility worth surfacing.

    NOTE: this is a WARNING-level assertion (uses pytest.warns-style approach
    but as a soft failure). We assert the count is zero and emit a clear
    message so the reviewer can decide whether the pattern is intentional.
    """
    paths = _find_live_config()
    if paths is None:
        pytest.skip("Live config not found")

    cats_path, sups_path = paths
    categories_config = json.loads(cats_path.read_text(encoding="utf-8"))
    suppliers_config = json.loads(sups_path.read_text(encoding="utf-8"))

    value_based_mappings = categories_config.get("value_based_mappings", [])
    suppliers = suppliers_config.get("suppliers", {})

    orphan_patterns: list[str] = []
    for vb_entry in value_based_mappings:
        vendor_pattern = vb_entry.get("vendor", "")
        if not vendor_pattern:
            continue
        has_match = any(
            _alias_matches_vendor_pattern(alias, vendor_pattern)
            for supplier in suppliers.values()
            for alias in supplier.get("aliases", [])
        )
        if not has_match:
            orphan_patterns.append(vendor_pattern)

    assert not orphan_patterns, (
        "value_based_mappings entries with no matching supplier alias "
        "(out-of-band rows will fall through to 'a_identificar'):\n"
        + "\n".join(f"  {p!r}" for p in orphan_patterns)
    )


def test_value_based_amount_bands_do_not_overlap():
    """±5% amount bands for the same vendor pattern must not overlap.

    Overlapping bands produce non-deterministic results because the first
    matching rule wins (list iteration order). This asserts that for each
    vendor pattern, no two entries have overlapping bands.
    """
    paths = _find_live_config()
    if paths is None:
        pytest.skip("Live config not found")

    cats_path, _ = paths
    categories_config = json.loads(cats_path.read_text(encoding="utf-8"))
    value_based_mappings = categories_config.get("value_based_mappings", [])

    # Group by vendor pattern
    by_vendor: dict[str, list[dict]] = {}
    for entry in value_based_mappings:
        vp = entry.get("vendor", "")
        by_vendor.setdefault(vp, []).append(entry)

    overlaps: list[str] = []
    for vendor, entries in by_vendor.items():
        if len(entries) < 2:
            continue
        # Build sorted list of (low, high, category)
        bands = sorted(
            (ref * 0.95, ref * 1.05, e.get("category", ""))
            for e in entries
            if (ref := float(e.get("amount", 0))) > 0
        )
        for idx in range(len(bands) - 1):
            low_a, high_a, cat_a = bands[idx]
            low_b, high_b, cat_b = bands[idx + 1]
            if high_a >= low_b:  # bands overlap
                overlaps.append(
                    f"vendor={vendor!r}: band [{low_a:.2f}, {high_a:.2f}] ({cat_a}) "
                    f"overlaps [{low_b:.2f}, {high_b:.2f}] ({cat_b})"
                )

    assert not overlaps, (
        "Overlapping value_based_mappings amount bands for same vendor:\n"
        + "\n".join(overlaps)
    )
