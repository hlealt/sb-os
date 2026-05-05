#!/usr/bin/env python3
"""Normalize bank statements and credit card invoices into standardized CSVs.

Usage:
    python normalize.py <raw_dir> <processed_dir> <config_folder>

    raw_dir:       Raw bank exports for the month (e.g., 3-resources/tools/finance/raw/2026-04/expenses)
    processed_dir: Where to write normalized CSVs (e.g., 3-resources/tools/finance/ledgers/expenses/2026-04)
    config_folder: Path to accountant config (e.g., .user/workflows/accountant/config)

Reads banks.json and passwords.json from config_folder.
For each bank, finds matching files in raw_dir, parses them,
and writes normalized CSVs to processed_dir.

For fatura inputs, additionally writes processed_dir/fatura_totals.json
with one entry per fatura (bank_id -> {bank_name, file, total, payment_date}).
The `payment_date` field is the binding contract between this script and
categorize.py for computing `data_caixa` on CC rows per data-model.md §9
(Option B — surface invoice payment date via fatura_totals.json).
"""

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

# Add parent dir to path so parsers can import utils
sys.path.insert(0, str(Path(__file__).parent))

from utils import derive_password, write_normalized_csv
from parsers import get_parser


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def match_file_to_bank(filepath: Path, bank: dict) -> bool:
    """Check if a file matches a bank's identification rules."""
    filename = filepath.name
    ident = bank.get("identification", {})

    # Exact filename match
    if "filename_exact" in ident:
        return filename == ident["filename_exact"]

    # Filename starts with
    if "filename_startswith" in ident:
        if not filename.startswith(ident["filename_startswith"]):
            return False
        return True

    # Filename contains
    if "filename_contains" in ident:
        return ident["filename_contains"] in filename

    # Content header match (for CSVs — check first 5 lines for header)
    if "content_header" in ident:
        for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
            try:
                with open(filepath, "r", encoding=enc) as f:
                    for _ in range(5):
                        line = f.readline()
                        if ident["content_header"] in line:
                            return True
            except (UnicodeDecodeError, PermissionError):
                continue
        return False

    return False


def scan_folder(data_folder: Path, banks: list[dict]) -> dict:
    """Scan data folder and match files to banks.

    Returns dict: bank_id -> list of matched file paths.
    """
    matches = {}
    matched_files = set()

    for bank in banks:
        bank_id = bank["id"]
        matches[bank_id] = []

        # Check for subfolder-specific banks (e.g., Wise in wise/)
        subfolder = bank.get("identification", {}).get("subfolder")
        if subfolder:
            search_dir = data_folder / subfolder
        else:
            search_dir = data_folder

        if not search_dir.exists():
            continue

        for filepath in search_dir.iterdir():
            if filepath.is_dir() or filepath.suffix == "":
                continue
            if filepath in matched_files:
                continue
            if match_file_to_bank(filepath, bank):
                matches[bank_id].append(filepath)
                matched_files.add(filepath)

    # Find unmatched files
    unmatched = []
    for filepath in data_folder.iterdir():
        if filepath.is_dir():
            continue
        if filepath in matched_files:
            continue
        if filepath.suffix.lower() in (".csv", ".pdf", ".xlsx"):
            unmatched.append(filepath)

    return matches, unmatched


def infer_date_range(folder_name: str) -> tuple[date, date] | None:
    """Infer valid date range from month folder name (e.g., '2026-03').

    Returns (min_date, max_date) with tolerance:
    - min: 5 days before month start (edge transactions)
    - max: 5 days after month end (edge transactions)

    Future installments (months ahead) get filtered out.
    """
    match = re.match(r"(\d{4})-(\d{2})", folder_name)
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2))
    month_start = date(year, month, 1)
    # Next month's start
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    month_end = next_month - timedelta(days=1)

    return (month_start - timedelta(days=5), month_end + timedelta(days=5))


