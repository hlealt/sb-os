"""Dedup engine for updating investment ledgers from normalized parser output.

Usage:
    python update_ledgers.py <processed_dir> [--tolerance N] [--update-fees]

Reads all CSVs in <processed_dir>, matches them to ledger files by filename
prefix, and inserts new rows while deduplicating against existing data.
"""

import argparse
import csv
import sys
from pathlib import Path


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return parent
    raise RuntimeError(f"Vault root not found from {__file__}")


VAULT_ROOT = _find_vault_root()

# Ensure scripts/ is on path for utils import
sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    ORDERS_COLUMNS, PROVENTOS_COLUMNS, BALCAO_COLUMNS,
    CRYPTO_COLUMNS, CORPORATE_ACTIONS_COLUMNS, AVENUE_FX_COLUMNS,
)

LEDGER_DIR = VAULT_ROOT / "3-resources" / "tools" / "finance" / "ledgers" / "investimentos"

# Map: normalized CSV prefix → (target ledger filename, column list)
PREFIX_TO_LEDGER = {
    'orders':   ('orders.csv', ORDERS_COLUMNS),
    'proventos': ('proventos.csv', PROVENTOS_COLUMNS),
    'balcao':   ('balcao.csv', BALCAO_COLUMNS),
    'crypto':   ('crypto.csv', CRYPTO_COLUMNS),
    'corporate': ('corporate_actions.csv', CORPORATE_ACTIONS_COLUMNS),
    'avenue_fx': ('avenue_fx.csv', AVENUE_FX_COLUMNS),
}

# Match fields per ledger: (exact_fields, numeric_fields)
MATCH_FIELDS = {
    'orders.csv': (
        ['date', 'side', 'ticker', 'currency', 'broker'],
        ['quantity', 'price'],
    ),
    'proventos.csv': (
        ['date', 'type', 'ticker', 'currency', 'broker'],
        ['quantity', 'gross_value'],
    ),
    'balcao.csv': (
        ['date', 'operation', 'product_id', 'broker'],
        ['amount'],
    ),
    'crypto.csv': (
        ['date', 'operation', 'buy_asset', 'sell_asset', 'exchange'],
        ['buy_quantity', 'sell_quantity'],
    ),
    'corporate_actions.csv': (
        ['date', 'action_type', 'ticker', 'new_ticker', 'broker'],
        [],
    ),
    'avenue_fx.csv': (
        ['date', 'operation'],
        ['brl_amount', 'usd_amount', 'fx_rate'],
    ),
}


def resolve_ledger(filename: str) -> tuple[str, list[str]] | None:
    """Map a normalized CSV filename to its target ledger and columns.

    Filename convention: {source}_{ledger_suffix}.csv
    e.g. b3_orders.csv → orders.csv, safra_balcao.csv → balcao.csv
    """
    stem = Path(filename).stem  # e.g. "b3_orders"
    for prefix, (ledger_name, columns) in PREFIX_TO_LEDGER.items():
        if stem.endswith(f'_{prefix}') or stem == prefix:
            return ledger_name, columns
    return None


