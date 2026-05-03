"""Generate thin loader files for skills and commands.

Architecture §4 + §10 item 3: skills and commands installed into a vault's
`.claude/` are SHORT files that point back to the sb-os repo source. The
agent reads the loader, then follows the imperative `Read [...]` line to
the canonical source under `{sb_os_path}/skills/<name>/SKILL.md` or
`{sb_os_path}/commands/<name>.md`.

`sb_os_path` is the path from the vault root to the sb-os repo. It is
captured at install time (e.g., `3-resources/tools/sb-os` after kebab
rename, or any user-chosen path) and persisted indirectly through the
loader content — never hardcoded here.

The skill loader carries a YAML frontmatter block whose `description`
field Claude Code reads to surface the skill in the harness. The command
loader is a single line — Claude Code does not require frontmatter on
commands.

This module also exposes the declarative component manifest reader. The
manifest at ``module-manifest.json`` (sibling to this file) is the single
source of truth for what the installer ships — adding a component is a
JSON edit, not a Python edit. ``fresh.py`` and ``upgrade.py`` consume
``SKILLS``, ``COMMANDS``, and ``RULES`` derived from the manifest.

Pure stdlib (json, pathlib).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Module manifest — declarative component list
# ---------------------------------------------------------------------------

MODULE_MANIFEST_FILENAME = "module-manifest.json"


def _module_manifest_path() -> Path:
    """Return the on-disk path to ``module-manifest.json``.

    The manifest sits beside this file under ``admin/install/``. Resolving
    against ``__file__`` keeps the lookup independent of the caller's cwd.
    """
    return Path(__file__).resolve().parent / MODULE_MANIFEST_FILENAME


def read_module_manifest() -> dict[str, Any]:
    """Load and return ``module-manifest.json`` as a dict.

    Raises ``FileNotFoundError`` when the manifest is missing — the file is
    required for the installer to function. The error message includes the
    expected path so the user can diagnose a broken sb-os checkout.
    """
    path = _module_manifest_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"sb-os module manifest missing: {path}. The sb-os repo is "
            "incomplete — re-clone the repo or restore the file from git."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_modules() -> dict[str, dict[str, Any]]:
    """Return the modules dict in manifest order."""
    manifest = read_module_manifest()
    if "modules" not in manifest:
        raise ValueError(
            f"Module manifest at {_module_manifest_path()} has no 'modules' "
            "key. The manifest is from an older sb-os version — re-pull the "
            "sb-os repo or restore the file from git."
        )
    return manifest["modules"]


def select_modules(
    selected: tuple[str, ...] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return only the modules whose name is in ``selected`` (always-installed
    modules are forcibly included). When ``selected`` is None, returns all.
    """
    modules = manifest_modules()
    if selected is None:
        return modules
    chosen = set(selected)
    chosen.update(
        name for name, mod in modules.items() if mod.get("always_installed")
    )
    return {name: mod for name, mod in modules.items() if name in chosen}


def _flatten(
    modules: dict[str, dict[str, Any]],
    kind: str,
    excluded: set[str] | None = None,
) -> list[dict[str, Any]]:
    excluded = excluded or set()
    out: list[dict[str, Any]] = []
    for mod in modules.values():
        for entry in mod.get(kind, []):
            target = entry.get("target", "").replace("\\", "/")
            if target in excluded:
                continue
            out.append(entry)
    return out


def manifest_skills(
    modules: dict[str, dict[str, Any]] | None = None,
    excluded: set[str] | None = None,
) -> tuple[tuple[str, str], ...]:
    """Return ``((name, description), ...)`` for every shippable skill.

    With no args, returns ALL skills across ALL modules (used by upgrade
    orphan-cleanup and tests). Pass ``modules`` to scope to selected ones.
    """
    mods = modules if modules is not None else manifest_modules()
    return tuple(
        (entry["name"], entry.get("description", ""))
        for entry in _flatten(mods, "skills", excluded)
    )


def manifest_commands(
    modules: dict[str, dict[str, Any]] | None = None,
    excluded: set[str] | None = None,
) -> tuple[str, ...]:
    """Return command names. See ``manifest_skills`` for arg semantics."""
    mods = modules if modules is not None else manifest_modules()
    return tuple(entry["name"] for entry in _flatten(mods, "commands", excluded))


