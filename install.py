#!/usr/bin/env python3
"""install.py — sb-os installer entry point.

Interactive bootstrap or refresh of an sb-os vault. The installer:

* Walks upward from cwd looking for ``sb-os.json``.
* If found, offers to upgrade that install.
* Otherwise prompts for a target vault path. If the typed path holds an
  ``sb-os.json``, runs upgrade; otherwise runs fresh.
* On fresh, offers a dry-run preview before any writes, then bootstraps a
  clean PARA vault and relocates the running sb-os clone into
  ``{target}/3-resources/tools/sb-os/`` as the final step.
* Lets the user select which modules and individual components to install.
  ``wiki`` is atomic — selecting it installs all wiki components plus the
  wiki folder + wiki CLAUDE.md; deselecting it skips all of them.

Run::

    python install.py
    python install.py --modules core,wiki,life-planner
    python install.py --non-interactive   # uses prior selection from sb-os.json

Stdlib only (pathlib, sys, argparse).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _bootstrap_import_path() -> Path:
    repo_root = Path(__file__).resolve().parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    return repo_root


def _validate_runtime_env(repo_root: Path) -> int:
    install_pkg = repo_root / "admin" / "install"
    expected = ("fresh.py", "upgrade.py", "cli.py", "manifest.py", "loaders.py")
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


def _resolve_target(cli_mod, manifest_mod, repo_root: Path) -> tuple[Path, bool]:
    found = cli_mod.find_manifest_upward(Path.cwd())
    if found is not None:
        print(f"  Found existing sb-os install at: {found}")
        if cli_mod.confirm("  Use this as the target?", default=True):
            return found, True

    # When the user runs install.py from inside the sb-os repo directory, cwd
    # IS the repo — not a sensible vault root.  Default to its parent instead.
    cwd = Path.cwd()
    default_target = str(repo_root.parent if cwd.resolve() == repo_root else cwd)
    target = cli_mod.prompt_target(default=default_target)

    has_manifest = (target / manifest_mod.MANIFEST_FILENAME).is_file()
    return target, has_manifest


def _resolve_selection(
    cli_mod,
    loaders_mod,
    manifest_mod,
    target: Path,
    args: argparse.Namespace,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return ``(selected_modules, excluded_components)``.

    Resolution order:
      1. ``--modules`` flag → use that selection, no customization pass.
      2. ``--non-interactive`` → use sb-os.json prior selection (or all modules).
      3. Interactive: show module checkbox, then optional component customization.
    """
    all_modules = loaders_mod.manifest_modules()
    always = [n for n, m in all_modules.items() if m.get("always_installed")]
    available = list(all_modules.keys())

    existing = manifest_mod.read(target) or {}
    prev_selected = existing.get("selected_modules") or None
    prev_excluded = existing.get("excluded_components") or []

    if args.modules:
        chosen = [m.strip() for m in args.modules.split(",") if m.strip()]
        for m in always:
            if m not in chosen:
                chosen.insert(0, m)
        for m in chosen:
            if m not in available:
                raise SystemExit(f"Unknown module: {m}")
        return tuple(chosen), tuple(prev_excluded)

    if args.non_interactive:
        chosen = prev_selected if prev_selected else available
        return tuple(chosen), tuple(prev_excluded)

    selected = cli_mod.prompt_modules(all_modules, prev_selected)
    excluded = cli_mod.prompt_module_components(all_modules, selected, prev_excluded)
    return tuple(selected), tuple(excluded)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install or upgrade sb-os in a target vault.")
    parser.add_argument("--target", type=Path, default=None, help="Target vault path (skips upward search).")
    parser.add_argument("--modules", type=str, default="", help="Comma-separated module names (skips interactive prompt).")
    parser.add_argument("--non-interactive", action="store_true", help="Use sb-os.json prior selection; no prompts.")
    args = parser.parse_args(argv)

    repo_root = _bootstrap_import_path()
    code = _validate_runtime_env(repo_root)
    if code != 0:
        return code

    from install import cli as cli_mod
    from install import fresh as fresh_mod
    from install import loaders as loaders_mod
    from install import manifest as manifest_mod
    from install import upgrade as upgrade_mod

    print(f"\n{cli_mod.bold('sb-os installer')} v{manifest_mod.VERSION}\n")

    if args.target is not None:
        target = args.target.expanduser().resolve()
        has_manifest = (target / manifest_mod.MANIFEST_FILENAME).is_file()
    else:
        target, has_manifest = _resolve_target(cli_mod, manifest_mod, repo_root)

    selected, excluded = _resolve_selection(
        cli_mod, loaders_mod, manifest_mod, target, args
    )

    if has_manifest:
        return upgrade_mod.run_upgrade(
            target, repo_root,
            selected_modules=selected,
            excluded_components=excluded,
        )

    print()
    preview = (
        not args.non_interactive
        and cli_mod.confirm(
            "Run a dry-run preview first? "
            f"{cli_mod.dim('(prints every planned action without writing files)')}",
            default=True,
        )
    )
    if preview:
        fresh_mod.dry_run_fresh(target, repo_root, selected, excluded)
        if not cli_mod.confirm("\nProceed with the actual install now?", default=True):
            cli_mod.abort("User declined.")
            return 1
        code = fresh_mod.run_fresh(
            target, repo_root,
            skip_confirm=True,
            selected_modules=selected,
            excluded_components=excluded,
        )
    else:
        code = fresh_mod.run_fresh(
            target, repo_root,
            skip_confirm=args.non_interactive,
            selected_modules=selected,
            excluded_components=excluded,
        )

    if code == 0:
        print()
        print(cli_mod.bold("Your vault is ready."))
        print("Open it in Claude Code and run  /sb-onboarder  to set up your PARA structure.\n")

    return code


if __name__ == "__main__":
    sys.exit(main())
