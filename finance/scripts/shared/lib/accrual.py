"""Caixa + Competência computation for the gastos pipeline.

Computes the two basis dates that drive the dashboard's caixa/competência
toggle, given a normalized transaction and (for CC rows) the invoice payment
date plus original purchase date.

The four canonical scenarios from the spec behavior matrix are handled here:

    1. CC single (source_type='fatura', no installment metadata):
       caixa = invoice_payment_date
       competência = original_purchase_date  (= the transaction's `date`)

    2. CC installment (source_type='fatura', installment_total >= 2):
       caixa = invoice_payment_date  (per-INVOICE — every parcela in the
              same invoice shares one caixa date)
       competência = original_purchase_date  (the SAME value for every
                    parcela of the same purchase — collapse to original
                    purchase month)

    3. Non-CC (source_type='extrato' or 'Cash'):
       caixa = transaction['date']
       competência = caixa  (skip-default per spec Q13a)

    4. Reimbursement:
       caixa = transaction['date']  (received date — IMMUTABLE per spec Q12)
       competência = data_caixa unless the caller provides a manual_override
                    that links the reimbursement to its original-expense month

Hard invariants (data-model.md §6):

  - `data_caixa` is IMMUTABLE. `compute_data_competencia` returns a fresh
    `date` value and NEVER mutates `data_caixa` or `transaction['data_caixa']`.
  - For CC fatura rows, `invoice_payment_date` is REQUIRED — raises ValueError
    if absent.
  - For CC fatura rows, `original_purchase_date` is REQUIRED — raises
    ValueError if absent.
  - Reimbursement caixa NEVER moves (Q12). The only override applies to
    competência via `manual_override`.

Pure module: no file I/O, no global state, no input mutation.
"""

from __future__ import annotations

from datetime import date
from typing import Any

Transaction = dict[str, Any]


def _is_cc_fatura(transaction: Transaction) -> bool:
    return str(transaction.get("source_type", "")).lower() == "fatura"


def _installment_total(transaction: Transaction) -> int:
    raw = transaction.get("installment_total", "")
    if raw in (None, ""):
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def compute_data_caixa(
    transaction: Transaction,
    invoice_payment_date: date | None = None,
) -> date:
    """Compute the immutable cash-flow date for a transaction.

    Rules:
      - source_type == 'fatura' (CC purchase, single or installment parcela):
        REQUIRES invoice_payment_date — returns it as-is. (Per-INVOICE: every
        parcela appearing in a single invoice shares one caixa date.)
      - source_type == 'extrato' or 'Cash':
        returns transaction['date'].
      - Reimbursements: caller passes the received-date as transaction['date']
        for non-CC reimbursements; this function applies no special-case logic.

    Raises:
      ValueError if a CC fatura row is passed without invoice_payment_date.
      ValueError if transaction['date'] is missing/unparsable for non-fatura.

    Pure. No file I/O. Does not mutate `transaction`.
    """
    if _is_cc_fatura(transaction):
        if invoice_payment_date is None:
            raise ValueError(
                "CC fatura row requires invoice_payment_date "
                "(per-invoice caixa pinning per spec R2)."
            )
        return invoice_payment_date

    raw_date = transaction.get("date")
    if raw_date is None or raw_date == "":
        raise ValueError("transaction is missing 'date' for non-fatura row")
    if isinstance(raw_date, date):
        return raw_date
    # Accept ISO string (YYYY-MM-DD) — categorize.py reads CSVs as strings.
    return date.fromisoformat(str(raw_date))


def compute_data_competencia(
    transaction: Transaction,
    data_caixa: date,
    *,
    original_purchase_date: date | None = None,
    manual_override: date | None = None,
) -> date:
    """Compute the analytical attribution date for a transaction.

    Resolution order (first matching rule wins):

      1. manual_override is not None
         → return manual_override (caller-driven Pass 2 boundary or
            cross-month reimbursement linkage).

      2. source_type == 'fatura'
         → REQUIRES original_purchase_date. Returns it. For installments
           (installment_total >= 2), the caller MUST pass the SAME
           original_purchase_date for every parcela of the same purchase
           so they collapse to one competência month.

      3. otherwise (extrato / Cash / reimbursement without override)
         → return data_caixa  (skip-default per Q13a; no silent push).

    Hard invariants (data-model.md §6):
      - NEVER mutates `data_caixa` — the returned date is independent.
      - NEVER mutates `transaction`.

    Pure. No file I/O.
    """
    if manual_override is not None:
        return manual_override

    if _is_cc_fatura(transaction):
        if original_purchase_date is None:
            raise ValueError(
                "CC fatura row requires original_purchase_date "
                "(competência collapses to original purchase month)."
            )
        return original_purchase_date

    return data_caixa
