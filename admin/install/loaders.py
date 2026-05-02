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

Pure stdlib (pathlib).
"""
from __future__ import annotations

from pathlib import Path


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