def derive_payment_date_from_folder(folder_name: str) -> date | None:
    """Derive invoice payment date from month folder name per data-model §9.2.

    Convention: a fatura under `YYYY-MM/raw/` is paid on day 10 of the
    FOLLOWING month (the user's habitual invoice-due day, R3 finding).

    E.g., `2026-03` → 2026-04-10. Returns None if folder_name does not
    match the YYYY-MM pattern.
    """
    match = re.match(r"(\d{4})-(\d{2})", folder_name)
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2))
    if month == 12:
        return date(year + 1, 1, 10)
    return date(year, month + 1, 10)


def resolve_payment_date(parser, filepath: Path, password: str | None,
                         folder_payment_date: date | None) -> date | None:
    """Resolve invoice payment date for a fatura file per data-model §9.2.

    Resolution order (first hit wins):
      1. Parser-supplied via `extract_payment_date(filepath, password)` —
         BaseParser default returns None; per-parser overrides are optional.
      2. Folder-name convention — day 10 of the month following the folder's
         YYYY-MM name (the user's habitual invoice-due day).
    """
    # Step 1: parser-supplied override (optional method on subclasses).
    extractor = getattr(parser, "extract_payment_date", None)
    if callable(extractor):
        try:
            parser_date = extractor(filepath, password=password)
        except Exception:
            parser_date = None
        if isinstance(parser_date, date):
            return parser_date

    # Step 2: folder convention.
    return folder_payment_date


def filter_by_date(rows: list[dict], date_range: tuple[date, date], bank_id: str,
                   source_type: str = "") -> tuple[list[dict], int]:
    """Filter transactions outside the expected date range.

    For faturas: uses ±5 day tolerance (billing cycles don't align with months).
    For extratos: uses strict month boundaries (dates are exact).

    Returns (filtered_rows, num_removed).
    """
    min_date, max_date = date_range

    if source_type == "extrato":
        # Strict: only transactions within the calendar month
        min_date = min_date + timedelta(days=5)   # undo the -5 tolerance
        max_date = max_date - timedelta(days=5)   # undo the +5 tolerance

    kept = []
    removed = 0
    for row in rows:
        try:
            tx_date = date.fromisoformat(row.get("date", ""))
            if min_date <= tx_date <= max_date:
                kept.append(row)
            else:
                removed += 1
        except (ValueError, TypeError):
            kept.append(row)  # keep rows with unparseable dates
    return kept, removed


