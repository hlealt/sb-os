"""Upsert rows into assets.csv via the field-ownership manifest.

Usage:
    # Dry-run (safe default — prints per-row diff, writes nothing)
    python upsert_assets.py <input_csv>

    # Apply mutation
    python upsert_assets.py <input_csv> --apply

    # Custom actor identity (for field-ownership source_bound gate)
    python upsert_assets.py <input_csv> [--apply] [--actor <actor_id>]

Input CSV must carry the same schema as assets.csv
(id,asset_class,name,type,sector,currency,current_broker,active,issuer,
indexer,rate,indexer_pct,application_date,maturity_date,cnpj,manager).

Dry-run output per row:
    INSERT  <id>   — id absent from destination; all fields shown.
    UPDATE  <id>   — id present; per-field old→new diff shown for
                     fields that would change under ownership rules.
    NOOP    <id>   — id present; no field would change.

Summary line: X inserts, Y updates, Z noops, W ownership-blocked.

Field-ownership semantics (loaded from .user/finance/bookkeeper/config/_field_ownership.yaml):
    curated      — populated on insert; NEVER overwritten on update.
    source_bound — only parsers listed in owners[] may write; this tool
                   runs as --actor agent_manual (default) and will skip
                   source_bound fields unless --actor matches an owner.
    derived      — freely overwritable.

    id is the primary key; never overwritten.

Unknown fields in the input or destination CSV trigger a
field_ownership_unknown audit event and a hard exit (no writes).

On --apply the write is wrapped with audit.track_write() (one event,
fail-soft). Existing rows are preserved in their original order; new rows
are inserted at their byte/ASCII sort position by id (uppercase sorts
before lowercase, e.g. XRP before aplicacoes_renda_fixa).
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Vault root + path resolution
# ---------------------------------------------------------------------------


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            return parent
    raise RuntimeError(f"Vault root not found from {__file__}")


VAULT_ROOT = _find_vault_root()
SCRIPTS_DIR = Path(__file__).resolve().parents[1]

# Make shared lib importable
sys.path.insert(0, str(SCRIPTS_DIR / "shared"))

from lib import audit  # noqa: E402
from lib import field_ownership  # noqa: E402
from lib import tool_schema_check  # noqa: E402
from lib.field_ownership import FieldClass, FieldOwnershipError, assert_known_fields, can_write  # noqa: E402
from lib.safe_write import atomic_write  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = VAULT_ROOT / ".user" / "finance" / "bookkeeper" / "data"
DESTINATION = DATA_DIR / "assets.csv"
CONFIG_DIR = VAULT_ROOT / ".user" / "finance" / "bookkeeper" / "config"

# ---------------------------------------------------------------------------
# Known type and class sets (from position_calculator.py and the live CSV)
# ---------------------------------------------------------------------------

_LISTED_TYPES = {
    "acao", "fii", "bdr", "opcao", "etf", "stock_us", "etf_us",
    "direito_subscricao",
}
_BALCAO_TYPES = {
    "cra", "deb", "lca", "lci", "cdb", "cdb_mp", "tesouro", "lc", "cri", "rf",
    "fia_br", "fia_usa", "fim_br", "firf_br", "fidc", "coe", "di",
}
_ALL_TYPES = _LISTED_TYPES | _BALCAO_TYPES | {"crypto", "recibo_subscricao"}
_ALL_ASSET_CLASSES = {"variable_income", "fixed_income", "funds", "crypto"}

# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Return (header, rows-as-dicts). Header preserves original column order."""
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        rows = list(reader)
    return header, rows


