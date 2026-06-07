"""restamp_supplier_canonical — bulk supplier_canonical re-stamp on closed months.

CLASS: write / retro-rewrite
OWNER: migrations/restamp_supplier_canonical.py

Rewrites the `supplier_canonical` column — and ONLY that column — on every
row of ledgers/fechamento/{month}/transactions.csv whose value exactly equals
`--from VALUE`, setting it to `--to VALUE`. Built for casing-duplicate
canonical merges (e.g. 'Mercado livre' vs 'Mercado Livre') where a config-side
rename (`rename_canonical`) or a standing-rule change fixes future closes but
leaves already-stamped derived rows split across two spend buckets.

Why this is NOT an append-only violation: fechamento transactions.csv is a
DERIVED output (categorize.py regenerates it from raw ledgers + config +
corrections). This tool brings the derived rows current with what categorize.py
would stamp TODAY — it refuses any `--to` value that the live
name-canonicalization pipeline would not itself produce, so a later
regeneration converges to the same value. The durable record of the rename
lives in config (suppliers.json, standing-rules.yaml exceptions) and in
corrections/vendor-canonicals.csv (written by rename_canonical), not here.

Safety rails:
  * DRY-RUN is the DEFAULT — per-month row-count preview; `--apply` to execute.
  * `--to` MUST equal the live canonical form: a supplier in suppliers.json
    must resolve (canonical -> apply_name_canonicalization) to exactly the
    `--to` string. Otherwise the operation is REFUSED (would diverge on the
    next regeneration).
  * Touches ONLY the supplier_canonical column. data_caixa (and every other
    column) is preserved byte-for-byte at the field level.
  * Timestamped .bak backup of every written file + rollback manifest;
    `--rollback TOKEN` restores.
  * One `ledger_write` audit event per written transactions.csv (fail-soft).

Usage
-----
  # Dry-run (default): per-month counts, nothing written
  python restamp_supplier_canonical.py --from "Mercado livre" --to "Mercado Livre"

  # Scope to specific months
  python restamp_supplier_canonical.py --from "Iof" --to "IOF" \\
      --months 2026-04,2026-05,2026-06

  # Execute
  python restamp_supplier_canonical.py --from "Iof" --to "IOF" --apply

  # Undo
  python restamp_supplier_canonical.py --rollback 20260607T120000
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

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

from _retro_rewrite_common import (  # noqa: E402
    ImpactReport,
    backup_path_for,
    _backup_token,  # type: ignore[attr-defined]
    config_dir,
    corrections_dir,
    ledger_fechamento_dir,
    load_json,
    print_impact_report,
    rollback as _rollback,
    write_manifest,
)

TOOL_NAME = "restamp_supplier_canonical"
COLUMN = "supplier_canonical"


# ---------------------------------------------------------------------------
# Live-canonical validation
# ---------------------------------------------------------------------------

def live_canonical_forms() -> set[str]:
    """The set of supplier_canonical values categorize.py would stamp today:
    every suppliers.json canonical passed through the live
    name-canonicalization standing rule."""
    from lib.standing_rules import (  # noqa: E402 — lazy: needs config on path
        apply_name_canonicalization,
        load_name_canonicalization,
        load_standing_rules,
    )

    suppliers = load_json(config_dir() / "suppliers.json").get("suppliers", {})
    rules = load_standing_rules(config_dir())
    cfg = load_name_canonicalization(rules)
    return {
        apply_name_canonicalization(v.get("canonical", ""), cfg)
        for v in suppliers.values()
        if v.get("canonical")
    }


# ---------------------------------------------------------------------------
# Impact analysis
# ---------------------------------------------------------------------------

def analyse_impact(
    *,
    from_value: str,
    to_value: str,
    months: list[str] | None,
) -> ImpactReport:
    """Build the fix-impact preview without touching any file."""
    operation = f"re-stamp {COLUMN} '{from_value}' -> '{to_value}'" + (
        f"  (months: {', '.join(months)})" if months else "  (all fechamento months)"
    )
    report = ImpactReport(tool=TOOL_NAME, operation=operation)

    if from_value == to_value:
        report.errors.append("--from and --to are identical; nothing to re-stamp.")
        return report

    try:
        live = live_canonical_forms()
    except Exception as e:
        report.errors.append(f"Could not resolve live canonical forms: {e}")
        return report

    if to_value not in live:
        report.errors.append(
            f"--to '{to_value}' is NOT a value the live pipeline would stamp "
            "(no suppliers.json canonical resolves to it through the "
            "name-canonicalization standing rule). A re-stamp to this value "
            "would diverge on the next regeneration. Fix config first "
            "(rename_canonical / standing-rules.yaml exceptions)."
        )
        return report
    if from_value in live:
        report.warnings.append(
            f"--from '{from_value}' is ALSO a live canonical form — the pipeline "
            "still stamps it for some supplier. Re-stamped rows may reappear on "
            "future closes. Confirm this is intended."
        )

    base = ledger_fechamento_dir()
    if not base.exists():
        report.errors.append(f"Fechamento ledger dir not found: {base}")
        return report

    month_dirs = sorted(d for d in base.iterdir() if d.is_dir())
    if months:
        wanted = set(months)
        missing = wanted - {d.name for d in month_dirs}
        if missing:
            report.errors.append(
                f"Month(s) not found in fechamento: {', '.join(sorted(missing))}"
            )
            return report
        month_dirs = [d for d in month_dirs if d.name in wanted]

    total_rows = 0
    for month_dir in month_dirs:
        txpath = month_dir / "transactions.csv"
        if not txpath.exists():
            continue
        with open(txpath, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = list(reader.fieldnames or [])
            rows = list(reader)
        if COLUMN not in header:
            report.warnings.append(
                f"{month_dir.name}: no '{COLUMN}' column — skipped."
            )
            continue
        n = sum(1 for r in rows if r.get(COLUMN, "") == from_value)
        if n == 0:
            continue
        total_rows += n

        def _writer_for(
            _txpath=txpath, _header=header, _rows=rows, _month=month_dir.name
        ):
            def _write() -> None:
                new_rows = [
                    {**r, COLUMN: to_value} if r.get(COLUMN, "") == from_value else r
                    for r in _rows
                ]

                def _w(f) -> None:
                    writer = csv.DictWriter(
                        f,
                        fieldnames=_header,
                        extrasaction="ignore",
                        lineterminator="\r\n",
                    )
                    writer.writeheader()
                    writer.writerows(new_rows)

                atomic_write(_txpath, _w, encoding="utf-8", newline="")

                if _audit is not None:
                    try:
                        _audit.emit(
                            "ledger_write",
                            source_function=f"{TOOL_NAME}._write",
                            destination=_txpath,
                            action="overwrite",
                            materiality="high",
                            summary={
                                "tool": TOOL_NAME,
                                "month": _month,
                                "column": COLUMN,
                                "from": from_value,
                                "to": to_value,
                                "rows_restamped": sum(
                                    1 for r in _rows if r.get(COLUMN, "") == from_value
                                ),
                            },
                        )
                    except Exception:  # pragma: no cover
                        pass

            return _write

        report.add(
            kind="output-rows",
            location=str(txpath),
            detail=f"{n} row(s) with {COLUMN}=='{from_value}' -> '{to_value}'",
            writable=True,
            writer=_writer_for(),
            materiality="high",
        )

    if total_rows == 0 and not report.errors:
        report.warnings.append(
            f"No rows carry {COLUMN}=='{from_value}' in the scoped months — NO-OP."
        )
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=(
            "Bulk re-stamp supplier_canonical on closed fechamento months. "
            "DRY-RUN by default; pass --apply to execute."
        ),
    )
    p.add_argument("--from", dest="from_value", help="Exact current value to replace")
    p.add_argument("--to", dest="to_value", help="Target canonical value")
    p.add_argument(
        "--months",
        help="Comma-separated month scope (e.g. 2026-04,2026-05). Omit for all.",
    )
    p.add_argument("--apply", action="store_true",
                   help="Execute the writes. Omit for DRY-RUN (default).")
    p.add_argument("--rollback", metavar="TOKEN",
                   help="Restore from a prior run's backups; ignores other args.")
    return p.parse_args(argv)


def _do_rollback(token: str) -> int:
    manifest_path = corrections_dir() / ".rollback" / f"{TOOL_NAME}-{token}.json"
    if not manifest_path.exists():
        print(f"ERROR: rollback manifest not found: {manifest_path}", file=sys.stderr)
        return 1
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    for action in _rollback(manifest):
        print(f"  {action}")
    print("Rollback complete.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.rollback:
        return _do_rollback(args.rollback)

    if not args.from_value or not args.to_value:
        print("ERROR: --from and --to are required (or --rollback TOKEN).",
              file=sys.stderr)
        return 2

    months = [m.strip() for m in args.months.split(",")] if args.months else None
    report = analyse_impact(
        from_value=args.from_value, to_value=args.to_value, months=months
    )
    print_impact_report(report, applying=args.apply)

    if report.errors:
        return 1

    if args.apply and report.writable_impacts():
        import shutil

        token = _backup_token()  # microsecond resolution (shared helper)
        backups: list[dict] = []
        for imp in report.writable_impacts():
            target = Path(imp.location)
            backup = backup_path_for(target, token)
            shutil.copy2(target, backup)
            backups.append({
                "target": str(target),
                "backup": str(backup),
                "existed_before": True,
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
        print(f"\nAPPLIED. Rollback token: {token}")
        print(f"  Undo with: python {TOOL_NAME}.py --rollback {token}")
        print(f"  Manifest:  {manifest_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
