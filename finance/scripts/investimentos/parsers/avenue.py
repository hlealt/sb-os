"""Avenue trade confirmation PDF parser.

Parses Avenue/Apex Clearing trade confirmation PDFs into orders.csv format.
Each PDF may contain multiple trades. Currency is always USD, market is 'us'.
"""

import re
from pathlib import Path

import pdfplumber

from .base import InvestmentBaseParser, ParseResult

# Trade line pattern from Apex Clearing PDF
# Format: Type B/S Trade_Date Settle_Date QTY SYM PRICE Principal COMM Tran_Fee Fees Number Net_Amount
_TRADE_RE = re.compile(
    r'^\d+\s+'                      # Account type
    r'([BS])\s+'                    # Buy/Sell
    r'(\d{2}/\d{2}/\d{2})\s+'      # Trade date MM/DD/YY
    r'\d{2}/\d{2}/\d{2}\s+'        # Settle date (ignore)
    r'([\d,.]+)\s+'                 # Quantity
    r'([A-Z.]+)\s+'                 # Symbol
    r'([\d,.]+)\s+'                 # Price
    r'([\d,.]+)\s+'                 # Principal
    r'([\d,.]+)\s+'                 # Commission
    r'([\d,.]+)\s+'                 # Tran fee
    r'([\d,.]+)\s+'                 # Fees
)


class AvenueParser(InvestmentBaseParser):
    source_id = "avenue"

    def parse(self, filepath: Path, name_map=None) -> ParseResult:
        result = ParseResult()
        result.outputs = {'orders': []}

        # Handle single file or directory of PDFs
        if filepath.is_dir():
            pdf_files = sorted(filepath.glob("*.pdf"))
        else:
            pdf_files = [filepath]

        for pdf_file in pdf_files:
            self._parse_pdf(pdf_file, result)

        return result

    def _parse_pdf(self, filepath: Path, result: ParseResult):
        """Parse a single trade confirmation PDF."""
        try:
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if not text:
                        continue
                    self._extract_trades(text, result)
        except Exception as e:
            result.flags.append(type('Flag', (), {
                'date': '', 'operation': 'PDF_ERROR',
                'product': str(filepath.name),
                'values': {'error': str(e)},
                'reason': f'Failed to parse PDF: {e}',
                'line_number': 0
            })())

    def _extract_trades(self, text: str, result: ParseResult):
        """Extract trade rows from PDF page text."""
        for line in text.split('\n'):
            m = _TRADE_RE.match(line.strip())
            if not m:
                continue

            side_raw = m.group(1)  # B or S
            trade_date = m.group(2)  # MM/DD/YY
            qty = self._parse_us_decimal(m.group(3))
            symbol = m.group(4)
            price = self._parse_us_decimal(m.group(5))
            principal = self._parse_us_decimal(m.group(6))
            commission = self._parse_us_decimal(m.group(7))
            tran_fee = self._parse_us_decimal(m.group(8))
            fees = self._parse_us_decimal(m.group(9))

            side = 'C' if side_raw == 'B' else 'V'
            date = self._parse_date(trade_date)
            total = round(principal + commission + tran_fee + fees, 2)

            result.outputs['orders'].append({
                'date': date,
                'side': side,
                'ticker': symbol,
                'quantity': str(round(qty, 8)),
                'price': str(round(price, 8)),
                'currency': 'USD',
                'total': str(total),
                'fees_exchange': str(round(tran_fee + fees, 2)),
                'fees_brokerage': str(round(commission, 2)),
                'fees_irrf': '0',
                'broker': 'avenue',
                'asset_type': 'acao',
                'market': 'us',
                'source': 'avenue',
            })

    def _parse_date(self, date_str: str) -> str:
        """MM/DD/YY → YYYY-MM-DD."""
        if not date_str:
            return ''
        parts = date_str.split('/')
        if len(parts) == 3:
            m, d, y = parts
            year = f'20{y}' if int(y) < 50 else f'19{y}'
            return f'{year}-{m.zfill(2)}-{d.zfill(2)}'
        return date_str

    def _parse_us_decimal(self, val: str) -> float:
        """Parse US decimal format: '1,104.18' → 1104.18."""
        if not val:
            return 0.0
        try:
            return float(val.replace(',', ''))
        except (ValueError, TypeError):
            return 0.0
