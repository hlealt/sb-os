"""Import dividends/JCP/rendimentos from spreadsheet CSV into proventos.csv ledger.

Usage:
    python import_proventos.py <source_csv> <output_dir>

Source: 'Investimentos - Bolsa - histórico proventos.csv'
  - Rows 0-1: metadata (skip)
  - Row 2: headers (Data, Tipo, Papel, Valor, Instituição, QTD, Valor/unidade, Tipo, Ano, Mês)
  - Row 3+: data rows
  - Note: two 'Tipo' columns — col 1 = provento type, col 7 = asset type
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    parse_ptbr_decimal, parse_date_ddmmyyyy, normalize_broker,
    write_ledger_csv, PROVENTOS_COLUMNS
)

TYPE_MAP = {
    'rendimento': 'rendimento',
    'dividendos': 'dividendo',
    'dividendo': 'dividendo',
    'jcp': 'jcp',
}


def import_proventos(source_csv: Path, output_dir: Path) -> int:
    """Import spreadsheet proventos CSV into ledger format. Returns row count."""
    rows = []

    with open(source_csv, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        all_rows = list(reader)

    # Data starts at row 3 (0-indexed), header at row 2
    for i in range(3, len(all_rows)):
        row = all_rows[i]
        if len(row) < 7 or not row[0].strip() or '/' not in row[0]:
            continue

        date = parse_date_ddmmyyyy(row[0])
        tipo_raw = row[1].strip().lower()
        tipo = TYPE_MAP.get(tipo_raw, tipo_raw)
        ticker = row[2].strip()
        valor = parse_ptbr_decimal(row[3])
        instituicao = normalize_broker(row[4])
        qtd = parse_ptbr_decimal(row[5])
        valor_unidade = parse_ptbr_decimal(row[6])

        if not ticker:
            continue

        # JCP has IRRF withheld (15%), but the spreadsheet shows net value
        # We don't have gross vs net separation in the source — treat valor as net
        irrf = 0.0
        gross = abs(valor)
        net = abs(valor)

        rows.append({
            'date': date,
            'type': tipo,
            'ticker': ticker,
            'quantity': qtd,
            'value_per_unit': round(abs(valor_unidade), 6),
            'gross_value': round(gross, 2),
            'irrf': round(irrf, 2),
            'net_value': round(net, 2),
            'broker': instituicao,
            'source': 'spreadsheet',
        })

    rows.sort(key=lambda r: r['date'])

    output_path = output_dir / 'proventos.csv'
    write_ledger_csv(output_path, rows, PROVENTOS_COLUMNS)
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

    count = import_proventos(source, output)
    print(f'Imported {count} proventos → {output / "proventos.csv"}')
