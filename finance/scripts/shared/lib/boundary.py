"""Boundary-day detection + Pass 2 prompt scope (spec T5).

A "boundary day" is `data_caixa.day ∈ [1..5] ∪ [last_day_of_month-4 ..
last_day_of_month]`. Pass 2 of the review queue prompts the user to move
`data_competencia` ONLY when ALL of:

  1. data_caixa is a boundary day, AND
  2. the supplier's effective `movable` flag is True, AND
  3. source_type != 'fatura'  (CC rows already have data_caixa pinned to
     invoice payment date — boundary becomes coincidental, not analytical;
     CC accrual collapse is governed by accrual.compute_data_competencia,
     not boundary prompts).

Pure module: no file I/O, no global state.
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any

Transaction = dict[str, Any]


def is_boundary_day(d: date) -> bool:
    """True iff d.day ∈ [1..5] ∪ [last_day_of_month-4 .. last_day_of_month].

    `calendar.monthrange(year, month)[1]` returns the correct last day for
    28/29/30/31-day months (including Feb 29 in leap years).

    Pure.
    """
    if d.day <= 5:
        return True
    last_day = calendar.monthrange(d.year, d.month)[1]
    return d.day >= last_day - 4


def needs_boundary_prompt(
    transaction: Transaction,
    supplier_movable: bool,
    data_caixa: date,
) -> bool:
    """True iff the transaction should surface a Pass 2 boundary prompt.

    Conditions (ALL must hold):
      - is_boundary_day(data_caixa) is True
      - supplier_movable is True
      - source_type != 'fatura'

    Pure.
    """
    if not supplier_movable:
        return False
    source_type = str(transaction.get("source_type", "")).lower()
    if source_type == "fatura":
        return False
    return is_boundary_day(data_caixa)
