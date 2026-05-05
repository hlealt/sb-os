"""Santander current account PDF parser (extrato_conta.pdf).

Layout: Table with columns Data | Descricao | Docto | Situacao | Credito | Debito | Saldo.
Date format: DD/MM/YYYY. PT-BR decimals. Negative debits with minus sign.
Pages: page 1 = transactions, page 2+ = summary/contact (ignore).
"""

import re
from pathlib import Path

import pdfplumber

from utils import parse_date, parse_ptbr_decimal, parse_installment
from .base import BaseParser


class SantanderExtratoParser(BaseParser):
    bank_id = "santander_extrato"
    source_type = "extrato"

    # Regex for transaction lines extracted from PDF text
    _TX_RE = re.compile(
        r"(\d{2}/\d{2}/\d{4})\s+"  # date
        r"(.+?)\s+"                  # description
        r"(\d+)\s+"                  # doc number
        r"(?:([\d.,]+)\s+)?"         # credit (optional)
        r"(?:-([\d.,]+)\s+)?"        # debit with minus (optional)
        r"(-?[\d.,]+)"              # balance
    )

    def parse(self, filepath: Path, password: str | None = None) -> list[dict]:
        rows = []

        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                # Try table extraction first
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        rows.extend(self._parse_table(table))
                    continue

                # Fallback: text extraction with regex
                text = page.extract_text() or ""
                rows.extend(self._parse_text(text))

        return rows

    def _parse_table(self, table: list[list]) -> list[dict]:
        """Parse a pdfplumber-extracted table."""
        rows = []
        for row in table:
            if not row or len(row) < 6:
                continue

            date_str = (row[0] or "").strip()
            if not re.match(r"\d{2}/\d{2}/\d{4}", date_str):
                continue

            description = (row[1] or "").strip()
            doc = (row[2] or "").strip()
            credit_str = (row[4] or "").strip() if len(row) > 4 else ""
            debit_str = (row[5] or "").strip() if len(row) > 5 else ""
            balance_str = (row[6] or "").strip() if len(row) > 6 else ""

            # Skip "Saldo anterior" or summary rows
            if "saldo" in description.lower():
                continue

            credit = parse_ptbr_decimal(credit_str)
            debit = parse_ptbr_decimal(debit_str)
            balance = parse_ptbr_decimal(balance_str)

            # Amount: credits positive, debits negative (already negative in source)
            amount = credit if credit > 0 else debit

            parsed_date = parse_date(date_str)
            inst_current, inst_total = parse_installment(description)

            rows.append(self._make_row(
                date_str=parsed_date.isoformat(),
                description=description,
                amount=amount,
                balance=balance,
                original_ref=doc,
                installment_current=inst_current,
                installment_total=inst_total,
            ))
        return rows

    def _parse_text(self, text: str) -> list[dict]:
        """Fallback: parse transactions from raw text."""
        rows = []
        for line in text.split("\n"):
            line = line.strip()
            match = re.match(
                r"(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(\d{3,})\s+(.*)",
                line,
            )
            if not match:
                continue

            date_str = match.group(1)
            description = match.group(2).strip()
            doc = match.group(3)
            amounts_part = match.group(4).strip()

            if "saldo" in description.lower():
                continue

            # Parse amounts from remaining text
            numbers = re.findall(r"-?[\d.,]+", amounts_part)
            amount = 0.0
            balance = 0.0

            if len(numbers) >= 2:
                # Last number is balance, second-to-last is amount
                balance = parse_ptbr_decimal(numbers[-1])
                amount = parse_ptbr_decimal(numbers[-2])
            elif len(numbers) == 1:
                amount = parse_ptbr_decimal(numbers[0])

            parsed_date = parse_date(date_str)
            inst_current, inst_total = parse_installment(description)

            rows.append(self._make_row(
                date_str=parsed_date.isoformat(),
                description=description,
                amount=amount,
                balance=balance,
                original_ref=doc,
                installment_current=inst_current,
                installment_total=inst_total,
            ))
        return rows
