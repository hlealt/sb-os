"""Fresh install mode.

Bootstraps a clean vault per architecture §3:

* PARA folders + ``.user/`` + optional non-default wiki root.
* Managed CLAUDE.mds (marker-block protocol).
* Thin loaders for skills and commands.
* Verbatim rule copies in ``.claude/rules/``.
* Initial ``sb-os.json`` manifest.
* Auto-relocate of the running sb-os clone into
  ``{target}/3-resources/tools/sb-os/`` as the final step.

NEVER writes ``.claude/settings.json`` (architecture §8 + §10 item 14).
NEVER writes inside ``.user/`` except for the single templates carve-out
documented in architecture §3 — manifest-declared templates are installed
at their manifest-declared ``.user/`` targets (periodic-note templates,
finance investor policy skeletons) using install-if-missing semantics so
user edits are never overwritten.
NEVER ships ``_system/``.

Public API:
* ``run_fresh(target_root, sb_os_root, *, skip_confirm=False) -> int``
* ``dry_run_fresh(target_root, sb_os_root) -> int``
* ``build_fresh_plan(target_root, sb_os_root) -> cli.Plan``

Pure stdlib (pathlib, shutil).
"""
from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path
from typing import Iterable

from . import cli, finance, loaders, manifest, markers


# ---------------------------------------------------------------------------
# Inventory — what fresh ships
# ---------------------------------------------------------------------------
#
# SKILLS, COMMANDS, and RULES are derived from ``module-manifest.json``
# (read via ``loaders.py``). The manifest is the single source of truth for
# what the installer ships — adding a component is a JSON edit, not a
# Python edit.

SKILLS: tuple[tuple[str, str], ...] = loaders.manifest_skills()
COMMANDS: tuple[str, ...] = loaders.manifest_commands()
RULES: tuple[str, ...] = loaders.manifest_rules()
TEMPLATES: tuple[tuple[str, str], ...] = loaders.manifest_templates()

WIKI_MODULE_NAME = "wiki"
FINANCE_MODULE_NAME = "finance"


def _module_has_wiki_artifacts(modules: dict, selected: list[str] | tuple[str, ...]) -> bool:
    """True when any selected module declares ``wiki_artifacts: true``.

    Drives whether fresh creates the wiki folder + wiki CLAUDE.md.
    """
    for name in selected:
        if modules.get(name, {}).get("wiki_artifacts"):
            return True
    return False

# Managed CLAUDE.md source → destination map (architecture §4).
CLAUDE_MD_MAP: tuple[tuple[str, str], ...] = (
    ("para/claude-mds/root.md", "CLAUDE.md"),
    ("para/claude-mds/projects.md", "1-projects/CLAUDE.md"),
    ("para/claude-mds/areas.md", "2-areas/CLAUDE.md"),
    ("para/claude-mds/resources.md", "3-resources/CLAUDE.md"),
    ("para/claude-mds/archives.md", "4-archives/CLAUDE.md"),
    ("para/claude-mds/workbench.md", "5-workbench/CLAUDE.md"),
)

WIKI_CLAUDE_MD_SOURCE = "wiki/claude-mds/wiki.md"

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

# Canonical install location for the sb-os repo, vault-relative.
CANONICAL_SB_OS_REL = "3-resources/tools/sb-os"


# ---------------------------------------------------------------------------
# Plan-builder helpers
# ---------------------------------------------------------------------------

def _add_folder_actions(plan: cli.Plan, folders: Iterable[str]) -> None:
    for rel in folders:
        plan.add(cli.Action(category="folder", target=rel + "/"))


def _add_file_action(plan: cli.Plan, target: str, detail: str = "") -> None:
    plan.add(cli.Action(category="file", target=target, detail=detail))


def _add_loader_action(plan: cli.Plan, target: str, detail: str = "") -> None:
    plan.add(cli.Action(category="loader", target=target, detail=detail))


# ---------------------------------------------------------------------------
# File-system helpers
# ---------------------------------------------------------------------------

def _ensure_folder(target_root: Path, rel: str, created: list[str]) -> None:
    abs_path = target_root / rel
    abs_path.mkdir(parents=True, exist_ok=True)
    if rel + "/" not in created:
        created.append(rel + "/")


