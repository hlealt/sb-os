"""Resolve this vault's finance data root.

One source for the `.user/finance` prefix. `sb-os.json` may set optional
`finance_root` (vault-relative). Absent or empty means `.user/finance`, so
other vaults keep the historical default. `BOOKKEEPER_ROOT`, when set, is
the absolute bookkeeper directory (test isolation) and wins over the manifest.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_FINANCE_ROOT = ".user/finance"
FINANCE_ROOT_KEY = "finance_root"


def find_vault_root(start: Path | None = None) -> Path:
    """Walk up from `start` (default: this file) for sb-os.json or .obsidian."""
    current = (start or Path(__file__)).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "sb-os.json").exists() or (candidate / ".obsidian").exists():
            return candidate
    raise RuntimeError("Vault root not found (looking for sb-os.json or .obsidian)")


def finance_root_rel(vault_root: Path) -> str:
    """Vault-relative finance root. Default `.user/finance` when unset."""
    manifest = Path(vault_root) / "sb-os.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        rel = data.get(FINANCE_ROOT_KEY) if isinstance(data, dict) else None
        if isinstance(rel, str) and rel.strip():
            return rel.strip().strip("/")
    return DEFAULT_FINANCE_ROOT


def finance_root(vault_root: Path | None = None) -> Path:
    root = Path(vault_root) if vault_root is not None else find_vault_root()
    return root / finance_root_rel(root)


def bookkeeper_root(vault_root: Path | None = None) -> Path:
    """`{finance_root}/bookkeeper`, or `BOOKKEEPER_ROOT` when set."""
    override = os.environ.get("BOOKKEEPER_ROOT")
    if override:
        return Path(override)
    return finance_root(vault_root) / "bookkeeper"


def rebase_finance_rel(vault_root: Path | str, rel: str) -> str:
    """Rewrite a vault-relative path that sits under the default finance root.

    Paths that do not start with `.user/finance` are returned unchanged, so
    installer defaults for other users stay put. When `finance_root` is unset
    this is the identity function.
    """
    normalized = rel.replace("\\", "/").lstrip("/")
    default = DEFAULT_FINANCE_ROOT.strip("/")
    configured = finance_root_rel(Path(vault_root)).strip("/")
    if normalized == default or normalized.startswith(default + "/"):
        return configured + normalized[len(default):]
    return normalized
