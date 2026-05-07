"""Incremental dry-run: simulates importing the 6 bootstrap CSVs into balcao.csv,
balance-snapshots.csv and assets.csv WITHOUT writing. Reuses the real upsert
logic from import_balance_snapshots and reports per-file diffs.

Outputs:
  - inserted vs skipped per file per bucket
  - inserted rows GROUPED by (product_id, operation) so the user can spot anomalies
  - any product_id that would CHANGE its earliest-flow date (could affect IRR)
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
from import_balance_snapshots import (
    BALCAO_FILE, SNAPSHOTS_FILE, ASSETS_FILE, load_existing,
    _INSERT_ONLY_FIELDS,
)

BOOTSTRAP_DIR = VAULT_ROOT / '.user' / 'finance' / 'bookkeeper' / 'raw-data' / 'safra-bootstrap-2024-2026'

FILES = [
    ('fundos', 'safra-fundos-2024.csv'),
    ('fundos', 'safra-fundos-2025.csv'),
    ('fundos', 'safra-fundos-2026.csv'),
    ('rf',     'safra-rf-2024.csv'),
    ('rf',     'safra-rf-2025.csv'),
    ('rf',     'safra-rf-2026.csv'),
]


def simulate_balcao_upsert(existing: list[dict], new_tx: list[dict],
                           new_seeds: list[dict]) -> dict:
    """Mirrors upsert_balcao() logic but only reports counts/details."""
    keys = {(r['date'], r['operation'], r['product_id'], r['amount']) for r in existing}
    earliest = {}
    earliest_origin = {}
    for r in existing:
        pid, d = r['product_id'], r['date']
        if pid not in earliest or d < earliest[pid]:
            earliest[pid] = d
            earliest_origin[pid] = r.get('source', '?')

    inserted_tx = []
    skipped_tx = []
    for row in new_tx:
        k = (row['date'], row['operation'], row['product_id'], row['amount'])
        if k in keys:
            skipped_tx.append(row)
            continue
        inserted_tx.append(row)
        keys.add(k)
        pid, d = row['product_id'], row['date']
        if pid not in earliest or d < earliest[pid]:
            earliest[pid] = d
            earliest_origin[pid] = row.get('source', '?')

    inserted_seed = []
    skipped_seed_history = []
    skipped_seed_dup = []
    for row in new_seeds:
        pid, seed_date = row['product_id'], row['date']
        if pid in earliest and earliest[pid] < seed_date:
            skipped_seed_history.append((row, earliest[pid], earliest_origin[pid]))
            continue
        k = (row['date'], row['operation'], row['product_id'], row['amount'])
        if k in keys:
            skipped_seed_dup.append(row)
            continue
        inserted_seed.append(row)
        keys.add(k)
        if pid not in earliest or seed_date < earliest[pid]:
            earliest[pid] = seed_date
            earliest_origin[pid] = row.get('source', '?')

    return {
        'inserted_tx': inserted_tx,
        'skipped_tx': skipped_tx,
        'inserted_seed': inserted_seed,
        'skipped_seed_history': skipped_seed_history,
        'skipped_seed_dup': skipped_seed_dup,
    }


def simulate_snapshots_upsert(existing: list[dict], new_rows: list[dict]) -> dict:
    keys = {(r['date'], r['product_id']) for r in existing}
    inserted, skipped = [], []
    for row in new_rows:
        k = (row['date'], row['product_id'])
        if k in keys:
            skipped.append(row)
        else:
            inserted.append(row)
            keys.add(k)
    return {'inserted': inserted, 'skipped': skipped}


def simulate_assets_upsert(existing_by_id: dict, new_rows: list[dict]) -> dict:
    inserted, updated = [], []
    for row in new_rows:
        pid = row['id']
        if pid in existing_by_id:
            target = existing_by_id[pid]
            changes = {}
            for k, v in row.items():
                if k in _INSERT_ONLY_FIELDS:
                    continue
                if v and target.get(k, '') != v:
                    changes[k] = (target.get(k, ''), v)
            if changes:
                updated.append((pid, changes))
        else:
            inserted.append(row)
    return {'inserted': inserted, 'updated': updated}


def main():
    name_map = NameMapResolver()
    parsers = {
        'fundos': SafraFundosMovimentacoesParser(),
        'rf': SafraRfMovimentacoesParser(),
    }

    existing_balcao = load_existing(BALCAO_FILE)
    existing_snaps = load_existing(SNAPSHOTS_FILE)
    existing_assets = load_existing(ASSETS_FILE)
    existing_assets_by_id = {r['id']: r for r in existing_assets}

    print(f'Existing ledger:')
    print(f'  balcao.csv             {len(existing_balcao):4d} rows')
    print(f'  balance-snapshots.csv  {len(existing_snaps):4d} rows')
    print(f'  assets.csv             {len(existing_assets):4d} rows')

    # Cumulative state across files (since file order matters for dedup)
    cum_balcao = list(existing_balcao)
    cum_snaps = list(existing_snaps)
    cum_assets = dict(existing_assets_by_id)

    grand_inserted_tx = 0
    grand_inserted_seed = 0
    grand_inserted_snap = 0
    grand_inserted_asset = 0
    grand_updated_asset = 0
    grand_skipped_seed_history = 0

    for kind, fname in FILES:
        filepath = BOOTSTRAP_DIR / fname
        if not filepath.exists():
            print(f'\nMISSING: {filepath}')
            continue
        result = parsers[kind].parse(filepath, name_map=name_map)

        sim_b = simulate_balcao_upsert(
            cum_balcao,
            result.outputs.get('balcao', []),
            result.outputs.get('balcao_seeds', []),
        )
        sim_s = simulate_snapshots_upsert(cum_snaps, result.outputs.get('balance_snapshots', []))
        sim_a = simulate_assets_upsert(cum_assets, result.outputs.get('assets', []))

        print(f'\n=== {kind:6s}  {fname}')
        # Balcao tx
        ins_tx = sim_b['inserted_tx']
        if ins_tx:
            ops = Counter((r['product_id'], r['operation']) for r in ins_tx)
            print(f'  balcao tx inserted: {len(ins_tx):4d}  (skipped dup: {len(sim_b["skipped_tx"]):3d})')
            for (pid, op), n in sorted(ops.items()):
                print(f'    + {pid:38s} op={op:14s} {n:3d}')
        else:
            print(f'  balcao tx inserted:    0  (skipped dup: {len(sim_b["skipped_tx"]):3d})')

        # Seeds
        ins_seed = sim_b['inserted_seed']
        sk_seed_h = sim_b['skipped_seed_history']
        sk_seed_d = sim_b['skipped_seed_dup']
        print(f'  seeds inserted:     {len(ins_seed):4d}  (skipped_history: {len(sk_seed_h):3d}, skipped_dup: {len(sk_seed_d):3d})')
        if ins_seed:
            for r in ins_seed:
                print(f'    + SEED {r["product_id"]:38s} {r["date"]} amount={r["amount"]}')

        # Snapshots
        ins_snap = sim_s['inserted']
        print(f'  snapshots inserted: {len(ins_snap):4d}  (skipped dup: {len(sim_s["skipped"]):3d})')

        # Assets
        ins_asset = sim_a['inserted']
        upd_asset = sim_a['updated']
        if ins_asset:
            print(f'  assets INSERTED:    {len(ins_asset):4d}')
            for r in ins_asset:
                print(f'    + NEW ASSET {r["id"]:38s} type={r.get("type","")} class={r.get("asset_class","")}')
        if upd_asset:
            print(f'  assets UPDATED:     {len(upd_asset):4d}')
            for pid, changes in upd_asset:
                fields = ', '.join(f'{k}: {repr(o)}→{repr(n)}' for k, (o, n) in changes.items())
                print(f'    ~ {pid}: {fields}')

        # Apply to cumulative state
        cum_balcao.extend(ins_tx)
        cum_balcao.extend(ins_seed)
        cum_snaps.extend(ins_snap)
        for r in ins_asset:
            cum_assets[r['id']] = r

        grand_inserted_tx += len(ins_tx)
        grand_inserted_seed += len(ins_seed)
        grand_inserted_snap += len(ins_snap)
        grand_inserted_asset += len(ins_asset)
        grand_updated_asset += len(upd_asset)
        grand_skipped_seed_history += len(sk_seed_h)

    print('\n=== TOTAL CHANGES (if all 6 imports run)')
    print(f'  balcao tx inserted:    {grand_inserted_tx:4d}')
    print(f'  seeds inserted:        {grand_inserted_seed:4d}')
    print(f'  seeds skipped (history existed): {grand_skipped_seed_history:4d}')
    print(f'  snapshots inserted:    {grand_inserted_snap:4d}')
    print(f'  assets new:            {grand_inserted_asset:4d}')
    print(f'  assets updated:        {grand_updated_asset:4d}')
    print(f'\n  Final balcao rows:     {len(cum_balcao):4d}  (was {len(existing_balcao)})')
    print(f'  Final snapshots rows:  {len(cum_snaps):4d}  (was {len(existing_snaps)})')
    print(f'  Final assets rows:     {len(cum_assets):4d}  (was {len(existing_assets)})')


if __name__ == '__main__':
    main()
