"""--dry-run wrapper, combinable with --fresh and --upgrade.

Architecture §6: ``--dry-run`` "prints every planned action without
executing. Combinable with the above."

Implementation choice: ``fresh.py`` and ``upgrade.py`` already accept a
``dry_run`` flag on ``args`` and short-circuit before any file-system
write when set. This module is a thin wrapper that:

* Forces ``args.dry_run = True`` so the underlying mode handler builds and
  prints the planned-action list without writing.
* Returns the underlying handler's exit code.

The alternative (a "predict-only" file-system layer) was rejected as
over-engineering for v1 — the mode handlers' early-return path is simpler,
and the planned-action list is already a complete account of what would
happen on a real run.

Public API: ``run_dry_run(target_root, args, mode, plan) -> int`` where
``mode`` is ``"fresh"`` or ``"upgrade"``.

Pure stdlib.
"""
from __future__ import annotations

from pathlib import Path

from . import cli
from .fresh import run_fresh
from .upgrade import run_upgrade


def run_dry_run(
    target_root: Path | str,
    args,
    mode: str,
    plan: cli.Plan | None = None,
) -> int:
    """Print the planned-action list for ``mode`` without executing.

    ``mode`` MUST be ``"fresh"`` or ``"upgrade"``.

    Sets ``args.dry_run = True`` so the underlying handler short-circuits
    after printing. Returns the handler's exit code (0 on success).
    """
    if mode not in {"fresh", "upgrade"}:
        cli.abort(f"--dry-run mode must be 'fresh' or 'upgrade', got {mode!r}.")
        return 1  # unreachable

    # Force dry-run mode on the namespace. ``args`` is whatever object the
    # caller passed (typically argparse.Namespace); set the attribute even
    # if it was not already present so downstream ``getattr(args, "dry_run",
    # False)`` reads ``True``.
    try:
        args.dry_run = True
    except AttributeError:
        # Read-only namespace (rare). Fall back to a wrapping shim that
        # exposes everything from `args` plus dry_run=True.
        args = _DryRunArgs(args)

    plan = plan if plan is not None else cli.Plan()
    if mode == "fresh":
        return run_fresh(target_root, args, plan=plan)
    return run_upgrade(target_root, args, plan=plan)


class _DryRunArgs:
    """Read-only-namespace shim. Forwards attribute access to the wrapped
    object but always returns ``True`` for ``dry_run``."""

    def __init__(self, wrapped):
        self._wrapped = wrapped

    def __getattr__(self, item):
        if item == "dry_run":
            return True
        return getattr(self._wrapped, item)


__all__ = ["run_dry_run"]
