"""Supplier alias detection + render-time `Outros` rollup.

Two distinct concerns, both pure:

  1. DETECTION (parser/categorize-time)
     Resolve a canonical supplier name from a raw bank description via
     `suppliers.json`. Aliases are sorted longest-first at load time and
     evaluated first-match-wins — no accumulation, no multi-supplier rows.
     See data-model.md §3.3.

  2. ROLLUP (presentation-time, dashboard)
     Bucket low-volume suppliers into 'Outros' based on a rolling
     3-month window per spec T6. The rollup is computed per render — the
     storage layer NEVER holds 'Outros' as supplier_canonical (data-model
     §6 invariant 6).

Case-sensitivity: matching is case-insensitive (description is uppercased
once). Accent-sensitive — `.upper()` preserves accents.

Pure module: no global state. `load_suppliers` is the only side-effecting
boundary (file read).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

Transaction = dict[str, Any]


class UnresolvedMovableError(ValueError):
    """Raised when a supplier's effective movable flag cannot be resolved.

    Fires when the supplier is unknown AND the category hint is 'mixed' —
    the caller (Pass 1 review) must surface this to the user before Pass 2
    boundary checks can fire.
    """


@dataclass(frozen=True)
class _Alias:
    upper: str             # uppercased alias text used for matching
    slug: str              # supplier slug (key in suppliers.json)
    canonical: str         # canonical display name


@dataclass
class SupplierIndex:
    """Indexed view of suppliers.json. Construct via `load_suppliers`."""

    raw: dict[str, Any]
    aliases_longest_first: list[_Alias] = field(default_factory=list)

    def get_supplier(self, slug: str) -> dict[str, Any] | None:
        return self.raw.get("suppliers", {}).get(slug)

    def find_by_canonical(self, canonical: str) -> dict[str, Any] | None:
        if canonical is None:
            return None
        suppliers = self.raw.get("suppliers", {})
        # Exact match takes priority.
        for slug, supplier in suppliers.items():
            if supplier.get("canonical") == canonical:
                return supplier
        # Case-insensitive fallback: the stored canonical is raw, but a row's
        # supplier_canonical is name-canonicalized (titlecase), so an acronym
        # canonical ("TT Técnica") diverges from its row form ("Tt Técnica").
        # The divergence is casing-only, so a lowercased compare re-binds it.
        target = canonical.strip().lower()
        for slug, supplier in suppliers.items():
            if str(supplier.get("canonical", "")).strip().lower() == target:
                return supplier
        return None


def load_suppliers(suppliers_json_path: Path) -> SupplierIndex:
    """Load suppliers.json and return an indexed structure.

    Aliases are flattened across all suppliers and sorted by length
    DESCENDING so longer/more-specific aliases match before generic ones.
    """
    with open(suppliers_json_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    aliases: list[_Alias] = []
    for slug, supplier in raw.get("suppliers", {}).items():
        canonical = supplier.get("canonical", slug)
        for alias in supplier.get("aliases", []):
            if not alias:
                continue
            aliases.append(_Alias(upper=alias.upper(), slug=slug, canonical=canonical))

    aliases.sort(key=lambda a: len(a.upper), reverse=True)
    return SupplierIndex(raw=raw, aliases_longest_first=aliases)


def detect_supplier(
    description: str,
    index: SupplierIndex,
) -> tuple[str | None, str]:
    """Find the canonical supplier for a transaction description.

    Returns (canonical_name | None, match_confidence) where:
      - full alias == description.upper()  → ('<canonical>', 'exact')
      - alias is a substring of description.upper() → ('<canonical>', 'partial')
      - no match → (None, 'none')

    Iterates aliases longest-first and stops at the FIRST hit. Pure.
    """
    if not description:
        return None, "none"
    desc_upper = description.upper()
    for alias in index.aliases_longest_first:
        if alias.upper == desc_upper:
            return alias.canonical, "exact"
        if alias.upper in desc_upper:
            return alias.canonical, "partial"
    return None, "none"


def get_supplier_movable(
    canonical: str,
    index: SupplierIndex,
    category_hint: str = "non-movable",
) -> bool:
    """Resolve the effective movable flag for a supplier.

    Rules (per spec T1):
      - Supplier exists in the index → return its 'movable' field.
      - Supplier missing → fall back to category_hint:
          * 'movable'     → True
          * 'non-movable' → False
          * 'mixed'       → raise UnresolvedMovableError (caller MUST prompt
                            user before Pass 2 boundary checks fire).

    Pure. No file I/O.
    """
    supplier = index.find_by_canonical(canonical) if canonical else None
    if supplier is not None and "movable" in supplier:
        return bool(supplier["movable"])

    hint = (category_hint or "non-movable").strip().lower()
    if hint == "movable":
        return True
    if hint == "non-movable":
        return False
    if hint == "mixed":
        raise UnresolvedMovableError(
            f"Supplier '{canonical or '<unknown>'}' has no explicit movable flag "
            f"and category hint is 'mixed' — surface to user before Pass 2."
        )
    # Unknown hint value defaults to non-movable (conservative).
    return False


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _three_month_window_start(window_end: date) -> date:
    """Inclusive start of the trailing 3-month window ending on window_end.

    Implementation: subtract ~92 days. The spec ("rolling 3-month window")
    is an analytical heuristic, not an accounting period; using a fixed-
    length sliding window keeps the rollup deterministic and avoids
    month-arithmetic edge cases.
    """
    return window_end - timedelta(days=92)


def rollup_outros(
    transactions: list[Transaction],
    rolling_3_month_window_end: date,
    threshold_brl: float = 200.0,
) -> dict[str, str]:
    """Render-time rollup helper (T6).

    Computes, for each distinct `supplier_canonical` appearing in the
    transactions list, whether its absolute-spend over the trailing
    3-month window ending on `rolling_3_month_window_end` (inclusive)
    crosses `threshold_brl`. Returns a mapping
    `supplier_canonical -> display_name` where display_name is either
    the canonical name (sum >= threshold) or 'Outros' (sum < threshold,
    OR supplier_canonical is empty/None).

    Invariants:
      - 'Outros' is presentation-only — NEVER persisted to storage.
      - The rollup sums absolute amount across ALL categories (per-supplier).
      - Reimbursements (negative amounts under expense suppliers) shrink the
        per-supplier sum via abs() — that is intentional: a supplier whose
        net activity is small belongs in 'Outros'.
      - The mapping ALWAYS includes an entry for the empty-supplier case
        ('') → 'Outros' if any input row has empty supplier_canonical.

    Pure. No file I/O. Does not mutate `transactions`.
    """
    window_start = _three_month_window_start(rolling_3_month_window_end)
    sums: dict[str, float] = {}
    saw_empty = False

    for tx in transactions:
        sup = tx.get("supplier_canonical") or ""
        if not sup:
            saw_empty = True
            continue
        # Use data_caixa for window membership (cash basis defines render time).
        # Fall back to 'date' for legacy rows without basis dates.
        d = _parse_date(tx.get("data_caixa")) or _parse_date(tx.get("date"))
        if d is None:
            continue
        if d < window_start or d > rolling_3_month_window_end:
            continue
        try:
            amt = float(tx.get("amount", 0) or 0)
        except (TypeError, ValueError):
            amt = 0.0
        sums[sup] = sums.get(sup, 0.0) + abs(amt)

    mapping: dict[str, str] = {}
    for sup, total in sums.items():
        mapping[sup] = sup if total >= threshold_brl else "Outros"

    # Ensure suppliers seen but with zero in-window activity still appear.
    for tx in transactions:
        sup = tx.get("supplier_canonical") or ""
        if sup and sup not in mapping:
            mapping[sup] = "Outros"

    if saw_empty:
        mapping[""] = "Outros"

    return mapping