def main():
    if len(sys.argv) < 4:
        print("Usage: python normalize.py <raw_dir> <processed_dir> <config_folder>")
        print("  raw_dir:       Path to raw bank exports for the month (e.g., 3-resources/tools/finance/raw/2026-04/expenses)")
        print("  processed_dir: Path to write normalized CSVs (e.g., 3-resources/tools/finance/ledgers/expenses/2026-04)")
        print("  config_folder: Path to config (e.g., .user/workflows/accountant/config)")
        sys.exit(1)

    raw_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    config_folder = Path(sys.argv[3])

    if not raw_dir.exists():
        print(f"ERROR: Raw folder not found: {raw_dir}")
        sys.exit(1)

    # Load config
    banks_config = load_json(config_folder / "banks.json")
    passwords_config = load_json(config_folder / "passwords.json")
    banks = banks_config["banks"]
    cpf = passwords_config.get("cpf", "")

    # Infer date range from month name (parent of raw_dir, i.e., raw/{YYYY-MM}/expenses → {YYYY-MM})
    month_name = raw_dir.parent.name
    date_range = infer_date_range(month_name)
    folder_payment_date = derive_payment_date_from_folder(month_name)

    matches, unmatched = scan_folder(raw_dir, banks)

    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("NORMALIZE — Bank Statement Parser")
    print("=" * 60)
    print(f"Raw folder: {raw_dir}")
    print(f"Processed folder: {output_dir}")
    print(f"Config: {config_folder}")
    if folder_payment_date:
        print(f"Folder-derived fatura payment date: {folder_payment_date.isoformat()}")
    print()

    # Report matches
    total_transactions = 0
    errors = []
    fatura_totals = {}  # bank_id → {bank_name, total, file, payment_date}

    for bank in banks:
        bank_id = bank["id"]
        files = matches.get(bank_id, [])

        if not files:
            print(f"  [ ] {bank['name']} — no file found")
            continue

        for filepath in files:
            print(f"  [*] {bank['name']} — {filepath.name}")

            try:
                parser_id = bank.get("parser", bank_id)
                parser = get_parser(parser_id)

                # Derive password if needed
                password = None
                if bank.get("password_required") and cpf:
                    rule = bank.get("password_rule", "")
                    password = derive_password(cpf, rule)

                # Parse
                rows = parser.parse(filepath, password=password)

                # Override bank field if parser id differs from config id
                if parser_id != bank_id:
                    for row in rows:
                        row["bank"] = bank_id

                if not rows:
                    print(f"      WARNING: No transactions extracted")
                    continue

                # Filter transactions outside month range
                if date_range:
                    rows, removed = filter_by_date(
                        rows, date_range, bank_id,
                        source_type=bank.get("type", ""),
                    )
                    if removed:
                        print(f"      Filtered {removed} transactions outside date range")

                # Write normalized CSV
                output_file = output_dir / f"{bank_id}.csv"
                # For Wise with multiple files, append currency to filename
                if bank_id == "wise_extrato" and len(files) > 1:
                    currency = re.search(r"_([A-Z]{3})_", filepath.name)
                    suffix = f"_{currency.group(1)}" if currency else f"_{filepath.stem[-3:]}"
                    output_file = output_dir / f"{bank_id}{suffix}.csv"

                count = write_normalized_csv(rows, output_file)
                total_transactions += count
                print(f"      {count} transactions -> {output_file.name}")

                # Extract fatura total + payment date for credit card invoices
                if bank.get("type") == "fatura":
                    payment_date = resolve_payment_date(
                        parser, filepath, password, folder_payment_date,
                    )
                    entry = {
                        "bank_name": bank["name"],
                        "file": filepath.name,
                    }
                    try:
                        total = parser.extract_total(filepath, password=password)
                        if total is not None:
                            entry["total"] = total
                            print(f"      Fatura total: R$ {total:,.2f}")
                    except Exception:
                        pass  # Non-critical — agent can fall back to summing
                    if payment_date is not None:
                        entry["payment_date"] = payment_date.isoformat()
                        print(f"      Fatura payment_date: {entry['payment_date']}")
                    else:
                        print(f"      WARNING: could not resolve payment_date for {bank_id}")
                    fatura_totals[bank_id] = entry

            except Exception as e:
                error_msg = f"ERROR parsing {filepath.name}: {e}"
                print(f"      {error_msg}")
                errors.append(error_msg)

    # Report unmatched files
    if unmatched:
        print()
        print("  UNMATCHED FILES:")
        for f in unmatched:
            print(f"    ? {f.name}")

    # Write fatura totals
    if fatura_totals:
        totals_file = output_dir / "fatura_totals.json"
        with open(totals_file, "w", encoding="utf-8") as f:
            json.dump(fatura_totals, f, indent=2, ensure_ascii=False)

    print()
    print("-" * 60)
    print(f"Total: {total_transactions} transactions normalized")
    if fatura_totals:
        print(f"Fatura totals extracted: {len(fatura_totals)}")
        for bid, info in fatura_totals.items():
            total_str = f"R$ {info['total']:,.2f}" if "total" in info else "(total n/a)"
            pd_str = info.get("payment_date", "(no payment_date)")
            print(f"  {info['bank_name']}: {total_str}  paid {pd_str}")
    if errors:
        print(f"Errors: {len(errors)}")
        for e in errors:
            print(f"  - {e}")
    print("=" * 60)


if __name__ == "__main__":
    main()
