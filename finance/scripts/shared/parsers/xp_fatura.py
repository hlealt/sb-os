"""XP credit card invoice CSV parser.

Format: semicolon-delimited, PT-BR decimals with R$ prefix, DD/MM/YYYY dates.
Header: Data;Estabelecimento;Portador;Valor;Parcela
"""

import csv
from pathlib import Path
from utils import parse_date, parse_ptbr_decimal, parse_installment
from .base import BaseParser


class XPFaturaParser(BaseParser):
    bank_id = "xp_fatura"
    source_type = "fatura"

    def parse(self, filepath: Path, password: str | None = None) -> list[dict]:
        rows = []
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            for record in reader:
                date_str = record.get("Data", "").strip()
                if not date_str:
                    continue

                description = record.get("Estabelecimento", "").strip()
                valor_str = record.get("Valor", "").strip()
                parcela_str = record.get("Parcela", "").strip()

                parsed_date = parse_date(date_str)
                raw_amount = parse_ptbr_decimal(valor_str)
                # Negate: positive in CSV = purchase = negative in normalized;
                # negative in CSV = payment/credit = positive in normalized
                amount = -raw_amount

                # Parse installment from Parcela column or description
                inst_current, inst_total = None, None
                if parcela_str and parcela_str != "-":
                    inst_current, inst_total = parse_installment(parcela_str)
                if inst_current is None:
                    inst_current, inst_total = parse_installment(description)

                rows.append(self._make_row(
                    date_str=parsed_date.isoformat(),
                    description=description,
                    amount=amount,
                    installment_current=inst_current,
                    installment_total=inst_total,
                ))
        return rows
