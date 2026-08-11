"""Schema-conformance + schema-gap dual-surfacing for the tool-builder companion.

Sources: `shape.md` "Tool-builder authority boundary" (schema-conformance
check + dual-surfacing).

The `tool-builder` companion (`finance/workflows/tool-builder/tool-builder.md`)
builds tools whose output MUST conform, by default, to the destination
artifact's existing schema. This module is the mechanized embodiment of that
quality bar — the primitive every generated `write` tool's schema-validation
test calls, and the single place the schema-gap dual-surfacing fires:

    destination_schema(artifact)   The current field set of a destination
                                   (CSV header, JSON top-level keys, or the
                                   classified fields of _field_ownership.yaml).
    conformance_gap(out, dst)      Output fields the destination does NOT carry
                                   (empty set = conforms).
    assert_conforms(out, dst)      Raise SchemaGapError on a non-empty gap
                                   (used by the generated tool's pytest test).
    surface_schema_gap(...)        Dual-surface a gap: emit a `schema_gap_finding`
                                   audit event AND return the user-facing prompt.
                                   Writes NOTHING to the destination.

Authority-boundary invariant (load-bearing): NOTHING in this module writes to a
ledger, portfolio.json, a dashboard artifact, or the destination whose schema it
inspects. `destination_schema` is read-only; `surface_schema_gap` only emits an
audit event (best-effort) and returns text. A schema gap is therefore never
silently flattened (the field is reported, not dropped) and never unilaterally
migrated (no destination is mutated). Resolving a gap is the caller's decision,
routed back through the companion — never an automatic side effect here.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from . import audit


SCHEMA_GAP_EVENT_TYPE = "schema_gap_finding"


class SchemaGapError(RuntimeError):
    """Raised by `assert_conforms` when a tool's output fields are not all
    present in the destination artifact's current schema."""


# ---------------------------------------------------------------------------
# Destination schema resolution (read-only)
# ---------------------------------------------------------------------------


def _csv_header_fields(path: Path) -> list[str]:
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return []
    return [h.strip() for h in header if h.strip()]


def _json_top_level_keys(path: Path) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return sorted(data.keys())
    if isinstance(data, list) and data and isinstance(data[0], dict):
        # Array-of-objects store (e.g. value_based_mappings): the schema is the
        # union of the first object's keys — the per-record field set.
        return sorted(data[0].keys())
    raise SchemaGapError(
        f"cannot derive a field schema from JSON at {path}: "
        f"top level is neither an object nor an array of objects"
    )


def destination_schema(artifact: Path | str) -> set[str]:
    """Return the current field set of a destination artifact.

    Read-only. Supports:
      - `.csv`  → the header row's column names.
      - `.json` → the top-level object keys, or (for an array-of-objects store)
                  the first record's keys.
      - `_field_ownership.yaml` → the classified field names (the manifest is
        the schema-of-record for assets.csv; loaded via `lib.field_ownership`).

    Raises `SchemaGapError` if the artifact is missing or its shape is not a
    recognized schema carrier — fail-loud, so a generated tool's test never
    passes against a phantom schema.
    """
    path = Path(artifact)
    if not path.exists():
        raise SchemaGapError(
            f"destination artifact {path} does not exist; cannot derive its "
            f"current schema. A write tool must target an existing store (or "
            f"its new store must clear the ME gate first)."
        )
    name = path.name.lower()
    suffix = path.suffix.lower()
    if name == "_field_ownership.yaml":
        # Defer to the manifest loader so the field set matches the live
        # write-permission gate exactly.
        from . import field_ownership

        manifest = field_ownership.load_field_ownership(path.parent)
        fields = set(manifest["fields"].keys())
        pk = (manifest.get("_meta") or {}).get("primary_key")
        if pk:
            fields.add(pk)
        return fields
    if suffix == ".csv":
        return set(_csv_header_fields(path))
    if suffix == ".json":
        return set(_json_top_level_keys(path))
    raise SchemaGapError(
        f"unsupported destination artifact {path}: only .csv, .json, and "
        f"_field_ownership.yaml carry a derivable field schema."
    )