def _read_source(sb_os_root: Path, rel_source: str) -> str:
    src = sb_os_root / rel_source
    if not src.is_file():
        raise FileNotFoundError(
            f"sb-os source missing: {src}. The repo at {sb_os_root} is "
            f"incomplete — expected file {rel_source!r}. Re-clone sb-os."
        )
    return src.read_text(encoding="utf-8")


def _write_managed(
    target_root: Path,
    rel_target: str,
    source_text: str,
    created: list[str],
) -> None:
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
    source_rel: str,
    rule_filename: str,
    sb_os_loader_path: str,
    created: list[str],
) -> None:
    loaders.install_rule(
        target_root=target_root,
        sb_os_root=sb_os_root,
        source_rel=source_rel,
        rule_filename=rule_filename,
        sb_os_path=sb_os_loader_path,
    )
    rel = f".claude/rules/{rule_filename}"
    if rel not in created:
        created.append(rel)


# ---------------------------------------------------------------------------
# Auto-relocate
# ---------------------------------------------------------------------------

def _rmtree(path: Path) -> None:
    """Remove a directory tree, handling Windows read-only files (e.g. .git)."""
    def _on_error(func, fpath, excinfo):
        # Windows marks some .git object files read-only; chmod and retry.
        try:
            os.chmod(fpath, stat.S_IWRITE)
            func(fpath)
        except Exception:
            raise excinfo[1]
    shutil.rmtree(path, onerror=_on_error)

def _canonical_clone_path(target_root: Path) -> Path:
    return (target_root / CANONICAL_SB_OS_REL).resolve()


def _relocate_sb_os_clone(sb_os_root: Path, target_root: Path) -> None:
    """Move the running sb-os clone into ``{target}/3-resources/tools/sb-os/``.

    Runs as the LAST step of a fresh install — after manifest is written and
    no further reads from the clone are needed. Safe-guards:

    * No-op when the clone is already at the canonical path.
    * Skipped (with a warning) if the canonical path already exists.
    * Uses ``copytree`` then ``rmtree`` so the new copy is verified before
      the original is removed.
    * Tolerates a partial removal of the original — Windows file locks on
      ``.pyc`` cache files are common and harmless after the copy succeeds.
    """
    canonical = _canonical_clone_path(target_root)
    src = sb_os_root.resolve()
    if src == canonical:
        return  # already in place

    if canonical.exists():
        print(cli.yellow("\n  Skipped sb-os relocation:"))
        print(f"    canonical path already exists: {canonical}")
        print(f"    current clone:                 {src}")
        print(cli.dim(
            "  (Loaders point at the canonical path; the clone you ran "
            "from will not be moved.)"
        ))
        return

    canonical.parent.mkdir(parents=True, exist_ok=True)

    # Guard: if canonical is inside src (e.g. the user ran the installer from
    # the vault root that IS the sb-os clone), copytree would recurse
    # infinitely into the destination it is creating.  Detect this, exclude
    # the destination subtree from the copy, and skip the rmtree — deleting
    # src would destroy the vault root.
    src_contains_canonical = False
    try:
        rel = canonical.relative_to(src)
        src_contains_canonical = True
        _skip_top = rel.parts[0]
        _base_ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
        def _ignore(directory: str, contents: list[str],
                    _skip: str = _skip_top,
                    _base: "Callable[[str, list[str]], set[str]]" = _base_ignore
                    ) -> set[str]:
            ignored = _base(directory, contents)
            if Path(directory).resolve() == src:
                ignored = ignored | {_skip}
            return ignored
        ignore_fn = _ignore
    except ValueError:
        ignore_fn = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")

    shutil.copytree(src, canonical, ignore=ignore_fn)
    removal_failed: Exception | None = None
    if src_contains_canonical:
        removal_failed = None  # cannot rmtree src — it is the vault root
    else:
        try:
            # On Windows, rmtree fails with WinError 32 if the process's cwd
            # is inside the tree being deleted.  Move out first.
            if Path.cwd().resolve().is_relative_to(src):
                os.chdir(target_root)
            _rmtree(src)
        except OSError as exc:
            removal_failed = exc

    print()
    print(cli.green("  Relocated sb-os clone:"))
    print(f"    {src}")
    print(f"    -> {canonical}")
    if src_contains_canonical:
        print(cli.dim(
            "  Original not removed: it is a parent of the canonical path."
        ))
    elif removal_failed is not None:
        print(cli.yellow(
            f"  Could not remove the original ({removal_failed}). Delete "
            f"{src} manually when convenient."
        ))
    print(cli.dim(
        "  Note: if your shell was cd'd into the old clone path, its cwd "
        "is now stale. cd to the new path to keep working in the repo."
    ))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_target(target_root: Path, sb_os_root: Path | None = None) -> bool:
    """Validate the target dir is empty OR confirm with the user."""
    if not target_root.exists():
        target_root.mkdir(parents=True, exist_ok=True)
        return True
    if not target_root.is_dir():
        print(cli.red(f"Target {target_root} exists and is not a directory."))
        return False
    # Exclude the sb-os clone itself — it is the installer's own source, not
    # pre-existing user content, and will be relocated during the install.
    exclude: set[Path] = {sb_os_root.resolve()} if sb_os_root else set()
    entries = [
        p for p in target_root.iterdir()
        if p.name not in {".git"} and p.resolve() not in exclude
    ]
    if not entries:
        return True
    print(cli.yellow(
        f"Target {target_root} contains existing entries. The installer "
        "writes only what sb-os ships and never overwrites unrelated "
        "files, but verify the listing below."
    ))
    for p in sorted(entries)[:20]:
        print(f"  {p.name}")
    if len(entries) > 20:
        print(f"  ... and {len(entries) - 20} more")
    return cli.confirm(
        "Continue with the install in this non-empty directory?",
        default=False,
    )


