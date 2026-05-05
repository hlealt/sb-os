"""Import balance snapshots, fund transactions, and bootstrap seeds from a
parser source file.

Currently wired for Safra fund statements. The parser must populate at least
result.outputs['balance_snapshots']; optionally:

  - balcao: regular fund transactions (aplicação/resgate/amortização)
  - balcao_seeds: synthetic carry-forward aplicações derived from "Saldo
    Anterior" rows. Seeds are inserted ONLY when the product_id has zero
    existing rows in balcao.csv — recurring statements never re-seed a
    fund that already has history.

Dedup keys:
  - balance-snapshots.csv: (date, product_id)
  - balcao.csv: (date, operation, product_id, amount)

Re-running the same statement is idempotent.

Usage:
    python import_balance_snapshots.py <source_csv> [--parser safra_fundos]
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from parsers.safra_fundos import SafraFundosParser
from parsers.safra_titulos import SafraTitulosParser
from parsers.safra_fundos_movimentacoes import SafraFundosMovimentacoesParser
from parsers.safra_rf_movimentacoes import SafraRfMovimentacoesParser
from parsers.name_map import NameMapResolver


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return parent
    raise RuntimeError(f"Vault root not found from {__file__}")


VAULT_ROOT = _find_vault_root()
LEDGER_DIR = VAULT_ROOT / "3-resources" / "tools" / "finance" / "ledgers" / "investimentos"
SNAPSHOTS_FILE = LEDGER_DIR / "balance-snapshots.csv"
BALCAO_FILE = LEDGER_DIR / "balcao.csv"
ASSETS_FILE = VAULT_ROOT / ".user" / "workflows" / "accountant" / "data" / "assets.csv"
SNAPSHOTS_COLUMNS = ['date', 'product_id', 'balance', 'source']
BALCAO_COLUMNS = ['date', 'operation', 'product_id', 'product_type', 'quantity',
                  'amount', 'irrf', 'iof', 'broker', 'source']

PARSERS = {
    'safra_fundos': SafraFundosParser,
    'safra_titulos': SafraTitulosParser,
    'safra_fundos_movimentacoes': SafraFundosMovimentacoesParser,
    'safra_rf_movimentacoes': SafraRfMovimentacoesParser,
}


def load_existing(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def write_all(path: Path, rows: list[dict], columns: list[str]):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, '') for k in columns})


def upsert_snapshots(new_rows: list[dict]) -> tuple[int, int, int]:
    existing = load_existing(SNAPSHOTS_FILE)
    keys = {(r['date'], r['product_id']) for r in existing}
    inserted = skipped = 0
    for row in new_rows:
        k = (row['date'], row['product_id'])
        if k in keys:
            skipped += 1
            continue
        existing.append(row)
        keys.add(k)
        inserted += 1
    if inserted:
        existing.sort(key=lambda r: (r['date'], r['product_id']))
        write_all(SNAPSHOTS_FILE, existing, SNAPSHOTS_COLUMNS)
    return inserted, skipped, len(existing)


def upsert_balcao(new_rows: list[dict], seed_rows: list[dict]) -> tuple[int, int, int, int]:
    existing = load_existing(BALCAO_FILE)

    keys = {(r['date'], r['operation'], r['product_id'], r['amount']) for r in existing}
    # Track earliest known date per product (across pre-existing AND newly-inserted tx)
    # so a seed only fires when no existing history predates it. A seed dated 2026-02-27
    # is correctly applied even if the same run inserts a 2026-03-06 aplicação for the
    # same product — the seed backfills the carrying balance from before our visibility.
    earliest = {}
    for r in existing:
        pid, d = r['product_id'], r['date']
        if pid not in earliest or d < earliest[pid]:
            earliest[pid] = d

    inserted_tx = skipped_tx = 0
    for row in new_rows:
        k = (row['date'], row['operation'], row['product_id'], row['amount'])
        if k in keys:
            skipped_tx += 1
            continue
        existing.append(row)
        keys.add(k)
        pid, d = row['product_id'], row['date']
        if pid not in earliest or d < earliest[pid]:
            earliest[pid] = d
        inserted_tx += 1

    inserted_seed = skipped_seed = 0
    for row in seed_rows:
        pid, seed_date = row['product_id'], row['date']
        # Skip when an existing row predates the seed (history already covers carry-forward),
        # or when an identical seed already exists (idempotent re-run).
        if pid in earliest and earliest[pid] < seed_date:
            skipped_seed += 1
            continue
        k = (row['date'], row['operation'], row['product_id'], row['amount'])
        if k in keys:
            skipped_seed += 1
            continue
        existing.append(row)
        keys.add(k)
        if pid not in earliest or seed_date < earliest[pid]:
            earliest[pid] = seed_date
        inserted_seed += 1

    if inserted_tx or inserted_seed:
        existing.sort(key=lambda r: (r['date'], r['product_id']))
        write_all(BALCAO_FILE, existing, BALCAO_COLUMNS)

    return inserted_tx, skipped_tx, inserted_seed, skipped_seed


_INSERT_ONLY_FIELDS = {'name', 'issuer', 'cnpj'}


def upsert_assets(new_rows: list[dict]) -> tuple[int, int]:
    """Merge new asset metadata into assets.csv by `id`.

    Existing rows are preserved; only fields explicitly set in new_rows overwrite
    the existing values. Missing fields stay as-is — protects manual edits.

    Fields in `_INSERT_ONLY_FIELDS` are populated only on insert and never
    overwritten on update — they are user-curated after the initial registration.
    """
    if not ASSETS_FILE.exists() or not new_rows:
        return 0, 0

    with open(ASSETS_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        columns = list(reader.fieldnames)
        existing = list(reader)

    by_id = {r['id']: r for r in existing}
    inserted = 0
    updated = 0
    for row in new_rows:
        pid = row['id']
        if pid in by_id:
            target = by_id[pid]
            changed = False
            for k, v in row.items():
                if k in _INSERT_ONLY_FIELDS:
                    continue
                if v and target.get(k, '') != v:
                    target[k] = v
                    changed = True
            if changed:
                updated += 1
        else:
            for c in columns:
                row.setdefault(c, '')
            existing.append(row)
            by_id[pid] = row
            inserted += 1

    with open(ASSETS_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for r in existing:
            writer.writerow({k: r.get(k, '') for k in columns})

    return inserted, updated


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source')
    ap.add_argument('--parser', default='safra_fundos', choices=list(PARSERS))
    args = ap.parse_args()

    source = Path(args.source).resolve()
    if not source.exists():
        print(f"ERROR: source not found: {source}", file=sys.stderr)
        sys.exit(1)

    parser = PARSERS[args.parser]()
    name_map = NameMapResolver()
    result = parser.parse(source, name_map=name_map)

    snap_rows = result.outputs.get('balance_snapshots', [])
    balcao_rows = result.outputs.get('balcao', [])
    seed_rows = result.outputs.get('balcao_seeds', [])
    asset_rows = result.outputs.get('assets', [])

    snap_inserted, snap_skipped, snap_total = upsert_snapshots(snap_rows)
    bal_inserted, bal_skipped, seed_inserted, seed_skipped = upsert_balcao(balcao_rows, seed_rows)
    asset_inserted, asset_updated = upsert_assets(asset_rows)

    print(f"parser:        {args.parser}")
    print(f"source:        {source}")
    print(f"")
    print(f"balance-snapshots: emitted={len(snap_rows)} inserted={snap_inserted} skipped={snap_skipped} total={snap_total}")
    print(f"balcao tx:         emitted={len(balcao_rows)} inserted={bal_inserted} skipped={bal_skipped}")
    print(f"balcao seeds:      emitted={len(seed_rows)} inserted={seed_inserted} skipped={seed_skipped} (skipped = product already has history)")
    print(f"assets metadata:   emitted={len(asset_rows)} inserted={asset_inserted} updated={asset_updated}")


if __name__ == '__main__':
    main()
