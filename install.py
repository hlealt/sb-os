#!/usr/bin/env python3
"""install.py — sb-os installer entry point.

Bootstraps a clean PARA vault (``--fresh``) or idempotently refreshes an
existing sb-os install (``--upgrade``). Combinable with ``--dry-run`` to
print every planned action without writing anything.

Usage::

    python install.py                          # auto-detect mode from target
    python install.py --target /path/to/vault  # explicit target
    python install.py --fresh                  # force fresh bootstrap
    python install.py --upgrade                # force upgrade refresh
    python install.py --dry-run                # combinable with --fresh/--upgrade

Mode auto-detection (architecture §6):
* ``sb-os.json`` exists at target root → default ``--upgrade``.
* ``sb-os.json`` is absent at target root → default ``--fresh``.
* User may override with explicit ``--fresh`` or ``--upgrade``.
* ``--fresh`` and ``--upgrade`` are mutually exclusive.

Exit codes:
* 0  success (or dry-run printed cleanly).
* 1  user abort, missing-markers error, or unknown error.
* 2  invalid invocation environment (target missing, modules missing, etc.).
* 3  ``--upgrade`` requested but no manifest at target.

Stdlib only (argparse, pathlib, sys).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Bootstrap — make ``admin/install/`` importable as a package.
# ---------------------------------------------------------------------------

def _bootstrap_import_path() -> Path:
    """Insert this script's parent dir on ``sys.path`` so ``admin.install.*``
    imports resolve. Returns the resolved sb-os repo root."""
    repo_root = Path(__file__).resolve().parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    return repo_root


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description=(
            "sb-os installer. Bootstraps a clean PARA vault (--fresh) or "
            "refreshes an existing install (--upgrade). Mode is auto-detected "
            "from the presence of sb-os.json at the target root unless "
            "explicitly overridden."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Mode auto-detection:\n"
            "  sb-os.json present at target  -> default --upgrade\n"
            "  sb-os.json absent at target   -> default --fresh\n"
            "\n"
            "Examples:\n"
            "  python install.py\n"
            "  python install.py --target /path/to/vault\n"
            "  python install.py --fresh --dry-run\n"
            "  python install.py --upgrade\n"
        ),
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--fresh",
        action="store_true",
        help="Force fresh-install mode (bootstrap a clean vault).",
    )
    mode_group.add_argument(
        "--upgrade",
        action="store_true",
        help="Force upgrade mode (refresh an existing install).",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Print every planned action without writing. Combinable with --fresh/--upgrade.",
    )

    parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="Target vault root. Defaults to the current working directory.",
    )
    parser.add_argument(
        "target_positional",
        nargs="?",
        default=None,
        metavar="TARGET",
        help="Target vault root (positional alternative to --target).",
    )

    # Advanced overrides used by the mode handlers (documented for power users).
    parser.add_argument(
        "--sb-os-source",
        dest="sb_os_source",
        type=str,
        default=None,
        help="Path to the sb-os source repo (default: this script's directory).",
    )
    parser.add_argument(
        "--sb-os-path",
        dest="sb_os_path",
        type=str,
        default=None,
        help="Vault-relative path baked into thin loaders (default: auto-detect).",
    )
    parser.add_argument(
        "--wiki-root",
        dest="wiki_root",
        type=str,
        default=None,
        help="Wiki root path (default: prompted on --fresh, preserved on --upgrade).",
    )
    parser.add_argument(
        "--user-context-root",
        dest="user_context_root",
        type=str,
        default=None,
        help="User-context root (default: prompted on --fresh, preserved on --upgrade).",
    )
    return parser


# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------

def _resolve_target(args: argparse.Namespace) -> Path:
    """Pick the target root from --target, positional arg, or cwd (in that
    order). Returns an absolute resolved Path."""
    raw = args.target or args.target_positional or "."
    return Path(raw).expanduser().resolve()


def _validate_runtime_env(repo_root: Path) -> int:
    """Confirm the script can find its sibling installer modules. Returns 0
    when the environment is sane, 2 otherwise."""
    install_pkg = repo_root / "admin" / "install"
    expected = ("fresh.py", "upgrade.py", "dry_run.py", "cli.py", "manifest.py")
    missing = [name for name in expected if not (install_pkg / name).is_file()]
    if missing:
        sys.stderr.write(
            "error: sb-os installer modules not found at "
            f"{install_pkg}.\n"
            f"  missing: {', '.join(missing)}\n"
            "  Run install.py from the cloned sb-os repo root.\n"
        )
        return 2
    return 0


def _validate_target_dir(target: Path, *, fresh_mode: bool) -> int:
    """Validate the target path. Returns 0 when ok, 2 otherwise.

    On --fresh the target may not yet exist (fresh.py creates it). On
    --upgrade the target MUST exist and be a directory.
    """
    if target.exists():
        if not target.is_dir():
            sys.stderr.write(
                f"error: target {target} exists and is not a directory.\n"
            )
            return 2
        return 0
    if fresh_mode:
        # fresh.py will create the dir.
        return 0
    sys.stderr.write(f"error: target {target} does not exist.\n")
    return 2


# ---------------------------------------------------------------------------
# Mode resolution
# ---------------------------------------------------------------------------

def _resolve_mode(
    args: argparse.Namespace, target: Path, manifest_module
) -> tuple[str, int]:
    """Return ``(mode, exit_code)``. ``exit_code`` is non-zero only when the
    invocation is invalid (e.g. --upgrade without manifest); ``mode`` is
    "fresh" or "upgrade" on success.
    """
    has_manifest = (target / manifest_module.MANIFEST_FILENAME).is_file()

    if args.fresh and args.upgrade:
        # argparse already enforces this — defensive.
        sys.stderr.write("error: --fresh and --upgrade are mutually exclusive.\n")
        return ("", 2)

    if args.upgrade:
        if not has_manifest:
            sys.stderr.write(
                f"error: --upgrade requested but no {manifest_module.MANIFEST_FILENAME} "
                f"at {target}.\n"
                "  Use --fresh to bootstrap a new vault, or seed the manifest first.\n"
            )
            return ("", 3)
        return ("upgrade", 0)

    if args.fresh:
        if has_manifest:
            # Destructive override — confirm before proceeding.
            sys.stderr.write(
                f"warning: {manifest_module.MANIFEST_FILENAME} already exists at "
                f"{target}.\n"
                "  --fresh against an existing install will overwrite the manifest "
                "and rewrite managed files.\n"
            )
            try:
                answer = input("Continue with --fresh anyway? [y/N]: ").strip().lower()
            except EOFError:
                answer = ""
            if answer not in {"y", "yes"}:
                sys.stderr.write("aborted.\n")
                return ("", 1)
        return ("fresh", 0)

    # Auto-detect.
    return ("upgrade" if has_manifest else "fresh", 0)


def _check_sb_os_path_drift(
    args: argparse.Namespace,
    target: Path,
    repo_root: Path,
    manifest_module,
) -> None:
    """Warn (do NOT abort) when an --upgrade is run from a clone whose
    location differs from the loader paths recorded in the existing manifest.
    Repo-relocation is normal — surface it but proceed.
    """
    existing = manifest_module.read(target)
    if not existing:
        return
    recorded = existing.get("created_paths") or []
    # Heuristic: if any recorded loader points at a path that isn't this
    # script's location relative to the target, flag it. We don't enforce —
    # the loader paths can validly differ across machines.
    try:
        rel_repo = repo_root.relative_to(target)
        rel_repo_str = str(rel_repo).replace("\\", "/").rstrip("/") + "/"
    except ValueError:
        rel_repo_str = None

    if rel_repo_str is None:
        sys.stderr.write(
            f"note: sb-os repo at {repo_root} is outside the target vault "
            f"{target}. Loaders will fall back to the configured default path.\n"
        )
        return

    # If a sample loader exists, peek at its content to see whether it points
    # at this repo. We only warn — fresh.py / upgrade.py do the real work.
    sample = target / ".claude" / "skills" / "sb-vault-ops" / "SKILL.md"
    if sample.is_file():
        try:
            text = sample.read_text(encoding="utf-8")
        except OSError:
            return
        if rel_repo_str.rstrip("/") not in text:
            sys.stderr.write(
                f"note: existing loaders do not appear to point at this sb-os "
                f"clone ({rel_repo_str}). Proceeding — loaders will be "
                "rewritten to point here on this run.\n"
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    repo_root = _bootstrap_import_path()

    parser = _build_parser()
    args = parser.parse_args(argv)

    # Sanity: installer modules present.
    code = _validate_runtime_env(repo_root)
    if code != 0:
        return code

    # Import handlers AFTER bootstrap so the `admin.install` package resolves.
    from admin.install import dry_run as dry_run_mod
    from admin.install import fresh as fresh_mod
    from admin.install import manifest as manifest_mod
    from admin.install import upgrade as upgrade_mod
    from admin.install import cli as cli_mod

    target = _resolve_target(args)

    code = _validate_target_dir(target, fresh_mode=args.fresh or not args.upgrade)
    if code != 0:
        return code

    mode, code = _resolve_mode(args, target, manifest_mod)
    if code != 0:
        return code

    if mode == "upgrade":
        _check_sb_os_path_drift(args, target, repo_root, manifest_mod)

    plan = cli_mod.Plan()

    if args.dry_run:
        return dry_run_mod.run_dry_run(target, args, mode, plan)
    if mode == "fresh":
        return fresh_mod.run_fresh(target, args, plan)
    return upgrade_mod.run_upgrade(target, args, plan)


if __name__ == "__main__":
    sys.exit(main())
