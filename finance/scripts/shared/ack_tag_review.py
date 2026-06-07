"""ack_tag_review: write-class upsert tool — append tag-review ack rows.

WRITE-class, use=upsert. Appends acknowledgement rows to the append-only
side-ledger `.user/finance/bookkeeper/config/corrections/tag-review-acks.csv`
(header: tx_date,tx_description,tx_amount,month,acked_at,source,note). An ack
marks a large untagged despesa as reviewed-and-intentionally-untagged, so
`gate_coverage.py` renders it ACK instead of VIOLATION.

Replaces the three improvised hand-edit mechanisms used across the April / May /
June review and close sessions with one validated, deduped, audited writer.

IDENTITY PARITY (requirement 1). The identity an ack carries MUST be the SAME
identity `gate_coverage.py` joins on, or an ack written here would not render as
ACK there. This tool IMPORTS the gate's own identity helpers
(`gate_coverage._ack_identity`, `gate_coverage._tx_identity`,
`gate_coverage._tx_amount_key`) and reuses them verbatim — there is no second
identity implementation to drift. The amount key is `repr(float(amount))`, so
`-352.00`, `-352.0`, and `-352` all collapse to the same key the gate uses.

REDUNDANT IDENTIFICATION (requirement 2). Each ack reference carries three
identity fields — tx_date + tx_description + tx_amount — plus the run-level
month. ALL THREE must JOINTLY match the same row in
`ledgers/fechamento/{month}/transactions.csv`. A partial match (e.g. date+amount
match a row but the description does not) is a NAMED REFUSAL that prints the
near-miss candidates and writes NOTHING. Batch runs validate every row first;
ANY invalid row refuses the ENTIRE run (atomic — no partial appends).

tx_date may legitimately lie OUTSIDE {month} (credit-card invoice rows whose
data_caixa is the next month). Validation is membership in {month}'s
transactions.csv — NEVER a date-range check.

DEDUP (requirement 4). An ack already present in the side-ledger (by the
identity triple) is reported as `SKIP duplicate` and is NOT an error; the run
proceeds for the remaining rows and exits 0 even if every row was a duplicate.

MULTI-MATCH (requirement 5). N>1 identical triples in transactions.csv is fine
(one ack row covers all, matching gate semantics) — the preview surfaces
`matches N transactions`.

DRY-RUN IS THE DEFAULT. A real append requires --apply. Append-only: existing
bytes of the ack file are never modified; rows are written with the csv module
(minimal quoting, the file's existing convention) preserving its CRLF line
terminator and UTF-8 encoding for byte-compatibility with existing content.

Usage:
    # single ack (dry-run preview)
    python ack_tag_review.py --month 2026-03 --source review-mode-2026-03 \\
        --date 2026-03-22 --description "R13 IBIRAPUERA" --amount -300.0 \\
        --note "marketplace purchase - no dimensional tag applies"

    # batch ack from a JSON file (primary path — avoids shell-quoting)
    python ack_tag_review.py --month 2026-03 --source review-mode-2026-03 \\
        --input acks.json

    # apply (mutates the side-ledger)
    python ack_tag_review.py --month 2026-03 --source review-mode-2026-03 \\
        --input acks.json --apply

`--input FILE.json` is a list of objects, each with keys:
    tx_date, tx_description, tx_amount, note   (note optional)

Exit codes:
    0  success — rows would-append / appended, OR all rows were SKIP duplicate
       (no-op apply is success)
    1  validation refusal — at least one row failed to JOINTLY match a
       transactions.csv row (nothing written)
    2  usage error / missing files (transactions.csv or --input not found,
       bad JSON, malformed ack header)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Identity parity (requirement 1): reuse the gate's own helpers verbatim.
# gate_coverage imports `from lib import audit, standing_rules`; importing it
# here pulls those transitively. The helpers are module-level pure functions.
import gate_coverage as gate  # noqa: E402
from lib import audit  # noqa: E402

_TOOL = "ack_tag_review"
_ACK_HEADER = ["tx_date", "tx_description", "tx_amount", "month", "acked_at", "source", "note"]
# Mirror gate_coverage's required identity columns (fail-loud parity).
_ACK_IDENTITY_COLS = gate._ACK_IDENTITY_COLS


# ---------------------------------------------------------------------------
# Vault / path resolution (no personal paths hardcoded — sb- component rule)
# ---------------------------------------------------------------------------


def _find_vault_root() -> Path:
    for parent in (_HERE, *_HERE.parents):
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return parent
    raise RuntimeError(f"Vault root not found from {_HERE}")


def _default_ack_path(vault_root: Path) -> Path:
    return (
        vault_root
        / ".user" / "finance" / "bookkeeper" / "config" / "corrections"
        / "tag-review-acks.csv"
    )


def _default_fechamento_dir(vault_root: Path) -> Path:
    return vault_root / ".user" / "finance" / "bookkeeper" / "ledgers" / "fechamento"


def _now_iso() -> str:
    """Seconds-precision UTC-naive ISO stamp, matching the existing acked_at
    column convention (e.g. 2026-06-06T20:58:42)."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Identity (delegated to the gate — requirement 1)
