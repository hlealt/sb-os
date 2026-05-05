"""Wise multi-currency CSV parser.

Format: comma-delimited, international decimals, DD-MM-YYYY dates.
24 columns. One file per currency account. Skip header-only files.

Non-BRL files: two-pass parsing.
  Pass 1 — collect exchange rates from TRANSFER (funding) rows.
  Pass 2 — convert amounts to BRL using the most recent rate,
            storing original foreign-currency amount and rate used.
BRL files: single pass, no conversion needed.
"""

import csv
from pathlib import Path
from utils import parse_date, parse_intl_decimal, parse_installment
from .base import BaseParser


class WiseExtratoParser(BaseParser):
    bank_id = "wise_extrato"
    source_type = "extrato"

    def parse(self, filepath: Path, password: str | None = None) -> list[dict]:
        records = self._read_records(filepath)
        if not records:
            return []

        currency = self._detect_currency(records)
        if currency == "BRL":
            return self._parse_brl(records)
        return self._parse_foreign(records, currency)

    # -- internal helpers -----------------------------------------------------

    def _read_records(self, filepath: Path) -> list[dict]:
        with open(filepath, "r", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def _detect_currency(self, records: list[dict]) -> str:
        for r in records:
            c = r.get("Currency", "").strip()
            if c:
                return c
        return "BRL"

    def _parse_brl(self, records: list[dict]) -> list[dict]:
        rows = []
        for record in records:
            row = self._record_to_row(record)
            if row:
                rows.append(row)
        return rows

    def _parse_foreign(self, records: list[dict], currency: str) -> list[dict]:
        # Pass 1: collect exchange rates from funding (TRANSFER) rows
        # Rate in Wise CSV is "Exchange From" -> "Exchange To", e.g. BRL->USD = 0.18813
        # To convert USD->BRL we need 1/rate
        rates: list[tuple[str, float]] = []  # (date_iso, brl_per_unit)
        for record in records:
            rate_str = record.get("Exchange Rate", "").strip()
            if not rate_str:
                continue
            rate = parse_intl_decimal(rate_str)
            if rate <= 0:
                continue
            exchange_from = record.get("Exchange From", "").strip()
            exchange_to = record.get("Exchange To", "").strip()
            date_str = record.get("Date", "").strip()
            if not date_str:
                continue
            date_iso = parse_date(date_str).isoformat()

            # Determine BRL per 1 unit of foreign currency
            if exchange_from == "BRL" and exchange_to == currency:
                # rate = BRL->foreign, so 1 foreign = 1/rate BRL
                brl_per_unit = 1.0 / rate
            elif exchange_from == currency and exchange_to == "BRL":
                # rate = foreign->BRL directly
                brl_per_unit = rate
            else:
                continue
            rates.append((date_iso, brl_per_unit))

        # Sort rates by date for chronological lookup
        rates.sort(key=lambda x: x[0])

        # Fallback: if no rates found, cannot convert — keep original amounts
        if not rates:
            return self._parse_brl(records)

        # Pass 2: convert each transaction
        rows = []
        for record in records:
            date_str = record.get("Date", "").strip()
            if not date_str:
                continue

            parsed_date = parse_date(date_str)
            date_iso = parsed_date.isoformat()
            amount = parse_intl_decimal(record.get("Amount", ""))
            balance = parse_intl_decimal(record.get("Running Balance", ""))
            description = record.get("Description", "").strip()
            ref_id = record.get("TransferWise ID", "").strip()
            inst_current, inst_total = parse_installment(description)

            # Find the best rate: most recent rate on or before this transaction date
            brl_rate = rates[0][1]  # default to earliest
            for r_date, r_rate in rates:
                if r_date <= date_iso:
                    brl_rate = r_rate
                else:
                    break

            amount_brl = round(amount * brl_rate, 2)
            balance_brl = round(balance * brl_rate, 2) if balance else balance

            rows.append(self._make_row(
                date_str=date_iso,
                description=description,
                amount=amount_brl,
                balance=balance_brl,
                currency=currency,
                original_ref=ref_id,
                installment_current=inst_current,
                installment_total=inst_total,
                original_amount=amount,
                exchange_rate=round(brl_rate, 6),
            ))
        return rows

    def _record_to_row(self, record: dict) -> dict | None:
        date_str = record.get("Date", "").strip()
        if not date_str:
            return None
        amount = parse_intl_decimal(record.get("Amount", ""))
        currency = record.get("Currency", "BRL").strip()
        description = record.get("Description", "").strip()
        balance = parse_intl_decimal(record.get("Running Balance", ""))
        ref_id = record.get("TransferWise ID", "").strip()
        parsed_date = parse_date(date_str)
        inst_current, inst_total = parse_installment(description)

        return self._make_row(
            date_str=parsed_date.isoformat(),
            description=description,
            amount=amount,
            balance=balance,
            currency=currency,
            original_ref=ref_id,
            installment_current=inst_current,
            installment_total=inst_total,
        )
