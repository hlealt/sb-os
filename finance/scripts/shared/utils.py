"""Shared utilities for date/decimal normalization and CSV I/O."""

import csv
import re
from datetime import date, datetime
from pathlib import Path

# Portuguese month abbreviations (used by Nubank, etc.)
PT_MONTHS = {
    "JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12,
}

NORMALIZED_COLUMNS = [
    "date", "description", "amount", "balance", "bank", "source_type",
    "currency", "original_ref", "installment_current", "installment_total",
    "original_amount", "exchange_rate",
]


def parse_date(date_str: str) -> date:
    """Parse date from various Brazilian bank formats to date object.

    Supported formats:
    - DD/MM/YYYY (Bradesco, Santander)
    - DD-MM-YYYY (XP, Wise)
    - DD MMM (Nubank — requires infer_year)
    """
    date_str = date_str.strip()

    # DD/MM/YYYY
    if "/" in date_str:
        return datetime.strptime(date_str, "%d/%m/%Y").date()

    # DD-MM-YYYY
    if "-" in date_str and len(date_str) == 10:
        return datetime.strptime(date_str, "%d-%m-%Y").date()

    # DD MMM (short month, Portuguese)
    match = re.match(r"(\d{1,2})\s+([A-Z]{3})", date_str.upper())
    if match:
        day = int(match.group(1))
        month = PT_MONTHS.get(match.group(2))
        if month:
            # Year will be set by caller via infer_year
            return date(2000, month, day)

    raise ValueError(f"Unrecognized date format: {date_str}")


def infer_year(d: date, reference_year: int) -> date:
    """Replace placeholder year (2000) with the actual year."""
    if d.year == 2000:
        return d.replace(year=reference_year)
    return d


def parse_ptbr_decimal(value_str: str) -> float:
    """Parse Brazilian decimal format: 1.234,56 -> 1234.56"""
    if not value_str or not value_str.strip():
        return 0.0
    cleaned = value_str.strip().replace("R$", "").replace(" ", "")
    if not cleaned or cleaned == "-":
        return 0.0
    # Handle negative with various formats
    negative = cleaned.startswith("-") or cleaned.startswith("−")
    cleaned = cleaned.lstrip("-−")
    # Remove thousands separator (period), replace decimal separator (comma)
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        result = float(cleaned)
        return -result if negative else result
    except ValueError:
        return 0.0


def parse_intl_decimal(value_str: str) -> float:
    """Parse international decimal format: 1234.56 -> 1234.56"""
    if not value_str or not value_str.strip():
        return 0.0
    cleaned = value_str.strip().replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


# Installment patterns found in Brazilian bank statements
INSTALLMENT_PATTERNS = [
    re.compile(r"(\d{1,2})/(\d{1,2})"),           # 3/7, 11/12
    re.compile(r"(\d{1,2})\s*de\s*(\d{1,2})"),     # 3 de 7
    re.compile(r"parcela\s*(\d{1,2})/(\d{1,2})", re.IGNORECASE),  # Parcela 3/7
    re.compile(r"parc\s*(\d{1,2})/(\d{1,2})", re.IGNORECASE),     # Parc 3/7
]


def parse_installment(description: str) -> tuple:
    """Extract installment info from description.

    Returns (current, total) or (None, None) if no installment found.
    """
    for pattern in INSTALLMENT_PATTERNS:
        match = pattern.search(description)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            # Sanity check: installments are typically 2-36
            if 1 <= current <= total <= 48 and total >= 2:
                return current, total
    return None, None


def write_normalized_csv(rows: list[dict], output_path: Path) -> int:
    """Write normalized transactions to CSV. Returns number of rows written."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=NORMALIZED_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in NORMALIZED_COLUMNS})
    return len(rows)


def read_normalized_csv(input_path: Path) -> list[dict]:
    """Read normalized CSV back into list of dicts."""
    rows = []
    with open(input_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def derive_password(cpf: str, rule: str) -> str:
    """Derive bank password from CPF based on rule."""
    digits = re.sub(r"\D", "", cpf)
    if rule == "cpf_first_5":
        return digits[:5]
    elif rule == "cpf_full":
        return digits
    else:
        raise ValueError(f"Unknown password rule: {rule}")
