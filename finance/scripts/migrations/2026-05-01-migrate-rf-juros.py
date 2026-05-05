"""One-shot migration: move historical RF juros/amortizações from proventos.csv → balcao.csv.

Why: b3_parser.py used to route PAGAMENTO DE JUROS to proventos.csv for ALL assets,
including RF. But RF income must net against aplicado in balcao to compute correct
P&L per position. The parser was fixed (PAGAMENTO DE JUROS now routes to balcao for
RF), but historical rows in proventos.csv need to be migrated.

Behavior:
- Identifies proventos.csv rows where ticker matches an RF prefix AND type ∈ {juros, amortizacao}
- Translates B3 auto-extracted slugs (e.g. deb_rdorb3) to canonical balcão IDs via SLUG_TO_CANONICAL
- Appends translated rows to balcao.csv as juros/amortizacao operations
- Removes migrated rows from proventos.csv
- Adds assets.csv entries for any new product_ids that don't exist yet
- Writes a log of every moved row to migrations/logs/

Idempotent: re-runs are safe — second run finds 0 RF rows in proventos.csv and exits.

Run:
    python 2026-05-01-migrate-rf-juros.py --dry-run   # preview
    python 2026-05-01-migrate-rf-juros.py             # apply
"""

import argparse
import csv
from datetime import datetime
from pathlib import Path


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return parent
    raise RuntimeError(f"Vault root not found from {__file__}")


VAULT = _find_vault_root()
LEDGER_DIR = VAULT / 'tools' / 'finance' / 'ledgers' / 'investimentos'
PROVENTOS = LEDGER_DIR / 'proventos.csv'
BALCAO = LEDGER_DIR / 'balcao.csv'
ASSETS = VAULT / '.user' / 'workflows' / 'accountant' / 'data' / 'assets.csv'
LOG_DIR = Path(__file__).parent / 'logs'


# B3 auto-extracted slug → canonical balcão product_id.
# Mirrors the name_map.csv b3,produto,... entries but keyed by post-extract slug
# (since proventos.csv stores the slug, not the original B3 produto string).
SLUG_TO_CANONICAL = {
    'deb_neoe26': 'deb_neoenergia_370',
    'deb_peja23': 'deb_petro_rio_jaguar_petroleo_740',
    'deb_rdorb3': 'deb_cdi_rede_d_or_sao_luiz_120',
    'deb_taeb15': 'deb_acucar_guarani_615',
}


# RF tickers without a balcão match — generate assets.csv entries with these names.
# Issuer info from B3 movimentação extract.
NEW_ASSET_NAMES = {
    'cra_cra01600021': ('CRA Vert Companhia Securitizadora (CRA01600021)', 'cra'),
    'cra_cra0190020f': ('CRA Eco Securitizadora (CRA0190020F)', 'cra'),
    'cra_cra019003jy': ('CRA Vert Companhia Securitizadora (CRA019003JY)', 'cra'),
    'cra_cra024002ml': ('CRA Eco Securitizadora (CRA024002ML)', 'cra'),
    'cra_cra02400ahy': ('CRA Virgo Companhia de Securitização (CRA02400AHY)', 'cra'),
    'tesouro_ipca_com_juros_semestrais_2032': ('Tesouro IPCA+ com Juros Semestrais 2032', 'tesouro'),
}


RF_PREFIX_TO_TYPE = (
    ('deb_', 'deb'),
    ('cra_', 'cra'),
    ('cri_', 'cri'),
    ('lca_', 'lca'),
    ('lci_', 'lci'),
    ('lc_', 'lc'),
    ('cdb_', 'cdb'),
    ('tesouro_', 'tesouro'),
)


def is_rf_ticker(ticker: str) -> bool:
    return any(ticker.startswith(p) for p, _ in RF_PREFIX_TO_TYPE)


def infer_type(ticker: str) -> str:
    for prefix, code in RF_PREFIX_TO_TYPE:
        if ticker.startswith(prefix):
            return code
    return 'rf'


