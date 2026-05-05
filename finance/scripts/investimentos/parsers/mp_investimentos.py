"""Mercado Pago investment parser.

Reads mp_extrato.csv from the fechamento financeiro workflow and filters
investment-related transactions (APLICAÇÃO, RESGATE CDB, RENDIMENTO)
into balcao.csv format with product_type=cdb_mp.
"""

import csv
import re
from pathlib import Path

from .base import InvestmentBaseParser, ParseResult

# Known investment-related patterns in MP extrato descriptions
_INVESTMENT_PATTERNS = [
    (re.compile(r'APLICAÇÃO', re.IGNORECASE), 'aplicacao'),
    (re.compile(r'RESGATE\s+CDB', re.IGNORECASE), 'resgate'),
    (re.compile(r'RENDIMENTO', re.IGNORECASE), 'rendimento'),
]


class MPInvestimentosParser(InvestmentBaseParser):
    source_id = "mp_investimentos"

    def parse(self, filepath: Path, name_map=None) -> ParseResult:
        result = ParseResult()
        result.outputs = {'balcao': []}

        if not filepath.exists():
            result.flags.append(type('Flag', (), {
                'date': '', 'operation': 'FILE_NOT_FOUND',
                'product': str(filepath),
                'values': {},
                'reason': 'mp_extrato.csv not found. Run fechamento financeiro first.',
                'line_number': 0
            })())
            return result

        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                desc = row.get('description', row.get('descricao', '')).strip()
                amount = self._parse_amount(row)
                date = row.get('date', row.get('data', '')).strip()

                operation = self._classify(desc)
                if operation is None:
                    continue

                # Normalize amount sign
                if operation == 'aplicacao':
                    amount = -abs(amount)
                elif operation in ('resgate', 'rendimento'):
                    amount = abs(amount)

                result.outputs['balcao'].append({
                    'date': date,
                    'operation': operation,
                    'product_id': 'cdb_mercado_pago',
                    'product_type': 'cdb_mp',
                    'quantity': '0',
                    'amount': str(round(amount, 2)),
                    'irrf': '0',
                    'iof': '0',
                    'broker': 'mercado_pago',
                    'source': 'mp_investimentos',
                })

        return result

    def _classify(self, desc: str) -> str | None:
        """Match description against investment patterns."""
        for pattern, operation in _INVESTMENT_PATTERNS:
            if pattern.search(desc):
                return operation
        return None

    def _parse_amount(self, row: dict) -> float:
        """Extract amount from row (field name varies by fechamento version)."""
        for key in ('amount', 'valor', 'value'):
            if key in row:
                try:
                    val = row[key].strip().replace(',', '.')
                    return float(val)
                except (ValueError, TypeError, AttributeError):
                    pass
        return 0.0