# ---------------------------------------------------------------------------


def _ack_request_identity(req: dict) -> tuple[str, str, str]:
    """Identity of an incoming ack request. Reuses gate._ack_identity, which
    keys off tx_date/tx_description/tx_amount — the ack-request fields."""
    return gate._ack_identity(req)


def _tx_row_identity(row: dict) -> tuple[str, str, str]:
    """Identity of a transactions.csv row. Reuses gate._tx_identity (keys off
    date/description/amount)."""
    return gate._tx_identity(row)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_tx_rows(tx_path: Path) -> list[dict]:
    with open(tx_path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _load_existing_acks(ack_path: Path) -> set[tuple[str, str, str]]:
    """Existing ack identity set. Reuses the gate's loader so the dedup set is
    exactly the set the gate reads (fail-soft missing file; fail-loud on a
    malformed header → exit 2)."""
    return gate.load_tag_review_acks(ack_path)


def _read_requests(args: argparse.Namespace) -> list[dict]:
    """Build the list of ack requests from --input JSON or single-row flags.

    Each request dict carries tx_date, tx_description, tx_amount, note.
    Raises SystemExit(2) on usage error.
    """
    if args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"ERROR: --input file not found: {input_path}", file=sys.stderr)
            raise SystemExit(2)
        try:
            data = json.loads(input_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"ERROR: could not parse --input JSON: {exc}", file=sys.stderr)
            raise SystemExit(2)
        if not isinstance(data, list):
            print("ERROR: --input JSON must be a list of objects.", file=sys.stderr)
            raise SystemExit(2)
        requests: list[dict] = []
        for i, obj in enumerate(data):
            if not isinstance(obj, dict):
                print(f"ERROR: --input item {i} is not an object.", file=sys.stderr)
                raise SystemExit(2)
            missing = [k for k in ("tx_date", "tx_description", "tx_amount") if k not in obj]
            if missing:
                print(
                    f"ERROR: --input item {i} missing required key(s): {missing}.",
                    file=sys.stderr,
                )
                raise SystemExit(2)
            requests.append(
                {
                    "tx_date": str(obj["tx_date"]).strip(),
                    "tx_description": str(obj["tx_description"]).strip(),
                    "tx_amount": obj["tx_amount"],
                    "note": str(obj.get("note", "")).strip(),
                }
            )
        return requests

    # Single-row flag path.
    if not (args.date and args.description and args.amount is not None):
        print(
            "ERROR: provide --input FILE.json OR all of --date --description --amount.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return [
        {
            "tx_date": str(args.date).strip(),
            "tx_description": str(args.description).strip(),
            "tx_amount": args.amount,
            "note": str(args.note or "").strip(),
        }
    ]


# ---------------------------------------------------------------------------
# Validation (requirement 2 — joint match or named refusal)
# ---------------------------------------------------------------------------


