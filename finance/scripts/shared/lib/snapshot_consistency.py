"""Snapshot-triplet consistency gate (p3-4 / DC-1-E).

A month-close writes three stores:
  - portfolio-{date}.json   (written by calculate.py write_portfolio)
  - snapshots.json          (manifest, written by calculate._update_snapshots_manifest)
  - balance-snapshots.csv   (per-product valuations, written separately by the
                             Safra parsers via import_balance_snapshots.py)

`calculate.py` writes the first two together; the third is a separate
invocation. That separation is the seam where an interrupted close drifts:
the parser runs (balance-snapshots.csv gains rows for the close date) but
calculate.py never runs, so no matching portfolio-{date}.json / snapshots.json
entry is produced.

This gate verifies the triplet agrees for a given close date and FAILS LOUD
(non-zero exit, named missing/stale store) on drift. It NEVER auto-repairs and
NEVER ships a silently-inconsistent triplet.

Invariants checked for a close date D:
  1. portfolio-{D}.json exists           <=> snapshots.json lists D
     (the two calculate.py-written stores must agree, both directions).
  2. If balance-snapshots.csv has any row dated D, then the calculate.py pair
     (portfolio-{D}.json + snapshots.json entry) MUST exist. This catches the
     interrupted close: parser ran, calculate.py did not.

The reverse of (2) is intentionally NOT enforced: a snapshot may legitimately
be cut on a date with no same-date balance-snapshots row (Safra valuation
dates do not always coincide with the chosen close date). Enforcing it would
raise false alarms.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _default_ledger_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return (parent / ".user" / "finance" / "bookkeeper"
                    / "ledgers" / "investimentos")
    raise RuntimeError(f"Vault root not found from {__file__}")


@dataclass
class TripletResult:
    cut_date: str
    consistent: bool
    problems: list[str] = field(default_factory=list)
    portfolio_exists: bool = False
    in_manifest: bool = False
    balance_rows: int = 0

    def report(self) -> str:
        lines = [f"Snapshot-triplet consistency gate — close date {self.cut_date}"]
        status = "PASS" if self.consistent else "FAIL"
        lines.append(f"  result: {status}")
        lines.append(f"  portfolio-{self.cut_date}.json present: {self.portfolio_exists}")
        lines.append(f"  snapshots.json lists {self.cut_date}: {self.in_manifest}")
        lines.append(f"  balance-snapshots.csv rows dated {self.cut_date}: {self.balance_rows}")
        for p in self.problems:
            lines.append(f"  DRIFT: {p}")
        return "\n".join(lines)


def _load_manifest_dates(snapshots_json: Path) -> list[str]:
    """Return the list of dates in snapshots.json, handling both the flat
    date-array schema and the object-array schema (forward-compatible)."""
    if not snapshots_json.exists():
        return []
    with open(snapshots_json, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        dates = []
        for item in raw:
            if isinstance(item, str):
                dates.append(item)
            elif isinstance(item, dict) and "date" in item:
                dates.append(item["date"])
        return dates
    if isinstance(raw, dict) and isinstance(raw.get("snapshots"), list):
        return [s["date"] for s in raw["snapshots"] if isinstance(s, dict) and "date" in s]
    return []


def _count_balance_rows(balance_csv: Path, cut_date: str) -> int:
    if not balance_csv.exists():
        return 0
    count = 0
    with open(balance_csv, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("date") == cut_date:
                count += 1
    return count


def check_triplet_consistency(cut_date: str, ledger_dir: Path | None = None) -> TripletResult:
    """Check that the snapshot triplet agrees for `cut_date`.

    Returns a TripletResult. `consistent=False` with a populated `problems`
    list signals drift; the caller (gate CLI / bookkeeper loop) halts on it.
    """
    ledger_dir = Path(ledger_dir) if ledger_dir is not None else _default_ledger_dir()
    portfolio_path = ledger_dir / f"portfolio-{cut_date}.json"
    snapshots_json = ledger_dir / "snapshots.json"
    balance_csv = ledger_dir / "balance-snapshots.csv"

    portfolio_exists = portfolio_path.exists()
    in_manifest = cut_date in _load_manifest_dates(snapshots_json)
    balance_rows = _count_balance_rows(balance_csv, cut_date)

    result = TripletResult(
        cut_date=cut_date,
        consistent=True,
        portfolio_exists=portfolio_exists,
        in_manifest=in_manifest,
        balance_rows=balance_rows,
    )

    # Invariant 1: the two calculate.py-written stores must agree, both ways.
    if portfolio_exists and not in_manifest:
        result.problems.append(
            f"snapshots.json is stale — portfolio-{cut_date}.json exists but "
            f"the manifest does not list {cut_date}."
        )
    if in_manifest and not portfolio_exists:
        result.problems.append(
            f"portfolio-{cut_date}.json is missing — the manifest lists "
            f"{cut_date} but the snapshot file is absent."
        )

    # Invariant 2: a parser run (balance rows for D) requires the calculate.py
    # pair. This catches the interrupted close.
    if balance_rows > 0 and not (portfolio_exists and in_manifest):
        missing = []
        if not portfolio_exists:
            missing.append(f"portfolio-{cut_date}.json")
        if not in_manifest:
            missing.append(f"snapshots.json entry for {cut_date}")
        result.problems.append(
            f"interrupted close — balance-snapshots.csv has {balance_rows} row(s) "
            f"dated {cut_date} but {', '.join(missing)} is missing. The Safra parser "
            f"ran but calculate.py --cut-date={cut_date} did not complete."
        )

    result.consistent = not result.problems
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the snapshot triplet agrees for a close date; "
                    "exit non-zero on drift."
    )
    parser.add_argument("cut_date", help="Close date to validate (YYYY-MM-DD)")
    parser.add_argument(
        "--ledger-dir",
        help="Override the investimentos ledger directory (default: vault path).",
    )
    args = parser.parse_args(argv)

    ledger_dir = Path(args.ledger_dir) if args.ledger_dir else None
    result = check_triplet_consistency(args.cut_date, ledger_dir)
    print(result.report(), file=sys.stderr if not result.consistent else sys.stdout)
    return 0 if result.consistent else 1


if __name__ == "__main__":
    raise SystemExit(main())
