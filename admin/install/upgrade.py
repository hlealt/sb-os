"""--upgrade install mode.

Idempotent refresh of an existing sb-os install. Per architecture §6/§8:

* Read existing ``sb-os.json`` at vault root; abort if missing.
* For each managed CLAUDE.md and ``Home.md``:
  - Read the corresponding source from ``sb-os/claude-mds/<name>.md`` or
    ``sb-os/dashboards/<name>.md``.
  - Replace the content BETWEEN ``<!-- sb:start v=1 -->`` and
    ``<!-- sb:end -->`` markers verbatim.
  - Preserve content OUTSIDE the markers (user-owned).
  - If markers are missing on the target, abort the entire upgrade with
    ``markers.MissingMarkersError`` (no other files modified).
* Refresh thin loaders for skills and commands (always rewritten — §8).
* Refresh ``.claude/rules/`` files verbatim from ``sb-os/rules/`` (always
  rewritten — §8).
* NEVER create new top-level folders.
* NEVER touch ``.user/`` or ``.claude/settings.json``.
* NEVER touch user-edited content outside markers (rules excepted —
  rules are always rewritten verbatim per §8; document in the planned-action
  list so the user is not surprised).
* Update ``sb-os.json`` via ``manifest.update_for_upgrade(...)`` —
  ``mode`` flips to ``"upgrade"``, ``installed_at`` refreshed,
  ``wiki_root`` / ``user_context_root`` / ``created_paths`` preserved.

Public API: ``run_upgrade(target_root, args, plan) -> int``.

Pure stdlib.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable

from . import cli, loaders, manifest, markers
from .fresh import (
    CLAUDE_MD_MAP,
    COMMANDS,
    DASHBOARD_MAP,
    RULES,
    SKILLS,
    WIKI_CLAUDE_MD_SOURCE,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_upgrade(
    target_root: Path | str,
    args,
    plan: cli.Plan | None = None,
) -> int:
    """Execute the ``--upgrade`` install flow.

    Returns 0 on success, 1 on abort or error.
    """
    target_root = Path(target_root)
    sb_os_root = _resolve_sb_os_root(args)
    dry_run = bool(getattr(args, "dry_run", False))
    plan = plan if plan is not None else cli.Plan()

    # ----- Read existing manifest -------------------------------------
    existing = manifest.read(target_root)
    if existing is None:
        cli.abort(
            f"No {manifest.MANIFEST_FILENAME} at {target_root}. Run with "
            "--fresh to bootstrap, or seed the manifest first."
        )
        return 1  # unreachable — abort raises

    wiki_root = existing.get("wiki_root", cli.DEFAULT_WIKI_ROOT)
    user_context_root = existing.get(
        "user_context_root", cli.DEFAULT_USER_CONTEXT_ROOT
    )
    sb_os_loader_path = _resolve_sb_os_loader_path(args, sb_os_root, target_root)

    # ----- Pre-flight: validate every managed file has markers --------
    # This MUST happen before any write — per architecture §6, missing
    # markers abort the upgrade entirely; no file is modified until every
    # file has been verified.
    managed_targets = list(_iter_managed_targets(wiki_root))
    missing: list[Path] = []
    for rel_target in managed_targets:
        abs_target = target_root / rel_target
        if not abs_target.is_file():
            # Missing managed file — same severity as missing markers; the
            # user removed/renamed something the installer expects to update.
            missing.append(abs_target)
            continue
        try:
            markers.validate_markers(abs_target)
        except markers.MissingMarkersError:
            missing.append(abs_target)
        except markers.MarkerVersionError as exc:
            cli.abort(str(exc))
            return 1
    if missing:
        bullet = "\n".join(f"  - {p}" for p in missing)
        cli.abort(
            "Cannot --upgrade: the following managed files are missing "
            "their marker block (or the file itself is missing).\n"
            f"{bullet}\n\n"
            "Restore the markers (or the file) and re-run --upgrade. To "
            "regenerate from scratch, delete the file and re-run with "
            "--fresh, or restore a known-good copy from version control."
        )
        return 1

    # ----- Build planned-action list ----------------------------------
    _build_plan(
        plan=plan,
        wiki_root=wiki_root,
        user_context_root=user_context_root,
    )

    # ----- Display + confirm -------------------------------------------
    if dry_run:
        cli.print_plan(plan.actions)
        print(f"\n{cli.cyan('Dry run — no files will be written.')}")
        return 0

    cli.print_plan(plan.actions)
    print(
        cli.dim(
            "\nNote: rules in .claude/rules/ are rewritten verbatim from "
            "the sb-os repo on every --upgrade (architecture §8). Edits to "
            "those files will be lost. Edit at the source: sb-os/rules/."
        )
    )
    if not cli.confirm("\nProceed with --upgrade?", default=True):
        cli.abort("User declined.")
        return 1

    # ----- Execute -----------------------------------------------------
    try:
        _execute_upgrade(
            target_root=target_root,
            sb_os_root=sb_os_root,
            sb_os_loader_path=sb_os_loader_path,
            wiki_root=wiki_root,
        )
    except markers.MissingMarkersError as exc:
        # Defensive — pre-flight should have caught this.
        cli.abort(str(exc))
        return 1
    except FileNotFoundError as exc:
        cli.abort(str(exc))
        return 1

    # ----- Update manifest --------------------------------------------
    updated = manifest.update_for_upgrade(target_root)
    manifest.write(target_root, updated)

    print(f"\n{cli.green('Upgrade complete.')}")
    print(f"  Vault root: {target_root}")
    print(f"  Manifest:   {target_root / manifest.MANIFEST_FILENAME}")
    return 0


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _resolve_sb_os_root(args) -> Path:
    explicit = getattr(args, "sb_os_source", None)
    if explicit:
        return Path(explicit).expanduser().resolve()
    return Path(__file__).resolve().parent.parent.parent


def _resolve_sb_os_loader_path(args, sb_os_root: Path, target_root: Path) -> str:
    explicit = getattr(args, "sb_os_path", None)
    if explicit:
        return str(explicit)
    try:
        rel = sb_os_root.relative_to(target_root)
        return str(rel).replace("\\", "/")
    except ValueError:
        return cli.DEFAULT_SB_OS_PATH


def _iter_managed_targets(wiki_root: str) -> Iterable[str]:
    """Yield vault-relative paths to every marker-managed file."""
    for _src, dest in CLAUDE_MD_MAP:
        yield dest
    yield wiki_root.rstrip("/") + "/CLAUDE.md"
    for _src, dest in DASHBOARD_MAP:
        yield dest


def _read_source(sb_os_root: Path, rel_source: str) -> str:
    src = sb_os_root / rel_source
    if not src.is_file():
        raise FileNotFoundError(
            f"sb-os source missing: {src}. Re-clone the sb-os repo or "
            "verify your --sb-os-source argument."
        )
    return src.read_text(encoding="utf-8")


def _build_plan(
    plan: cli.Plan,
    wiki_root: str,
    user_context_root: str,
) -> None:
    # Marker-block refreshes
    for source_rel, dest_rel in CLAUDE_MD_MAP:
        plan.add(
            cli.Action(
                category="file",
                target=dest_rel,
                detail=f"replace marker block (source: {source_rel})",
            )
        )
    plan.add(
        cli.Action(
            category="file",
            target=wiki_root.rstrip("/") + "/CLAUDE.md",
            detail=f"replace marker block (source: {WIKI_CLAUDE_MD_SOURCE})",
        )
    )
    for source_rel, dest_rel in DASHBOARD_MAP:
        plan.add(
            cli.Action(
                category="file",
                target=dest_rel,
                detail=f"replace marker block (source: {source_rel})",
            )
        )
    # Loaders — always rewritten
    for name, _desc in SKILLS:
        plan.add(
            cli.Action(
                category="loader",
                target=f".claude/skills/{name}/SKILL.md",
                detail="rewrite",
            )
        )
    for name in COMMANDS:
        plan.add(
            cli.Action(
                category="loader",
                target=f".claude/commands/{name}.md",
                detail="rewrite",
            )
        )
    # Rules — always rewritten
    for rule in RULES:
        plan.add(
            cli.Action(
                category="file",
                target=f".claude/rules/{rule}",
                detail="rewrite (verbatim from sb-os/rules/)",
            )
        )
    # Manifest
    plan.add(
        cli.Action(
            category="manifest",
            target=manifest.MANIFEST_FILENAME,
            detail=f"mode=upgrade, refresh installed_at "
            f"(preserve wiki_root={wiki_root}, "
            f"user_context_root={user_context_root})",
        )
    )


def _execute_upgrade(
    target_root: Path,
    sb_os_root: Path,
    sb_os_loader_path: str,
    wiki_root: str,
) -> None:
    # Marker-block replacements
    for source_rel, dest_rel in CLAUDE_MD_MAP:
        inside = _read_source(sb_os_root, source_rel)
        markers.replace_managed(target_root / dest_rel, inside)
    wiki_claude_inside = _read_source(sb_os_root, WIKI_CLAUDE_MD_SOURCE)
    markers.replace_managed(
        target_root / (wiki_root.rstrip("/") + "/CLAUDE.md"),
        wiki_claude_inside,
    )
    for source_rel, dest_rel in DASHBOARD_MAP:
        inside = _read_source(sb_os_root, source_rel)
        markers.replace_managed(target_root / dest_rel, inside)

    # Loaders — always rewritten (§8)
    for name, desc in SKILLS:
        loaders.install_skill_loader(
            target_root=target_root,
            name=name,
            sb_os_path=sb_os_loader_path,
            description=desc,
        )
    for name in COMMANDS:
        loaders.install_command_loader(
            target_root=target_root,
            name=name,
            sb_os_path=sb_os_loader_path,
        )

    # Rules — verbatim copies (§8: always rewritten)
    for rule in RULES:
        src = sb_os_root / "rules" / rule
        if not src.is_file():
            raise FileNotFoundError(
                f"sb-os rule source missing: {src}. Re-clone the sb-os repo."
            )
        dst = target_root / ".claude" / "rules" / rule
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)


__all__ = ["run_upgrade"]