def _near_misses(req: dict, tx_rows: list[dict]) -> list[dict]:
    """Rows sharing the date OR the amount key with the request — the closest
    candidates surfaced when a joint match fails."""
    want_date = str(req.get("tx_date", "")).strip()
    want_amt = gate._tx_amount_key(req.get("tx_amount", ""))
    out: list[dict] = []
    for row in tx_rows:
        rd = str(row.get("date", "")).strip()
        ra = gate._tx_amount_key(row.get("amount", ""))
        if rd == want_date or ra == want_amt:
            out.append(row)
    return out


def _match_count(req: dict, tx_index: dict[tuple[str, str, str], int]) -> int:
    return tx_index.get(_ack_request_identity(req), 0)


def _build_tx_index(tx_rows: list[dict]) -> dict[tuple[str, str, str], int]:
    """Count of transactions.csv rows per identity triple (multi-match aware)."""
    idx: dict[tuple[str, str, str], int] = {}
    for row in tx_rows:
        key = _tx_row_identity(row)
        idx[key] = idx.get(key, 0) + 1
    return idx


# ---------------------------------------------------------------------------
# Append (only under --apply)
# ---------------------------------------------------------------------------


def _append_rows(ack_path: Path, rows: list[dict], month: str, source: str, acked_at: str) -> None:
    """Append ack rows to the side-ledger, preserving its CRLF/UTF-8/minimal-
    quoting convention. Existing bytes are never touched (mode 'a')."""
    write_header = not ack_path.exists()
    ack_path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" lets the csv module own line terminators; default lineterminator
    # is "\r\n", matching the existing file. QUOTE_MINIMAL matches the file's one
    # quoted note (a value containing a comma).
    with open(ack_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        if write_header:
            writer.writerow(_ACK_HEADER)
        for req in rows:
            writer.writerow(
                [
                    req["tx_date"],
                    req["tx_description"],
                    req["tx_amount"],
                    month,
                    acked_at,
                    source,
                    req["note"],
                ]
            )


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    vault_root = _find_vault_root()

    ack_path = Path(args.ack_file) if args.ack_file else _default_ack_path(vault_root)
    fechamento_dir = (
        Path(args.fechamento_dir) if args.fechamento_dir else _default_fechamento_dir(vault_root)
    )
    tx_path = fechamento_dir / args.month / "transactions.csv"

    if not tx_path.exists():
        print(f"ERROR: transactions.csv not found for month {args.month}: {tx_path}", file=sys.stderr)
        return 2

    requests = _read_requests(args)  # may raise SystemExit(2)

    try:
        tx_rows = _load_tx_rows(tx_path)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"ERROR: could not read transactions file: {exc}", file=sys.stderr)
        return 2

    # Existing ack set (gate's loader; exits 2 on malformed header).
    existing = _load_existing_acks(ack_path)
    tx_index = _build_tx_index(tx_rows)

    # --- Classify every request (validate ALL before any write — atomic) ------
    to_append: list[dict] = []
    skips: list[dict] = []
    refusals: list[tuple[dict, list[dict]]] = []

    for req in requests:
        ident = _ack_request_identity(req)
        n = _match_count(req, tx_index)
        if n == 0:
            refusals.append((req, _near_misses(req, tx_rows)))
            continue
        req["_match_count"] = n
        if ident in existing:
            skips.append(req)
        else:
            # Guard against duplicate triples inside this same batch.
            if any(_ack_request_identity(a) == ident for a in to_append):
                skips.append(req)
            else:
                to_append.append(req)

    applying = args.apply
    mode = "APPLY" if applying else "DRY-RUN"
    print(f"ack_tag_review [{mode}] — month {args.month}, source {args.source}")
    print(f"  ack ledger:    {ack_path}")
    print(f"  transactions:  {tx_path}")
    print(f"  requests: {len(requests)}  |  would-append: {len(to_append)}  "
          f"|  skip-duplicate: {len(skips)}  |  refusals: {len(refusals)}")
    print()

    # --- Refusals (requirement 2): print near-miss diagnostics, write nothing -
    if refusals:
        print("REFUSED — no joint (date+description+amount) match in transactions.csv:", file=sys.stderr)
        for req, candidates in refusals:
            print(
                f"  NO MATCH  {req['tx_date']}  {req['tx_description'][:48]}  "
                f"{req['tx_amount']}",
                file=sys.stderr,
            )
            if candidates:
                print("    near-miss candidates (shared date or amount):", file=sys.stderr)
                for c in candidates[:6]:
                    print(
                        f"      {c.get('date','')}  {str(c.get('description',''))[:48]}  "
                        f"{c.get('amount','')}",
                        file=sys.stderr,
                    )
            else:
                print("    (no rows share the date or amount)", file=sys.stderr)
        print(
            f"\n{_TOOL}: REFUSED — {len(refusals)} row(s) failed joint match; "
            f"NOTHING written (atomic).",
            file=sys.stderr,
        )
        return 1

    # --- Skips (requirement 4): visible, not an error -------------------------
    for req in skips:
        mm = f"  (matches {req['_match_count']} transactions)" if req.get("_match_count", 0) > 1 else ""
        print(f"  SKIP duplicate  {req['tx_date']}  {req['tx_description'][:48]}  {req['tx_amount']}{mm}")

    # --- Would-append / append ------------------------------------------------
    verb = "appended" if applying else "would append"
    for req in to_append:
        mm = f"  (matches {req['_match_count']} transactions)" if req.get("_match_count", 0) > 1 else ""
        print(f"  {verb}  {req['tx_date']}  {req['tx_description'][:48]}  {req['tx_amount']}{mm}")

    if not to_append:
        # No-op apply (all duplicates) is success (requirement 4).
        print(f"\n{_TOOL}: no new acks to write "
              f"({len(skips)} duplicate(s) skipped). exit 0.")
        return 0

    if not applying:
        print(f"\n{_TOOL}: DRY-RUN — {len(to_append)} row(s) would append; "
              f"nothing written. Re-run with --apply to write.")
        return 0

    # APPLY: one config_write audit event for the run (fail-soft; respects
    # BOOKKEEPER_AUDIT_DISABLED / BOOKKEEPER_AUDIT_LOG_DIR inside audit.py).
    acked_at = _now_iso()
    with audit.track_write(
        ack_path,
        materiality="medium",
        action="append",
        event_type="config_write",
        kind="csv",
        source_function=f"{_TOOL}.run",
        trigger_context={
            "month": args.month,
            "source": args.source,
            "appended": len(to_append),
            "skipped_duplicate": len(skips),
        },
    ):
        _append_rows(ack_path, to_append, args.month, args.source, acked_at)

    print(f"\n{_TOOL}: APPLIED — {len(to_append)} ack row(s) appended to {ack_path}"
          f"{f'; {len(skips)} duplicate(s) skipped' if skips else ''}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Append tag-review ack rows to tag-review-acks.csv with identity "
            "validation, dedup, and audit. DRY-RUN by default; --apply to write."
        )
    )
    parser.add_argument("--month", required=True, metavar="YYYY-MM",
                        help="Run-level month whose transactions.csv validates every row.")
    parser.add_argument("--source", required=True, metavar="LABEL",
                        help="Provenance label (e.g. review-mode-2026-03).")
    # Single-row flags.
    parser.add_argument("--date", metavar="YYYY-MM-DD", help="tx_date (single-row mode).")
    parser.add_argument("--description", metavar="TEXT", help="tx_description (single-row mode).")
    parser.add_argument("--amount", metavar="AMT", help="tx_amount (single-row mode); numeric, e.g. -352.00.")
    parser.add_argument("--note", metavar="TEXT", default="", help="Optional note (single-row mode).")
    # Batch path (primary).
    parser.add_argument("--input", metavar="FILE.json",
                        help="JSON list of {tx_date,tx_description,tx_amount,note} (batch mode).")
    # Mutation + test-isolation overrides.
    parser.add_argument("--apply", action="store_true",
                        help="Execute the append. WITHOUT this flag the tool is dry-run only.")
    parser.add_argument("--ack-file", metavar="PATH",
                        help="Override the ack ledger path (test isolation).")
    parser.add_argument("--fechamento-dir", metavar="PATH",
                        help="Override the fechamento base dir holding {month}/transactions.csv (test isolation).")
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
