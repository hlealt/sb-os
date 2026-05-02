"""--fresh install mode.

Bootstraps a clean vault per architecture §3:

* PARA folders: ``0-periodic-notes/{daily,weekly,monthly,quarterly}/``,
  ``1-projects/``, ``2-areas/``, ``3-resources/``, ``4-archives/``,
  ``5-workbench/``.
* ``.user/`` directory marker (per Decisions Log #26 — installer creates the
  dir on ``--fresh`` so the configured ``user_context_root`` resolves; never
  writes inside it thereafter).
* ``{wiki_root}/`` directory if non-default (default
  ``3-resources/knowledge-base/`` already created above).
* Managed CLAUDE.mds — read each source in ``sb-os/claude-mds/<name>.md`` and
  write to its destination per architecture §4 destination map, wrapped in
  marker block ``<!-- sb:start v=1 -->...<!-- sb:end -->``.
* ``Home.md`` — read ``sb-os/dashboards/home.md`` and write to vault root
  with marker block.
* Thin loaders for every selected skill and command via ``loaders.py``.
* Rule copies — copy each ``sb-os/rules/<name>.md`` verbatim to
  ``.claude/rules/<name>.md``.
* Initial ``sb-os.json`` manifest at vault root with ``mode="fresh"``,
  ``wiki_root``, ``user_context_root``, and the full ``created_paths`` list.

NEVER writes ``.claude/settings.json`` (architecture §8 + §10 item 14).
NEVER writes inside ``.user/`` (architecture §3 + Decisions Log #26).
NEVER ships ``_system/``.

Public API: ``run_fresh(target_root, args, plan) -> int`` — returns process
exit code (0 success, 1 abort/error).

Pure stdlib (pathlib, shutil, datetime).
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable

from . import cli, loaders, manifest, markers


# ---------------------------------------------------------------------------
# Inventory — what `sb-os --fresh` ships in v1
# ---------------------------------------------------------------------------
#
# SKILLS, COMMANDS, and RULES are derived from ``module-manifest.json``
# (read via ``loaders.py``). The manifest is the single source of truth for
# what the installer ships — adding a component is a JSON edit, not a
# Python edit. Module-level evaluation keeps the existing import-time shape
# (``from .fresh import SKILLS, COMMANDS, RULES`` continues to work in
# upgrade.py and any test).

# Skills — each entry: (name, description used in loader frontmatter).
SKILLS: tuple[tuple[str, str], ...] = loaders.manifest_skills()

# Commands — each entry: command name (no .md extension).
COMMANDS: tuple[str, ...] = loaders.manifest_commands()

# Rules — copied verbatim from sb-os/rules/ to .claude/rules/.
RULES: tuple[str, ...] = loaders.manifest_rules()

# Managed CLAUDE.md source → destination map (architecture §4).
# Source paths are RELATIVE to the sb-os repo root.
# Destination paths are RELATIVE to the target vault root.
CLAUDE_MD_MAP: tuple[tuple[str, str], ...] = (
    ("claude-mds/root.md", "CLAUDE.md"),
    ("claude-mds/projects.md", "1-projects/CLAUDE.md"),
    ("claude-mds/areas.md", "2-areas/CLAUDE.md"),
    ("claude-mds/resources.md", "3-resources/CLAUDE.md"),
    ("claude-mds/archives.md", "4-archives/CLAUDE.md"),
    ("claude-mds/workbench.md", "5-workbench/CLAUDE.md"),
)

# Wiki CLAUDE.md (conditional — written only when feature enabled).
WIKI_CLAUDE_MD_SOURCE = "claude-mds/wiki.md"

# Marker-managed dashboards (architecture §4 + Decisions Log #28).
DASHBOARD_MAP: tuple[tuple[str, str], ...] = (
    ("dashboards/home.md", "Home.md"),
)

# Folders the installer creates on --fresh (architecture §3 expected shape).
PARA_FOLDERS: tuple[str, ...] = (
    "0-periodic-notes",
    "0-periodic-notes/daily",
    "0-periodic-notes/weekly",
    "0-periodic-notes/monthly",
    "0-periodic-notes/quarterly",
    "1-projects",
    "2-areas",
    "3-resources",
    "4-archives",
    "5-workbench",
)


# ---------------------------------------------------------------------------
# Plan-builder helpers
# ---------------------------------------------------------------------------

def _add_folder_actions(plan: cli.Plan, folders: Iterable[str]) -> None:
    for rel in folders:
        plan.add(cli.Action(category="folder", target=rel + "/"))


def _add_file_action(
    plan: cli.Plan, target: str, detail: str = ""
) -> None:
    plan.add(cli.Action(category="file", target=target, detail=detail))


def _add_loader_action(
    plan: cli.Plan, target: str, detail: str = ""
) -> None:
    plan.add(cli.Action(category="loader", target=target, detail=detail))


# ---------------------------------------------------------------------------
# File-system helpers (skipped when dry-run)
# ---------------------------------------------------------------------------

def _ensure_folder(target_root: Path, rel: str, created: list[str]) -> None:
    abs_path = target_root / rel
    abs_path.mkdir(parents=True, exist_ok=True)
    if rel + "/" not in created:
        created.append(rel + "/")


def _read_source(sb_os_root: Path, rel_source: str) -> str:
    """Read a source file from the sb-os repo. Raises FileNotFoundError with
    a clear remediation hint when missing — sb-os repo is the source of
    truth, so a missing source means the repo is incomplete."""
    src = sb_os_root / rel_source
    if not src.is_file():
        raise FileNotFoundError(
            f"sb-os source missing: {src}. The repo at {sb_os_root} is "
            f"incomplete — expected file {rel_source!r}. Re-clone sb-os or "
            "verify your --sb-os-source argument."
        )
    return src.read_text(encoding="utf-8")


def _write_managed(
    target_root: Path,
    rel_target: str,
    source_text: str,
    created: list[str],
) -> None:
    """Write a fresh managed file.

    ``source_text`` is the FULL source-file content read from
    ``sb-os/claude-mds/<name>.md`` or ``sb-os/dashboards/<name>.md``. When
    the source already carries the ``<!-- sb:start v=1 -->...<!-- sb:end -->``
    pair (the v1 convention — the source IS the install template), the
    destination is written verbatim. When the source lacks markers, wrap it
    so the destination still satisfies the marker-block protocol.
    """
    abs_path = target_root / rel_target
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    if markers.parse(source_text) is None:
        content = markers.wrap(source_text)
    else:
        content = source_text
    abs_path.write_text(content, encoding="utf-8")
    if rel_target not in created:
        created.append(rel_target)


def _copy_rule(
    sb_os_root: Path,
    target_root: Path,
    rule_name: str,
    created: list[str],
) -> None:
    src = sb_os_root / "rules" / rule_name
    if not src.is_file():
        raise FileNotFoundError(
            f"sb-os rule source missing: {src}. Re-clone the sb-os repo."
        )
    dst = target_root / ".claude" / "rules" / rule_name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    rel = f".claude/rules/{rule_name}"
    if rel not in created:
        created.append(rel)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_fresh(
    target_root: Path | str,
    args,
    plan: cli.Plan | None = None,
) -> int:
    """Execute the ``--fresh`` install flow.

    ``args`` is the parsed argparse namespace from ``install.py``. The
    attributes consulted here are documented inline; ``getattr`` with a
    default is used so the helper can be invoked with a partial namespace
    in tests.

    ``plan`` is optional — if absent, a new ``cli.Plan`` is constructed.
    Passing one in lets ``dry_run.py`` reuse the same plan-builder logic
    while suppressing execution.

    Returns the process exit code (0 = success, 1 = abort or error).
    """
    target_root = Path(target_root)
    sb_os_root = _resolve_sb_os_root(args)
    sb_os_loader_path = _resolve_sb_os_loader_path(args, sb_os_root, target_root)
    dry_run = bool(getattr(args, "dry_run", False))
    plan = plan if plan is not None else cli.Plan()

    # ----- Empty-target validation ------------------------------------
    if not _validate_target(target_root, dry_run=dry_run):
        return 1

    # ----- Configurable paths -----------------------------------------
    wiki_root = _resolve_or_prompt(
        getattr(args, "wiki_root", None),
        cli.prompt_wiki_root,
        cli.DEFAULT_WIKI_ROOT,
    )
    user_context_root = _resolve_or_prompt(
        getattr(args, "user_context_root", None),
        cli.prompt_user_context_root,
        cli.DEFAULT_USER_CONTEXT_ROOT,
    )

    # ----- Build component opt-out list -------------------------------
    components = _build_component_inventory(wiki_root)
    if dry_run:
        # Dry-run keeps every component — there's nothing to install, only
        # something to print. Skip the interactive opt-out prompt entirely.
        kept = list(components)
    else:
        kept = cli.prompt_components(components, default_all_in=True)

    kept_names = {(c.kind, c.name) for c in kept}

    # ----- Build planned-action list ----------------------------------
    _build_plan(
        plan=plan,
        wiki_root=wiki_root,
        user_context_root=user_context_root,
        kept_names=kept_names,
        sb_os_loader_path=sb_os_loader_path,
    )

    # ----- Display + confirm -------------------------------------------
    if dry_run:
        cli.print_plan(plan.actions)
        print(f"\n{cli.cyan('Dry run — no files will be written.')}")
        return 0

    cli.print_plan(plan.actions)
    if not cli.confirm("\nProceed with --fresh install?", default=True):
        cli.abort("User declined.")
        return 1  # unreachable — abort raises SystemExit

    # ----- Execute -----------------------------------------------------
    created: list[str] = []
    try:
        _execute_fresh(
            target_root=target_root,
            sb_os_root=sb_os_root,
            sb_os_loader_path=sb_os_loader_path,
            wiki_root=wiki_root,
            user_context_root=user_context_root,
            kept_names=kept_names,
            created=created,
        )
    except FileNotFoundError as exc:
        # Clean error from _read_source / _copy_rule — surface and exit 1
        # without writing the manifest (partial install state is preserved
        # for the user to inspect and remediate).
        cli.abort(str(exc))
        return 1

    # ----- Write manifest ---------------------------------------------
    initial = manifest.create_initial(
        vault_root=target_root,
        mode="fresh",
        wiki_root=wiki_root,
        user_context_root=user_context_root,
        created_paths=created,
    )
    manifest.write(target_root, initial)
    created.append(manifest.MANIFEST_FILENAME)

    print(f"\n{cli.green('Fresh install complete.')}")
    print(f"  Vault root: {target_root}")
    print(f"  Manifest:   {target_root / manifest.MANIFEST_FILENAME}")
    return 0


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _resolve_sb_os_root(args) -> Path:
    """Locate the sb-os repo source on disk.

    Priority: ``--sb-os-source`` argparse flag → ``args.sb_os_source`` →
    auto-detect by walking up from this module's path (this module lives at
    ``<sb-os-root>/admin/install/fresh.py``).
    """
    explicit = getattr(args, "sb_os_source", None)
    if explicit:
        return Path(explicit).expanduser().resolve()
    # Auto-detect: this module is sb-os/admin/install/fresh.py
    return Path(__file__).resolve().parent.parent.parent


def _resolve_sb_os_loader_path(args, sb_os_root: Path, target_root: Path) -> str:
    """Vault-relative path that ends up baked into thin loaders.

    Priority:
    1. Explicit ``args.sb_os_path`` (already vault-relative string).
    2. Compute relative path from ``target_root`` to ``sb_os_root`` if
       ``sb_os_root`` is inside the vault.
    3. Fall back to ``cli.DEFAULT_SB_OS_PATH`` (``3-resources/tools/sb-os/``).
    """
    explicit = getattr(args, "sb_os_path", None)
    if explicit:
        return str(explicit)
    try:
        rel = sb_os_root.relative_to(target_root)
        return str(rel).replace("\\", "/")
    except ValueError:
        return cli.DEFAULT_SB_OS_PATH


def _resolve_or_prompt(value, prompt_fn, default: str) -> str:
    if value:
        return str(value)
    return prompt_fn(default=default)


def _validate_target(target_root: Path, dry_run: bool) -> bool:
    """Validate the target dir is empty OR confirm with the user.

    Returns True to continue, False to abort.
    """
    if not target_root.exists():
        target_root.mkdir(parents=True, exist_ok=True)
        return True
    if not target_root.is_dir():
        print(cli.red(f"Target {target_root} exists and is not a directory."))
        return False
    # Check for existing entries (ignore hidden VCS metadata only when
    # spotting "is this dir empty" — `.git` is normal in an existing repo).
    entries = [p for p in target_root.iterdir() if p.name not in {".git"}]
    if not entries:
        return True
    if dry_run:
        # Dry run never writes; warning only.
        print(
            cli.yellow(
                f"Target {target_root} is not empty. Dry run will still "
                "show the planned actions for documentation purposes."
            )
        )
        return True
    print(
        cli.yellow(
            f"Target {target_root} contains existing entries. --fresh "
            "writes only what sb-os ships and never overwrites unrelated "
            "files, but verify the listing below."
        )
    )
    for p in sorted(entries)[:20]:
        print(f"  {p.name}")
    if len(entries) > 20:
        print(f"  ... and {len(entries) - 20} more")
    return cli.confirm(
        "Continue with --fresh install in this non-empty directory?",
        default=False,
    )


def _build_component_inventory(wiki_root: str) -> list[cli.Component]:
    components: list[cli.Component] = []
    for name, desc in SKILLS:
        components.append(
            cli.Component(
                name=name,
                kind="skill",
                target=f".claude/skills/{name}/SKILL.md",
                description=desc,
            )
        )
    for name in COMMANDS:
        components.append(
            cli.Component(
                name=name,
                kind="command",
                target=f".claude/commands/{name}.md",
                description="",
            )
        )
    # Rules are not opt-out-able in v1: Claude Code auto-loads from
    # `.claude/rules/`, the rule set is small, and partial rule installs
    # break referenced behavior. They appear in the plan but not in the
    # opt-out picker.
    return components


def _build_plan(
    plan: cli.Plan,
    wiki_root: str,
    user_context_root: str,
    kept_names: set[tuple[str, str]],
    sb_os_loader_path: str,
) -> None:
    # Folders
    _add_folder_actions(plan, PARA_FOLDERS)
    plan.add(cli.Action(category="folder", target=".user/", detail="user-owned root"))
    # Wiki folder — only add if the wiki_root is non-default (default lives
    # under 3-resources/knowledge-base/ which is created lazily as needed).
    if wiki_root and wiki_root.rstrip("/") not in {"3-resources/knowledge-base"}:
        plan.add(
            cli.Action(category="folder", target=wiki_root, detail="wiki root")
        )

    # Managed CLAUDE.mds
    for source_rel, dest_rel in CLAUDE_MD_MAP:
        _add_file_action(plan, dest_rel, detail=f"managed (source: {source_rel})")
    # Wiki CLAUDE.md is conditional — always shipped in v1 (placeholder
    # per architecture §12) so the wiki slot is discoverable.
    wiki_claude_md = wiki_root.rstrip("/") + "/CLAUDE.md"
    _add_file_action(
        plan,
        wiki_claude_md,
        detail=f"managed (source: {WIKI_CLAUDE_MD_SOURCE})",
    )

    # Dashboards (Home.md)
    for source_rel, dest_rel in DASHBOARD_MAP:
        _add_file_action(plan, dest_rel, detail=f"managed (source: {source_rel})")

    # Loaders for kept skills and commands
    for name, _desc in SKILLS:
        if ("skill", name) in kept_names:
            _add_loader_action(plan, f".claude/skills/{name}/SKILL.md")
    for name in COMMANDS:
        if ("command", name) in kept_names:
            _add_loader_action(plan, f".claude/commands/{name}.md")

    # Rules (always-on)
    for rule in RULES:
        _add_file_action(plan, f".claude/rules/{rule}", detail="rule (verbatim copy)")

    # Manifest
    plan.add(
        cli.Action(
            category="manifest",
            target=manifest.MANIFEST_FILENAME,
            detail=f"mode=fresh, wiki_root={wiki_root}, user_context_root={user_context_root}",
        )
    )


def _execute_fresh(
    target_root: Path,
    sb_os_root: Path,
    sb_os_loader_path: str,
    wiki_root: str,
    user_context_root: str,
    kept_names: set[tuple[str, str]],
    created: list[str],
) -> None:
    # Folders
    for rel in PARA_FOLDERS:
        _ensure_folder(target_root, rel, created)
    # .user/ — created so the configured user_context_root resolves
    # (Decisions Log #26). Never written inside thereafter.
    _ensure_folder(target_root, ".user", created)
    # Wiki folder — create if non-default; if default, ensure the parent
    # exists (it does — 3-resources was just created above) and then create
    # the knowledge-base subdir lazily.
    wiki_rel = wiki_root.rstrip("/")
    if wiki_rel and wiki_rel != "3-resources/knowledge-base":
        _ensure_folder(target_root, wiki_rel, created)
    else:
        _ensure_folder(target_root, "3-resources/knowledge-base", created)

    # Managed CLAUDE.mds
    for source_rel, dest_rel in CLAUDE_MD_MAP:
        inside = _read_source(sb_os_root, source_rel)
        _write_managed(target_root, dest_rel, inside, created)
    # Wiki CLAUDE.md
    wiki_claude_inside = _read_source(sb_os_root, WIKI_CLAUDE_MD_SOURCE)
    wiki_claude_dest = wiki_rel + "/CLAUDE.md"
    _write_managed(target_root, wiki_claude_dest, wiki_claude_inside, created)

    # Dashboards
    for source_rel, dest_rel in DASHBOARD_MAP:
        inside = _read_source(sb_os_root, source_rel)
        _write_managed(target_root, dest_rel, inside, created)

    # Loaders
    for name, desc in SKILLS:
        if ("skill", name) in kept_names:
            loaders.install_skill_loader(
                target_root=target_root,
                name=name,
                sb_os_path=sb_os_loader_path,
                description=desc,
            )
            rel = f".claude/skills/{name}/SKILL.md"
            if rel not in created:
                created.append(rel)
    for name in COMMANDS:
        if ("command", name) in kept_names:
            loaders.install_command_loader(
                target_root=target_root,
                name=name,
                sb_os_path=sb_os_loader_path,
            )
            rel = f".claude/commands/{name}.md"
            if rel not in created:
                created.append(rel)

    # Rules — verbatim copies
    for rule in RULES:
        _copy_rule(sb_os_root, target_root, rule, created)


__all__ = ["run_fresh", "SKILLS", "COMMANDS", "RULES", "CLAUDE_MD_MAP", "DASHBOARD_MAP"]
