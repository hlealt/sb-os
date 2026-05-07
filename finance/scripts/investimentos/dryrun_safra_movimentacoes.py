"""Dry-run validation of the new Safra movimentacoes parsers against the
bootstrap CSVs (2024-2026). Prints summary stats per file + per-output bucket
and surfaces any flagged unknown lançamentos. Writes nothing to ledgers.

Usage:
    python dryrun_safra_movimentacoes.py
"""

import sys
from collections import Counter
from pathlib import Path


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / 'CLAUDE.md').exists() and (parent / '.user').is_dir():
            return parent
    raise RuntimeError('Vault root not found')


VAULT_ROOT = _find_vault_root()
sys.path.insert(0, str(Path(__file__).parent))

from parsers.safra_fundos_movimentacoes import SafraFundosMovimentacoesParser
from parsers.safra_rf_movimentacoes import SafraRfMovimentacoesParser
from parsers.name_map import NameMapResolver

BOOTSTRAP_DIR = VAULT_ROOT / '.user' / 'finance' / 'bookkeeper' / 'raw-data' / 'safra-bootstrap-2024-2026'

FILES = [
    ('fundos', 'safra-fundos-2024.csv'),
    ('fundos', 'safra-fundos-2025.csv'),
    ('fundos', 'safra-fundos-2026.csv'),
    ('rf',     'safra-rf-2024.csv'),
    ('rf',     'safra-rf-2025.csv'),
    ('rf',     'safra-rf-2026.csv'),
]


def summarize(parser_kind: str, filename: str, result):
    print(f'\n=== {parser_kind:6s}  {filename}')
    for bucket, rows in result.outputs.items():
        if not rows:
            continue
        print(f'  {bucket:20s} {len(rows):4d} rows')
        if bucket == 'balcao':
            ops = Counter(r['operation'] for r in rows)
            for op, n in sorted(ops.items()):
                print(f'      op={op:18s} {n:4d}')
        elif bucket == 'assets':
            ids = sorted({r['id'] for r in rows})
            for pid in ids:
                print(f'      asset_id={pid}')
    if result.flags:
        print(f'  FLAGS: {len(result.flags)}')
        for f in result.flags:
            print(f'    line {f.line_number}: {f.operation!r} on {f.product!r} — {f.reason}')


def main():
    name_map = NameMapResolver()
    fundos = SafraFundosMovimentacoesParser()
    rf = SafraRfMovimentacoesParser()

    grand = {'balcao': 0, 'balance_snapshots': 0, 'balcao_seeds': 0, 'assets': 0, 'flags': 0}

    for kind, fname in FILES:
        filepath = BOOTSTRAP_DIR / fname
        if not filepath.exists():
            print(f'MISSING: {filepath}')
            continue
        parser = fundos if kind == 'fundos' else rf
        result = parser.parse(filepath, name_map=name_map)
        summarize(kind, fname, result)
        for k, v in result.outputs.items():
            grand[k] = grand.get(k, 0) + len(v)
        grand['flags'] += len(result.flags)

    print('\n=== TOTALS')
    for k, v in grand.items():
        print(f'  {k:20s} {v:5d}')


if __name__ == '__main__':
    main()
