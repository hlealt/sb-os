"""Resolve optional vault-relative roots from the vault's ``sb-os.json``.

One mechanism — read an optional manifest key, then rebase vault-relative
paths that sit under the key's default root onto the configured one —
shared by every module-specific root resolver:

* ``finance_root`` (default ``.user/finance``) — facade and runtime
  consumers in ``lib.finance_paths`` (bookkeeper, investor, dashboard).
* ``templates_root`` (default ``.user/config/templates``) — periodic-note
  templates; consumed by the installer's template-target rebasing and
  managed-CLAUDE.md rendering (``install/loaders.py``).

Absent or empty key means the default, so vaults that never set a field
keep the historical layout.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_FINANCE_ROOT = ".user/finance"
FINANCE_ROOT_KEY = "finance_root"

DEFAULT_TEMPLATES_ROOT = ".user/config/templates"
TEMPLATES_ROOT_KEY = "templates_root"


def root_rel(vault_root: Path, key: str, default: str) -> str:
    """Vault-relative root configured for ``key``; ``default`` when unset.

    Unset, empty, non-string, or an unreadable/invalid manifest all mean
    the default — a broken ``sb-os.json`` must never redirect data paths.
    """
    manifest = Path(vault_root) / "sb-os.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        rel = data.get(key) if isinstance(data, dict) else None
        if isinstance(rel, str) and rel.strip():
            return rel.strip().strip("/")
    return default


def rebase_root_rel(
    vault_root: Path | str, rel: str, key: str, default_root: str
) -> str:
    """Rewrite a vault-relative path that sits under ``default_root``.

    Paths that do not start with ``default_root`` are returned unchanged,
    so installer defaults for other users stay put. When ``key`` is unset
    this is the identity function.
    """
    normalized = rel.replace("\\", "/").lstrip("/")
    default = default_root.strip("/")
    configured = root_rel(Path(vault_root), key, default).strip("/")
    if normalized == default or normalized.startswith(default + "/"):
        return configured + normalized[len(default):]
    return normalized


def templates_root_rel(vault_root: Path) -> str:
    """Vault-relative periodic-note templates root (``templates_root``)."""
    return root_rel(vault_root, TEMPLATES_ROOT_KEY, DEFAULT_TEMPLATES_ROOT)


def rebase_manifest_rel(vault_root: Path | str, rel: str) -> str:
    """Apply every configured root override to a vault-relative path.

    Installer entry point for manifest-declared template targets: a target
    under the default finance root follows ``finance_root``; a target under
    the default templates root follows ``templates_root``. All other
    targets pass through unchanged.
    """
    rebased = rebase_root_rel(vault_root, rel, FINANCE_ROOT_KEY, DEFAULT_FINANCE_ROOT)
    return rebase_root_rel(vault_root, rebased, TEMPLATES_ROOT_KEY, DEFAULT_TEMPLATES_ROOT)
