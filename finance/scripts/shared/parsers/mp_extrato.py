"""Mercado Pago account statement CSV parser.

Format: semicolon-delimited, PT-BR decimals, DD-MM-YYYY dates.
Double header: rows 1-3 are summary, row 4+ are transactions.
Header: RELEASE_DATE;TRANSACTION_TYPE;REFERENCE_ID;TRANSACTION_NET_AMOUNT;PARTIAL_BALANCE
"""

import csv
from pathlib import Path
from utils import parse_date, parse_ptbr_decimal, parse_installment
from .base import BaseParser


class MPExtratoParser(BaseParser):
    bank_id = "mp_extrato"
    source_type = "extrato"

    def parse(self, filepath: Path, password: str | None = None) -> list[dict]:
        rows = []
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Find the transaction header line
        tx_start = None
        for i, line in enumerate(lines):
            if line.startswith("RELEASE_DATE"):
                tx_start = i
                break

        if tx_start is None:
            return rows

        # Parse from transaction header onwards
        reader = csv.DictReader(lines[tx_start:], delimiter=";")
        for record in reader:
            date_str = record.get("RELEASE_DATE", "").strip()
            if not date_str:
                continue

            description = record.get("TRANSACTION_TYPE", "").strip()
            ref_id = record.get("REFERENCE_ID", "").strip()
            amount = parse_ptbr_decimal(record.get("TRANSACTION_NET_AMOUNT", ""))
            balance = parse_ptbr_decimal(record.get("PARTIAL_BALANCE", ""))

            parsed_date = parse_date(date_str)
            inst_current, inst_total = parse_installment(description)

            rows.append(self._make_row(
                date_str=parsed_date.isoformat(),
                description=description,
                amount=amount,
                balance=balance,
                original_ref=ref_id,
                installment_current=inst_current,
                installment_total=inst_total,
            ))
        return rows
