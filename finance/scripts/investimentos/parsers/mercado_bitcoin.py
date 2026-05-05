"""Mercado Bitcoin CSV parser.

Parses MB extrato CSV into crypto.csv format.
Transactions come in pairs: BTC line + BRL line for each trade.
Critical: skip Dec 2023 BTC deposit (0.06442762 — transfer FROM Binance).
"""

import csv
import re
from pathlib import Path

from .base import InvestmentBaseParser, ParseResult

# Amount uses PT-BR format: "0,04645994" or "-10000,00"
_PTBR_RE = re.compile(r'^["\s]*(-?[\d.,]+)["\s]*$')


class MercadoBitcoinParser(InvestmentBaseParser):
    source_id = "mercado_bitcoin"

    def parse(self, filepath: Path, name_map=None) -> ParseResult:
        result = ParseResult()
        result.outputs = {'crypto': []}

        rows = self._read_csv(filepath)

        # Process rows in pairs (BTC row + BRL row for each trade)
        i = 0
        while i < len(rows):
            row = rows[i]
            desc = row.get('Descrição', '').strip()
            moeda = row.get('Moeda', '').strip()
            date_str = row.get('Data', '').strip()
            date = self._parse_date(date_str)

            # Skip Depósito BRL (just funding)
            if desc == 'Depósito' and moeda == 'BRL':
                i += 1
                continue

            # Skip Dec 2023 BTC deposit (Binance transfer, not a purchase)
            if desc == 'Depósito' and moeda == 'BTC':
                qty = self._parse_ptbr(row.get('Quantidade (ativo)', '0'))
                if date.startswith('2023-12') and abs(qty - 0.06442762) < 0.00001:
                    i += 1
                    continue
                # Other BTC deposits are also transfers, not purchases
                i += 1
                continue

            # Execução de ordem: paired BTC + BRL rows
            if desc == 'Execução de ordem':
                if moeda == 'BTC':
                    btc_qty = self._parse_ptbr(row.get('Quantidade (ativo)', '0'))
                    # Look for matching BRL row
                    brl_amount = 0.0
                    if i + 1 < len(rows):
                        next_row = rows[i + 1]
                        if (next_row.get('Descrição', '').strip() == 'Execução de ordem'
                                and next_row.get('Moeda', '').strip() == 'BRL'):
                            brl_amount = abs(self._parse_ptbr(
                                next_row.get('Valor R$', '0')
                            ))
                            i += 1  # Consume the BRL row

                    result.outputs['crypto'].append({
                        'date': date,
                        'operation': 'compra',
                        'buy_asset': 'BTC',
                        'buy_quantity': str(round(btc_qty, 8)),
                        'sell_asset': 'BRL',
                        'sell_quantity': str(round(brl_amount, 2)),
                        'price_brl': str(round(brl_amount, 2)),
                        'fee_pct': '',
                        'fee_amount': '',
                        'fee_currency': '',
                        'exchange': 'mb',
                        'source': 'mercado_bitcoin',
                    })
                elif moeda == 'BRL':
                    # Orphan BRL row (BTC row was previous) — skip
                    pass

            i += 1

        return result

    def _read_csv(self, filepath: Path) -> list[dict]:
        with open(filepath, 'r', encoding='utf-8') as f:
            return list(csv.DictReader(f))

    def _parse_date(self, date_str: str) -> str:
        """DD/MM/YYYY HH:MM:SS → YYYY-MM-DD."""
        if not date_str:
            return ''
        date_part = date_str.split(' ')[0]
        parts = date_part.split('/')
        if len(parts) == 3:
            return f'{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}'
        return date_str

    def _parse_ptbr(self, val: str) -> float:
        """Parse PT-BR decimal: '0,04645994' or '-10.000,00'."""
        if not val or val.strip() in ('-', ''):
            return 0.0
        s = val.strip().strip('"')
        s = s.replace('.', '').replace(',', '.')
        try:
            return float(s)
        except (ValueError, TypeError):
            return 0.0
