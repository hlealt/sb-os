"""apply_review_resolution — row-level review-mode resolution for closed months.

CLASS: write / retro-rewrite
OWNER: migrations/apply_review_resolution.py

Applies a single row-level resolution on a closed fechamento month:

  1. Re-stamps mutable field(s) on the matching row of
     ledgers/fechamento/{month}/transactions.csv  (atomic write via safe_write).
  2. Optionally appends the canonical correction row to a side-ledger
     (manual-overrides.csv or competencia-overrides.csv) so categorize.py
     re-stamps the override on the next regeneration.
  3. Emits one audit event per (source, destination) via lib.audit (fail-soft).

DRY-RUN is the DEFAULT. Mutation requires an explicit --apply flag.

Row identity: tx_date | tx_description | tx_amount (composite, amount as
normalized float, tolerance < 0.005). Exactly-one-match required; 0 or >1
matches abort with a hard error before any write.

Mutable field whitelist: category, tags, recurrence, supplier_canonical,
data_competencia, manual_override.  data_caixa is NEVER mutated (immutable
raw field — hardcoded reject).

Usage
-----
  # Dry-run (default) — show the would-be diff, write nothing
  python apply_review_resolution.py \\
      --month 2026-04 \\
      --date 2026-04-07 \\
      --description "Pix enviado Henrique Leal Teixeira" \\
      --amount -78.6 \\
      --set tags=alimentacao \\
      --corrections-file manual-overrides.csv \\
      --reason "mis-tagged in review" \\
      --source review-mode-type-4

  # Execute
  python apply_review_resolution.py ... --apply
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Bootstrap: make scripts/shared/ importable (same idiom as other migrations).
# ---------------------------------------------------------------------------

_SCRIPTS = Path(__file__).resolve().parents[1]
_SHARED = _SCRIPTS / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

try:
    from lib import audit as _audit
except Exception:  # pragma: no cover — audit is best-effort
    _audit = None  # type: ignore

try:
    from lib.safe_write import atomic_write
except Exception as e:  # pragma: no cover
    raise ImportError(f"safe_write not found in {_SHARED}: {e}") from e

# Import path helpers from the shared retro-rewrite scaffolding.
from _retro_rewrite_common import (  # noqa: E402
    ImpactReport,
    bookkeeper_root,
    corrections_dir,
    ledger_fechamento_dir,
    now_iso,
    print_impact_report,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOOL_NAME = "apply_review_resolution"

MUTABLE_FIELDS = frozenset(
    {"category", "tags", "recurrence", "supplier_canonical",
     "data_competencia", "manual_override"}
)

NEVER_MUTABLE = frozenset({"data_caixa"})

# Correction-file schemas (CONVENTION.md canonical)
MANUAL_OVERRIDES_FIELDS = [
    "tx_date", "tx_description", "tx_amount",
    "override_category", "override_tags",
    "month", "added_at", "source", "note",
]

COMPETENCIA_OVERRIDES_FIELDS = [
    "tx_date", "tx_description", "tx_amount",
    "override_data_competencia", "reason",
    "month", "added_at", "source", "note",
]

# Maps a mutable field to which corrections file records it canonically.
FIELD_TO_CORRECTIONS_FILE: dict[str, str] = {
    "category": "manual-overrides.csv",
    "tags": "manual-overrides.csv",
    "manual_override": "manual-overrides.csv",
    "data_competencia": "competencia-overrides.csv",
}


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def transactions_path(month: str) -> Path:
    return ledger_fechamento_dir() / month / "transactions.csv"


def corrections_file_path(filename: str) -> Path:
    return corrections_dir() / filename


# ---------------------------------------------------------------------------
# Row matching
# ---------------------------------------------------------------------------

def _normalize_amount(s: str) -> float:
    """Parse amount string to float for comparison."""
    return float(s.strip())


def _amounts_equal(a: str, b: str | float, *, tol: float = 0.005) -> bool:
    try:
        fa = _normalize_amount(str(a))
        fb = float(b) if isinstance(b, (int, float)) else _normalize_amount(str(b))
        return abs(fa - fb) < tol
    except (ValueError, TypeError):
        return False


def find_matching_row(
    rows: list[dict],
    *,
    tx_date: str,
    description: str,
    amount: float,
) -> tuple[int, dict] | None:
    """Return (index, row) for the unique row matching the identity triple.

    Returns None when 0 matches; raises ValueError when >1 matches.
    """
    matches = [
        (i, r) for i, r in enumerate(rows)
        if r.get("date", "") == tx_date
        and r.get("description", "") == description
        and _amounts_equal(r.get("amount", ""), amount)
    ]
    if len(matches) == 0:
        return None
    if len(matches) > 1:
        raise ValueError(
            f"Ambiguous identity: {len(matches)} rows match "
            f"{tx_date} | {description} | {amount}. "
            "Supply a more specific identity or fix the ledger first."
        )
    return matches[0]


# ---------------------------------------------------------------------------
# Idempotency detection
# ---------------------------------------------------------------------------

def _is_already_applied(current_value: str, new_value: str) -> bool:
    """Return True when the row's current value already equals the target."""
    return current_value.strip() == new_value.strip()


