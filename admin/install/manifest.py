"""Read/write/update the `sb-os.json` install manifest.

Schema (architecture §6)::

    {
      "version": "0.1.0",
      "installed_at": "2026-05-01T12:00:00Z",
      "mode": "fresh",
      "wiki_root": "3-resources/knowledge-base/",
      "user_context_root": ".user/context/",
      "created_paths": []
    }

The manifest is the sb-os-owned record at vault root. It tracks WHAT the
installer created (not file hashes) — paired with the marker-block protocol
this is enough state for idempotent --upgrade runs.

`__VERSION__` is the canonical sb-os release version. `install.py` and the
own-vault cutover seed (plan task p7-7) read it from this module so there
is exactly one source of truth.

Pure stdlib (json, datetime, pathlib).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


__VERSION__ = "0.2.0"
VERSION = __VERSION__  # alias for callers that prefer non-dunder

MANIFEST_FILENAME = "sb-os.json"

# Stable key order matching the schema in architecture §6.
_KEY_ORDER = (
    "version",
    "installed_at",
    "mode",
    "wiki_root",
    "user_context_root",
    "created_paths",
)


def _manifest_path(vault_root: Path | str) -> Path:
    return Path(vault_root) / MANIFEST_FILENAME


def _now_iso_utc() -> str:
    """Return current UTC time as a second-precision ISO 8601 string with 'Z'."""
    # Use second precision to keep manifests diff-friendly across re-runs.
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _ordered(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict with keys in schema order; unknown keys appended."""
    ordered: dict[str, Any] = {}
    for key in _KEY_ORDER:
        if key in manifest:
            ordered[key] = manifest[key]
    for key, value in manifest.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def read(vault_root: Path | str) -> dict[str, Any] | None:
    """Read sb-os.json from vault_root. Return parsed dict, or None if absent."""
    path = _manifest_path(vault_root)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write(vault_root: Path | str, manifest_dict: dict[str, Any]) -> Path:
    """Write sb-os.json to vault_root with stable key order.

    Format: UTF-8, 2-space indent, trailing newline. Returns the written path.
    """
    path = _manifest_path(vault_root)
    payload = _ordered(manifest_dict)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def create_initial(
    vault_root: Path | str,
    mode: str,
    wiki_root: str,
    user_context_root: str,
    created_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Build a fresh-install manifest dict.

    Caller is responsible for passing the actual list of paths the installer
    created (or [] for the p7-7 own-vault seed where PARA folders pre-exist).
    Does not write — caller passes the result to `write()`.
    """
    return {
        "version": __VERSION__,
        "installed_at": _now_iso_utc(),
        "mode": mode,
        "wiki_root": wiki_root,
        "user_context_root": user_context_root,
        "created_paths": list(created_paths) if created_paths is not None else [],
    }


def update_for_upgrade(
    vault_root: Path | str,
    extra_created_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Read existing manifest, flip mode to 'upgrade', refresh installed_at.

    Preserves wiki_root, user_context_root, and the existing created_paths
    list. New paths created during the upgrade (if any) are appended without
    de-duplication or reordering — the order reflects creation history.

    Returns the updated dict. Caller passes it to `write()` to persist.
    Raises FileNotFoundError if no manifest exists at vault_root.
    """
    existing = read(vault_root)
    if existing is None:
        raise FileNotFoundError(
            f"No {MANIFEST_FILENAME} at {vault_root!s}; cannot upgrade an "
            "uninstalled vault. Run with --fresh or seed the manifest first."
        )
    updated = dict(existing)
    updated["version"] = __VERSION__
    updated["installed_at"] = _now_iso_utc()
    updated["mode"] = "upgrade"
    if extra_created_paths:
        existing_paths = list(updated.get("created_paths", []))
        for p in extra_created_paths:
            if p not in existing_paths:
                existing_paths.append(p)
        updated["created_paths"] = existing_paths
    return updated
