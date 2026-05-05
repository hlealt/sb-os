"""Unit tests for `lib.suppliers` — alias matching, movable cascade,
R$200 rollup boundaries, and invariant 6 ("Outros" is presentation-only).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from lib.suppliers import (
    SupplierIndex,
    UnresolvedMovableError,
    detect_supplier,
    get_supplier_movable,
    load_suppliers,
    rollup_outros,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def suppliers_index() -> SupplierIndex:
    return load_suppliers(FIXTURES / "suppliers.json")


# ---------------------------------------------------------------------------
# Alias matching — longest-first + first-match-wins
# ---------------------------------------------------------------------------

def test_longest_first_specific_alias_wins(suppliers_index: SupplierIndex):
    """A description matching the LONGER alias must resolve to its supplier,
    not the shorter generic alias (data-model §3.3, T6)."""
    canonical, conf = detect_supplier(
        "IFD*ARCOS DOURADOS SP", suppliers_index,
    )
    assert canonical == "McDonald's (iFood)"
    assert conf == "partial"


def test_short_alias_matches_when_long_does_not(suppliers_index: SupplierIndex):
    """The short alias still wins when the long one does not match the
    description."""
    canonical, conf = detect_supplier("IFD*PIZZARIA TONHO", suppliers_index)
    assert canonical == "iFood (generic)"
    assert conf == "partial"


def test_exact_match_returns_exact_confidence(suppliers_index: SupplierIndex):
    canonical, conf = detect_supplier("UBER", suppliers_index)
    assert canonical == "Uber"
    assert conf == "exact"


def test_no_match_returns_none(suppliers_index: SupplierIndex):
    canonical, conf = detect_supplier("UNKNOWN MERCHANT XYZ", suppliers_index)
    assert canonical is None
    assert conf == "none"


def test_first_match_wins_with_equal_length_aliases(tmp_path: Path):
    """Two aliases of identical length: the one encountered FIRST in the
    longest-first iteration wins. Sort is stable per Python `list.sort`,
    and dict iteration order in JSON-loaded objects preserves insertion
    (Python 3.7+ guarantee). So the supplier whose alias was loaded first
    wins on ties.
    """
    fixture = {
        "version": 1,
        "suppliers": {
            "supplier_a": {
                "canonical": "A Corp",
                "aliases": ["AAA"],
                "movable": False,
            },
            "supplier_b": {
                "canonical": "B Corp",
                "aliases": ["BBB"],
                "movable": False,
            },
        },
    }
    import json
    p = tmp_path / "suppliers.json"
    p.write_text(json.dumps(fixture), encoding="utf-8")
    idx = load_suppliers(p)
    # Description matches BBB only; A Corp has no overlap. Sanity:
    canonical, _ = detect_supplier("BBB MERCHANT", idx)
    assert canonical == "B Corp"

    # Now an overlapping equal-length case: both AAA and BBB present in
    # description, both length 3 — the first loaded (supplier_a) wins.
    canonical, _ = detect_supplier("AAA BBB COMBINED", idx)
    assert canonical == "A Corp"


def test_empty_description(suppliers_index: SupplierIndex):
    canonical, conf = detect_supplier("", suppliers_index)
    assert canonical is None
    assert conf == "none"


# ---------------------------------------------------------------------------
# Movable cascade — supplier explicit, category hint, mixed-raises
# ---------------------------------------------------------------------------

def test_movable_explicit_supplier_overrides_hint(suppliers_index: SupplierIndex):
    """`Dr. XYZ` has explicit movable=true; even with category hint
    'non-movable' the explicit flag wins."""
    assert get_supplier_movable("Dr. XYZ", suppliers_index, "non-movable") is True


def test_movable_falls_back_to_category_hint_when_supplier_unknown(
    suppliers_index: SupplierIndex,
):
    """Unknown supplier + hint='movable' → True. Hint='non-movable' → False."""
    assert get_supplier_movable("UNKNOWN", suppliers_index, "movable") is True
    assert get_supplier_movable("UNKNOWN", suppliers_index, "non-movable") is False


def test_movable_unknown_supplier_with_mixed_hint_raises(
    suppliers_index: SupplierIndex,
):
    """Unknown supplier + hint='mixed' → raise UnresolvedMovableError so the
    caller surfaces it to the user before Pass 2 fires (T1 + invariant 9)."""
    with pytest.raises(UnresolvedMovableError):
        get_supplier_movable("UNKNOWN_DOCTOR", suppliers_index, "mixed")


# ---------------------------------------------------------------------------
# rollup_outros — R$200 threshold boundary cases (invariant 6)
# ---------------------------------------------------------------------------

def _tx(supplier: str, amount: float, day: int) -> dict:
    return {
        "supplier_canonical": supplier,
        "amount": amount,
        "data_caixa": f"2026-04-{day:02d}",
    }


def test_rollup_below_threshold_maps_to_outros():
    """R$199 in the 92-day window → 'Outros'."""
    txs = [_tx("Rare Shop", -199.00, 15)]
    mapping = rollup_outros(txs, date(2026, 4, 30), threshold_brl=200.0)
    assert mapping["Rare Shop"] == "Outros"


def test_rollup_above_threshold_keeps_canonical():
    """R$201 in the 92-day window → canonical name preserved."""
    txs = [_tx("Active Shop", -201.00, 15)]
    mapping = rollup_outros(txs, date(2026, 4, 30), threshold_brl=200.0)
    assert mapping["Active Shop"] == "Active Shop"


def test_rollup_at_threshold_exact_keeps_canonical():
    """Sum == threshold (>=) is canonical, not Outros."""
    txs = [_tx("Active Shop", -200.00, 15)]
    mapping = rollup_outros(txs, date(2026, 4, 30), threshold_brl=200.0)
    assert mapping["Active Shop"] == "Active Shop"


def test_rollup_outside_window_drops_to_outros():
    """Activity OUTSIDE the 92-day window doesn't count toward the sum."""
    # 92-day window ends Apr 30 → starts ~Jan 28. Tx on Jan 1 is outside.
    txs = [{"supplier_canonical": "Rare Shop", "amount": -300.00,
            "data_caixa": "2026-01-01"}]
    mapping = rollup_outros(txs, date(2026, 4, 30), threshold_brl=200.0)
    # Outside window → no in-window activity → mapped to Outros.
    assert mapping["Rare Shop"] == "Outros"


def test_rollup_92_day_window_inclusive_start():
    """The 92-day window is inclusive of (window_end - 92 days).

    For window_end = 2026-04-30, the window starts at 2026-01-28. A tx on
    that exact day must count.
    """
    txs = [_tx_with("Active Shop", -250.00, "2026-01-28")]
    mapping = rollup_outros(txs, date(2026, 4, 30), threshold_brl=200.0)
    assert mapping["Active Shop"] == "Active Shop"


def _tx_with(supplier: str, amount: float, iso_date: str) -> dict:
    return {"supplier_canonical": supplier, "amount": amount,
            "data_caixa": iso_date}
