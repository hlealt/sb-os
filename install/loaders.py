"""Generate thin loader files for skills and commands.

Architecture §4 + §10 item 3: skills and commands installed into a vault's
`.claude/` are SHORT files that point back to the sb-os repo source. The
agent reads the loader, then follows the imperative `Read [...]` line to
the canonical source under
`{sb_os_path}/{module}/skills/<name>/SKILL.md` or
`{sb_os_path}/{module}/commands/<name>.md`. The `{module}` segment is the
on-disk module folder owning the source (`para` or `wiki`); each
component declares its module via the `module` field in the manifest.

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
import re
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Module manifest — declarative component list
# ---------------------------------------------------------------------------

MODULE_MANIFEST_FILENAME = "module-manifest.json"


def _module_manifest_path() -> Path:
    """Return the on-disk path to ``module-manifest.json``.

    The manifest sits beside this file under ``install/``. Resolving
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
            if entry.get("stale"):
                # Retired component: never shipped. Skipped at the single
                # chokepoint so every manifest_* reader (fresh/upgrade install,
                # orphan-cleanup, tests) ignores it uniformly.
                continue
            target = entry.get("target", "").replace("\\", "/")
            if target in excluded:
                continue
            out.append(entry)
    return out


def _entry_module(entry: dict[str, Any]) -> str:
    """Return the module folder declared by a manifest entry.

    Every component MUST declare ``module`` (``para`` or ``wiki``). Raise a
    clear error when missing — silently defaulting would emit loaders with
    broken paths.
    """
    module = entry.get("module")
    if not module:
        raise ValueError(
            f"Manifest entry {entry.get('name')!r} is missing the required "
            "'module' field. Add 'module: para' or 'module: wiki'."
        )
    return module


def _repo_root() -> Path:
    """Return the sb-os repo root (the parent of the ``install/`` package)."""
    return _module_manifest_path().parent.parent


