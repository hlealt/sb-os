"""Import crypto trades from spreadsheet CSV into crypto.csv ledger.

Usage:
    python import_crypto.py <source_csv> <output_dir>

Source: 'Investimentos - Crypto - histórico de ordens.csv'
  - Rows 0-1: metadata (skip)
  - Row 2: headers (moeda comprada (C), moeda vendida (V), data, quantidade (C),
            quantidade (V), taxa, moeda taxa, valor de mercado, ...)
  - Row 3+: data rows

Handles three trade types:
  - Fiat buy: buy_asset=BTC, sell_asset=BRL → operation=compra
  - Fiat sell: buy_asset=BRL, sell_asset=BTC → operation=venda
  - Crypto swap: buy_asset=NMR, sell_asset=BTC → operation=swap
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    parse_ptbr_decimal, parse_date_ddmmyyyy,
    write_ledger_csv, CRYPTO_COLUMNS
)

# Map exchange from fee currency column
EXCHANGE_MAP = {
    'bnb': 'binance',
    'brl': 'bipa',  # BRL fee transactions are from Bipa (2021+) or MB
}


def determine_operation(buy_asset: str, sell_asset: str) -> str:
    """Determine operation type from the trade pair."""
    if sell_asset == 'BRL':
        return 'compra'  # Buying crypto with BRL
    elif buy_asset == 'BRL':
        return 'venda'   # Selling crypto for BRL
    else:
        return 'swap'    # Crypto-to-crypto


def import_crypto(source_csv: Path, output_dir: Path) -> int:
    """Import spreadsheet crypto CSV into ledger format. Returns row count."""
    rows = []
    skipped = 0

    with open(source_csv, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        all_rows = list(reader)

    for i in range(3, len(all_rows)):
        row = all_rows[i]
        if len(row) < 9:
            continue

        buy_asset = row[0].strip()   # moeda comprada (C)
        sell_asset = row[1].strip()  # moeda vendida (V)
        date_raw = row[2].strip()    # data

        # Skip adjustment rows (no date)
        if not date_raw or '/' not in date_raw:
            skipped += 1
            continue

        # Skip rows with empty buy AND sell asset
        if not buy_asset and not sell_asset:
            skipped += 1
            continue

        date = parse_date_ddmmyyyy(date_raw)
        buy_qty = parse_ptbr_decimal(row[3])   # quantidade (C)
        sell_qty = parse_ptbr_decimal(row[4])   # quantidade (V)
        fee_rate = parse_ptbr_decimal(row[5])   # taxa
        fee_currency = row[6].strip()           # moeda taxa
        # valor de mercado (R$, V) col 7 — BRL market value reference
        market_val = parse_ptbr_decimal(row[7])
        # valor da transação (mercado, R$) col 8 — BRL value of this transaction
        tx_brl = parse_ptbr_decimal(row[8])

        operation = determine_operation(buy_asset, sell_asset)

        # Determine exchange from fee currency
        exchange = EXCHANGE_MAP.get(fee_currency.lower(), 'unknown')
        # If fee currency is a crypto asset (not BNB, not BRL), it's Binance
        if fee_currency and fee_currency.lower() not in ('brl', 'bnb', '0', ''):
            exchange = 'binance'

        # For BRL buys/sells, price_brl is the transaction value
        # For swaps, price_brl is the BRL equivalent
        price_brl = abs(tx_brl) if tx_brl else abs(sell_qty) if sell_asset == 'BRL' else abs(buy_qty) if buy_asset == 'BRL' else 0.0

        # Fee calculation
        fee_pct = abs(fee_rate) * 100 if fee_rate and fee_rate < 1 else abs(fee_rate)
        fee_amount = 0.0
        fee_curr = fee_currency if fee_currency and fee_currency != '0' else ''

        rows.append({
            'date': date,
            'operation': operation,
            'buy_asset': buy_asset,
            'buy_quantity': round(abs(buy_qty), 8),
            'sell_asset': sell_asset,
            'sell_quantity': round(abs(sell_qty), 8),
            'price_brl': round(price_brl, 2),
            'fee_pct': round(fee_pct, 4) if fee_pct else '',
            'fee_amount': round(fee_amount, 8) if fee_amount else '',
            'fee_currency': fee_curr,
            'exchange': exchange,
            'source': 'spreadsheet',
        })

    rows.sort(key=lambda r: r['date'])

    output_path = output_dir / 'crypto.csv'
    write_ledger_csv(output_path, rows, CRYPTO_COLUMNS)

    if skipped:
        print(f'Skipped {skipped} adjustment/empty rows')

    return len(rows)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f'Usage: python {sys.argv[0]} <source_csv> <output_dir>')
        sys.exit(1)

    source = Path(sys.argv[1])
    output = Path(sys.argv[2])

    if not source.exists():
        print(f'Error: source file not found: {source}')
        sys.exit(1)

    count = import_crypto(source, output)
    print(f'Imported {count} crypto trades → {output / "crypto.csv"}')