def load_csv(path: Path) -> tuple[list[dict], list[str]]:
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    return rows, fields


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='Preview without writing')
    args = ap.parse_args()

    prov_rows, prov_fields = load_csv(PROVENTOS)
    balc_rows, balc_fields = load_csv(BALCAO)
    asset_rows, asset_fields = load_csv(ASSETS)
    existing_asset_ids = {r['id'] for r in asset_rows}

    # Partition proventos
    move_rows: list[dict] = []
    keep_rows: list[dict] = []
    for r in prov_rows:
        ticker = r.get('ticker', '')
        ptype = r.get('type', '')
        if is_rf_ticker(ticker) and ptype in ('juros', 'amortizacao'):
            move_rows.append(r)
        else:
            keep_rows.append(r)

    if not move_rows:
        print('No RF rows in proventos.csv. Nothing to migrate.')
        return

    # Build new balcão rows + collect needed asset ids
    new_balcao: list[dict] = []
    new_asset_ids: set[str] = set()
    slug_translations: dict[str, str] = {}

    for r in move_rows:
        old_id = r['ticker']
        canonical = SLUG_TO_CANONICAL.get(old_id, old_id)
        slug_translations[old_id] = canonical
        product_type = infer_type(canonical)
        operation = 'juros' if r['type'] == 'juros' else 'amortizacao'

        new_balcao.append({
            'date': r['date'],
            'operation': operation,
            'product_id': canonical,
            'product_type': product_type,
            'quantity': r.get('quantity', '0'),
            'amount': str(round(float(r.get('net_value', 0) or 0), 2)),
            'irrf': r.get('irrf', '0') or '0',
            'iof': '0',
            'broker': r.get('broker', ''),
            'source': r.get('source', 'b3'),
        })

        if canonical not in existing_asset_ids:
            new_asset_ids.add(canonical)

    # Build new assets.csv rows
    new_assets: list[dict] = []
    for aid in sorted(new_asset_ids):
        if aid in NEW_ASSET_NAMES:
            name, ptype = NEW_ASSET_NAMES[aid]
        else:
            name = aid.replace('_', ' ').title()
            ptype = infer_type(aid)
        # Build with all fields (defaulting empty)
        row = {field: '' for field in asset_fields}
        row.update({
            'id': aid,
            'asset_class': 'fixed_income',
            'name': name,
            'type': ptype,
            'currency': 'BRL',
            'current_broker': 'safra',
            'active': 'false',
        })
        new_assets.append(row)

    # Report
    print(f'Migration plan:')
    print(f'  proventos.csv: {len(prov_rows)} rows → keep {len(keep_rows)}, move {len(move_rows)}')
    print(f'  balcao.csv:    {len(balc_rows)} rows → {len(balc_rows) + len(new_balcao)} after merge')
    print(f'  assets.csv:    {len(new_assets)} new RF entries to add')
    print()
    print(f'Slug translations ({len(slug_translations)} unique):')
    for old in sorted(slug_translations):
        new = slug_translations[old]
        tag = '(name_map → canonical)' if old != new else '(unchanged, new asset)'
        print(f'  {old:50s} → {new:50s} {tag}')

    if new_assets:
        print()
        print(f'New assets.csv entries:')
        for a in new_assets:
            print(f'  {a["id"]:50s} {a["name"]}')

    if args.dry_run:
        print('\n[DRY RUN] No files written.')
        return

    # Write log
    LOG_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path = LOG_DIR / f'rf_juros_migration_{timestamp}.csv'
    with open(log_path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['canonical_id'] + prov_fields)
        w.writeheader()
        for r in move_rows:
            row = {'canonical_id': slug_translations[r['ticker']]}
            row.update(r)
            w.writerow(row)
    print(f'\nLog written: {log_path}')

    # Update proventos.csv (sorted by date for stable diff)
    keep_rows.sort(key=lambda r: r.get('date', ''))
    write_csv(PROVENTOS, keep_rows, prov_fields)
    print(f'Updated: {PROVENTOS} ({len(keep_rows)} rows)')

    # Update balcao.csv (append + re-sort by date)
    all_balcao = balc_rows + new_balcao
    all_balcao.sort(key=lambda r: r.get('date', ''))
    write_csv(BALCAO, all_balcao, balc_fields)
    print(f'Updated: {BALCAO} ({len(all_balcao)} rows)')

    # Update assets.csv (append new entries)
    if new_assets:
        all_assets = asset_rows + new_assets
        write_csv(ASSETS, all_assets, asset_fields)
        print(f'Updated: {ASSETS} (+{len(new_assets)} new entries)')


if __name__ == '__main__':
    main()
