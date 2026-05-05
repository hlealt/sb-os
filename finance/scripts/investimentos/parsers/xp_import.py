"""XP fund account statement CSV parser (one-time import).

Parses XP extrato CSV into balcao.csv format.
Special format: skip rows 1-13, headers at row 14.
Dates are M/D/YYYY (American format).
Amounts: "R$ 30.372,82" or "-R$ 805,92".
"""

import csv
import re
from pathlib import Path

from .base import InvestmentBaseParser, ParseResult
from .name_map import NameMapResolver

# Amount pattern: "R$ 30.372,82" or "-R$ 805,92"
_AMOUNT_RE = re.compile(r'^["\s]*(-?)\s*R\$\s*([\d.,]+)["\s]*$')

# Known XP fund operation patterns
_APLICACAO_PATTERNS = {'Aplicação', 'APLICACAO', 'Aporte'}
_RESGATE_PATTERNS = {'Resgate', 'RESGATE'}
_RENDIMENTO_PATTERNS = {'Rendimento', 'RENDIMENTO'}
_INVESTBACK_PATTERNS = {'Investback'}


class XPImportParser(InvestmentBaseParser):
    source_id = "xp_import"

    def parse(self, filepath: Path, name_map: NameMapResolver = None) -> ParseResult:
        result = ParseResult()
        result.outputs = {'balcao': []}

        rows = self._read_csv(filepath)

        for row in rows:
            date = self._parse_date(row.get('Data', ''))
            if not date:
                continue

            desc = row.get('Descrição', row.get('Descricao', '')).strip()
            amount = self._parse_amount(row.get('Valor', row.get('Valor (R$)', '0')))

            if not desc or amount == 0:
                continue

            # Determine operation from description
            operation = self._classify_operation(desc)
            if operation is None:
                continue

            # Extract fund name from description for product_id
            fund_name = self._extract_fund_name(desc)
            canonical = None
            if name_map and fund_name:
                canonical = name_map.resolve_value('xp', 'fundo', fund_name)
            if canonical is None and fund_name:
                canonical = re.sub(r'[^a-z0-9]+', '_', fund_name.lower()).strip('_')
            if not canonical:
                canonical = 'xp_unknown'

            result.outputs['balcao'].append({
                'date': date,
                'operation': operation,
                'product_id': canonical,
                'product_type': self._infer_type(desc),
                'quantity': '0',
                'amount': str(round(amount, 2)),
                'irrf': '0',
                'iof': '0',
                'broker': 'xp',
                'source': 'xp_import',
            })

        return result

    def _read_csv(self, filepath: Path) -> list[dict]:
        """Read XP CSV, skipping the first 13 rows."""
        rows = []
        with open(filepath, 'r', encoding='utf-8') as f:
            # Skip first 13 lines
            for _ in range(13):
                next(f, None)
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        return rows

    def _parse_date(self, date_str: str) -> str:
        """M/D/YYYY (American format) → YYYY-MM-DD."""
        if not date_str:
            return ''
        s = date_str.strip()
        parts = s.split('/')
        if len(parts) == 3:
            m, d, y = parts
            return f'{y}-{m.zfill(2)}-{d.zfill(2)}'
        return s

    def _parse_amount(self, val: str) -> float:
        """Parse 'R$ 30.372,82' or '-R$ 805,92' format."""
        if not val or val.strip() in ('-', ''):
            return 0.0
        s = val.strip().strip('"')
        # Detect negative
        neg = '-' in s.split('R$')[0] if 'R$' in s else s.startswith('-')
        # Remove R$ and whitespace
        s = re.sub(r'[-\s]*R\$\s*', '', s)
        # PT-BR decimal
        s = s.replace('.', '').replace(',', '.')
        try:
            result = float(s)
            return -result if neg else result
        except (ValueError, TypeError):
            return 0.0

    def _classify_operation(self, desc: str) -> str | None:
        """Classify operation from description text."""
        desc_upper = desc.upper()
        if any(p.upper() in desc_upper for p in _APLICACAO_PATTERNS):
            return 'aplicacao'
        if any(p.upper() in desc_upper for p in _RESGATE_PATTERNS):
            return 'resgate'
        if any(p.upper() in desc_upper for p in _RENDIMENTO_PATTERNS):
            return 'rendimento'
        if any(p.upper() in desc_upper for p in _INVESTBACK_PATTERNS):
            return 'rendimento'  # Investback is a form of yield
        return None

    def _extract_fund_name(self, desc: str) -> str:
        """Try to extract fund name from description."""
        # Common patterns: "Aplicação - Fund Name", "Resgate - Fund Name"
        m = re.search(r'(?:Aplicação|Resgate|Rendimento|Investback)\s*[-:]\s*(.+)', desc)
        if m:
            return m.group(1).strip()
        return desc

    def _infer_type(self, desc: str) -> str:
        """Infer product type from description."""
        desc_upper = desc.upper()
        if 'FIA' in desc_upper:
            return 'fia_br'
        if 'FIM' in desc_upper:
            return 'fim_br'
        if 'FIRF' in desc_upper or 'RF' in desc_upper:
            return 'firf_br'
        return 'fim_br'