def _is_correction_already_recorded(
    corrections_path: Path,
    tx_date: str,
    description: str,
    amount: float,
    field: str,
    new_value: str,
) -> bool:
    """Check if a matching correction row already exists in the corrections file.

    Checks the relevant override column based on the file type.
    """
    if not corrections_path.exists():
        return False
    try:
        with open(corrections_path, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if (
                    row.get("tx_date", "") == tx_date
                    and row.get("tx_description", "") == description
                    and _amounts_equal(row.get("tx_amount", ""), amount)
                ):
                    # Check the relevant override column
                    if "competencia" in corrections_path.name:
                        recorded = row.get("override_data_competencia", "")
                    else:
                        # manual-overrides: check both category and tags
                        if field in ("category", "manual_override"):
                            recorded = row.get("override_category", "")
                        elif field == "tags":
                            recorded = row.get("override_tags", "")
                        else:
                            recorded = ""
                    if recorded.strip() == new_value.strip():
                        return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Impact analysis (builds the ImpactReport before any write)
# ---------------------------------------------------------------------------

def analyse_impact(
    *,
    month: str,
    tx_date: str,
    description: str,
    amount: float,
    field_changes: dict[str, str],
    corrections_filename: str | None,
    reason: str,
    source: str,
    note: str,
) -> ImpactReport:
    """Build a full ImpactReport without touching any file."""

    operation = (
        f"re-stamp {list(field_changes.keys())} on "
        f"{tx_date} | {description} | {amount}  (month={month})"
    )
    report = ImpactReport(tool=TOOL_NAME, operation=operation)

    # 1. Validate field whitelist ----------------------------------------
    for field in field_changes:
        if field in NEVER_MUTABLE:
            report.errors.append(
                f"Field '{field}' is IMMUTABLE (data_caixa is a raw parser field; "
                "use data_competencia for accrual re-attribution)."
            )
        elif field not in MUTABLE_FIELDS:
            report.errors.append(
                f"Field '{field}' is not in the mutable-fields whitelist: "
                f"{sorted(MUTABLE_FIELDS)}."
            )

    if report.errors:
        return report  # abort early — no further analysis needed

    # 2. Load the transactions.csv ----------------------------------------
    txpath = transactions_path(month)
    if not txpath.exists():
        report.errors.append(f"Ledger not found: {txpath}")
        return report

    with open(txpath, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        rows = list(reader)

    # 3. Find matching row ------------------------------------------------
    try:
        match = find_matching_row(
            rows, tx_date=tx_date, description=description, amount=amount
        )
    except ValueError as e:
        report.errors.append(str(e))
        return report

    if match is None:
        report.errors.append(
            f"No row found matching {tx_date} | {description} | {amount} "
            f"in {txpath}."
        )
        return report

    row_idx, matched_row = match

    # 4. Per-field impact analysis ----------------------------------------
    any_real_change = False
    field_deltas: list[tuple[str, str, str]] = []  # (field, current, new)

    for field, new_value in field_changes.items():
        current = matched_row.get(field, "")
        if _is_already_applied(current, new_value):
            report.warnings.append(
                f"Field '{field}': already '{current}' — NO-OP (already applied)."
            )
        else:
            field_deltas.append((field, current, new_value))
            any_real_change = True

    if not any_real_change:
        # All fields already match — fully idempotent, no writes
        report.add(
            kind="output-rows",
            location=str(txpath),
            detail=(
                f"Row at index {row_idx} — ALL fields already match target values. "
                "No write needed (idempotent — already applied)."
            ),
            writable=False,
        )
        return report

    # Build the writer for transactions.csv (atomic overwrite)
    def _write_transactions() -> None:
        new_rows = list(rows)
        updated = dict(matched_row)
        for fld, _, new_val in field_deltas:
            updated[fld] = new_val
        new_rows[row_idx] = updated

        def _writer(f: Any) -> None:
            writer = csv.DictWriter(
                f,
                fieldnames=header,
                extrasaction="ignore",
                lineterminator="\r\n",
            )
            writer.writeheader()
            writer.writerows(new_rows)

        atomic_write(txpath, _writer, encoding="utf-8", newline="")

        # Audit: ledger_write
        if _audit is not None:
            try:
                _audit.emit(
                    "ledger_write",
                    source_function="apply_review_resolution._write_transactions",
                    destination=txpath,
                    action="overwrite",
                    materiality="high",
                    summary={
                        "tool": TOOL_NAME,
                        "month": month,
                        "row_identity": {
                            "tx_date": tx_date,
                            "tx_description": description,
                            "tx_amount": str(amount),
                        },
                        "field_changes": {
                            fld: {"from": cur, "to": nv}
                            for fld, cur, nv in field_deltas
                        },
                        "source": source,
                        "reason": reason,
                    },
                )
            except Exception:  # pragma: no cover
                pass

    delta_summary = "; ".join(
        f"{fld}: '{cur}' → '{nv}'" for fld, cur, nv in field_deltas
    )
    report.add(
        kind="output-rows",
        location=str(txpath),
        detail=(
            f"Row at index {row_idx} — {delta_summary}"
        ),
        writable=True,
        writer=_write_transactions,
        materiality="high",
    )

    # 5. Corrections side-ledger ------------------------------------------
    if corrections_filename is not None:
        corr_path = corrections_file_path(corrections_filename)
        is_competencia = "competencia" in corrections_filename

        # Build the correction row according to CONVENTION.md schema
        added_at = now_iso() + "Z"

        if is_competencia:
            new_competencia = field_changes.get("data_competencia", "")
            already_in_corr = _is_correction_already_recorded(
                corr_path, tx_date, description, amount,
                "data_competencia", new_competencia,
            )
            if already_in_corr:
                report.warnings.append(
                    f"competencia-overrides.csv: identical row already present "
                    f"(override_data_competencia={new_competencia!r}) — "
                    "append skipped (idempotent)."
                )
            else:
                corr_row = {
                    "tx_date": tx_date,
                    "tx_description": description,
                    "tx_amount": str(amount),
                    "override_data_competencia": new_competencia,
                    "reason": reason or "review_resolution",
                    "month": month,
                    "added_at": added_at,
                    "source": source,
                    "note": note,
                }
                fieldnames = COMPETENCIA_OVERRIDES_FIELDS

                def _write_competencia_corr(
                    _cp=corr_path, _fn=fieldnames, _cr=corr_row
                ) -> None:
                    _append_correction_row(_cp, _fn, _cr)
                    if _audit is not None:
                        try:
                            _audit.emit(
                                "config_write",
                                source_function=(
                                    "apply_review_resolution._write_competencia_corr"
                                ),
                                destination=_cp,
                                action="append",
                                materiality="high",
                                summary={
                                    "tool": TOOL_NAME,
                                    "corrections_file": corrections_filename,
                                    "row": _cr,
                                },
                            )
                        except Exception:  # pragma: no cover
                            pass

                report.add(
                    kind="correction-ledger",
                    location=str(corr_path),
                    detail=(
                        f"Append: override_data_competencia={new_competencia!r}, "
                        f"source={source!r}"
                    ),
                    writable=True,
                    writer=_write_competencia_corr,
                    materiality="high",
                )
        else:
            # manual-overrides.csv
            new_category = field_changes.get("category", "")
            new_tags = field_changes.get("tags", "")
            # Idempotency: check if this exact override already in file
            # Check by category if category is being set, else tags
            check_field = "category" if new_category else "tags"
            check_value = new_category if new_category else new_tags
            already_in_corr = _is_correction_already_recorded(
                corr_path, tx_date, description, amount,
                check_field, check_value,
            )
            if already_in_corr:
                report.warnings.append(
                    f"manual-overrides.csv: identical row already present — "
                    "append skipped (idempotent)."
                )
            else:
                corr_row = {
                    "tx_date": tx_date,
                    "tx_description": description,
                    "tx_amount": str(amount),
                    "override_category": new_category,
                    "override_tags": new_tags,
                    "month": month,
                    "added_at": added_at,
                    "source": source,
                    "note": note,
                }
                fieldnames = MANUAL_OVERRIDES_FIELDS

                def _write_manual_corr(
                    _cp=corr_path, _fn=fieldnames, _cr=corr_row
                ) -> None:
                    _append_correction_row(_cp, _fn, _cr)
                    if _audit is not None:
                        try:
                            _audit.emit(
                                "config_write",
                                source_function=(
                                    "apply_review_resolution._write_manual_corr"
                                ),
                                destination=_cp,
                                action="append",
                                materiality="high",
                                summary={
                                    "tool": TOOL_NAME,
                                    "corrections_file": corrections_filename,
                                    "row": _cr,
                                },
                            )
                        except Exception:  # pragma: no cover
                            pass

                report.add(
                    kind="correction-ledger",
                    location=str(corr_path),
                    detail=(
                        f"Append: override_category={new_category!r}, "
                        f"override_tags={new_tags!r}, source={source!r}"
                    ),
                    writable=True,
                    writer=_write_manual_corr,
                    materiality="high",
                )

    return report


# ---------------------------------------------------------------------------
# Append helper (local — does not use _retro_rewrite_common.append_correction_row
# because that helper writes header only on empty; this file must tolerate
# an existing file with rows and append without rewriting the header)
# ---------------------------------------------------------------------------

def _append_correction_row(
    path: Path, fieldnames: list[str], row: dict
) -> None:
    """Append one row to an append-only corrections CSV.

    Writes the CSV header only when the file is new / empty.
    NEVER rewrites existing rows.
    """
    exists = path.exists() and path.stat().st_size > 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="apply_review_resolution",
        description=(
            "Apply a row-level review resolution on a closed fechamento month. "
            "DRY-RUN by default; pass --apply to execute."
        ),
    )
    p.add_argument("--month", required=True,
                   help="Fechamento month, e.g. 2026-04")
    p.add_argument("--date", required=True, dest="tx_date",
                   help="Row identity: tx_date (YYYY-MM-DD)")
    p.add_argument("--description", required=True,
                   help="Row identity: tx_description (exact, case-sensitive)")
    p.add_argument("--amount", required=True, type=float,
                   help="Row identity: tx_amount (float)")
    p.add_argument("--set", action="append", dest="field_sets",
                   metavar="FIELD=VALUE",
                   help="Field re-stamp (repeatable). E.g. --set tags=saude")
    p.add_argument("--corrections-file", dest="corrections_filename",
                   metavar="FILENAME",
                   help=(
                       "Corrections side-ledger to append to "
                       "(e.g. manual-overrides.csv or competencia-overrides.csv). "
                       "Omit to re-stamp only, without recording a correction."
                   ))
    p.add_argument("--reason", default="",
                   help="Reason for the override (used in corrections row)")
    p.add_argument("--source", default="review-mode-manual",
                   help="Source identifier for the audit trail (default: review-mode-manual)")
    p.add_argument("--note", default="",
                   help="Human note for the corrections row")
    p.add_argument("--apply", action="store_true",
                   help="Execute the writes. Omit for DRY-RUN (default).")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # Parse --set field=value pairs
    field_changes: dict[str, str] = {}
    for item in (args.field_sets or []):
        if "=" not in item:
            print(f"ERROR: --set must be in FIELD=VALUE form, got: {item!r}",
                  file=sys.stderr)
            return 2
        fld, _, val = item.partition("=")
        field_changes[fld.strip()] = val.strip()

    if not field_changes:
        print("ERROR: at least one --set FIELD=VALUE is required.", file=sys.stderr)
        return 2

    # Build impact report
    try:
        report = analyse_impact(
            month=args.month,
            tx_date=args.tx_date,
            description=args.description,
            amount=args.amount,
            field_changes=field_changes,
            corrections_filename=args.corrections_filename,
            reason=args.reason,
            source=args.source,
            note=args.note,
        )
    except Exception as e:
        print(f"ERROR during impact analysis: {e}", file=sys.stderr)
        return 3

    applying = args.apply
    print_impact_report(report, applying=applying)

    if report.errors:
        return 1

    if applying:
        # Execute writable impacts (backup-before-write is handled individually
        # here: each writer is a closure; rollback is via the .bak files the
        # _retro_rewrite_common.apply_writes() would create — but since this
        # tool has two heterogeneous writers (atomic overwrite + append) we
        # drive them directly with inline backup for the transactions.csv).
        # Back up the transactions.csv before overwriting it.
        from _retro_rewrite_common import (  # noqa: F401
            backup_path_for,
            _backup_token,  # type: ignore[attr-defined]
            write_manifest,
        )
        import shutil

        token = _backup_token()
        backups: list[dict] = []

        for imp in report.writable_impacts():
            target = Path(imp.location)
            existed_before = target.exists()
            backup = None
            if existed_before:
                backup = backup_path_for(target, token)
                shutil.copy2(target, backup)
            backups.append({
                "target": str(target),
                "backup": str(backup) if backup else None,
                "existed_before": existed_before,
            })
            assert imp.writer is not None
            imp.writer()

        manifest = {
            "tool": TOOL_NAME,
            "operation": report.operation,
            "token": token,
            "backups": backups,
        }
        manifest_path = write_manifest(manifest, label=TOOL_NAME)
        print(f"\n  Rollback manifest written: {manifest_path}")
        print(f"  Applied {len(report.writable_impacts())} write(s).")
    else:
        # DRY-RUN: verify nothing was written (the writers are closures, never
        # called above). The ImpactReport documents WOULD-BE writes only.
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
