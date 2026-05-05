"""Unit tests for `lib.boundary` and `lib.tags` token validation
(invariants 7, 9 from data-model.md §6).

`is_boundary_day` is exercised across 28-day Feb (Feb 2026), 30-day April,
and 31-day Jan per the task spec. The data-model contract is
`[1..5] ∪ [last_day-4..last_day]`. Per shape entry (2026-05-02) Feb 23
is NOT a boundary day for Feb 2026 (last=28, window=[24..28]).

`needs_boundary_prompt` is exercised across the four (movable T/F) ×
(boundary T/F) combinations plus a fatura row in the boundary window
with movable=true (must return False — invariant 9 third clause).

Tag-token validation lives in lib.tags but is consolidated here because it
is a single boundary-style check with a regex (invariant 7).
"""
from __future__ import annotations

from datetime import date

import pytest

from lib.boundary import is_boundary_day, needs_boundary_prompt
from lib.tags import is_valid_token


# ---------------------------------------------------------------------------
# is_boundary_day — month-length sensitivity
# ---------------------------------------------------------------------------

# Per data-model contract: window = [1..5] ∪ [last_day-4 .. last_day].
# Feb 2026: last=28 → trailing window = [24..28]
# Apr 2026: last=30 → trailing window = [26..30]
# Jan 2026: last=31 → trailing window = [27..31]

@pytest.mark.parametrize(
    "d, expected",
    [
        # Leading window — universal across months
        (date(2026, 2, 1), True),
        (date(2026, 2, 5), True),
        (date(2026, 2, 6), False),
        # 28-day Feb — trailing window [24..28]
        (date(2026, 2, 23), False),  # shape entry: 23 is NOT boundary
        (date(2026, 2, 24), True),
        (date(2026, 2, 28), True),
        # 30-day April — trailing window [26..30]
        (date(2026, 4, 25), False),
        (date(2026, 4, 26), True),
        (date(2026, 4, 30), True),
        # 31-day January — trailing window [27..31]
        (date(2026, 1, 26), False),
        (date(2026, 1, 27), True),
        (date(2026, 1, 31), True),
        # Mid-month negatives
        (date(2026, 4, 15), False),
        (date(2026, 1, 15), False),
    ],
)
def test_is_boundary_day(d: date, expected: bool):
    assert is_boundary_day(d) is expected


# ---------------------------------------------------------------------------
# needs_boundary_prompt — invariant 9 truth table
# ---------------------------------------------------------------------------

def test_needs_prompt_movable_true_boundary_true_non_fatura():
    """Movable supplier + boundary day + extrato → prompt fires."""
    tx = {"source_type": "extrato"}
    assert needs_boundary_prompt(tx, True, date(2026, 4, 30)) is True


def test_needs_prompt_movable_true_boundary_false():
    """Movable supplier + non-boundary day → no prompt."""
    tx = {"source_type": "extrato"}
    assert needs_boundary_prompt(tx, True, date(2026, 4, 15)) is False


def test_needs_prompt_movable_false_boundary_true():
    """Non-movable supplier + boundary day → no prompt."""
    tx = {"source_type": "extrato"}
    assert needs_boundary_prompt(tx, False, date(2026, 4, 30)) is False


def test_needs_prompt_movable_false_boundary_false():
    """Non-movable + non-boundary → no prompt."""
    tx = {"source_type": "extrato"}
    assert needs_boundary_prompt(tx, False, date(2026, 4, 15)) is False


def test_needs_prompt_fatura_excluded_even_if_boundary_movable():
    """A CC fatura row in the boundary window with movable=true must NOT
    fire a prompt — invariant 9 third clause (CC accrual is governed by
    accrual.compute_data_competencia, not the boundary prompt)."""
    tx = {"source_type": "fatura"}
    assert needs_boundary_prompt(tx, True, date(2026, 4, 30)) is False


# ---------------------------------------------------------------------------
# is_valid_token — invariant 7 (lowercase kebab-case ASCII without `;`)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "token, expected",
    [
        # Accept
        ("tennis", True),
        ("trip-2026", True),
        ("a", True),
        ("ab1", True),
        # Reject — uppercase
        ("Tennis", False),
        ("TENNIS", False),
        # Reject — semicolon (would break the column separator)
        ("tennis;trip", False),
        # Reject — leading whitespace
        (" tennis", False),
        # Reject — underscore (kebab-case is hyphen, not underscore)
        ("tennis_trip", False),
        # Reject — empty
        ("", False),
        # Reject — accents
        ("reembolsável", False),
        # Reject — leading hyphen
        ("-tennis", False),
    ],
)
def test_is_valid_token(token: str, expected: bool):
    assert is_valid_token(token) is expected


# ---------------------------------------------------------------------------
# Invariant 8 — Pass 2 fires ONLY after Pass 1 is complete
# ---------------------------------------------------------------------------
# `build_pass_2_queue` raises `QueueOrderingError` when called with
# transactions lacking resolved category/supplier/caixa. Tested here
# because it is the orchestration layer that gates the boundary prompt.

from pathlib import Path

from lib.queue import QueueOrderingError, build_pass_2_queue
from lib.suppliers import load_suppliers


_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture_suppliers():
    return load_suppliers(_FIXTURES / "suppliers.json")


def _load_fixture_categories():
    import json
    with open(_FIXTURES / "categories.json", "r", encoding="utf-8") as f:
        return json.load(f)


def test_pass_2_raises_when_category_unresolved():
    """A transaction with category='a_identificar' blocks Pass 2."""
    txs = [{
        "category": "a_identificar",
        "supplier_canonical": "Claro",
        "data_caixa": "2026-04-30",
        "source_type": "extrato",
    }]
    with pytest.raises(QueueOrderingError):
        build_pass_2_queue(txs, _load_fixture_suppliers(),
                           _load_fixture_categories())


def test_pass_2_raises_when_data_caixa_missing():
    """Pass 2 requires data_caixa already computed by accrual."""
    txs = [{
        "category": "moradia",
        "supplier_canonical": "Claro",
        "source_type": "extrato",
        # data_caixa intentionally missing
    }]
    with pytest.raises(QueueOrderingError):
        build_pass_2_queue(txs, _load_fixture_suppliers(),
                           _load_fixture_categories())


def test_pass_2_raises_when_movable_unresolved_for_mixed_hint():
    """Unknown supplier under a 'mixed' category (saude) must raise — Pass 1
    must explicitly classify movable before Pass 2 fires."""
    txs = [{
        "category": "saude",
        "supplier_canonical": "",
        "data_caixa": "2026-04-30",
        "source_type": "extrato",
    }]
    with pytest.raises(QueueOrderingError):
        build_pass_2_queue(txs, _load_fixture_suppliers(),
                           _load_fixture_categories())


def test_pass_2_emits_boundary_item_for_movable_in_window():
    """Smoke check the happy path: explicit movable supplier in the trailing
    window emits exactly one boundary QueueItem."""
    txs = [{
        "category": "moradia",
        "supplier_canonical": "Claro",
        "data_caixa": "2026-04-30",
        "data_competencia": "2026-04-30",
        "source_type": "extrato",
        "description": "CLARO",
        "amount": "-120.00",
    }]
    items = build_pass_2_queue(txs, _load_fixture_suppliers(),
                                _load_fixture_categories())
    assert len(items) == 1
    assert items[0].item_type == "boundary"
    assert items[0].prompt_default == "keep"