# ---------------------------------------------------------------------------
# Plan construction
# ---------------------------------------------------------------------------

def build_fresh_plan(
    target_root: Path,
    sb_os_root: Path,
    selected_modules: tuple[str, ...] | None = None,
    excluded_components: tuple[str, ...] | None = None,
    finance_dashboard_html_path: str = cli.DEFAULT_FINANCE_DASHBOARD_HTML_PATH,
) -> cli.Plan:
    """Build the planned-action list for a fresh install. Pure — no FS writes."""
    plan = cli.Plan()
    wiki_root = cli.detect_wiki_default_root(target_root)
    user_context_root = cli.DEFAULT_USER_CONTEXT_ROOT

    all_modules = loaders.manifest_modules()
    selected = selected_modules or tuple(all_modules.keys())
    excluded = set(excluded_components or ())
    modules_scoped = loaders.select_modules(selected)
    install_wiki = _module_has_wiki_artifacts(all_modules, selected)

    # Folders
    _add_folder_actions(plan, PARA_FOLDERS)
    plan.add(cli.Action(category="folder", target=".user/", detail="user-owned root"))
    if install_wiki and wiki_root.rstrip("/") != "3-resources/knowledge-base":
        plan.add(cli.Action(category="folder", target=wiki_root, detail="wiki root"))

    # Managed CLAUDE.mds (always — these are vault structure, not module components)
    for source_rel, dest_rel in CLAUDE_MD_MAP:
        _add_file_action(plan, dest_rel, detail=f"managed (source: {source_rel})")
    if install_wiki:
        wiki_claude_md = wiki_root.rstrip("/") + "/CLAUDE.md"
        _add_file_action(plan, wiki_claude_md, detail=f"managed (source: {WIKI_CLAUDE_MD_SOURCE})")

    # Loaders + rules for selected modules
    skills = loaders.manifest_skills(modules_scoped, excluded)
    commands = loaders.manifest_commands(modules_scoped, excluded)
    rules = loaders.manifest_rules(modules_scoped, excluded)
    templates = loaders.manifest_templates(modules_scoped, excluded)
    for name, _desc, _module in skills:
        _add_loader_action(plan, f".claude/skills/{name}/SKILL.md")
    for name, _module in commands:
        _add_loader_action(plan, f".claude/commands/{name}.md")
    for filename, _module in rules:
        _add_file_action(plan, f".claude/rules/{filename}", detail="rule (verbatim copy)")
    for _src, target_rel in templates:
        _add_file_action(plan, target_rel, detail="template (install-if-missing)")

    # Finance dashboard entry HTML — rendered from the module template with
    # vault-root-absolute asset paths (see install/finance.py).
    if FINANCE_MODULE_NAME in selected:
        _add_file_action(
            plan,
            finance_dashboard_html_path,
            detail="finance dashboard entry HTML (rendered, install-if-missing)",
        )

    # Manifest
    plan.add(cli.Action(
        category="manifest",
        target=manifest.MANIFEST_FILENAME,
        detail=f"mode=fresh, wiki_root={wiki_root}, user_context_root={user_context_root}",
    ))

    # sb-os relocation — included in the plan when the clone is not already
    # at the canonical path. The action category is reused to keep the plan
    # display compact; categories drive only the section grouping.
    canonical = _canonical_clone_path(target_root)
    if sb_os_root.resolve() != canonical:
        plan.add(cli.Action(
            category="manifest",
            target=f"{CANONICAL_SB_OS_REL}/",
            detail=f"relocate sb-os clone from {sb_os_root}",
        ))

    return plan


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def dry_run_fresh(
    target_root: Path | str,
    sb_os_root: Path | str,
    selected_modules: tuple[str, ...] | None = None,
    excluded_components: tuple[str, ...] | None = None,
    finance_dashboard_html_path: str = cli.DEFAULT_FINANCE_DASHBOARD_HTML_PATH,
) -> int:
    """Print the planned-action list without writing anything."""
    target_root = Path(target_root)
    sb_os_root = Path(sb_os_root).resolve()
    plan = build_fresh_plan(
        target_root, sb_os_root, selected_modules, excluded_components,
        finance_dashboard_html_path,
    )
    cli.print_plan(plan.actions)
    print(cli.cyan("\n[Preview — no files will be written]"))
    return 0


