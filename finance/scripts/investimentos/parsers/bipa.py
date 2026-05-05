"""Bipa crypto exchange CSV parser.

Parses Bipa extrato CSV into crypto.csv format.
All assets are BTC. Date includes time (truncated to date only).
"""

import csv
from pathlib import Path

from .base import InvestmentBaseParser, ParseResult

# Map Bipa transaction types to crypto.csv operations
_OP_MAP = {
    'COMPRA': 'compra',
    'COMPRA_RECORRENTE': 'compra',
    'RECEBIMENTO_REWARDS': 'recebimento',
    'RECEBIMENTO_INDICADO': 'recebimento',
    'RECEBIMENTO_LIGHTNING': 'recebimento',
    'ENVIO_ONCHAIN': 'envio',
    'VENDA': 'venda',
}


class BipaParser(InvestmentBaseParser):
    source_id = "bipa"

    def parse(self, filepath: Path, name_map=None) -> ParseResult:
        result = ParseResult()
        result.outputs = {'crypto': []}

        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                tipo = row.get('Tipo_Transacao', '').strip()
                op = _OP_MAP.get(tipo)
                if op is None:
                    result.flags.append(type('Flag', (), {
                        'date': '', 'operation': tipo,
                        'product': row.get('Ativo', ''),
                        'values': row, 'reason': f'Unknown Bipa operation: {tipo}',
                        'line_number': 0
                    })())
                    continue

                asset = row.get('Ativo', 'BTC').strip()
                date_raw = row.get('Data', '').strip()
                # Date format: DD/MM/YYYY HH:MM:SS → YYYY-MM-DD
                date = self._parse_date(date_raw)

                valor_op = self._parse_decimal(row.get('Valor da operacao', '0'))
                valor_liq = self._parse_decimal(row.get('Valor liquido da operacao', '0'))
                qty = self._parse_decimal(row.get('Qtd de ativo', '0'))
                fee_pct = self._parse_decimal(row.get('Taxa (%)', '0'))
                fee_amount = self._parse_decimal(row.get('Taxa (Qtd de ativo)', '0'))
                fee_currency = row.get('Taxa (Ativo)', '').strip()

                es = row.get('E/S', '').strip()

                if es == 'Entrada':
                    buy_asset = asset
                    buy_qty = qty
                    sell_asset = 'BRL'
                    sell_qty = valor_op
                elif es == 'Saida':
                    buy_asset = 'BRL' if op == 'venda' else ''
                    buy_qty = valor_liq if op == 'venda' else 0
                    sell_asset = asset
                    sell_qty = qty
                else:
                    buy_asset = asset
                    buy_qty = qty
                    sell_asset = 'BRL'
                    sell_qty = valor_op

                result.outputs['crypto'].append({
                    'date': date,
                    'operation': op,
                    'buy_asset': buy_asset,
                    'buy_quantity': str(round(buy_qty, 8)),
                    'sell_asset': sell_asset,
                    'sell_quantity': str(round(sell_qty, 8)),
                    'price_brl': str(round(valor_op, 2)),
                    'fee_pct': str(round(fee_pct, 2)) if fee_pct else '',
                    'fee_amount': str(round(fee_amount, 8)) if fee_amount else '',
                    'fee_currency': fee_currency if fee_amount else '',
                    'exchange': 'bipa',
                    'source': 'bipa',
                })

        return result

    def _parse_date(self, date_str: str) -> str:
        """DD/MM/YYYY HH:MM:SS → YYYY-MM-DD (truncate time)."""
        if not date_str:
            return ''
        date_part = date_str.split(' ')[0]
        parts = date_part.split('/')
        if len(parts) == 3:
            return f'{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}'
        return date_str

    def _parse_decimal(self, val: str) -> float:
        """Parse decimal value (already uses dots in Bipa CSV)."""
        if not val or val.strip() == '-':
            return 0.0
        try:
            return float(val.strip().replace(',', '.'))
        except (ValueError, TypeError):
            return 0.0