def _parse_frontmatter_description(text: str) -> str | None:
    """Extract the ``description`` value from a file's YAML frontmatter block.

    Handles the single-line form sb-os skills use (quoted or unquoted). Returns
    None when there is no leading ``---`` frontmatter, no ``description:`` key,
    an empty value, or a YAML block scalar (``>``/``|``). Pure string parsing —
    no YAML dependency, so the installer stays stdlib-only.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    block: list[str] | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            block = lines[1:i]
            break
    if block is None:
        return None
    for line in block:
        m = re.match(r"\s*description:\s*(.*)$", line)
        if not m:
            continue
        val = m.group(1).strip()
        if not val or val[0] in (">", "|"):
            return None
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            quote = val[0]
            inner = val[1:-1]
            if quote == "'":
                inner = inner.replace("''", "'")
            else:
                inner = inner.replace('\\"', '"').replace("\\\\", "\\")
            val = inner.strip()
        return val or None
    return None


def _read_skill_description(repo_root: Path, module: str, name: str) -> str | None:
    """Return the ``description`` from a skill's source ``SKILL.md`` frontmatter.

    The skill source lives at ``{repo_root}/{module}/skills/{name}/SKILL.md``.
    Returns None when the file is missing or carries no usable description.
    """
    src = Path(repo_root) / module / "skills" / name / "SKILL.md"
    if not src.is_file():
        return None
    return _parse_frontmatter_description(src.read_text(encoding="utf-8"))


def manifest_skills(
    modules: dict[str, dict[str, Any]] | None = None,
    excluded: set[str] | None = None,
) -> tuple[tuple[str, str, str], ...]:
    """Return ``((name, description, module), ...)`` for every shippable skill.

    The ``description`` is read from each skill's source ``SKILL.md``
    frontmatter — the single source of truth — NOT from the manifest, so a
    description edit propagates on the next install with no manifest sync
    (architecture §4, Loader pattern). A skill whose ``SKILL.md`` lacks a
    description is warned about and falls back to a loader placeholder.

    With no args, returns ALL skills across ALL modules (used by upgrade
    orphan-cleanup and tests). Pass ``modules`` to scope to selected ones.
    """
    mods = modules if modules is not None else manifest_modules()
    repo_root = _repo_root()
    out: list[tuple[str, str, str]] = []
    for entry in _flatten(mods, "skills", excluded):
        name = entry["name"]
        module = _entry_module(entry)
        description = _read_skill_description(repo_root, module, name)
        if not description:
            sys.stderr.write(
                f"warning: sb-os skill {name!r} has no usable 'description' in its "
                f"source frontmatter ({module}/skills/{name}/SKILL.md); the installed "
                "loader will use a placeholder.\n"
            )
            description = ""
        out.append((name, description, module))
    return tuple(out)


def _read_command_description(repo_root: Path, module: str, name: str) -> str | None:
    """Return the ``description`` from a command's source frontmatter.

    The command source lives at ``{repo_root}/{module}/commands/{name}.md``.
    Returns None when the file is missing or carries no usable description.
    """
    src = Path(repo_root) / module / "commands" / f"{name}.md"
    if not src.is_file():
        return None
    return _parse_frontmatter_description(src.read_text(encoding="utf-8"))


def manifest_commands(
    modules: dict[str, dict[str, Any]] | None = None,
    excluded: set[str] | None = None,
) -> tuple[tuple[str, str, str], ...]:
    """Return ``((name, description, module), ...)`` for every shippable command.

    The ``description`` is read from each command's source frontmatter — the
    single source of truth, same as skills — NOT from the manifest. A command
    whose source lacks a description is warned about and falls back to a loader
    placeholder.

    With no args, returns ALL commands across ALL modules. Pass ``modules`` to
    scope to selected ones.
    """
    mods = modules if modules is not None else manifest_modules()
    repo_root = _repo_root()
    out: list[tuple[str, str, str]] = []
    for entry in _flatten(mods, "commands", excluded):
        name = entry["name"]
        module = _entry_module(entry)
        description = _read_command_description(repo_root, module, name)
        if not description:
            sys.stderr.write(
                f"warning: sb-os command {name!r} has no usable 'description' in its "
                f"source frontmatter ({module}/commands/{name}.md); the installed loader "
                "will use a placeholder.\n"
            )
            description = ""
        out.append((name, description, module))
    return tuple(out)


def manifest_rules(
    modules: dict[str, dict[str, Any]] | None = None,
    excluded: set[str] | None = None,
) -> tuple[tuple[str, str], ...]:
    """Return ``((filename, module), ...)`` for every shippable rule.

    ``filename`` includes the ``.md`` suffix.
    """
    mods = modules if modules is not None else manifest_modules()
    return tuple(
        (f"{entry['name']}.md", _entry_module(entry))
        for entry in _flatten(mods, "rules", excluded)
    )


def manifest_templates(
    modules: dict[str, dict[str, Any]] | None = None,
    excluded: set[str] | None = None,
) -> tuple[tuple[str, str], ...]:
    """Return ``((source, target), ...)`` for every shippable template.

    Templates are copied verbatim from the sb-os repo into the target vault
    using install-if-missing semantics — they bootstrap on fresh, and on
    upgrade only when the target does not already exist. User customizations
    are never overwritten. See ``install_template_if_missing``. ``source``
    is repo-relative and already includes the module folder prefix.
    """
    mods = modules if modules is not None else manifest_modules()
    return tuple(
        (entry["source"], entry["target"])
        for entry in _flatten(mods, "templates", excluded)
    )


def manifest_rule_sources(
    modules: dict[str, dict[str, Any]] | None = None,
    excluded: set[str] | None = None,
) -> tuple[tuple[str, str, str], ...]:
    """Return ``((filename, source_path, module), ...)`` for every rule.

    ``source_path`` is the repo-relative path (already module-prefixed).
    ``filename`` is the rule's installed filename (with ``.md``).
    """
    mods = modules if modules is not None else manifest_modules()
    return tuple(
        (f"{entry['name']}.md", entry["source"], _entry_module(entry))
        for entry in _flatten(mods, "rules", excluded)
    )


#: Imperative directive emitted by every sb-os thin loader. Used by orphan
#: detection to recover the source path a loader points at.
_READ_DIRECTIVE_RE = re.compile(r"Read and execute `([^`]+)`")


def find_orphaned_loaders(
    target_root: Path | str,
    sb_os_path: str | Path,
    known_targets: set[str],
    excluded: set[str] | None = None,
) -> list[str]:
    """Return vault-relative paths of sb-os-shaped loaders with no manifest entry.

    Scans ``.claude/commands/*.md`` and ``.claude/skills/*/SKILL.md``. A file
    is an orphan when ALL hold (architecture §6, Orphaned loaders):

    * its ``Read and execute`` directive resolves into ``sb_os_path`` —
      loaders pointing anywhere else (user, RBTV, personal) are never flagged;
    * its vault-relative path is absent from ``known_targets`` (the full
      manifest universe, stale entries included);
    * its vault-relative path is absent from ``excluded`` — exclusion is an
      explicit user signal, never deleted.

    Returns a sorted list of forward-slash vault-relative paths. Pure scan —
    no deletion happens here.
    """
    root = Path(target_root)
    base = _normalize_sb_os_path(sb_os_path)
    excluded = excluded or set()

    candidates: list[Path] = []
    commands_dir = root / ".claude" / "commands"
    if commands_dir.is_dir():
        candidates.extend(p for p in commands_dir.glob("*.md") if p.is_file())
    skills_dir = root / ".claude" / "skills"
    if skills_dir.is_dir():
        candidates.extend(
            p for p in skills_dir.glob("*/SKILL.md") if p.is_file()
        )

    orphans: list[str] = []
    for path in candidates:
        rel = path.relative_to(root).as_posix()
        if rel in known_targets or rel in excluded:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue  # unreadable file: leave it alone
        match = _READ_DIRECTIVE_RE.search(text)
        if not match:
            continue  # self-contained file, not a thin loader
        ref = match.group(1).replace("\\", "/").lstrip("/")
        # Segment-aware prefix match: `sb-os-extras/...` must not match `sb-os`.
        if ref == base or ref.startswith(base + "/"):
            orphans.append(rel)
    return sorted(orphans)


def _normalize_sb_os_path(sb_os_path: str | Path) -> str:
    """Return a forward-slash path without leading/trailing slash.

    Loaders ship as text consumed by an agent; using POSIX separators keeps
    them portable across OSes regardless of where install runs.
    """
    text = str(sb_os_path).replace("\\", "/").strip("/")
    if not text:
        raise ValueError("sb_os_path must be a non-empty path")
    return text


def _validate_module(module: str) -> str:
    """Return ``module`` after lightweight sanity checks.

    Module names are short folder names (``para``, ``wiki``, ...). Reject
    empty or path-bearing values so callers can't smuggle absolute paths
    through the loader.
    """
    text = module.strip().strip("/").replace("\\", "/")
    if not text or "/" in text:
        raise ValueError(
            f"module must be a single folder name (got {module!r})"
        )
    return text


def _yaml_quote(value: str) -> str:
    """Return ``value`` as a YAML-safe scalar for a loader ``description:``.

    Plain scalars are kept as-is when safe; a value containing a colon, ``#``,
    or a leading YAML indicator is single-quoted (doubling any apostrophe) so
    generated frontmatter never breaks a YAML parser — e.g. a description like
    "Backfill the wiki: ingest …".
    """
    if (
        value
        and ":" not in value
        and "#" not in value
        and value[0] not in "!&*?|>%@`\"'-[]{} "
    ):
        return value
    return "'" + value.replace("'", "''") + "'"


def generate_skill_loader(
    name: str,
    sb_os_path: str | Path,
    module: str,
    description: str = "",
) -> str:
    """Return the file content for `.claude/skills/<name>/SKILL.md`.

    The loader has a YAML frontmatter block (Claude Code requires `name`;
    `description` surfaces in the skill picker) followed by an imperative
    Read directive pointing to the canonical source in the sb-os repo.
    ``module`` selects the module folder (``para`` or ``wiki``) under which
    the skill source lives.
    """
    base = _normalize_sb_os_path(sb_os_path)
    mod = _validate_module(module)
    desc = description.strip() or f"Loader for sb-os skill `{name}`."
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {_yaml_quote(desc)}\n"
        "---\n"
        "\n"
        f"Read and execute `{base}/{mod}/skills/{name}/SKILL.md`.\n"
    )


def generate_command_loader(
    name: str,
    sb_os_path: str | Path,
    module: str,
    description: str = "",
) -> str:
    """Return the file content for `.claude/commands/<name>.md`.

    The command loader carries a YAML frontmatter block (`name` +
    `description`) followed by the imperative Read directive pointing to the
    canonical source. The ``description`` is single-sourced from the command's
    own source frontmatter — editing it there propagates on the next install
    with no manifest sync. ``module`` selects the module folder under which the
    command source lives.
    """
    base = _normalize_sb_os_path(sb_os_path)
    mod = _validate_module(module)
    desc = description.strip() or f"Loader for sb-os command `{name}`."
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {_yaml_quote(desc)}\n"
        "---\n"
        "\n"
        f"Read and execute `{base}/{mod}/commands/{name}.md`.\n"
    )


def install_skill_loader(
    target_root: Path | str,
    name: str,
    sb_os_path: str | Path,
    module: str,
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
        generate_skill_loader(name, sb_os_path, module, description),
        encoding="utf-8",
    )
    return target


def install_command_loader(
    target_root: Path | str,
    name: str,
    sb_os_path: str | Path,
    module: str,
    description: str = "",
) -> Path:
    """Write the command loader to `target_root/.claude/commands/<name>.md`.

    Creates parent directories as needed. Overwrites any existing file.
    Returns the written path.
    """
    target = Path(target_root) / ".claude" / "commands" / f"{name}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        generate_command_loader(name, sb_os_path, module, description),
        encoding="utf-8",
    )
    return target


def install_template_if_missing(
    target_root: Path | str,
    sb_os_root: Path | str,
    source_rel: str,
    target_rel: str,
) -> Path | None:
    """Copy a template from sb-os source to the target vault if absent.

    Templates are user-customizable defaults (e.g., periodic-note templates).
    They are bootstrapped on fresh install and, on upgrade, copied only when
    the target file does not already exist. Existing files are NEVER
    overwritten — user edits survive every install run.

    Returns the written path on copy, or ``None`` when the target already
    exists (no-op).
    """
    src = Path(sb_os_root) / source_rel
    if not src.is_file():
        raise FileNotFoundError(
            f"sb-os template source missing: {src}. Re-clone the sb-os repo."
        )
    dst = Path(target_root) / target_rel
    if dst.exists():
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dst


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
    source_rel: str,
    rule_filename: str,
    sb_os_path: str | Path,
) -> Path:
    """Install a rule file from sb-os source to ``.claude/rules/`` with
    placeholder substitution.

    ``source_rel`` is the manifest-declared repo-relative path (already
    module-prefixed, e.g. ``para/rules/sb-source-of-truth.md``).
    ``rule_filename`` is the installed filename under ``.claude/rules/``.

    Per architecture §8 rules are always rewritten on ``--upgrade`` — the
    call is idempotent.
    """
    src = Path(sb_os_root) / source_rel
    if not src.is_file():
        raise FileNotFoundError(
            f"sb-os rule source missing: {src}. Re-clone the sb-os repo."
        )
    dst = Path(target_root) / ".claude" / "rules" / rule_filename
    dst.parent.mkdir(parents=True, exist_ok=True)
    text = src.read_text(encoding="utf-8")
    dst.write_text(substitute_rule_placeholders(text, sb_os_path), encoding="utf-8")
    return dst