def _write_csv(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    """Atomic write — preserves existing row order; new rows inserted at byte-sort position.

    Existing rows are written in their original order (no re-sort).  New rows
    (those not already present in the on-disk file at read time) are inserted at
    the position determined by plain byte/ASCII comparison on the ``id`` field —
    uppercase letters sort before lowercase letters (e.g. ``XRP`` < ``aplicacoes``).

    This function receives ``rows`` as a list where existing rows are already in
    their original order (the destination was read sequentially) and new rows
    were appended by the caller via ``new_dest_rows.append(merged_row)``.  We
    bisect-insert each new row into the ordered existing sequence rather than
    re-sorting the whole list, so not a single pre-existing line changes position.
    """
    # Separate existing rows (preserve order) from new rows (need placement).
    # We rely on the fact that _read_csv returns rows in file order and the
    # caller appends new rows at the end of new_dest_rows.
    # Re-build the sorted list without touching existing-row relative order:
    # walk the existing sequence and bisect-insert each new id by byte comparison.
    from bisect import insort

    # Build an index of ids that were in the file before this run (i.e. all rows
    # except the ones that were just appended).  We can reconstruct this by
    # reading the existing ids from the file before the write — but at this point
    # the file hasn't been rewritten yet, so we read it here for its id list.
    try:
        with open(path, "r", encoding="utf-8", newline="") as _f:
            existing_ids_ordered = [r["id"] for r in csv.DictReader(_f)]
    except FileNotFoundError:
        existing_ids_ordered = []

    existing_id_set = set(existing_ids_ordered)

    # Split rows into existing (preserve order) and new (need placement).
    existing_rows = [r for r in rows if r.get("id", "") in existing_id_set]
    new_rows = [r for r in rows if r.get("id", "") not in existing_id_set]

    if not new_rows:
        # Pure updates/noops — preserve order exactly.
        final_rows = existing_rows
    else:
        # Merge new rows into the existing sequence at their byte-sort positions.
        # Strategy: build a sorted list of (id, row) for existing rows, then
        # bisect-insert new rows by id using plain str comparison (byte/ASCII).
        # After insertion, strip the key to get the final row list.
        keyed: list[tuple[str, dict]] = [(r["id"], r) for r in existing_rows]
        for new_row in new_rows:
            nid = new_row.get("id", "")
            insort(keyed, (nid, new_row), key=lambda t: t[0])
        final_rows = [r for _, r in keyed]

    def _write(f: Any) -> None:
        writer = csv.DictWriter(
            f,
            fieldnames=header,
            lineterminator="\n",
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writeheader()
        writer.writerows(final_rows)

    atomic_write(path, _write, encoding="utf-8", newline="")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_input_rows(
    rows: list[dict[str, str]],
    input_path: Path,
) -> None:
    """Fail-loud on empty id, duplicate id, invalid type, invalid active flag."""
    seen_ids: dict[str, int] = {}
    for lineno, row in enumerate(rows, start=2):  # 1 = header
        rid = row.get("id", "").strip()
        if not rid:
            print(
                f"ERROR: row {lineno} in {input_path}: empty `id` field. "
                "Every row must have a non-empty id.",
                file=sys.stderr,
            )
            sys.exit(1)

        if rid in seen_ids:
            print(
                f"ERROR: duplicate id `{rid}` on rows {seen_ids[rid]} and {lineno} "
                f"in {input_path}. Input ids must be unique.",
                file=sys.stderr,
            )
            sys.exit(1)
        seen_ids[rid] = lineno

        typ = row.get("type", "").strip()
        if typ and typ not in _ALL_TYPES:
            print(
                f"ERROR: row {lineno} id=`{rid}`: unknown type `{typ}`. "
                f"Known types: {sorted(_ALL_TYPES)}",
                file=sys.stderr,
            )
            sys.exit(1)

        active = row.get("active", "").strip().lower()
        if active not in {"true", "false", ""}:
            print(
                f"ERROR: row {lineno} id=`{rid}`: `active` must be `true` or `false`; "
                f"got `{row.get('active', '')}`.",
                file=sys.stderr,
            )
            sys.exit(1)


# ---------------------------------------------------------------------------
# Per-row diff logic
# ---------------------------------------------------------------------------


_ROW_TAG = "  "
_SEP = "─" * 72


def _row_diff(
    incoming: dict[str, str],
    existing: dict[str, str] | None,
    manifest: dict[str, Any],
    header: list[str],
    actor: str,
) -> tuple[str, dict[str, str], list[str]]:
    """Compute the action and the mutation for one row.

    Returns:
        action: "insert" | "update" | "noop"
        merged_row: the row that WOULD be written (or existing on noop)
        blocked_fields: fields skipped due to ownership
    """
    rid = incoming["id"]
    is_insert = existing is None

    if is_insert:
        # On insert: write all fields the actor is permitted to write.
        merged = dict(existing or {})
        merged["id"] = rid
        blocked: list[str] = []
        for field in header:
            if field == "id":
                continue
            val = incoming.get(field, "")
            if can_write(manifest, field, source_id=actor, is_insert=True):
                merged[field] = val
            else:
                # source_bound field on insert; actor not an owner.
                merged[field] = ""
                if val:
                    blocked.append(field)
        return "insert", merged, blocked

    # Update path: only overwrite fields the actor may change.
    merged = dict(existing)
    changed = False
    blocked = []
    for field in header:
        if field == "id":
            continue
        new_val = incoming.get(field, "")
        old_val = existing.get(field, "")
        if not can_write(manifest, field, source_id=actor, is_insert=False):
            if new_val and new_val != old_val:
                blocked.append(field)
            continue  # skip — ownership blocks this field
        if new_val != old_val:
            merged[field] = new_val
            changed = True

    action = "update" if changed else "noop"
    return action, merged, blocked


# ---------------------------------------------------------------------------
# Dry-run printer
# ---------------------------------------------------------------------------


def _print_insert(rid: str, row: dict[str, str], header: list[str]) -> None:
    print(f"INSERT  {rid}")
    for field in header:
        if field == "id":
            continue
        val = row.get(field, "")
        if val:
            print(f"{_ROW_TAG}{field}: {val!r}")


def _print_update(
    rid: str,
    incoming: dict[str, str],
    existing: dict[str, str],
    header: list[str],
    manifest: dict[str, Any],
    actor: str,
) -> None:
    print(f"UPDATE  {rid}")
    for field in header:
        if field == "id":
            continue
        new_val = incoming.get(field, "")
        old_val = existing.get(field, "")
        if not can_write(manifest, field, source_id=actor, is_insert=False):
            continue
        if new_val != old_val:
            print(f"{_ROW_TAG}{field}: {old_val!r} → {new_val!r}")


def _print_noop(rid: str) -> None:
    print(f"NOOP    {rid}")


def _print_blocked(rid: str, fields: list[str]) -> None:
    if fields:
        print(f"  [ownership-blocked fields skipped: {', '.join(fields)}]")


# ---------------------------------------------------------------------------
# Main upsert logic
# ---------------------------------------------------------------------------


def run(
    input_path: Path,
    *,
    apply: bool,
    actor: str,
) -> int:
    """Execute the upsert. Returns exit code (0 = ok, 1 = error)."""

    # --- 1. Load destination ---
    if not DESTINATION.exists():
        print(
            f"ERROR: destination {DESTINATION} does not exist. "
            "Cannot upsert into a non-existent store.",
            file=sys.stderr,
        )
        return 1

    dest_header, dest_rows = _read_csv(DESTINATION)
    dest_by_id: dict[str, dict[str, str]] = {r["id"]: r for r in dest_rows}

    # --- 2. Load field-ownership manifest ---
    try:
        manifest = field_ownership.load_field_ownership(CONFIG_DIR)
    except FieldOwnershipError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    # --- 3. Load input ---
    if not input_path.exists():
        print(f"ERROR: input file {input_path} does not exist.", file=sys.stderr)
        return 1

    in_header, in_rows = _read_csv(input_path)
    if not in_rows:
        print("WARNING: input CSV is empty; nothing to do.", file=sys.stderr)
        return 0

    # --- 4. Schema conformance check ---
    dest_schema = tool_schema_check.destination_schema(DESTINATION)
    gap = tool_schema_check.conformance_gap(set(in_header), dest_schema)
    if gap:
        prompt = tool_schema_check.surface_schema_gap(
            gap,
            DESTINATION,
            tool_name="upsert_assets",
            actor=actor,
        )
        print("SCHEMA GAP DETECTED:\n", file=sys.stderr)
        print(prompt, file=sys.stderr)
        return 1

    # --- 5. Unknown-field gate (input columns + destination header vs manifest) ---
    # Exclude the primary key from the gate — it is always known.
    pk = (manifest.get("_meta") or {}).get("primary_key", "id")
    all_fields_to_check = (set(in_header) | set(dest_header)) - {pk}
    # Filter to fields actually in the manifest's fields section
    try:
        assert_known_fields(manifest, all_fields_to_check, primary_key=pk)
    except FieldOwnershipError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    # --- 6. Validate input rows ---
    _validate_input_rows(in_rows, input_path)

    # --- 7. Compute per-row diffs ---
    print(_SEP)
    if apply:
        print(f"MODE: APPLY  (actor={actor})")
    else:
        print(f"MODE: DRY-RUN (actor={actor})  — pass --apply to mutate")
    print(_SEP)

    counts = {"insert": 0, "update": 0, "noop": 0, "blocked_fields": 0}
    new_dest_rows = list(dest_rows)  # copy for mutation
    dest_id_set = set(dest_by_id)

    for incoming in in_rows:
        rid = incoming["id"].strip()
        existing = dest_by_id.get(rid)

        action, merged_row, blocked = _row_diff(
            incoming, existing, manifest, dest_header, actor
        )
        counts[action] += 1
        counts["blocked_fields"] += len(blocked)

        if action == "insert":
            _print_insert(rid, merged_row, dest_header)
            _print_blocked(rid, blocked)
            if apply:
                new_dest_rows.append(merged_row)
                dest_id_set.add(rid)
        elif action == "update":
            assert existing is not None
            _print_update(rid, incoming, existing, dest_header, manifest, actor)
            _print_blocked(rid, blocked)
            if apply:
                # Replace existing row in list
                for i, r in enumerate(new_dest_rows):
                    if r["id"] == rid:
                        new_dest_rows[i] = merged_row
                        break
        else:  # noop
            _print_noop(rid)

    print(_SEP)
    print(
        f"SUMMARY: {counts['insert']} inserts, {counts['update']} updates, "
        f"{counts['noop']} noops, {counts['blocked_fields']} ownership-blocked fields"
    )

    # --- 8. Write (--apply only) ---
    if apply:
        if counts["insert"] == 0 and counts["update"] == 0:
            print("No changes to write.")
            return 0

        with audit.track_write(
            DESTINATION,
            materiality="high",
            action="upsert",
            event_type="ledger_write",
            source_function="upsert_assets.run",
            actor=actor,
            trigger_context={
                "input_file": str(input_path),
                "inserts": counts["insert"],
                "updates": counts["update"],
                "noops": counts["noop"],
            },
        ):
            _write_csv(DESTINATION, dest_header, new_dest_rows)

        print(f"Written → {DESTINATION}")
        audit.emit_docs_potentially_stale(
            DESTINATION,
            source_function="upsert_assets.run",
            actor=actor,
        )
    else:
        print("Dry-run complete — nothing written.")

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Upsert rows into assets.csv via the field-ownership manifest. "
            "DRY-RUN is the safe default; pass --apply to mutate the destination."
        )
    )
    parser.add_argument(
        "input_csv",
        type=Path,
        help="CSV file to ingest (must match assets.csv schema).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write changes to assets.csv (default: dry-run only).",
    )
    parser.add_argument(
        "--actor",
        default="agent_manual",
        help=(
            "Actor identity for field-ownership source_bound gate. "
            "Default: agent_manual. Use a parser's source_id (e.g. safra_titulos) "
            "when ingesting from a named source that owns source_bound fields."
        ),
    )
    args = parser.parse_args()
    sys.exit(run(args.input_csv, apply=args.apply, actor=args.actor))


if __name__ == "__main__":
    main()
