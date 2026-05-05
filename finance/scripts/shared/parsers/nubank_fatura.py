"""Nubank credit card PDF parser.

File pattern: Nubank_*.pdf
No password required.
Layout:
  - Pages 1-4: Summary, payment options (ignore)
  - Last page(s): TRANSACOES section with transaction lines
  - Date format: DD MMM (Portuguese abbreviated months, no year)
  - Amounts: R$ X.XXX,XX
  - IOF lines are separate entries
  - "Pagamentos e Financiamentos" section = payments (mark as ignorar)
"""

import re
from pathlib import Path

import pdfplumber

from utils import parse_date, parse_ptbr_decimal, parse_installment, infer_year
from .base import BaseParser


class NubankFaturaParser(BaseParser):
    bank_id = "nubank_fatura"
    source_type = "fatura"

    # Transaction line: DD MMM [card] Description R$ amount
    _TX_RE = re.compile(
        r"(\d{1,2}\s+[A-Z]{3})\s+"  # date (DD MMM)
        r"(?:[\u2022\u00b7•·]+\s*\d{4}\s+)?"  # optional card number (•••• 7321)
        r"(.+?)\s+"                   # description
        r"R\$\s*([\d.,]+)"           # amount
    )

    # IOF line: DD MMM IOF de "Vendor" R$ amount
    _IOF_RE = re.compile(
        r"(\d{1,2}\s+[A-Z]{3})\s+"
        r'IOF\s+de\s+"(.+?)"\s+'
        r"R\$\s*([\d.,]+)"
    )

    # Payment line: DD MMM Pagamento em DD MMM -R$ amount
    _PAY_RE = re.compile(
        r"(\d{1,2}\s+[A-Z]{3})\s+"
        r"(Pagamento\s+em\s+.+?)\s+"
        r"[−-]?R\$\s*([\d.,]+)"
    )

    def parse(self, filepath: Path, password: str | None = None) -> list[dict]:
        rows = []
        reference_year = self._extract_year(filepath)

        with pdfplumber.open(filepath) as pdf:
            in_transactions = False
            in_payments = False

            for page in pdf.pages:
                text = page.extract_text() or ""

                for line in text.split("\n"):
                    line = line.strip()

                    # Detect transaction section
                    if re.search(r"TRANSA[CÇ][OÕ]ES", line, re.IGNORECASE):
                        in_transactions = True
                        in_payments = False
                        continue

                    # Detect payment section
                    if "Pagamentos e Financiamentos" in line:
                        in_payments = True
                        continue

                    if not in_transactions:
                        continue

                    # Skip conversion detail lines
                    if re.match(r"(?:BRL|USD|EUR|ARS|MXN)\s+[\d.]+", line):
                        continue
                    if line.startswith("Convers"):
                        continue

                    # Skip cardholder subtotal lines
                    if re.match(r"[A-Z][a-z].*R\$\s*[\d.,]+$", line):
                        continue

                    # Skip zero-value "saldo restante" lines
                    if "saldo restante" in line.lower():
                        continue

                    # Try payment pattern
                    pay_match = self._PAY_RE.match(line)
                    if pay_match and in_payments:
                        date_str = pay_match.group(1)
                        description = pay_match.group(2)
                        amount = parse_ptbr_decimal(pay_match.group(3))
                        parsed_date = infer_year(parse_date(date_str), reference_year)
                        rows.append(self._make_row(
                            date_str=parsed_date.isoformat(),
                            description=description,
                            amount=-amount,  # payments are negative
                        ))
                        continue

                    # Try IOF pattern
                    iof_match = self._IOF_RE.match(line)
                    if iof_match:
                        date_str = iof_match.group(1)
                        vendor = iof_match.group(2)
                        amount = parse_ptbr_decimal(iof_match.group(3))
                        parsed_date = infer_year(parse_date(date_str), reference_year)
                        rows.append(self._make_row(
                            date_str=parsed_date.isoformat(),
                            description=f"IOF {vendor}",
                            amount=-amount,
                        ))
                        continue

                    # Try regular transaction pattern
                    tx_match = self._TX_RE.match(line)
                    if tx_match:
                        date_str = tx_match.group(1)
                        description = tx_match.group(2).strip()
                        amount = parse_ptbr_decimal(tx_match.group(3))
                        parsed_date = infer_year(parse_date(date_str), reference_year)
                        inst_current, inst_total = parse_installment(description)
                        rows.append(self._make_row(
                            date_str=parsed_date.isoformat(),
                            description=description,
                            amount=-amount,  # credit card charges are outflows
                            installment_current=inst_current,
                            installment_total=inst_total,
                        ))
                        continue

        return rows

    def extract_total(self, filepath: Path, password: str | None = None) -> float | None:
        """Extract fatura total from Nubank PDF.

        Must use 'Pagamento total da fatura' (definitive field),
        NOT 'Total a pagar' which appears in the installment options section
        with a different (higher) value.
        """
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                # Definitive field: "Pagamento total da fatura R$ 257,54"
                match = re.search(
                    r"Pagamento\s+total\s+da\s+fatura\s+R\$\s*([\d.,]+)",
                    text, re.IGNORECASE,
                )
                if match:
                    return parse_ptbr_decimal(match.group(1))

        # Fallback: "Total a pagar" on summary page (later pages)
        with pdfplumber.open(filepath) as pdf:
            for page in reversed(pdf.pages):
                text = page.extract_text() or ""
                match = re.search(
                    r"Total\s+a\s+pagar\s+R\$\s*([\d.,]+)",
                    text, re.IGNORECASE,
                )
                if match:
                    return parse_ptbr_decimal(match.group(1))
        return None

    def _extract_year(self, filepath: Path) -> int:
        """Extract year from filename or PDF content."""
        # Try filename: Nubank_2026-04-09.pdf
        match = re.search(r"(\d{4})", filepath.stem)
        if match:
            return int(match.group(1))
        return 2026
