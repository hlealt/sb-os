"""Shared utilities for investment ledger import scripts."""

import csv
import re
from pathlib import Path

# --- Column definitions for each ledger ---

ORDERS_COLUMNS = [
    'date', 'side', 'ticker', 'quantity', 'price', 'currency',
    'total', 'fees_exchange', 'fees_brokerage', 'fees_irrf',
    'broker', 'asset_type', 'market', 'source'
]

PROVENTOS_COLUMNS = [
    'date', 'type', 'ticker', 'quantity', 'value_per_unit',
    'gross_value', 'currency', 'irrf', 'withholding_tax',
    'net_value', 'broker', 'source'
]

BALCAO_COLUMNS = [
    'date', 'operation', 'product_id', 'product_type',
    'quantity', 'amount', 'irrf', 'iof', 'broker', 'source'
]

CRYPTO_COLUMNS = [
    'date', 'operation', 'buy_asset', 'buy_quantity',
    'sell_asset', 'sell_quantity', 'price_brl',
    'fee_pct', 'fee_amount', 'fee_currency',
    'exchange', 'source'
]

CORPORATE_ACTIONS_COLUMNS = [
    'date', 'action_type', 'ticker', 'new_ticker',
    'ratio_from', 'ratio_to', 'broker', 'source', 'notes'
]

AVENUE_FX_COLUMNS = [
    'date', 'operation', 'brl_amount', 'usd_amount',
    'fx_rate', 'source'
]


# --- Parsing utilities ---

def parse_ptbr_decimal(s: str) -> float:
    """Convert PT-BR decimal format to float. '1.343,41' → 1343.41, '-5.000,00' → -5000.0"""
    if not s or not s.strip():
        return 0.0
    s = s.strip().strip('"')
    # Remove R$ prefix if present
    s = re.sub(r'^-?\s*R\$\s*', lambda m: '-' if '-' in m.group() else '', s)
    # Handle negative in parentheses: (1.234,56)
    neg = False
    if s.startswith('(') and s.endswith(')'):
        neg = True
        s = s[1:-1]
    elif s.startswith('-'):
        neg = True
        s = s[1:].strip()
    # Remove thousand separator (.) and convert decimal comma to dot
    s = s.replace('.', '').replace(',', '.')
    try:
        val = float(s)
        return -val if neg else val
    except ValueError:
        return 0.0


def parse_date_ddmmyyyy(s: str) -> str:
    """Convert DD/MM/YYYY or D/M/YYYY to YYYY-MM-DD."""
    if not s or not s.strip():
        return ''
    s = s.strip()
    parts = s.split('/')
    if len(parts) != 3:
        return s
    d, m, y = parts
    return f'{y}-{m.zfill(2)}-{d.zfill(2)}'


def normalize_broker(corretora: str) -> str:
    """Map spreadsheet broker names to canonical IDs."""
    mapping = {
        'clear': 'clear',
        'guide': 'guide',
        'avenue': 'avenue',
        'safra': 'safra',
        'xp': 'xp',
    }
    return mapping.get(corretora.strip().lower(), corretora.strip().lower())


def normalize_asset_type(tipo: str) -> str:
    """Map spreadsheet asset type names to canonical IDs."""
    mapping = {
        'ação': 'acao',
        'acao': 'acao',
        'fii': 'fii',
        'etf': 'etf',
    }
    return mapping.get(tipo.strip().lower(), tipo.strip().lower())


# --- CSV I/O ---

def write_ledger_csv(filepath: Path, rows: list[dict], columns: list[str]):
    """Write rows to a CSV file with enforced column order."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def read_ledger_csv(filepath: Path) -> list[dict]:
    """Read a ledger CSV back as list of dicts."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return list(csv.DictReader(f))
