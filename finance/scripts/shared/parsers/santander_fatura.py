"""Santander Visa credit card PDF parser (password-protected).

File pattern: Fatura_*_HENRIQUE_*_VISA_*.PDF
Password: full CPF (no punctuation).

Layout handling:
- Multi-card faturas (titular + adicionais) are laid out in TWO columns.
  Each page is cropped into left/right halves and parsed per-column so
  pdfplumber's full-page extraction does not interleave the cards' rows.
- Within a column, adjacent table rows can still merge into one line;
  _try_split splits them at embedded DD/MM date / IOF patterns.
- Parcelamento rows carry the ORIGINAL purchase date; they are re-dated to
  the invoice cycle (first day of the Vencimento month) so they land in the
  current close, with the original date preserved in original_ref.
- No value-based dedup: per-column parsing removed the double-extraction it
  guarded, so identical (date, description, amount) rows are kept as the
  distinct charges they are.
"""

import re
from datetime import date
from pathlib import Path

import pikepdf
import pdfplumber

from utils import parse_date, parse_ptbr_decimal, parse_installment
from .base import BaseParser

# Pattern: ...AMOUNT DD/MM VENDOR — the DD/MM in the middle is the second transaction's date
_SPLIT_RE = re.compile(
    r"^(.+?[\d,]+(?:\s+\d[\d.,]*)*)\s+(\d{2}/\d{2})\s+([A-Za-z*].*)$"
)

# Pattern: ...AMOUNT IOF ... — IOF as a separate charge appended to the line
_IOF_SPLIT_RE = re.compile(
    r"^(.+?)\s+([\d.,]+)\s+(IOF\s+.+)$"
)


_SKIP_KEYWORDS = [
    "total", "pagamento", "limite", "vencimento", "encargo",
    "pagamento minimo", "valor total", "deb autom", "anuidade",
    "reversao", "saldo anterior", "desconto do",
]

# Standalone IOF line (no date — inherits from previous transaction)
_IOF_STANDALONE_RE = re.compile(
    r"^IOF\s+DESPESA\s+NO\s+EXTERIOR\s+([\d.,]+)\s*$"
)

# COTAÇÃO exchange rate line (metadata, not a transaction)
_COTACAO_SUFFIX_RE = re.compile(r"\s+COTAÇÃO.*$", re.IGNORECASE)


