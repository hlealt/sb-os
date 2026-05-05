"""Bradesco current account CSV parser.

Format: semicolon-delimited, PT-BR decimals, DD/MM/YYYY dates.
Header: Data;Historico;Docto.;Credito (R$);Debito (R$);Saldo (R$)
"""

import csv
import re
from pathlib import Path
from utils import parse_date, parse_ptbr_decimal, parse_installment
from .base import BaseParser


class BradescoExtratoParser(BaseParser):
    bank_id = "bradesco_extrato"
    source_type = "extrato"

    def parse(self, filepath: Path, password: str | None = None) -> list[dict]:
        rows = []
        # Try multiple encodings (Bradesco exports vary)
        content = None
        for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
            try:
                content = filepath.read_text(encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        if content is None:
            return rows
        # Skip non-header lines before the actual CSV header
        import io
        lines = content.splitlines(keepends=True)
        header_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("Data;"):
                header_idx = i
                break
        f = io.StringIO("".join(lines[header_idx:]))
        with f:
            reader = csv.DictReader(f, delimiter=";")
            for record in reader:
                date_str = record.get("Data", "").strip()
                if not date_str or not re.match(r"\d{2}/\d{2}/\d{4}", date_str):
                    continue

                description = record.get("Histórico", record.get("Historico", "")).strip()
                doc = record.get("Docto.", "").strip()
                credit = parse_ptbr_decimal(record.get("Crédito (R$)", record.get("Credito (R$)", "")))
                debit = parse_ptbr_decimal(record.get("Débito (R$)", record.get("Debito (R$)", "")))
                balance = parse_ptbr_decimal(record.get("Saldo (R$)", ""))

                # Amount: credit is positive, debit is negative
                amount = credit if credit else -abs(debit) if debit else 0.0

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
