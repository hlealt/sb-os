"""Resolve this vault's finance data root.

One source for the `.user/finance` prefix. `sb-os.json` may set optional
`finance_root` (vault-relative). Absent or empty means `.user/finance`, so
other vaults keep the historical default. `BOOKKEEPER_ROOT`, when set, is
the absolute bookkeeper directory (test isolation) and wins over the manifest.

Key-reading and prefix-rebasing live in `lib.manifest_roots` (the one
mechanism, shared with `templates_root`); this module is the finance facade.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from .manifest_roots import (
        DEFAULT_FINANCE_ROOT,
        FINANCE_ROOT_KEY,
        rebase_root_rel,
        root_rel,
    )
except ImportError:  # executed outside a package (plain script dir on sys.path)
    from manifest_roots import (  # type: ignore
        DEFAULT_FINANCE_ROOT,
        FINANCE_ROOT_KEY,
        rebase_root_rel,
        root_rel,
    )


def find_vault_root(start: Path | None = None) -> Path:
    """Walk up from `start` (default: this file) for sb-os.json or .obsidian."""
    current = (start or Path(__file__)).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "sb-os.json").exists() or (candidate / ".obsidian").exists():
            return candidate
    raise RuntimeError("Vault root not found (looking for sb-os.json or .obsidian)")


def finance_root_rel(vault_root: Path) -> str:
    """Vault-relative finance root. Default `.user/finance` when unset."""
    return root_rel(vault_root, FINANCE_ROOT_KEY, DEFAULT_FINANCE_ROOT)


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
    return rebase_root_rel(vault_root, rel, FINANCE_ROOT_KEY, DEFAULT_FINANCE_ROOT)
