"""Mercado Pago credit card PDF parser (password-protected).

File pattern: Fatura_MP_*.pdf
Password: first 5 digits of CPF.
Layout: Text-based fatura with transaction lines.
"""

import re
from pathlib import Path

import pikepdf
import pdfplumber

from utils import parse_date, parse_ptbr_decimal, parse_installment
from .base import BaseParser


class MPFaturaParser(BaseParser):
    bank_id = "mp_fatura"
    source_type = "fatura"

    def parse(self, filepath: Path, password: str | None = None) -> list[dict]:
        rows = []
        decrypted_path = filepath.with_suffix(".decrypted.pdf")

        try:
            if password:
                with pikepdf.open(filepath, password=password) as pdf:
                    pdf.save(decrypted_path)
                target = decrypted_path
            else:
                target = filepath

            with pdfplumber.open(target) as pdf:
                for page in pdf.pages:
                    # Try table extraction
                    tables = page.extract_tables()
                    if tables:
                        for table in tables:
                            rows.extend(self._parse_table(table))

                    # Also try text
                    text = page.extract_text() or ""
                    rows.extend(self._parse_text(text))

        finally:
            if decrypted_path.exists():
                decrypted_path.unlink()

        return self._deduplicate(rows)

    def extract_total(self, filepath: Path, password: str | None = None) -> float | None:
        """Extract fatura total from Mercado Pago PDF."""
        decrypted_path = filepath.with_suffix(".decrypted.pdf")
        try:
            if password:
                with pikepdf.open(filepath, password=password) as pdf:
                    pdf.save(decrypted_path)
                target = decrypted_path
            else:
                target = filepath

            # MP: "Total R$ 9.727,55" repeats on pages 2+.
            # Collect all matches, most frequent = current fatura total.
            from collections import Counter
            all_totals = []
            with pdfplumber.open(target) as pdf:
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    for line in text.split("\n"):
                        line = line.strip()
                        # "Pagamento total da fatura R$ X" — definitive
                        m = re.search(r"Pagamento\s+total.*?R\$\s*([\d.,]+)", line, re.IGNORECASE)
                        if m:
                            return parse_ptbr_decimal(m.group(1))
                        # "Total R$ X" at start of line (not "Total da fatura de...")
                        if line.startswith("Total") and "da fatura de" not in line.lower():
                            m = re.search(r"R\$\s*([\d.,]+)", line)
                            if m:
                                val = parse_ptbr_decimal(m.group(1))
                                if val > 0:
                                    all_totals.append(val)

            if all_totals:
                return Counter(all_totals).most_common(1)[0][0]
        finally:
            if decrypted_path.exists():
                decrypted_path.unlink()
        return None

    def _parse_table(self, table: list[list]) -> list[dict]:
        rows = []
        for row in table:
            if not row or len(row) < 3:
                continue

            date_str = (row[0] or "").strip()
            if not re.match(r"\d{2}/\d{2}", date_str):
                continue

            description = (row[1] or "").strip()
            amount_str = (row[-1] or "").strip()

            if not description or "total" in description.lower():
                continue

            amount = -abs(parse_ptbr_decimal(amount_str))

            if len(date_str) == 5:
                date_str = date_str + "/2026"
            parsed_date = parse_date(date_str)

            inst_current, inst_total = parse_installment(description)

            rows.append(self._make_row(
                date_str=parsed_date.isoformat(),
                description=description,
                amount=amount,
                installment_current=inst_current,
                installment_total=inst_total,
            ))
        return rows

    def _parse_text(self, text: str) -> list[dict]:
        rows = []
        for line in text.split("\n"):
            line = line.strip()
            match = re.match(
                r"(\d{2}/\d{2}(?:/\d{4})?)\s+(.+?)\s+(?:R\$\s*)?([\d.,]+)\s*$",
                line,
            )
            if not match:
                continue

            date_str = match.group(1)
            description = match.group(2).strip()
            amount_str = match.group(3)

            skip_keywords = ["total", "pagamento", "limite", "vencimento"]
            if any(kw in description.lower() for kw in skip_keywords):
                continue

            if len(date_str) == 5:
                date_str = date_str + "/2026"
            parsed_date = parse_date(date_str)

            amount = -abs(parse_ptbr_decimal(amount_str))
            inst_current, inst_total = parse_installment(description)

            rows.append(self._make_row(
                date_str=parsed_date.isoformat(),
                description=description,
                amount=amount,
                installment_current=inst_current,
                installment_total=inst_total,
            ))
        return rows

    def _deduplicate(self, rows: list[dict]) -> list[dict]:
        seen = set()
        unique = []
        for row in rows:
            key = (row["date"], row["description"], row["amount"])
            if key not in seen:
                seen.add(key)
                unique.append(row)
        return unique
