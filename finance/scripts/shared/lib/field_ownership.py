"""Field-ownership loader + write-permission gate for `assets.csv`.

Spec: `1-projects/finance-system/finance-system-v2-foundation/phase-1/p1-21.task.md`.

Loads the declarative field-ownership manifest from
`.user/finance/bookkeeper/config/_field_ownership.yaml` and exposes a small
helper used by `upsert_assets` (and any future asset-metadata writer) to
decide whether a parser may overwrite a given field on an existing asset
row. Three classes:

    curated       Set on insert by anyone; never overwritten on update.
    source_bound  Only parsers listed in `owners:` may write/overwrite.
    derived       Freely overwritable.

Unknown fields (present in incoming rows or in the assets.csv header but
absent from the manifest) trigger a fail-loud `field_ownership_unknown`
audit event and a `FieldOwnershipError` — per the task's
"fail-loud / runtime prompt for genuinely-new fields" requirement.

Failure mode at load is fail-loud: missing file, parse error, missing
required section, unsupported schema version all raise
`FieldOwnershipError`. Callers SHOULD let it propagate so the calling
script halts.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from . import audit


SUPPORTED_SCHEMA_VERSION = 1
REQUIRED_TOP_LEVEL_SECTIONS = {"_meta", "fields"}
REQUIRED_META_FIELDS = {"schema_version", "manifest_version"}


class FieldClass(str, Enum):
    CURATED = "curated"
    SOURCE_BOUND = "source_bound"
    DERIVED = "derived"


class FieldOwnershipError(RuntimeError):
    """Raised when the manifest is missing/invalid or when an unknown field
    is encountered during write."""


def manifest_path(config_folder: Path | str) -> Path:
    """Canonical path to the manifest inside a bookkeeper config folder."""
    return Path(config_folder) / "_field_ownership.yaml"


def load_field_ownership(config_folder: Path | str) -> dict[str, Any]:
    """Load + validate the field-ownership manifest.

    Returns the parsed mapping. Raises `FieldOwnershipError` on any failure.
    """
    path = manifest_path(config_folder)
    if not path.exists():
        raise FieldOwnershipError(
            f"_field_ownership.yaml not found at {path}. asset-metadata "
            f"upserts require the manifest to run."
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise FieldOwnershipError(
            f"_field_ownership.yaml at {path} failed to parse: {e}"
        ) from e

    if not isinstance(data, dict):
        raise FieldOwnershipError(
            f"_field_ownership.yaml at {path} must be a YAML mapping at the top level"
        )

    missing = REQUIRED_TOP_LEVEL_SECTIONS - data.keys()
    if missing:
        raise FieldOwnershipError(
            f"_field_ownership.yaml missing required sections: {sorted(missing)}"
        )

    meta = data.get("_meta") or {}
    if not isinstance(meta, dict):
        raise FieldOwnershipError("_field_ownership.yaml `_meta` must be a mapping")
    missing_meta = REQUIRED_META_FIELDS - meta.keys()
    if missing_meta:
        raise FieldOwnershipError(
            f"_field_ownership.yaml `_meta` missing fields: {sorted(missing_meta)}"
        )
    if meta.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise FieldOwnershipError(
            f"_field_ownership.yaml schema_version "
            f"{meta.get('schema_version')!r} unsupported; expected "
            f"{SUPPORTED_SCHEMA_VERSION}"
        )

    fields = data.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise FieldOwnershipError(
            "_field_ownership.yaml `fields` must be a non-empty mapping"
        )

    for fname, spec in fields.items():
        if not isinstance(spec, dict):
            raise FieldOwnershipError(
                f"field `{fname}` spec must be a mapping; got {type(spec).__name__}"
            )
        cls = spec.get("class")
        try:
            FieldClass(cls)
        except ValueError as e:
            raise FieldOwnershipError(
                f"field `{fname}` has unknown class {cls!r}; "
                f"expected one of {[c.value for c in FieldClass]}"
            ) from e
        if cls == FieldClass.SOURCE_BOUND.value:
            owners = spec.get("owners")
            if not isinstance(owners, list) or not owners:
                raise FieldOwnershipError(
                    f"source_bound field `{fname}` must declare a non-empty `owners` list"
                )

    return data


def can_write(
    manifest: dict[str, Any],
    field: str,
    *,
    source_id: str,
    is_insert: bool,
    primary_key: str | None = None,
) -> bool:
    """Return True if `source_id` is allowed to write `field`.

    `is_insert=True` means this is the first time the row is being written
    (no existing row with this id). Insert allows writing all classified
    fields regardless of class — the curated-protection only applies on
    update.

    The primary-key field (e.g. `id`) is always writable; callers usually
    avoid routing it through this gate, but treating it as writable here is
    the safe default.

    Unknown fields raise `FieldOwnershipError` AFTER emitting an audit
    event — per the task's fail-loud requirement. Callers MUST therefore
    pre-check unknowns up-front (see `assert_known_fields`) when they want
    a single batched event instead of one-per-field.
    """
    pk = primary_key or (manifest.get("_meta") or {}).get("primary_key")
    if pk is not None and field == pk:
        return True

    spec = manifest["fields"].get(field)
    if spec is None:
        audit.emit(
            "field_ownership_unknown",
            source_function="lib.field_ownership.can_write",
            trigger_context={"field": field, "source_id": source_id},
        )
        raise FieldOwnershipError(
            f"field `{field}` is not classified in _field_ownership.yaml; "
            f"add it to the manifest before writing."
        )

    cls = spec["class"]
    if cls == FieldClass.DERIVED.value:
        return True
    if cls == FieldClass.CURATED.value:
        return is_insert
    if cls == FieldClass.SOURCE_BOUND.value:
        return source_id in spec.get("owners", [])
    return False  # pragma: no cover — load_field_ownership guards class set


def assert_known_fields(
    manifest: dict[str, Any],
    fields: list[str] | set[str],
    *,
    primary_key: str | None = None,
) -> None:
    """Raise `FieldOwnershipError` if any of `fields` is not classified.

    Emits a single `field_ownership_unknown` event listing all unknowns.
    Used by `upsert_assets` to halt at the start of a run when the
    incoming schema or the existing CSV header drifts beyond the manifest.
    """
    pk = primary_key or (manifest.get("_meta") or {}).get("primary_key")
    classified = set(manifest["fields"].keys())
    if pk:
        classified.add(pk)
    unknown = sorted(set(fields) - classified)
    if not unknown:
        return
    audit.emit(
        "field_ownership_unknown",
        source_function="lib.field_ownership.assert_known_fields",
        trigger_context={"unknown_fields": unknown},
    )
    raise FieldOwnershipError(
        f"unknown fields not classified in _field_ownership.yaml: {unknown}. "
        f"Classify them before continuing."
    )