class SantanderFaturaParser(BaseParser):
    bank_id = "santander_fatura"
    source_type = "fatura"
    _cycle_date: str | None = None

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
                page_texts = []      # full-page text — cycle-date detection
                column_texts = []    # per-column text — de-interleaved parsing
                for page in pdf.pages:
                    page_texts.append(page.extract_text() or "")
                    # Santander faturas lay multiple cards (titular + adicionais)
                    # in TWO columns; pdfplumber's full-page extract_text()
                    # interleaves them line-by-line and the row regex then drops
                    # the merged transactions. Crop each page into left/right
                    # halves and parse each column separately so each card's
                    # rows stay contiguous.
                    w, h = page.width, page.height
                    for bbox in ((0, 0, w / 2, h), (w / 2, 0, w, h)):
                        column_texts.append(page.crop(bbox).extract_text() or "")

            self._cycle_date = self._extract_cycle_date("\n".join(page_texts))
            for text in column_texts:
                rows.extend(self._parse_text(text))

        finally:
            if decrypted_path.exists():
                decrypted_path.unlink()

        # No value-based dedup: per-column parsing (above) removed the
        # full-page row-interleaving that caused double-extraction, so a
        # (date, description, amount) collision now means two GENUINELY
        # distinct charges (e.g. two identical subscriptions or IOF lines on
        # the same day). Dropping them would lose real transactions; a
        # spurious double-emit, if it ever recurs, is caught loudly by the
        # fatura-total reconciliation rather than silently hidden here.
        return rows

    def _extract_cycle_date(self, text: str) -> str | None:
        """Statement cycle date = first day of the Vencimento month.

        Parcelamento rows carry the ORIGINAL purchase date in the "Compra"
        column (an installment 18/21 shows the first-purchase date, years
        back). The close needs them dated to the CURRENT invoice cycle so
        they survive normalize's month filter and let categorize's
        competencia rule derive the accrual month from (cycle - (N-1)
        months). Anchor that cycle to the first day of the Vencimento month.
        Returns None if Vencimento is not found (rows keep their parsed date).
        """
        m = re.search(
            r"Vencimento.*?(\d{2})/(\d{2})/(\d{4})", text,
            re.DOTALL | re.IGNORECASE,
        )
        if not m:
            return None
        _, month, year = m.group(1), m.group(2), m.group(3)
        return date(int(year), int(month), 1).isoformat()

    def _make_row(self, date_str: str, description: str, amount: float, **kwargs) -> dict:
        """Re-date parcelamento installments to the invoice cycle.

        For rows with installment_total > 1, replace the original "Compra"
        purchase date with the statement cycle date (preserving the original
        in original_ref) so the installment falls in the current close.
        Non-installment rows are unchanged.
        """
        inst_total = kwargs.get("installment_total")
        if self._cycle_date and isinstance(inst_total, int) and inst_total > 1:
            if not kwargs.get("original_ref"):
                kwargs["original_ref"] = f"compra:{date_str}"
            date_str = self._cycle_date
        return super()._make_row(date_str, description, amount, **kwargs)

    def extract_total(self, filepath: Path, password: str | None = None) -> float | None:
        """Extract fatura total from Santander Visa PDF."""
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
                    text = page.extract_text() or ""
                    # Try common patterns for Santander fatura total
                    for pattern in [
                        r"Total\s+da\s+fatura\s+R?\$?\s*([\d.,]+)",
                        r"Total\s+a\s+pagar\s+R?\$?\s*([\d.,]+)",
                        r"Valor\s+total\s+R?\$?\s*([\d.,]+)",
                        r"Total\s+R?\$?\s*([\d.,]+)",
                    ]:
                        match = re.search(pattern, text, re.IGNORECASE)
                        if match:
                            val = parse_ptbr_decimal(match.group(1))
                            if val > 0:
                                return val
        finally:
            if decrypted_path.exists():
                decrypted_path.unlink()
        return None

    def _preprocess_line(self, line: str) -> str:
        """Clean PDF extraction artifacts before regex matching.

        Handles three issues from pdfplumber's two-column text extraction:
        1. COTAÇÃO exchange rate info merged from adjacent column
        2. Leading parcela/reference numbers before DD/MM dates
        3. Non-transaction prefixes (card headers, section headers) merged
           with transaction data
        """
        # Strip leading parcela/reference number before DD/MM date
        line = re.sub(r"^\d{1,2}\s+(?=\d{2}/\d{2})", "", line)

        # If line doesn't start with DD/MM, try extracting from first DD/MM
        # (handles card headers, section headers merged with transactions)
        if not re.match(r"\d{2}/\d{2}", line):
            dd_mm = re.search(r"(?:\d{1,2}\s+)?(\d{2}/\d{2})", line)
            if dd_mm:
                line = line[dd_mm.start():]
                line = re.sub(r"^\d{1,2}\s+(?=\d{2}/\d{2})", "", line)

        return line

    def _parse_text(self, text: str) -> list[dict]:
        rows = []
        last_date = None

        for line in text.split("\n"):
            line = line.strip()

            # Strip COTAÇÃO suffix early (can be merged with IOF lines)
            line = _COTACAO_SUFFIX_RE.sub("", line).strip()

            # Capture standalone IOF lines (no date — inherit from previous)
            iof_standalone = _IOF_STANDALONE_RE.match(line)
            if iof_standalone and last_date:
                amount = -abs(parse_ptbr_decimal(iof_standalone.group(1)))
                if abs(amount) > 0.01:
                    rows.append(self._make_row(
                        date_str=last_date,
                        description="IOF DESPESA NO EXTERIOR",
                        amount=amount,
                    ))
                continue

            line = self._preprocess_line(line)

            # Match initial: DD/MM ... amount
            match = re.match(
                r"(\d{2}/\d{2}(?:/\d{4})?)\s+(.+?)\s+(?:R\$\s*)?([\d.,]+)\s*$",
                line,
            )
            if not match:
                continue

            date_a_str = match.group(1)
            full_desc = match.group(2).strip()
            amount_b_str = match.group(3)

            last_date = parse_date(self._fix_date(date_a_str)).isoformat()

            # Try to split merged lines BEFORE skip check — the right-side
            # transaction in a merged line may be valid even if the left side
            # is a payment/header that should be skipped.
            split_result = self._try_split(date_a_str, full_desc, amount_b_str)

            if split_result:
                # Filter skip keywords per-transaction, not on the merged line
                for row in split_result:
                    desc_lower = row["description"].lower()
                    if not any(kw in desc_lower for kw in _SKIP_KEYWORDS):
                        rows.append(row)
            else:
                # Skip headers, totals, payment lines
                if any(kw in full_desc.lower() for kw in _SKIP_KEYWORDS):
                    continue
                # No split — single transaction
                date_str = self._fix_date(date_a_str)
                parsed_date = parse_date(date_str)
                amount = -abs(parse_ptbr_decimal(amount_b_str))

                # Check if description has embedded amount
                desc_clean, embedded_amount = self._extract_embedded_amount(full_desc)
                if embedded_amount is not None and embedded_amount > abs(amount):
                    # International purchase: embedded = BRL (real charge),
                    # CSV amount = foreign currency. Use BRL.
                    inst_current, inst_total = parse_installment(desc_clean)
                    rows.append(self._make_row(
                        date_str=parsed_date.isoformat(),
                        description=desc_clean,
                        amount=-abs(embedded_amount),
                        installment_current=inst_current,
                        installment_total=inst_total,
                    ))
                elif embedded_amount is not None and abs(amount) < 10:
                    # Small CSV amount + embedded = charge + IOF/minor fee
                    rows.append(self._make_row(
                        date_str=parsed_date.isoformat(),
                        description=desc_clean,
                        amount=-abs(embedded_amount),
                    ))
                    if abs(amount) > 0.01:
                        rows.append(self._make_row(
                            date_str=parsed_date.isoformat(),
                            description=f"IOF/encargo {desc_clean}",
                            amount=amount,
                        ))
                else:
                    inst_current, inst_total = parse_installment(full_desc)
                    rows.append(self._make_row(
                        date_str=parsed_date.isoformat(),
                        description=full_desc,
                        amount=amount,
                        installment_current=inst_current,
                        installment_total=inst_total,
                    ))

        return rows

    def _try_split(self, date_a_str: str, full_desc: str, amount_b_str: str) -> list | None:
        """Try to split a merged line into two transactions.

        Pattern: VENDOR_A [PARCELA] AMOUNT_A [IOF] DD/MM VENDOR_B
        The DD/MM in the middle is Transaction B's date.
        """

        # Check for DD/MM split (two transactions merged)
        split_match = _SPLIT_RE.match(full_desc)
        if split_match:
            desc_a_raw = split_match.group(1).strip()
            date_b_dd_mm = split_match.group(2)
            desc_b = split_match.group(3).strip()

            # Extract Transaction A's amounts from embedded numbers
            desc_a_clean, amounts_a = self._extract_transaction_a(desc_a_raw)

            # Transaction B uses the original CSV amount
            amount_b = -abs(parse_ptbr_decimal(amount_b_str))

            date_a = parse_date(self._fix_date(date_a_str))
            date_b = parse_date(self._fix_date(date_b_dd_mm))

            result = []

            # Transaction A — use first number as BRL amount
            # (second number, if present, is USD for international purchases;
            #  real IOFs are captured from standalone "IOF DESPESA" lines)
            if amounts_a:
                main_amount = amounts_a[0]
                if abs(main_amount) > 0.01:
                    inst_a_cur, inst_a_tot = parse_installment(desc_a_clean)
                    result.append(self._make_row(
                        date_str=date_a.isoformat(),
                        description=desc_a_clean,
                        amount=-abs(main_amount),
                        installment_current=inst_a_cur,
                        installment_total=inst_a_tot,
                    ))

            # Transaction B — check for international purchase (embedded BRL)
            desc_b_clean, embedded_b = self._extract_embedded_amount(desc_b)
            if embedded_b is not None and embedded_b > abs(amount_b):
                inst_b_cur, inst_b_tot = parse_installment(desc_b_clean)
                result.append(self._make_row(
                    date_str=date_b.isoformat(),
                    description=desc_b_clean,
                    amount=-abs(embedded_b),
                    installment_current=inst_b_cur,
                    installment_total=inst_b_tot,
                ))
            else:
                inst_b_cur, inst_b_tot = parse_installment(desc_b)
                result.append(self._make_row(
                    date_str=date_b.isoformat(),
                    description=desc_b,
                    amount=amount_b,
                    installment_current=inst_b_cur,
                    installment_total=inst_b_tot,
                ))

            return result if result else None

        # Check for IOF suffix split (VENDOR AMOUNT IOF...)
        iof_match = _IOF_SPLIT_RE.match(full_desc)
        if iof_match:
            desc_a = iof_match.group(1).strip()
            amount_a_str = iof_match.group(2)
            iof_desc = iof_match.group(3).strip()

            amount_a = parse_ptbr_decimal(amount_a_str)
            amount_iof = -abs(parse_ptbr_decimal(amount_b_str))

            date_parsed = parse_date(self._fix_date(date_a_str))
            inst_cur, inst_tot = parse_installment(desc_a)

            return [
                self._make_row(
                    date_str=date_parsed.isoformat(),
                    description=desc_a,
                    amount=-abs(amount_a),
                    installment_current=inst_cur,
                    installment_total=inst_tot,
                ),
                self._make_row(
                    date_str=date_parsed.isoformat(),
                    description=iof_desc,
                    amount=amount_iof,
                ),
            ]

        return None

    def _extract_transaction_a(self, desc_a_raw: str) -> tuple[str, list[float]]:
        """Extract vendor name and amounts from Transaction A's raw description.

        Returns (clean_description, [amounts]) where amounts can be:
        - [main_amount] — single charge
        - [main_amount, iof_amount] — charge + IOF for international purchases

        For GUARANI transactions the structure is:
        VENDOR GUARANI_AMOUNT GUARANI BRL_AMOUNT [IOF_AMOUNT]
        The BRL amount (after GUARANI keyword) is the real charge.

        Examples:
        "HETZNER ONLINE GMBH 23,96 4,39" → ("HETZNER ONLINE GMBH", [23.96, 4.39])
        "LA TARANTELLA 40.000,00 GUARANI 33,56 5,96" → ("LA TARANTELLA", [33.56, 5.96])
        """
        numbers = re.findall(r"-?[\d.]+,\d{2}", desc_a_raw)
        if not numbers:
            return desc_a_raw, []

        # Clean description: remove everything from first number onwards
        first_num_pos = desc_a_raw.find(numbers[0])
        desc_clean = desc_a_raw[:first_num_pos].strip()
        desc_clean = re.sub(r"\s+\d\s*$", "", desc_clean)

        # For foreign currency transactions (GUARANI, etc.), use the BRL
        # amount that appears after the currency keyword
        guarani_match = re.search(r"GUARANI", desc_a_raw, re.IGNORECASE)
        if guarani_match:
            after_guarani = desc_a_raw[guarani_match.end():]
            brl_numbers = re.findall(r"-?[\d.]+,\d{2}", after_guarani)
            if brl_numbers:
                return desc_clean, [parse_ptbr_decimal(n) for n in brl_numbers]

        # Standard path
        amounts = [parse_ptbr_decimal(n) for n in numbers]
        return desc_clean, amounts

    def _extract_embedded_amount(self, desc: str) -> tuple[str, float | None]:
        """Extract amount embedded at the end of a description.

        E.g., "OBSIDIAN 27,75" → ("OBSIDIAN", 27.75)
        E.g., "CLAUDE AI SUBSCRIPTION 1.168,74" → ("CLAUDE AI SUBSCRIPTION", 1168.74)
        """
        match = re.match(r"^(.+?)\s+([\d.]+,\d{2})$", desc)
        if match:
            return match.group(1).strip(), parse_ptbr_decimal(match.group(2))
        return desc, None

    def _fix_date(self, date_str: str) -> str:
        """Add year if missing."""
        if len(date_str) == 5:  # DD/MM
            return date_str + "/2026"
        return date_str