# ---------------------------------------------------------------------------
# Conformance check
# ---------------------------------------------------------------------------


def conformance_gap(
    output_fields: Iterable[str], destination_schema: Iterable[str]
) -> set[str]:
    """Return the output fields absent from the destination schema.

    An empty set means the tool's output conforms to the destination's current
    schema. A non-empty set is a schema gap (→ `surface_schema_gap`). This is a
    pure set difference — it inspects nothing on disk and mutates nothing.
    """
    return set(output_fields) - set(destination_schema)


def assert_conforms(
    output_fields: Iterable[str],
    destination_schema: Iterable[str],
    *,
    destination: str | Path | None = None,
) -> None:
    """Raise `SchemaGapError` if `output_fields` is not a subset of the schema.

    The primitive a generated `write` tool's mandatory schema-validation test
    calls (tool-builder Step 5.1) to prove conformance against the destination
    artifact's current schema. Emits no audit event — surfacing is the
    companion's job at dry-run (`surface_schema_gap`); this is the test-time
    hard assertion.
    """
    gap = conformance_gap(output_fields, destination_schema)
    if gap:
        where = f" for {destination}" if destination is not None else ""
        raise SchemaGapError(
            f"tool output introduces field(s) absent from the destination "
            f"schema{where}: {sorted(gap)}. Conform to the existing schema, or "
            f"dual-surface the gap for a schema-extension decision — never "
            f"silently flatten or migrate."
        )


# ---------------------------------------------------------------------------
# Schema-gap dual-surfacing
# ---------------------------------------------------------------------------


def gap_prompt(gap_fields: Iterable[str], destination: str | Path) -> str:
    """The user-facing prompt for a schema gap (one of the two surfaces).

    Names the gap field(s) and the three options: extend the schema,
    flatten (drop the field, data lost), justify and defer.
    """
    fields = ", ".join(f"`{f}`" for f in sorted(gap_fields))
    return (
        f"The tool produces field(s) {fields} that do not exist in the current "
        f"schema of `{destination}`.\n\n"
        f"How do you want to proceed?\n"
        f"  [E] Extend the schema of `{destination}` to include the field(s) "
        f"— you approve the schema change; the tool starts writing the new field.\n"
        f"  [F] Flatten — the tool drops the field(s) and writes only the "
        f"existing fields. (the new data is lost)\n"
        f"  [J] Justify and defer — we record the gap and proceed without the "
        f"field(s) for now."
    )


def surface_schema_gap(
    gap_fields: Iterable[str],
    destination: str | Path,
    *,
    tool_name: str,
    source_function: str = "tool_schema_check.surface_schema_gap",
    actor: str | None = None,
) -> str:
    """Dual-surface a schema gap and return the user-facing prompt.

    Performs BOTH halves of the dual-surfacing the tool-builder authority
    boundary requires:
      1. emits a `schema_gap_finding` audit event (best-effort; never raises),
         carrying the destination, the gap fields, and the tool name;
      2. returns the user-facing prompt (`gap_prompt`) for the caller to
         surface to the user.

    Writes NOTHING to `destination`. A gap is thus never silently flattened
    (the fields are named in both surfaces) and never unilaterally migrated
    (no store is mutated here). Resolving the gap is the user's decision,
    routed back through the companion's caller.
    """
    fields = sorted(gap_fields)
    audit.emit(
        SCHEMA_GAP_EVENT_TYPE,
        source_function=source_function,
        actor=actor,
        destination=destination,
        materiality="high",
        trigger_context={
            "tool": tool_name,
            "destination": str(destination),
            "gap_fields": fields,
        },
        _stack_depth=3,
    )
    return gap_prompt(fields, destination)