def manifest_rules(
    modules: dict[str, dict[str, Any]] | None = None,
    excluded: set[str] | None = None,
) -> tuple[str, ...]:
    """Return rule filenames (with ``.md``). See ``manifest_skills`` for args."""
    mods = modules if modules is not None else manifest_modules()
    return tuple(
        f"{entry['name']}.md" for entry in _flatten(mods, "rules", excluded)
    )


def _normalize_sb_os_path(sb_os_path: str | Path) -> str:
    """Return a forward-slash path without leading/trailing slash.

    Loaders ship as text consumed by an agent; using POSIX separators keeps
    them portable across OSes regardless of where install runs.
    """
    text = str(sb_os_path).replace("\\", "/").strip("/")
    if not text:
        raise ValueError("sb_os_path must be a non-empty path")
    return text


def generate_skill_loader(name: str, sb_os_path: str | Path, description: str = "") -> str:
    """Return the file content for `.claude/skills/<name>/SKILL.md`.

    The loader has a YAML frontmatter block (Claude Code requires `name`;
    `description` surfaces in the skill picker) followed by an imperative
    Read directive pointing to the canonical source in the sb-os repo.
    """
    base = _normalize_sb_os_path(sb_os_path)
    desc = description.strip() or f"Loader for sb-os skill `{name}`."
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {desc}\n"
        "---\n"
        "\n"
        f"Read and execute `{base}/skills/{name}/SKILL.md`.\n"
    )


def generate_command_loader(name: str, sb_os_path: str | Path) -> str:
    """Return the file content for `.claude/commands/<name>.md`.

    Mirrors the existing sb-os command loader convention (one imperative
    Read line). Claude Code surfaces commands by filename, no frontmatter
    required.
    """
    base = _normalize_sb_os_path(sb_os_path)
    return f"Read and execute `{base}/commands/{name}.md`.\n"


def install_skill_loader(
    target_root: Path | str,
    name: str,
    sb_os_path: str | Path,
    description: str = "",
) -> Path:
    """Write the skill loader to `target_root/.claude/skills/<name>/SKILL.md`.

    Creates parent directories as needed. Overwrites any existing file
    (per architecture §8: thin loaders are always rewritten on --upgrade).
    Returns the written path.
    """
    target = Path(target_root) / ".claude" / "skills" / name / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        generate_skill_loader(name, sb_os_path, description),
        encoding="utf-8",
    )
    return target


def install_command_loader(
    target_root: Path | str,
    name: str,
    sb_os_path: str | Path,
) -> Path:
    """Write the command loader to `target_root/.claude/commands/<name>.md`.

    Creates parent directories as needed. Overwrites any existing file.
    Returns the written path.
    """
    target = Path(target_root) / ".claude" / "commands" / f"{name}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        generate_command_loader(name, sb_os_path),
        encoding="utf-8",
    )
    return target


def substitute_rule_placeholders(text: str, sb_os_path: str | Path) -> str:
    """Replace install-time placeholders in rule file content.

    Rule sources may carry the ``{sb_os_path}`` template placeholder so the
    sb-os-relative reference paths inside the file resolve correctly once
    installed at the user-chosen ``sb_os_path``. Without substitution, the
    placeholder reaches ``.claude/rules/`` unresolved and any ``Read ...``
    instruction following it fails.

    Currently only ``{sb_os_path}`` is substituted. Future placeholders
    (e.g., ``{user_context_root}``, ``{wiki_root}``) extend this function
    rather than scattering substitution across modules.
    """
    base = _normalize_sb_os_path(sb_os_path)
    return text.replace("{sb_os_path}", base)


def install_rule(
    target_root: Path | str,
    sb_os_root: Path | str,
    rule_name: str,
    sb_os_path: str | Path,
) -> Path:
    """Install a rule file from sb-os source to ``.claude/rules/`` with
    placeholder substitution.

    Replaces ``shutil.copyfile`` callers in ``fresh.py`` and ``upgrade.py``
    so rule install runs through the same substitution pass that loaders
    already use. Per architecture §8 rules are always rewritten on
    ``--upgrade`` — the call is idempotent.
    """
    src = Path(sb_os_root) / "rules" / rule_name
    if not src.is_file():
        raise FileNotFoundError(
            f"sb-os rule source missing: {src}. Re-clone the sb-os repo."
        )
    dst = Path(target_root) / ".claude" / "rules" / rule_name
    dst.parent.mkdir(parents=True, exist_ok=True)
    text = src.read_text(encoding="utf-8")
    dst.write_text(substitute_rule_placeholders(text, sb_os_path), encoding="utf-8")
    return dst