def read_csv(filepath: Path) -> list[dict]:
    """Read CSV file, return list of dicts."""
    if not filepath.exists():
        return []
    with open(filepath, 'r', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def write_csv(filepath: Path, rows: list[dict], columns: list[str]):
    """Write rows to CSV with enforced column order."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def values_match_numeric(val_a: str, val_b: str, tolerance_pct: float) -> bool:
    """Check if two numeric values match within tolerance."""
    try:
        a = float(val_a) if val_a else 0.0
        b = float(val_b) if val_b else 0.0
    except (ValueError, TypeError):
        return val_a == val_b

    if a == b:
        return True
    if tolerance_pct == 0:
        return False

    max_abs = max(abs(a), abs(b))
    if max_abs == 0:
        return True
    return abs(a - b) <= (tolerance_pct / 100.0) * max_abs


def compute_delta(val_a: str, val_b: str) -> str:
    """Compute delta string between two numeric values."""
    try:
        a = float(val_a) if val_a else 0.0
        b = float(val_b) if val_b else 0.0
    except (ValueError, TypeError):
        return "N/A"
    return f"{a - b:+.4f}"


def find_matches(row: dict, ledger_rows: list[dict],
                 exact_fields: list[str], numeric_fields: list[str],
                 tolerance_pct: float) -> list[tuple[int, bool]]:
    """Find matching rows in ledger for a given source row.

    Returns list of (ledger_index, is_exact) tuples.
    """
    matches = []
    for i, ledger_row in enumerate(ledger_rows):
        # Check exact fields
        exact_ok = all(
            str(row.get(f, '')).strip() == str(ledger_row.get(f, '')).strip()
            for f in exact_fields
        )
        if not exact_ok:
            continue

        # Check numeric fields
        all_numeric_ok = True
        is_exact = True
        for f in numeric_fields:
            rv = str(row.get(f, '')).strip()
            lv = str(ledger_row.get(f, '')).strip()
            if not values_match_numeric(rv, lv, tolerance_pct):
                all_numeric_ok = False
                break
            if rv != lv:
                is_exact = False

        if all_numeric_ok:
            matches.append((i, is_exact))

    return matches


def dedup_and_insert(source_rows: list[dict], ledger_rows: list[dict],
                     ledger_name: str, tolerance_pct: float,
                     update_fees: bool) -> dict:
    """Apply dedup logic and return report.

    Modifies ledger_rows in place (appends new rows).
    Returns report dict with counts and details.
    """
    exact_fields, numeric_fields = MATCH_FIELDS[ledger_name]

    report = {
        'inserted': 0,
        'skipped_exact': 0,
        'skipped_fuzzy': [],
        'forced_duplicates': [],
        'fee_updates': [],
    }

    # Group source rows by match signature for counting duplicates
    # (same exact+numeric values in source = potential legitimate duplicates)
    source_signatures: dict[tuple, list[int]] = {}
    for i, row in enumerate(source_rows):
        sig = tuple(
            str(row.get(f, '')).strip()
            for f in exact_fields
        )
        source_signatures.setdefault(sig, []).append(i)

    # Track which ledger rows have been matched (to avoid double-matching)
    ledger_matched: set[int] = set()

    # Process each unique signature group
    processed_source_indices: set[int] = set()

    for sig, source_indices in source_signatures.items():
        if not source_indices:
            continue

        # Use first row of this group to find ledger matches
        sample_row = source_rows[source_indices[0]]
        all_matches = find_matches(
            sample_row, ledger_rows, exact_fields, numeric_fields, tolerance_pct
        )

        # Filter out already-matched ledger rows
        available_matches = [
            (idx, exact) for idx, exact in all_matches
            if idx not in ledger_matched
        ]

        source_count = len(source_indices)
        ledger_count = len(available_matches)

        if ledger_count == 0:
            # No matches — insert all
            for si in source_indices:
                ledger_rows.append(source_rows[si])
                report['inserted'] += 1
                processed_source_indices.add(si)
        elif source_count > ledger_count:
            # More in source than ledger — insert the difference
            # Mark existing matches as consumed
            for idx, _ in available_matches:
                ledger_matched.add(idx)

            to_insert = source_count - ledger_count
            # Skip first ledger_count source rows (matched), insert rest
            for j, si in enumerate(source_indices):
                if j < ledger_count:
                    processed_source_indices.add(si)
                else:
                    ledger_rows.append(source_rows[si])
                    report['inserted'] += 1
                    processed_source_indices.add(si)

            report['forced_duplicates'].append({
                'date': sample_row.get('date', ''),
                'asset': sample_row.get('ticker', sample_row.get('product_id',
                         sample_row.get('buy_asset', ''))),
                'source_count': source_count,
                'ledger_count': ledger_count,
                'inserted': to_insert,
            })
        else:
            # source_count <= ledger_count — skip all
            for idx, exact in available_matches[:source_count]:
                ledger_matched.add(idx)

            for si in source_indices:
                processed_source_indices.add(si)

            # Report fuzzy matches
            for j, si in enumerate(source_indices):
                if j < len(available_matches):
                    ledger_idx, is_exact = available_matches[j]
                    if is_exact:
                        report['skipped_exact'] += 1
                        # Handle fee updates for exact matches on orders
                        if (update_fees and ledger_name == 'orders.csv'
                                and tolerance_pct == 0):
                            _update_fees(
                                source_rows[si], ledger_rows[ledger_idx], report
                            )
                    else:
                        # Fuzzy match — report deltas
                        deltas = {}
                        for f in numeric_fields:
                            rv = str(source_rows[si].get(f, ''))
                            lv = str(ledger_rows[ledger_idx].get(f, ''))
                            if rv != lv:
                                deltas[f] = {
                                    'source': rv,
                                    'ledger': lv,
                                    'delta': compute_delta(rv, lv),
                                }
                        report['skipped_fuzzy'].append({
                            'date': sample_row.get('date', ''),
                            'asset': sample_row.get('ticker',
                                     sample_row.get('product_id',
                                     sample_row.get('buy_asset', ''))),
                            'deltas': deltas,
                        })

    return report


def _update_fees(source_row: dict, ledger_row: dict, report: dict):
    """Update fee columns on an exact match (orders only)."""
    fee_fields = ['fees_exchange', 'fees_brokerage', 'fees_irrf']
    changes = {}
    for f in fee_fields:
        sv = source_row.get(f, '0')
        lv = ledger_row.get(f, '0')
        if sv != lv:
            changes[f] = {'old': lv, 'new': sv}
            ledger_row[f] = sv

    if changes:
        # Recalculate total
        qty = float(ledger_row.get('quantity', 0) or 0)
        price = float(ledger_row.get('price', 0) or 0)
        fe = float(ledger_row.get('fees_exchange', 0) or 0)
        fb = float(ledger_row.get('fees_brokerage', 0) or 0)
        fi = float(ledger_row.get('fees_irrf', 0) or 0)
        old_total = ledger_row.get('total', '')
        new_total = round(qty * price + fe + fb + fi, 2)
        ledger_row['total'] = str(new_total)
        changes['total'] = {'old': old_total, 'new': str(new_total)}

        report['fee_updates'].append({
            'date': ledger_row.get('date', ''),
            'ticker': ledger_row.get('ticker', ''),
            'changes': changes,
        })


def format_report(reports: dict[str, dict]) -> str:
    """Format all ledger reports into a human-readable summary."""
    lines = []
    for ledger_name, r in sorted(reports.items()):
        total_actions = r['inserted'] + r['skipped_exact'] + len(r['skipped_fuzzy'])
        if total_actions == 0:
            continue

        lines.append(f"\n{'='*60}")
        lines.append(f"  {ledger_name}")
        lines.append(f"{'='*60}")
        lines.append(f"  Inserted:       {r['inserted']}")
        lines.append(f"  Skipped (exact): {r['skipped_exact']}")
        lines.append(f"  Skipped (fuzzy): {len(r['skipped_fuzzy'])}")

        if r['forced_duplicates']:
            lines.append(f"\n  Forced duplicates:")
            for fd in r['forced_duplicates']:
                lines.append(
                    f"    {fd['date']} {fd['asset']}: "
                    f"source={fd['source_count']} vs ledger={fd['ledger_count']} "
                    f"→ inserted {fd['inserted']}"
                )

        if r['skipped_fuzzy']:
            lines.append(f"\n  Fuzzy matches (REVIEW):")
            for fm in r['skipped_fuzzy']:
                lines.append(f"    {fm['date']} {fm['asset']}:")
                for field, d in fm['deltas'].items():
                    lines.append(
                        f"      {field}: source={d['source']} "
                        f"ledger={d['ledger']} (Δ{d['delta']})"
                    )

        if r['fee_updates']:
            lines.append(f"\n  Fee updates:")
            for fu in r['fee_updates']:
                lines.append(f"    {fu['date']} {fu['ticker']}:")
                for field, ch in fu['changes'].items():
                    lines.append(f"      {field}: {ch['old']} → {ch['new']}")

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Update investment ledgers from normalized parser output."
    )
    parser.add_argument(
        'processed_dir',
        help="Directory containing normalized CSV files from parsers."
    )
    parser.add_argument(
        '--tolerance', type=float, default=0,
        help="Numeric tolerance percentage for fuzzy matching (default: 0)."
    )
    parser.add_argument(
        '--update-fees', action='store_true',
        help="Update fee columns on exact matches in orders.csv."
    )

    args = parser.parse_args()
    processed_dir = Path(args.processed_dir)

    if not processed_dir.exists():
        print(f"Error: directory not found: {processed_dir}")
        sys.exit(1)

    # Find all CSVs in processed directory
    csv_files = sorted(processed_dir.glob("*.csv"))
    if not csv_files:
        print(f"No CSV files found in {processed_dir}")
        sys.exit(0)

    print(f"Tolerance: {args.tolerance}%")
    print(f"Update fees: {args.update_fees}")
    print(f"Found {len(csv_files)} CSV files in {processed_dir}\n")

    all_reports: dict[str, dict] = {}

    for csv_file in csv_files:
        result = resolve_ledger(csv_file.name)
        if result is None:
            print(f"  SKIP: {csv_file.name} — unknown prefix")
            continue

        ledger_name, columns = result
        ledger_path = LEDGER_DIR / ledger_name
        print(f"  {csv_file.name} → {ledger_name}")

        source_rows = read_csv(csv_file)
        if not source_rows:
            print(f"    (empty file, skipping)")
            continue

        ledger_rows = read_csv(ledger_path)

        report = dedup_and_insert(
            source_rows, ledger_rows, ledger_name,
            args.tolerance, args.update_fees
        )

        # Merge reports by ledger (multiple source files → same ledger)
        if ledger_name not in all_reports:
            all_reports[ledger_name] = report
        else:
            existing = all_reports[ledger_name]
            existing['inserted'] += report['inserted']
            existing['skipped_exact'] += report['skipped_exact']
            existing['skipped_fuzzy'].extend(report['skipped_fuzzy'])
            existing['forced_duplicates'].extend(report['forced_duplicates'])
            existing['fee_updates'].extend(report['fee_updates'])

        # Write updated ledger
        write_csv(ledger_path, ledger_rows, columns)

    # Print summary
    print(format_report(all_reports))

    total_inserted = sum(r['inserted'] for r in all_reports.values())
    total_fuzzy = sum(len(r['skipped_fuzzy']) for r in all_reports.values())
    print(f"\n{'='*60}")
    print(f"  TOTAL: {total_inserted} inserted, {total_fuzzy} fuzzy matches to review")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
