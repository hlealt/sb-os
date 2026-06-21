"""Upgrade install mode.

Idempotent refresh of an existing sb-os install. Per architecture §6/§8:

* Read existing ``sb-os.json`` at vault root; abort if missing.
* For each managed CLAUDE.md:
  - Read the corresponding source from ``sb-os/claude-mds/<name>.md``.
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
  rules are always rewritten verbatim per §8).
* Update ``sb-os.json`` via ``manifest.update_for_upgrade(...)`` —
  ``mode`` flips to ``"upgrade"``, ``installed_at`` refreshed,
  ``wiki_root`` / ``user_context_root`` / ``created_paths`` preserved.

Public API: ``run_upgrade(target_root, sb_os_root, *,
skip_confirm=False, ...) -> int``.

Pure stdlib.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from . import cli, finance, hooks, loaders, manifest, markers
from .fresh import (
    CANONICAL_SB_OS_REL,
    CLAUDE_MD_MAP,
    CONTEXT_HOOK_COMPONENT,
    FINANCE_MODULE_NAME,
    WIKI_CLAUDE_MD_SOURCE,
    _module_has_wiki_artifacts,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_upgrade(
    target_root: Path | str,
    sb_os_root: Path | str,
    selected_modules: tuple[str, ...] | None = None,
    excluded_components: tuple[str, ...] | None = None,
    skip_confirm: bool = False,
) -> int:
    """Execute the upgrade flow. Returns 0 on success, 1 on abort or error.

    ``skip_confirm`` skips the "Proceed with the upgrade?" prompt — used by
    ``--non-interactive`` runs so scripted upgrades complete with zero
    prompts. The plan is still printed either way.
    """
    target_root = Path(target_root)
    sb_os_root = Path(sb_os_root).resolve()

    # ----- Read existing manifest -------------------------------------
    existing = manifest.read(target_root)
    if existing is None:
        cli.abort(
            f"No {manifest.MANIFEST_FILENAME} at {target_root}. Run from a "
            "fresh install location to bootstrap, or seed the manifest first."
        )
        return 1  # unreachable — abort raises

    wiki_root = existing.get("wiki_root", cli.DEFAULT_WIKI_ROOT)
    user_context_root = existing.get(
        "user_context_root", cli.DEFAULT_USER_CONTEXT_ROOT
    )
    # Finance entry-HTML knob: prompted only on fresh installs. On upgrade the
    # persisted value wins; older manifests without the field get the default
    # (back-filled into sb-os.json below).
    finance_html_path = (
        existing.get("finance_dashboard_html_path")
        or cli.DEFAULT_FINANCE_DASHBOARD_HTML_PATH
    )

    all_modules = loaders.manifest_modules()
    if selected_modules is None:
        prev = existing.get("selected_modules") or list(all_modules.keys())
        selected = tuple(prev)
    else:
        selected = tuple(selected_modules)
    if excluded_components is None:
        excluded = tuple(existing.get("excluded_components") or ())
    else:
        excluded = tuple(excluded_components)
    install_wiki = _module_has_wiki_artifacts(all_modules, selected)
    finance_selected = FINANCE_MODULE_NAME in selected

    # ----- Resolve loader path from clone location --------------------
    sb_os_loader_path = _loader_path_or_abort(sb_os_root, target_root)

    # ----- Pre-flight: validate every managed file has markers --------
    if not _preflight_markers(target_root, wiki_root, install_wiki):
        return 1

    # ----- Scan for orphaned loaders (renamed/removed components) -----
    orphaned_loaders = loaders.find_orphaned_loaders(
        target_root,
        sb_os_loader_path,
        known_targets=_all_manifest_loader_targets(),
        excluded=set(excluded),
    )
    # ----- Scan for orphaned rules (removed from manifest entirely) ---
    # Rules are not thin loaders, so find_orphaned_loaders never sees them.
    # This catches a rule whose manifest entry was dropped while its owning
    # module stays selected — de-selection + the stale flag are handled by
    # _clear_orphans below.
    orphaned_rules = loaders.find_orphaned_rules(
        target_root,
        known_rule_targets=_all_manifest_rule_targets(),
        excluded=set(excluded),
    )

    # ----- Build plan + confirm ---------------------------------------
    plan = build_upgrade_plan(
        wiki_root, user_context_root, selected, set(excluded), install_wiki,
        finance_dashboard_html_path=finance_html_path,
        orphaned_loaders=orphaned_loaders,
        orphaned_rules=orphaned_rules,
    )
    cli.print_plan(plan.actions)
    print(
        cli.dim(
            "\nNote: rules in .claude/rules/ are rewritten verbatim from "
            "the sb-os repo on every upgrade (architecture §8). Edits to "
            "those files will be lost. Edit at the source: sb-os/rules/."
        )
    )
    if not skip_confirm and not cli.confirm(
        "\nProceed with the upgrade?", default=True
    ):
        cli.abort("User declined.")
        return 1

    # ----- Execute -----------------------------------------------------
    try:
        _clear_orphans(target_root, selected, set(excluded))
        _prune_orphaned_loaders(target_root, orphaned_loaders)
        _prune_orphaned_rules(target_root, orphaned_rules)
        changed = _execute_upgrade(
            target_root=target_root,
            sb_os_root=sb_os_root,
            sb_os_loader_path=sb_os_loader_path,
            wiki_root=wiki_root,
            selected_modules=selected,
            excluded_components=set(excluded),
            install_wiki=install_wiki,
            finance_dashboard_html_path=finance_html_path,
        )
    except markers.MissingMarkersError as exc:
        cli.abort(str(exc))
        return 1
    except FileNotFoundError as exc:
        cli.abort(str(exc))
        return 1

    # ----- Update manifest --------------------------------------------
    # Pass sb_os_path with trailing slash so update_for_upgrade can back-fill
    # the field on manifests predating the v0.2.0 schema. update_for_upgrade
    # is idempotent — it will NOT overwrite an existing user-set value.
    sb_os_path_for_manifest = sb_os_loader_path.rstrip("/") + "/"
    updated = manifest.update_for_upgrade(
        target_root,
        sb_os_path=sb_os_path_for_manifest,
        selected_modules=list(selected),
        excluded_components=list(excluded),
        finance_dashboard_html_path=finance_html_path if finance_selected else None,
    )
    manifest.write(target_root, updated)

    # No-op signal: report how many installed files actually changed this run,
    # so a true no-op is self-evident from a single run rather than requiring a
    # cross-run diff. ``changed`` excludes the manifest timestamp refresh.
    print()
    if not changed:
        print(cli.green("Upgrade complete — already up to date (0 files changed)."))
    else:
        n = len(changed)
        print(cli.green(f"Upgrade complete — {n} file{'s' if n != 1 else ''} changed."))
        for rel in changed:
            print(f"  {cli.green('~')} {rel}")
    print(f"  Vault root: {target_root}")
    print(f"  Manifest:   {target_root / manifest.MANIFEST_FILENAME}")
    return 0


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _loader_path_or_abort(sb_os_root: Path, target_root: Path) -> str:
    """Return the vault-relative path baked into thin loaders.

    On upgrade the sb-os clone MUST live inside the target vault — loaders
    point at it via a relative path. If the running clone is outside the
    vault, the upgrade is unsafe (loaders would dangle): abort with a
    remediation hint.
    """
    try:
        rel = sb_os_root.relative_to(target_root)
    except ValueError:
        cli.abort(
            f"sb-os clone at {sb_os_root} is not inside the target vault "
            f"{target_root}.\n"
            f"Run install.py from inside the vault's sb-os clone, e.g.:\n"
            f"  cd {target_root / CANONICAL_SB_OS_REL}\n"
            f"  python install.py"
        )
        return ""  # unreachable — abort raises
    return str(rel).replace("\\", "/")


def _clear_orphans(
    target_root: Path,
    selected_modules: tuple[str, ...],
    excluded_components: set[str],
) -> None:
    """Remove sb-* loaders/rules that exist on disk but are no longer selected.

    Mirrors RBTV's clear_previous_install pattern but is selection-aware:
    only files that the new selection EXCLUDES are removed; files that will
    be rewritten by the upcoming install pass are left alone (no churn).
    """
    import shutil

    all_modules = loaders.manifest_modules()
    keep_modules = loaders.select_modules(selected_modules)
    keep_skill_targets = {
        e["target"].replace("\\", "/")
        for m in keep_modules.values() for e in m.get("skills", [])
        if e["target"].replace("\\", "/") not in excluded_components and not e.get("stale")
    }
    keep_command_targets = {
        e["target"].replace("\\", "/")
        for m in keep_modules.values() for e in m.get("commands", [])
        if e["target"].replace("\\", "/") not in excluded_components and not e.get("stale")
    }
    keep_rule_targets = {
        e["target"].replace("\\", "/")
        for m in keep_modules.values() for e in m.get("rules", [])
        if e["target"].replace("\\", "/") not in excluded_components and not e.get("stale")
    }

    all_skill_targets = {
        e["target"].replace("\\", "/")
        for m in all_modules.values() for e in m.get("skills", [])
    }
    all_command_targets = {
        e["target"].replace("\\", "/")
        for m in all_modules.values() for e in m.get("commands", [])
    }
    all_rule_targets = {
        e["target"].replace("\\", "/")
        for m in all_modules.values() for e in m.get("rules", [])
    }

    for rel in all_skill_targets - keep_skill_targets:
        skill_dir = target_root / Path(rel).parent
        if skill_dir.is_dir():
            shutil.rmtree(skill_dir)
    for rel in all_command_targets - keep_command_targets:
        f = target_root / rel
        if f.is_file():
            f.unlink()
    for rel in all_rule_targets - keep_rule_targets:
        f = target_root / rel
        if f.is_file():
            f.unlink()


def _all_manifest_loader_targets() -> set[str]:
    """Return every skill/command ``target`` across ALL modules, stale included.

    This is the orphan scan's "known" universe: anything the manifest has EVER
    declared under its current entries is handled by the selection-aware
    ``_clear_orphans`` path; only loaders absent from this set can be orphans
    left behind by a rename or removal.
    """
    out: set[str] = set()
    for mod in loaders.manifest_modules().values():
        for kind in ("skills", "commands"):
            for entry in mod.get(kind, []):
                target = entry.get("target", "")
                if target:
                    out.add(target.replace("\\", "/"))
    return out


def _all_manifest_rule_targets() -> set[str]:
    """Return every rule ``target`` across ALL modules, stale entries included.

    The rule orphan scan's "known" universe: any rule the manifest currently
    declares (stale too) is handled by the selection-aware ``_clear_orphans``
    path; only rule files absent from this set can be orphans left behind by a
    manifest removal. Mirrors ``_all_manifest_loader_targets`` for rules.
    """
    out: set[str] = set()
    for mod in loaders.manifest_modules().values():
        for entry in mod.get("rules", []):
            target = entry.get("target", "")
            if target:
                out.add(target.replace("\\", "/"))
    return out


def _prune_orphaned_rules(target_root: Path, orphans: Iterable[str]) -> None:
    """Delete orphaned rule files found by ``loaders.find_orphaned_rules``.

    Rules live flat in ``.claude/rules/`` — no enclosing per-component
    directory to clean up (unlike skill loaders), so this only unlinks each
    file. The ``is_file`` guard makes a double-delete (already removed by
    ``_clear_orphans``) a harmless no-op.
    """
    for rel in orphans:
        f = target_root / rel
        if f.is_file():
            f.unlink()


def _prune_orphaned_loaders(target_root: Path, orphans: Iterable[str]) -> None:
    """Delete orphaned loader files found by ``loaders.find_orphaned_loaders``.

    For skill loaders, the containing ``.claude/skills/<name>/`` directory is
    removed only when emptied by the deletion — user-added files inside the
    directory are never touched.
    """
    for rel in orphans:
        f = target_root / rel
        if f.is_file():
            f.unlink()
        parent = f.parent
        if (
            parent.parent.name == "skills"
            and parent.is_dir()
            and not any(parent.iterdir())
        ):
            parent.rmdir()


def _preflight_markers(target_root: Path, wiki_root: str, install_wiki: bool = True) -> bool:
    """Validate every managed file has its marker block before any write.

    Per architecture §6, missing markers abort the upgrade entirely; no file
    is modified until every file has been verified. Returns True when all
    files pass; False after calling cli.abort otherwise (False is unreachable
    because abort raises).
    """
    managed_targets = list(_iter_managed_targets(wiki_root, install_wiki))
    missing: list[Path] = []
    for rel_target in managed_targets:
        abs_target = target_root / rel_target
        if not abs_target.is_file():
            missing.append(abs_target)
            continue
        try:
            markers.validate_markers(abs_target)
        except markers.MissingMarkersError:
            missing.append(abs_target)
        except markers.MarkerVersionError as exc:
            cli.abort(str(exc))
            return False
    if missing:
        bullet = "\n".join(f"  - {p}" for p in missing)
        cli.abort(
            "Cannot upgrade: the following managed files are missing "
            "their marker block (or the file itself is missing).\n"
            f"{bullet}\n\n"
            "Restore the markers (or the file) and re-run the installer. "
            "To regenerate from scratch, delete the file and re-run from "
            "a fresh-install location, or restore a known-good copy from "
            "version control."
        )
        return False
    return True


def _iter_managed_targets(wiki_root: str, install_wiki: bool = True) -> Iterable[str]:
    """Yield vault-relative paths to every marker-managed file."""
    for _src, dest in CLAUDE_MD_MAP:
        yield dest
    if install_wiki:
        yield wiki_root.rstrip("/") + "/CLAUDE.md"


def _read_source(sb_os_root: Path, rel_source: str) -> str:
    src = sb_os_root / rel_source
    if not src.is_file():
        raise FileNotFoundError(
            f"sb-os source missing: {src}. Re-clone the sb-os repo."
        )
    return src.read_text(encoding="utf-8")


def build_upgrade_plan(
    wiki_root: str,
    user_context_root: str,
    selected_modules: tuple[str, ...] | None = None,
    excluded_components: set[str] | None = None,
    install_wiki: bool = True,
    finance_dashboard_html_path: str = cli.DEFAULT_FINANCE_DASHBOARD_HTML_PATH,
    orphaned_loaders: Iterable[str] = (),
    orphaned_rules: Iterable[str] = (),
) -> cli.Plan:
    """Build the planned-action list for an upgrade. Pure — no FS writes.

    ``orphaned_loaders`` and ``orphaned_rules`` are the pre-computed scan
    results from ``loaders.find_orphaned_loaders`` / ``find_orphaned_rules`` —
    surfaced in the plan so the user sees every planned deletion before the
    confirm prompt (architecture §6).
    """
    plan = cli.Plan()
    modules_scoped = loaders.select_modules(selected_modules)
    excl = excluded_components or set()
    finance_selected = (
        selected_modules is None or FINANCE_MODULE_NAME in selected_modules
    )

    for rel in orphaned_loaders:
        plan.add(cli.Action(
            category="delete",
            target=rel,
            detail="delete orphaned loader (no manifest entry: component renamed or removed)",
        ))
    for rel in orphaned_rules:
        plan.add(cli.Action(
            category="delete",
            target=rel,
            detail="delete orphaned rule (no manifest entry: rule removed while module stays selected)",
        ))

    for source_rel, dest_rel in CLAUDE_MD_MAP:
        plan.add(cli.Action(
            category="file",
            target=dest_rel,
            detail=f"replace marker block (source: {source_rel})",
        ))
    if install_wiki:
        plan.add(cli.Action(
            category="file",
            target=wiki_root.rstrip("/") + "/CLAUDE.md",
            detail=f"replace marker block (source: {WIKI_CLAUDE_MD_SOURCE})",
        ))
    for name, _desc, _module in loaders.manifest_skills(modules_scoped, excl):
        plan.add(cli.Action(
            category="loader",
            target=f".claude/skills/{name}/SKILL.md",
            detail="rewrite",
        ))
    for name, _desc, _module in loaders.manifest_commands(modules_scoped, excl):
        plan.add(cli.Action(
            category="loader",
            target=f".claude/commands/{name}.md",
            detail="rewrite",
        ))
    for filename, _module in loaders.manifest_rules(modules_scoped, excl):
        plan.add(cli.Action(
            category="file",
            target=f".claude/rules/{filename}",
            detail="rewrite (verbatim from sb-os module rules/)",
        ))
    for _src, target_rel in loaders.manifest_templates(modules_scoped, excl):
        plan.add(cli.Action(
            category="file",
            target=target_rel,
            detail="template (install-if-missing — skipped when target exists)",
        ))
    if finance_selected:
        plan.add(cli.Action(
            category="file",
            target=finance_dashboard_html_path,
            detail=(
                "finance dashboard entry HTML (rendered, install-if-missing "
                "— skipped when target exists)"
            ),
        ))
    plan.add(cli.Action(
        category="manifest",
        target=manifest.MANIFEST_FILENAME,
        detail=(
            f"mode=upgrade, refresh installed_at "
            f"(preserve wiki_root={wiki_root}, "
            f"user_context_root={user_context_root})"
        ),
    ))
    return plan


def _execute_upgrade(
    target_root: Path,
    sb_os_root: Path,
    sb_os_loader_path: str,
    wiki_root: str,
    selected_modules: tuple[str, ...],
    excluded_components: set[str],
    install_wiki: bool = True,
    finance_dashboard_html_path: str = cli.DEFAULT_FINANCE_DASHBOARD_HTML_PATH,
) -> list[str]:
    """Run the upgrade writes; return the vault-relative paths whose on-disk
    content actually changed.

    Every managed write is wrapped in ``_track`` so a write that produces
    byte-identical content is NOT reported as a change. The returned list
    drives the caller's no-op signal: an empty list means the run was a true
    no-op (every installed file already up to date). The ``sb-os.json``
    manifest refresh happens in ``run_upgrade`` and is deliberately excluded —
    its ``installed_at`` timestamp churns every run and is bookkeeping, not an
    installed-content change.
    """
    modules_scoped = loaders.select_modules(selected_modules)
    changed: list[str] = []

    def _track(dest: Path, write) -> None:
        """Run ``write`` (which writes ``dest``) and record ``dest`` as changed
        only when its content differs from before the write."""
        before = dest.read_text(encoding="utf-8") if dest.is_file() else None
        write()
        after = dest.read_text(encoding="utf-8") if dest.is_file() else None
        if after != before:
            changed.append(dest.relative_to(target_root).as_posix())

    # Context-injection hook — wire/unwire BOTH entries in
    # .claude/settings.local.json based on whether the context-injection-hook
    # component is excluded (decision D7/D10). Runs AFTER _clear_orphans (called
    # in run_upgrade) and BEFORE the rule rewrite below. Routed through _track so
    # the upgrade summary reports the hook changed/unchanged and a re-run reports
    # it as 0-changed.
    settings_dest = target_root / ".claude" / "settings.local.json"
    if CONTEXT_HOOK_COMPONENT in excluded_components:
        _track(settings_dest, lambda: hooks.remove_context_hook(target_root))
    else:
        _track(
            settings_dest,
            lambda: hooks.sync_context_hook(target_root, sb_os_loader_path),
        )

    # Marker-block replacements.
    for source_rel, dest_rel in CLAUDE_MD_MAP:
        inside = markers.extract_inside(_read_source(sb_os_root, source_rel))
        dest = target_root / dest_rel
        _track(dest, lambda dest=dest, inside=inside: markers.replace_managed(dest, inside))
    if install_wiki:
        wiki_claude_inside = markers.extract_inside(
            _read_source(sb_os_root, WIKI_CLAUDE_MD_SOURCE)
        )
        dest = target_root / (wiki_root.rstrip("/") + "/CLAUDE.md")
        _track(dest, lambda dest=dest, c=wiki_claude_inside: markers.replace_managed(dest, c))

    # Loaders — always rewritten (§8)
    for name, desc, module in loaders.manifest_skills(modules_scoped, excluded_components):
        dest = target_root / ".claude" / "skills" / name / "SKILL.md"
        _track(dest, lambda name=name, desc=desc, module=module: loaders.install_skill_loader(
            target_root=target_root,
            name=name,
            sb_os_path=sb_os_loader_path,
            module=module,
            description=desc,
        ))
    for name, desc, module in loaders.manifest_commands(modules_scoped, excluded_components):
        dest = target_root / ".claude" / "commands" / f"{name}.md"
        _track(dest, lambda name=name, desc=desc, module=module: loaders.install_command_loader(
            target_root=target_root,
            name=name,
            sb_os_path=sb_os_loader_path,
            module=module,
            description=desc,
        ))

    # Rules — copies with placeholder substitution (§8: always rewritten)
    for filename, source_rel, _module in loaders.manifest_rule_sources(
        modules_scoped, excluded_components
    ):
        dest = target_root / ".claude" / "rules" / filename
        _track(dest, lambda filename=filename, source_rel=source_rel: loaders.install_rule(
            target_root=target_root,
            sb_os_root=sb_os_root,
            source_rel=source_rel,
            rule_filename=filename,
            sb_os_path=sb_os_loader_path,
        ))

    # Templates — install-if-missing (preserve user customizations)
    for source_rel, target_rel in loaders.manifest_templates(
        modules_scoped, excluded_components
    ):
        dest = target_root / target_rel
        _track(dest, lambda source_rel=source_rel, target_rel=target_rel: loaders.install_template_if_missing(
            target_root=target_root,
            sb_os_root=sb_os_root,
            source_rel=source_rel,
            target_rel=target_rel,
        ))

    # Finance dashboard entry HTML — rendered with vault-root-absolute asset
    # paths derived from sb_os_path; install-if-missing (never clobbers a
    # user-placed/edited entry HTML). See install/finance.py.
    if FINANCE_MODULE_NAME in selected_modules:
        dest = target_root / finance_dashboard_html_path
        _track(dest, lambda: finance.install_dashboard_if_missing(
            target_root=target_root,
            sb_os_root=sb_os_root,
            sb_os_path=sb_os_loader_path,
            html_path=finance_dashboard_html_path,
        ))

    return changed


__all__ = ["run_upgrade", "build_upgrade_plan"]
