"""Import stock/ETF/FII orders from spreadsheet CSV into orders.csv ledger.

Usage:
    python import_orders.py <source_csv> <output_dir>

Source: 'Investimentos - Bolsa - histórico de ordens.csv'
  - Rows 0-2: metadata (skip)
  - Row 3: headers (Data, C/V, Ticker, Quantidade, Preço / ajuste, Corretora,
            Tipo de ativo, Valor operação (R$), Valor operação (moeda original),
            Moeda, Nota de corretagem, Taxas (guide), Taxas bolsa, ...)
  - Row 4+: data rows
  - Columns 13+: PM calculations (skip)
"""

import csv
import sys
from pathlib import Path

# Add scripts dir to path for utils
sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    parse_ptbr_decimal, parse_date_ddmmyyyy, normalize_broker,
    normalize_asset_type, write_ledger_csv, ORDERS_COLUMNS
)


def import_orders(source_csv: Path, output_dir: Path) -> int:
    """Import spreadsheet orders CSV into ledger format. Returns row count."""
    rows = []

    with open(source_csv, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        all_rows = list(reader)

    # Data starts at row 4 (0-indexed), header at row 3
    for i in range(4, len(all_rows)):
        row = all_rows[i]
        # Skip empty rows or rows without a date
        if len(row) < 10 or not row[0].strip() or '/' not in row[0]:
            continue

        date = parse_date_ddmmyyyy(row[0])
        side = row[1].strip()  # C or V
        ticker = row[2].strip()
        quantity = int(parse_ptbr_decimal(row[3]))
        price = parse_ptbr_decimal(row[4])
        corretora = normalize_broker(row[5])
        asset_type = normalize_asset_type(row[6])
        total_brl = parse_ptbr_decimal(row[7])
        total_original = parse_ptbr_decimal(row[8])
        currency = row[9].strip() if len(row) > 9 else 'BRL'
        # Fees: Taxas (guide) col 11, Taxas bolsa col 12
        fees_brokerage = parse_ptbr_decimal(row[11]) if len(row) > 11 else 0.0
        fees_exchange = parse_ptbr_decimal(row[12]) if len(row) > 12 else 0.0

        if not ticker:
            continue

        rows.append({
            'date': date,
            'side': side,
            'ticker': ticker,
            'quantity': quantity,
            'price': round(price, 2),
            'currency': currency or 'BRL',
            'total_brl': round(abs(total_brl), 2),
            'total_original': round(abs(total_original), 2),
            'fees_exchange': round(abs(fees_exchange), 2),
            'fees_brokerage': round(abs(fees_brokerage), 2),
            'fees_irrf': 0.0,
            'broker': corretora,
            'asset_type': asset_type,
            'market': 'vista',
            'source': 'spreadsheet',
        })

    # Sort by date
    rows.sort(key=lambda r: r['date'])

    output_path = output_dir / 'orders.csv'
    write_ledger_csv(output_path, rows, ORDERS_COLUMNS)
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

    count = import_orders(source, output)
    print(f'Imported {count} orders → {output / "orders.csv"}')