def run_fresh(
    target_root: Path | str,
    sb_os_root: Path | str,
    *,
    skip_confirm: bool = False,
    selected_modules: tuple[str, ...] | None = None,
    excluded_components: tuple[str, ...] | None = None,
    finance_dashboard_html_path: str | None = None,
) -> int:
    """Execute the fresh install flow.

    ``skip_confirm`` skips the in-mode "Proceed?" prompt — used when the
    caller already showed the plan as a dry-run preview and the user
    already confirmed.

    ``finance_dashboard_html_path`` is the finance entry-HTML knob the
    caller resolved (prompted on interactive fresh installs); None falls
    back to the default. Ignored when the finance module is not selected.

    Returns 0 on success, 1 on abort or error.
    """
    target_root = Path(target_root)
    sb_os_root = Path(sb_os_root).resolve()
    sb_os_loader_path = cli.DEFAULT_SB_OS_PATH
    wiki_root = cli.detect_wiki_default_root(target_root)
    finance_html_path = (
        finance_dashboard_html_path or cli.DEFAULT_FINANCE_DASHBOARD_HTML_PATH
    )

    if not _validate_target(target_root, sb_os_root):
        return 1

    all_modules = loaders.manifest_modules()
    selected = tuple(selected_modules) if selected_modules else tuple(all_modules.keys())
    excluded = tuple(excluded_components or ())
    finance_selected = FINANCE_MODULE_NAME in selected

    if not skip_confirm:
        plan = build_fresh_plan(
            target_root, sb_os_root, selected, excluded, finance_html_path
        )
        cli.print_plan(plan.actions)
        if not cli.confirm("\nProceed with the install?", default=True):
            cli.abort("User declined.")
            return 1

    created: list[str] = []
    try:
        _execute_fresh(
            target_root=target_root,
            sb_os_root=sb_os_root,
            sb_os_loader_path=sb_os_loader_path,
            wiki_root=wiki_root,
            created=created,
            selected_modules=selected,
            excluded_components=set(excluded),
            finance_dashboard_html_path=finance_html_path,
        )
    except FileNotFoundError as exc:
        cli.abort(str(exc))
        return 1

    initial = manifest.create_initial(
        vault_root=target_root,
        mode="fresh",
        wiki_root=wiki_root,
        user_context_root=cli.DEFAULT_USER_CONTEXT_ROOT,
        sb_os_path=sb_os_loader_path,
        created_paths=created,
        selected_modules=list(selected),
        excluded_components=list(excluded),
        finance_dashboard_html_path=finance_html_path if finance_selected else None,
    )
    manifest.write(target_root, initial)
    created.append(manifest.MANIFEST_FILENAME)

    print(f"\n{cli.green('Fresh install complete.')}")
    print(f"  Vault root: {target_root}")
    print(f"  Manifest:   {target_root / manifest.MANIFEST_FILENAME}")

    # Last step — relocate the running clone into the canonical path.
    _relocate_sb_os_clone(sb_os_root, target_root)
    return 0


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _execute_fresh(
    target_root: Path,
    sb_os_root: Path,
    sb_os_loader_path: str,
    wiki_root: str,
    created: list[str],
    selected_modules: tuple[str, ...],
    excluded_components: set[str],
    finance_dashboard_html_path: str = cli.DEFAULT_FINANCE_DASHBOARD_HTML_PATH,
) -> None:
    all_modules = loaders.manifest_modules()
    install_wiki = _module_has_wiki_artifacts(all_modules, selected_modules)
    modules_scoped = loaders.select_modules(selected_modules)

    # Folders
    for rel in PARA_FOLDERS:
        _ensure_folder(target_root, rel, created)
    _ensure_folder(target_root, ".user", created)
    if install_wiki:
        wiki_rel = wiki_root.rstrip("/")
        _ensure_folder(target_root, wiki_rel or "3-resources/knowledge-base", created)

    # Managed CLAUDE.mds (vault structure — always)
    for source_rel, dest_rel in CLAUDE_MD_MAP:
        inside = _read_source(sb_os_root, source_rel)
        _write_managed(target_root, dest_rel, inside, created)
    if install_wiki:
        wiki_claude_inside = _read_source(sb_os_root, WIKI_CLAUDE_MD_SOURCE)
        wiki_claude_dest = wiki_root.rstrip("/") + "/CLAUDE.md"
        _write_managed(target_root, wiki_claude_dest, wiki_claude_inside, created)

    # Loaders
    for name, desc, module in loaders.manifest_skills(modules_scoped, excluded_components):
        loaders.install_skill_loader(
            target_root=target_root,
            name=name,
            sb_os_path=sb_os_loader_path,
            module=module,
            description=desc,
        )
        rel = f".claude/skills/{name}/SKILL.md"
        if rel not in created:
            created.append(rel)
    for name, module in loaders.manifest_commands(modules_scoped, excluded_components):
        loaders.install_command_loader(
            target_root=target_root,
            name=name,
            sb_os_path=sb_os_loader_path,
            module=module,
        )
        rel = f".claude/commands/{name}.md"
        if rel not in created:
            created.append(rel)

    # Rules
    for filename, source_rel, _module in loaders.manifest_rule_sources(
        modules_scoped, excluded_components
    ):
        _copy_rule(sb_os_root, target_root, source_rel, filename, sb_os_loader_path, created)

    # Templates — install-if-missing (preserves user customizations across re-runs)
    for source_rel, target_rel in loaders.manifest_templates(
        modules_scoped, excluded_components
    ):
        written = loaders.install_template_if_missing(
            target_root=target_root,
            sb_os_root=sb_os_root,
            source_rel=source_rel,
            target_rel=target_rel,
        )
        if written is not None and target_rel not in created:
            created.append(target_rel)

    # Finance dashboard entry HTML — rendered with vault-root-absolute asset
    # paths derived from sb_os_path; install-if-missing (never clobbers a
    # user-placed/edited entry HTML). See install/finance.py.
    if FINANCE_MODULE_NAME in selected_modules:
        written = finance.install_dashboard_if_missing(
            target_root=target_root,
            sb_os_root=sb_os_root,
            sb_os_path=sb_os_loader_path,
            html_path=finance_dashboard_html_path,
        )
        if written is not None and finance_dashboard_html_path not in created:
            created.append(finance_dashboard_html_path)


__all__ = [
    "run_fresh",
    "dry_run_fresh",
    "build_fresh_plan",
    "SKILLS",
    "COMMANDS",
    "RULES",
    "TEMPLATES",
    "CLAUDE_MD_MAP",
    "WIKI_CLAUDE_MD_SOURCE",
    "PARA_FOLDERS",
    "CANONICAL_SB_OS_REL",
]
