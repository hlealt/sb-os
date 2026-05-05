"""Import fixed income and fund transactions from spreadsheet CSV into balcao.csv ledger.

Usage:
    python import_balcao.py <source_csv> <assets_json> <output_dir>

Source: 'Investimentos - Balcão - extrato.csv'
  - Rows 0-1: metadata (skip)
  - Row 2: headers (Liq, Mov, Histórico, Valor, Produto, Operação, [type], ...)
  - Row 3+: data rows
"""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    parse_ptbr_decimal, parse_date_ddmmyyyy,
    write_ledger_csv, BALCAO_COLUMNS
)

# Operations to import (mapped to canonical names)
OPERATION_MAP = {
    'aplicação fundos': 'aplicacao',
    'compra': 'aplicacao',
    'resgate': 'resgate',
    'resgate fundos': 'resgate',
    'pagamento de juros': 'juros',
    'irrf s/títulos': 'irrf',
    'irrf s/resgate fundos': 'irrf',
    'iof s/resgate fundos': 'iof',
}

# Operations to skip (not investment transactions)
SKIP_OPERATIONS = {
    'recebimento de ted', 'retirada',
}

# Products to skip (cash accounts, notes, non-investments)
SKIP_PRODUCTS = {
    '- spb', 'em c/c', 'guide cash', 'tropico cash',
    'is warren buffet?', 'living the american dream', 'tech games',
}


def build_alias_map(assets: dict) -> dict:
    """Build product name → (product_id, product_type) lookup from assets.json."""
    alias_map = {}
    for section in ['fixed_income', 'funds']:
        for pid, asset in assets.get(section, {}).items():
            ptype = asset.get('type', '')
            # Map by name
            alias_map[asset['name'].lower()] = (pid, ptype)
            # Map by aliases
            for alias in asset.get('aliases', []):
                alias_map[alias.lower()] = (pid, ptype)
    return alias_map


def import_balcao(source_csv: Path, assets_json: Path, output_dir: Path) -> int:
    """Import spreadsheet balcão CSV into ledger format. Returns row count."""
    with open(assets_json, 'r', encoding='utf-8') as f:
        assets = json.load(f)

    alias_map = build_alias_map(assets)
    rows = []
    warnings = []

    with open(source_csv, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        all_rows = list(reader)

    for i in range(3, len(all_rows)):
        row = all_rows[i]
        if len(row) < 6 or not row[0].strip() or '/' not in row[0]:
            continue

        date = parse_date_ddmmyyyy(row[0])
        valor = parse_ptbr_decimal(row[3])
        produto_raw = row[4].strip()
        operacao_raw = row[5].strip().lower()

        # Skip non-investment entries
        if produto_raw.lower() in SKIP_PRODUCTS:
            continue
        if operacao_raw in SKIP_OPERATIONS:
            continue

        # Map operation
        operation = OPERATION_MAP.get(operacao_raw)
        if not operation:
            # Try partial match
            for key, val in OPERATION_MAP.items():
                if key in operacao_raw:
                    operation = val
                    break
            if not operation:
                warnings.append(f'  Row {i}: unknown operation "{operacao_raw}" for {produto_raw}')
                continue

        # Resolve product name
        lookup = alias_map.get(produto_raw.lower())
        if lookup:
            product_id, product_type = lookup
        else:
            # Generate a sanitized ID
            product_id = produto_raw.lower().replace(' ', '_').replace('.', '').replace('/', '_')
            product_type = row[6].strip().lower().replace(' ', '_').replace('(', '').replace(')', '') if len(row) > 6 and row[6].strip() else 'unknown'
            warnings.append(f'  Row {i}: unresolved product "{produto_raw}" → {product_id}')

        # Determine broker from original context (Guide for most historical)
        broker = 'guide'

        rows.append({
            'date': date,
            'operation': operation,
            'product_id': product_id,
            'product_type': product_type,
            'amount': round(valor, 2),
            'broker': broker,
            'source': 'spreadsheet',
        })

    rows.sort(key=lambda r: r['date'])

    output_path = output_dir / 'balcao.csv'
    write_ledger_csv(output_path, rows, BALCAO_COLUMNS)

    if warnings:
        print(f'\nWarnings ({len(warnings)}):')
        for w in warnings:
            print(w)

    return len(rows)


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print(f'Usage: python {sys.argv[0]} <source_csv> <assets_json> <output_dir>')
        sys.exit(1)

    source = Path(sys.argv[1])
    assets = Path(sys.argv[2])
    output = Path(sys.argv[3])

    count = import_balcao(source, assets, output)
    print(f'\nImported {count} transactions → {output / "balcao.csv"}')
