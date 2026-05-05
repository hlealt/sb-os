"""Unit tests for `lib.accrual` — the four behavior-matrix scenarios plus
hard invariants 1–5 from `data-model.md` §6.
"""
from __future__ import annotations

from datetime import date

import pytest

from lib.accrual import compute_data_caixa, compute_data_competencia


# ---------------------------------------------------------------------------
# Behavior matrix — verbatim from spec §R3 / data-model §7
# ---------------------------------------------------------------------------

def test_scenario_a_cc_single_purchase():
    """Apr 12 single CC purchase paid May 10 invoice.

    Expected: data_caixa = May 10, data_competencia = Apr 12.
    """
    tx = {"source_type": "fatura", "date": "2026-04-12"}
    purchase = date(2026, 4, 12)
    invoice = date(2026, 5, 10)

    caixa = compute_data_caixa(tx, invoice_payment_date=invoice)
    comp = compute_data_competencia(tx, caixa, original_purchase_date=purchase)

    assert caixa == date(2026, 5, 10)
    assert comp == date(2026, 4, 12)


def test_scenario_b_cc_installments_collapse():
    """Mar 10 3× installments paid Apr 10 / May 10 / Jun 10.

    Expected per parcela:
      caixa = its own invoice payment date (Apr 10 / May 10 / Jun 10)
      competência = Mar 10 (collapse to original purchase month) — IDENTICAL
                    across all 3 parcelas (data-model §6 invariant 2).
    """
    purchase = date(2026, 3, 10)
    parcela_1 = {
        "source_type": "fatura", "date": "2026-03-10",
        "installment_current": 1, "installment_total": 3,
    }
    parcela_2 = {
        "source_type": "fatura", "date": "2026-03-10",
        "installment_current": 2, "installment_total": 3,
    }
    parcela_3 = {
        "source_type": "fatura", "date": "2026-03-10",
        "installment_current": 3, "installment_total": 3,
    }
    pay1, pay2, pay3 = date(2026, 4, 10), date(2026, 5, 10), date(2026, 6, 10)

    caixa1 = compute_data_caixa(parcela_1, invoice_payment_date=pay1)
    caixa2 = compute_data_caixa(parcela_2, invoice_payment_date=pay2)
    caixa3 = compute_data_caixa(parcela_3, invoice_payment_date=pay3)

    assert (caixa1, caixa2, caixa3) == (pay1, pay2, pay3)

    comp1 = compute_data_competencia(parcela_1, caixa1, original_purchase_date=purchase)
    comp2 = compute_data_competencia(parcela_2, caixa2, original_purchase_date=purchase)
    comp3 = compute_data_competencia(parcela_3, caixa3, original_purchase_date=purchase)

    # Invariant 2: all 3 parcelas collapse to ORIGINAL purchase date.
    assert comp1 == comp2 == comp3 == purchase


def test_scenario_c_non_cc_utility():
    """Apr 5 utility bill, debit account (non-CC).

    Expected: data_caixa = data_competencia = Apr 5 (skip-default per Q13a).
    Per data-model §6 invariant 5, no auto-rule and no manual_override
    means competência == caixa for non-CC rows.
    """
    tx = {"source_type": "extrato", "date": "2026-04-05"}

    caixa = compute_data_caixa(tx)
    comp = compute_data_competencia(tx, caixa)

    assert caixa == date(2026, 4, 5)
    assert comp == date(2026, 4, 5)


def test_scenario_d_reimbursement_manual_override():
    """Apr 30 reimbursement received for a March expense; manual override
    links it to the original-expense month.

    Expected (data-model §6 invariant 4):
      data_caixa = Apr 30 (received date, NEVER moves)
      data_competencia = March (manual_override applied)
    """
    tx = {"source_type": "extrato", "date": "2026-04-30"}
    received = date(2026, 4, 30)
    original_month = date(2026, 3, 15)

    caixa = compute_data_caixa(tx)
    assert caixa == received

    comp = compute_data_competencia(tx, caixa, manual_override=original_month)
    assert comp == original_month
    # data_caixa unchanged (invariant 4): re-compute and verify.
    caixa_again = compute_data_caixa(tx)
    assert caixa_again == received


# ---------------------------------------------------------------------------
# Hard invariants
# ---------------------------------------------------------------------------

def test_invariant_1_data_caixa_immutable_in_input_dict():
    """Invariant 1: compute_data_competencia MUST NOT mutate transaction['data_caixa'].

    We seed the input dict with a sentinel data_caixa and confirm it survives
    the call.
    """
    sentinel = date(2026, 1, 1)
    tx = {"source_type": "extrato", "date": "2026-04-05", "data_caixa": sentinel}
    caixa = compute_data_caixa(tx)
    _ = compute_data_competencia(tx, caixa)
    # No code path may write to transaction['data_caixa'].
    assert tx["data_caixa"] == sentinel


def test_invariant_3_cc_data_caixa_per_invoice_not_per_purchase():
    """Invariant 3: every parcela of a single invoice shares one data_caixa.

    Two parcelas from DIFFERENT purchases that happen to land in the SAME
    invoice both receive that invoice's payment_date as their data_caixa.
    """
    invoice_pd = date(2026, 5, 10)
    p1 = {"source_type": "fatura", "date": "2026-03-10",
          "installment_current": 2, "installment_total": 3}
    p2 = {"source_type": "fatura", "date": "2026-04-12",
          "installment_current": 1, "installment_total": 1}
    assert compute_data_caixa(p1, invoice_payment_date=invoice_pd) == invoice_pd
    assert compute_data_caixa(p2, invoice_payment_date=invoice_pd) == invoice_pd


def test_invariant_4_reimbursement_caixa_never_moves_with_override():
    """Invariant 4: even with manual_override on competência, caixa stays put."""
    tx = {"source_type": "extrato", "date": "2026-04-30"}
    caixa = compute_data_caixa(tx)
    assert caixa == date(2026, 4, 30)
    # Apply the override; caixa must remain unchanged on a re-compute.
    comp = compute_data_competencia(tx, caixa, manual_override=date(2026, 3, 1))
    assert comp == date(2026, 3, 1)
    assert compute_data_caixa(tx) == date(2026, 4, 30)


def test_invariant_5_skip_default_non_cc_no_override():
    """Invariant 5: non-CC, no override → competência == caixa exactly."""
    tx = {"source_type": "Cash", "date": "2026-04-15"}
    caixa = compute_data_caixa(tx)
    comp = compute_data_competencia(tx, caixa)
    assert comp == caixa == date(2026, 4, 15)


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

def test_cc_fatura_requires_invoice_payment_date():
    tx = {"source_type": "fatura", "date": "2026-04-12"}
    with pytest.raises(ValueError):
        compute_data_caixa(tx, invoice_payment_date=None)


def test_cc_fatura_competencia_requires_original_purchase_date():
    tx = {"source_type": "fatura", "date": "2026-04-12"}
    caixa = date(2026, 5, 10)
    with pytest.raises(ValueError):
        compute_data_competencia(tx, caixa, original_purchase_date=None)
