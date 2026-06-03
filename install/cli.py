"""Interactive prompt layer for the sb-os installer.

Consumed by ``fresh.py``, ``upgrade.py``, ``dry_run.py``, and ``install.py``.
Provides the user-facing primitives shared across install modes:

* Yes/no, path, and choice prompts (with sensible defaults).
* Per-component opt-out for the install plan.
* Configurable-path prompts for ``wiki_root``, ``user_context_root``, and the
  sb-os repo install location.
* A grouped planned-action display that mirrors RBTV's planned-action listing.
* A confirmation gate before any vault-modifying action.
* A clean abort path.

Stdlib only — uses ``sys``, ``shutil``, and ``dataclasses``. ANSI colors are
emitted only when stdout is a TTY so the layer remains graceful in CI logs and
redirected output.

The intent of this module is to keep the *interaction* concerns isolated from
the *side-effect* concerns. Each prompt returns plain Python data; mode
handlers consume that data and execute the install. Tests can substitute
``input`` and stdout.
"""
from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence


# ---------------------------------------------------------------------------
# ANSI color helpers (graceful when not a TTY)
# ---------------------------------------------------------------------------

def _supports_color() -> bool:
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _c(code: str, text: str) -> str:
    if not _supports_color():
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(text: str) -> str:
    return _c("1", text)


def dim(text: str) -> str:
    return _c("2", text)


def cyan(text: str) -> str:
    return _c("36", text)


def green(text: str) -> str:
    return _c("32", text)


def yellow(text: str) -> str:
    return _c("33", text)


def red(text: str) -> str:
    return _c("31", text)


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def _term_cols(default: int = 80) -> int:
    try:
        cols = shutil.get_terminal_size((default, 20)).columns
    except (AttributeError, ValueError, OSError):
        return default
    return max(40, cols)


def section_header(title: str) -> str:
    """Return a bold section header followed by a separator line.

    The separator uses ASCII ``-`` so the output renders identically across
    terminals that may not support box-drawing characters.
    """
    cols = _term_cols()
    bar = "-" * min(cols, max(8, len(title)))
    return f"\n{bold(title)}\n{dim(bar)}"


def print_section(title: str) -> None:
    print(section_header(title))


# ---------------------------------------------------------------------------
# Dataclasses describing the install plan
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Component:
    """A single installable unit (skill, command, rule, ...)."""

    name: str
    kind: str  # "skill", "command", "rule", "claude-md", "folder"
    target: str  # vault-relative path where the component lands
    description: str = ""


@dataclass(frozen=True)
class Action:
    """A single planned installer action.

    ``category`` groups actions in the planned-action list. Recognised values:
    ``folder``, ``file``, ``loader``, ``manifest``. Unknown categories sort
    after the recognised set, alphabetically.
    """

    category: str
    target: str
    detail: str = ""


@dataclass
class Plan:
    """The full set of actions an install mode intends to perform."""

    actions: list[Action] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)

    def add(self, action: Action) -> None:
        self.actions.append(action)


# ---------------------------------------------------------------------------
# Primitive prompts
# ---------------------------------------------------------------------------

_YES = {"y", "yes"}
_NO = {"n", "no"}


def _read_input(prompt: str) -> str:
    """Wrap ``input`` so KeyboardInterrupt produces a clean abort.

    ``EOFError`` (e.g., piped stdin closed) is treated as an abort signal.
    """
    try:
        return input(prompt)
    except (KeyboardInterrupt, EOFError):
        abort("Aborted by user.")


def confirm(question: str, default: bool = True) -> bool:
    """Yes/no prompt. Empty input returns ``default``.

    Re-prompts on unrecognised input rather than silently choosing ``default``
    so a typo cannot accidentally proceed.
    """
    hint = "Y/n" if default else "y/N"
    while True:
        response = _read_input(f"{question} [{hint}]: ").strip().lower()
        if not response:
            return default
        if response in _YES:
            return True
        if response in _NO:
            return False
        print(yellow("  Please answer y or n."))


# Backwards-friendly alias matching the task spec (`prompt_yes_no`).
def prompt_yes_no(question: str, default: bool = True) -> bool:
    return confirm(question, default=default)


def find_manifest_upward(start: Path) -> Path | None:
    """Walk from *start* toward the filesystem root looking for sb-os.json.

    Returns the directory containing the manifest, or None if no ancestor
    holds one. Used to auto-detect an existing install when the user runs
    ``install.py`` from anywhere inside a vault.
    """
    # Local import to avoid a circular dependency: cli is imported by manifest.
    from . import manifest

    current = start.resolve()
    for directory in [current] + list(current.parents):
        if (directory / manifest.MANIFEST_FILENAME).is_file():
            return directory
    return None


def prompt_target(default: str | None = None) -> Path:
    """Interactive prompt for the target vault path.

    Empty input returns ``default`` if provided, otherwise re-prompts.
    Always returns an absolute, expanded ``Path``.
    """
    while True:
        suffix = f" [{dim(default)}]" if default else ""
        raw = _read_input(f"Target vault path{suffix}: ").strip()
        if not raw:
            if default:
                raw = default
            else:
                print(yellow("  Path required."))
                continue
        return Path(raw).expanduser().resolve()


def prompt_path(
    question: str,
    default: str,
    must_exist: bool = False,
) -> str:
    """Path prompt. Empty input returns ``default``.

    Returns the entered string verbatim (callers resolve to ``Path`` as
    needed) so the caller controls absolute/relative semantics. When
    ``must_exist`` is true, the prompt re-asks until the path exists.
    """
    while True:
        suffix = f" [{dim(default)}]" if default else ""
        value = _read_input(f"{question}{suffix}: ").strip()
        if not value:
            value = default
        if not value:
            print(yellow("  Value required."))
            continue
        if must_exist and not Path(value).expanduser().exists():
            print(yellow(f"  Path does not exist: {value}"))
            continue
        return value


def prompt_choice(
    question: str,
    choices: Sequence[str],
    default: str,
) -> str:
    """Single-choice prompt. Empty input returns ``default``.

    Choices are shown inline. The default is highlighted. Re-prompts on
    invalid input.
    """
    if default not in choices:
        raise ValueError(f"default {default!r} not in choices {list(choices)}")
    rendered = " / ".join(
        bold(c) if c == default else c for c in choices
    )
    while True:
        value = _read_input(f"{question} ({rendered}) [{default}]: ").strip()
        if not value:
            return default
        if value in choices:
            return value
        print(yellow(f"  Choose one of: {', '.join(choices)}"))


def prompt_modules(
    modules: dict,
    previously_selected: list[str] | None = None,
) -> list[str]:
    """Keyboard checkbox selector for modules.

    Always-installed modules are listed but cannot be deselected. On re-install
    the previous selection is the default; on first install all optional
    modules default to selected. Atomic modules are toggled as a unit (the
    customization pass below skips them).
    """
    from .tui import checkbox

    names = list(modules.keys())
    always = {n for n, m in modules.items() if m.get("always_installed")}
    if previously_selected is None:
        defaults = set(names)
    else:
        defaults = set(previously_selected) | always

    items = []
    for name in names:
        mod = modules[name]
        marks = []
        if name in always:
            marks.append("always")
        if mod.get("atomic"):
            marks.append("atomic")
        suffix = f" [{', '.join(marks)}]" if marks else ""
        items.append(
            {
                "label": f"{name}{suffix}",
                "hint": mod.get("description", ""),
                "selected": name in defaults,
                "disabled": name in always,
            }
        )

    def detail_cb(index: int) -> str:
        name = names[index]
        mod = modules[name]
        lines = [f"  {name} - {mod.get('description', '')}", ""]
        stale_names: list[str] = []
        for group_name, key in (
            ("Skills", "skills"),
            ("Commands", "commands"),
            ("Rules", "rules"),
        ):
            all_of_kind = mod.get(key, [])
            entries = [e for e in all_of_kind if not e.get("stale")]
            stale_names += [
                e.get("name", e.get("target", "")) for e in all_of_kind if e.get("stale")
            ]
            lines.append(f"  {group_name} ({len(entries)}):")
            if entries:
                for entry in entries:
                    lines.append(f"    - {entry.get('name', entry.get('target', ''))}")
            else:
                lines.append("    - (none)")
            lines.append("")
        if stale_names:
            lines.append(f"  Stale (retired — not installed): {', '.join(stale_names)}")
            lines.append("")
        return "\n".join(lines)

    selected_indices = checkbox(
        "\nSelect modules to install:",
        items,
        min_selected=1,
        detail_callback=detail_cb,
    )

    chosen = [names[i] for i in selected_indices]
    for name in always:
        if name not in chosen:
            chosen.insert(0, name)
    return sorted(chosen, key=names.index)


def prompt_module_components(
    modules: dict,
    selected_modules: list[str],
    previously_excluded: list[str] | None = None,
) -> list[str]:
    """Keyboard checkbox selector for per-module component opt-out."""
    from .tui import checkbox

    if not confirm("\nCustomize individual components?", default=False):
        return list(previously_excluded or [])

    excluded: set[str] = set(previously_excluded or [])

    for name in selected_modules:
        mod = modules[name]
        if mod.get("atomic"):
            print(dim(f"\n  {name} is atomic — components install as a unit, skipping."))
            continue
        all_entries: list[tuple[str, str, str]] = []  # (kind, name, target)
        for entry in mod.get("skills", []):
            if entry.get("stale"):
                continue
            all_entries.append(("skill", entry["name"], entry["target"].replace("\\", "/")))
        for entry in mod.get("commands", []):
            if entry.get("stale"):
                continue
            all_entries.append(("cmd", entry["name"], entry["target"].replace("\\", "/")))
        for entry in mod.get("rules", []):
            if entry.get("stale"):
                continue
            all_entries.append(("rule", entry["name"], entry["target"].replace("\\", "/")))
        if not all_entries:
            continue
        items = [
            {
                "label": f"{kind:<5} {cname}",
                "hint": target,
                "selected": target not in excluded,
            }
            for kind, cname, target in all_entries
        ]
        selected_indices = checkbox(
            f"\nComponents in '{name}':",
            items,
        )
        selected_set = set(selected_indices)
        for i, (_kind, _cname, target) in enumerate(all_entries):
            if i in selected_set:
                excluded.discard(target)
            else:
                excluded.add(target)

    return sorted(excluded)


def prompt_components(
    components: Sequence[Component],
    default_all_in: bool = True,
) -> list[Component]:
    """Per-component opt-out. Returns the components the user kept.

    The user is shown a numbered list and may opt out by entering a
    comma-separated list of indices, the literal ``none`` to keep all, or
    Enter to accept the default.

    ``default_all_in=True`` keeps every component when the user presses
    Enter. ``False`` excludes every component by default — callers must then
    confirm explicitly to install anything.
    """
    if not components:
        return []

    print_section("Components")
    for i, comp in enumerate(components, start=1):
        desc = f"  {dim(comp.description)}" if comp.description else ""
        print(f"  {i:>2}. [{comp.kind}] {comp.name}  {dim('->')} {comp.target}{desc}")

    if default_all_in:
        prompt = (
            "\nOpt-out indices (comma-separated), Enter to keep all, "
            "or 'none' to keep all"
        )
    else:
        prompt = (
            "\nOpt-IN indices (comma-separated), Enter to skip all, "
            "or 'all' to keep all"
        )

    while True:
        raw = _read_input(f"{prompt}: ").strip().lower()
        if not raw:
            return list(components) if default_all_in else []
        if raw == "none" and default_all_in:
            return list(components)
        if raw == "all" and not default_all_in:
            return list(components)
        try:
            indices = {int(tok) for tok in raw.replace(" ", "").split(",") if tok}
        except ValueError:
            print(yellow("  Please enter integers separated by commas."))
            continue
        if any(i < 1 or i > len(components) for i in indices):
            print(yellow(f"  Indices must be between 1 and {len(components)}."))
            continue
        if default_all_in:
            return [c for i, c in enumerate(components, start=1) if i not in indices]
        return [c for i, c in enumerate(components, start=1) if i in indices]


# ---------------------------------------------------------------------------
# Configurable-path prompts (architecture §3 + §6 + Decisions Log #21)
# ---------------------------------------------------------------------------

DEFAULT_WIKI_ROOT = "3-resources/knowledge-base/"
DEFAULT_WIKI_ROOT_NO_PARA = "knowledge-management/"
DEFAULT_USER_CONTEXT_ROOT = ".user/context/"
DEFAULT_SB_OS_PATH = "3-resources/tools/sb-os/"
DEFAULT_FINANCE_DASHBOARD_HTML_PATH = ".user/finance/dashboard.html"


def detect_wiki_default_root(target_root: Path | str) -> str:
    """Pick the default wiki root for a target vault.

    When the target already has the PARA layout (``3-resources/`` exists),
    fall back to the canonical wiki slot inside Resources. Otherwise the
    install is wiki-only and the wiki root sits at the vault root under
    ``knowledge-management/``.
    """
    if (Path(target_root) / "3-resources").is_dir():
        return DEFAULT_WIKI_ROOT
    return DEFAULT_WIKI_ROOT_NO_PARA


def prompt_wiki_root(default: str = DEFAULT_WIKI_ROOT) -> str:
    return prompt_path(
        "wiki_root (vault-relative path for the optional wiki slot)",
        default=default,
    )


def prompt_user_context_root(default: str = DEFAULT_USER_CONTEXT_ROOT) -> str:
    return prompt_path(
        "user_context_root (where workflow-context YAMLs live)",
        default=default,
    )


def prompt_sb_os_path(default: str = DEFAULT_SB_OS_PATH) -> str:
    """Where the user has cloned the sb-os repo (loaders point here).

    Loaders carry this path verbatim — see ``loaders.py``. The path is
    vault-relative; the loader text is OS-portable (forward slashes).
    """
    return prompt_path(
        "sb-os repo path (vault-relative — loaders point here)",
        default=default,
    )


def prompt_finance_dashboard_html_path(
    default: str = DEFAULT_FINANCE_DASHBOARD_HTML_PATH,
) -> str:
    """Where the rendered finance dashboard entry HTML lands (vault-relative).

    The single configurable knob of the finance dashboard install (p1-3) —
    asset paths and the ``.user/finance/bookkeeper/`` data contract are
    fixed. Persisted in ``sb-os.json`` under ``finance_dashboard_html_path``;
    install-if-missing on upgrade (see ``install/finance.py``).
    """
    return prompt_path(
        "finance_dashboard_html_path (vault-relative — dashboard entry HTML)",
        default=default,
    )


# ---------------------------------------------------------------------------
# Planned-action list
# ---------------------------------------------------------------------------

_CATEGORY_ORDER = ("folder", "file", "loader", "manifest")
_CATEGORY_TITLES = {
    "folder": "Folders to create",
    "file": "Files to write",
    "loader": "Loaders to install",
    "manifest": "Manifest to write/update",
}


def _group_actions(actions: Iterable[Action]) -> dict[str, list[Action]]:
    groups: dict[str, list[Action]] = {}
    for action in actions:
        groups.setdefault(action.category, []).append(action)
    return groups


def print_plan(actions: list[Action] | list[dict]) -> None:
    """Pretty-print the planned actions, grouped by category.

    Accepts ``Action`` instances or plain dicts (with keys ``category``,
    ``target``, optional ``detail``) so callers building a plan ad-hoc do not
    need to import ``Action``.
    """
    normalized: list[Action] = []
    for entry in actions:
        if isinstance(entry, Action):
            normalized.append(entry)
        else:
            normalized.append(
                Action(
                    category=str(entry.get("category", "other")),
                    target=str(entry.get("target", "")),
                    detail=str(entry.get("detail", "")),
                )
            )

    groups = _group_actions(normalized)
    if not groups:
        print(dim("  (no planned actions)"))
        return

    ordered_categories = list(_CATEGORY_ORDER) + sorted(
        cat for cat in groups if cat not in _CATEGORY_ORDER
    )

    print_section("Planned actions")
    for category in ordered_categories:
        entries = groups.get(category)
        if not entries:
            continue
        title = _CATEGORY_TITLES.get(category, category.capitalize())
        print(f"\n{bold(title)} ({len(entries)})")
        for action in entries:
            line = f"  {green('+')} {action.target}"
            if action.detail:
                line += f"  {dim(action.detail)}"
            print(line)


# Spec-named alias matching the task file.
def display_planned_actions(actions: list[Action]) -> None:
    print_plan(actions)


# ---------------------------------------------------------------------------
# Confirmation gate + abort
# ---------------------------------------------------------------------------

def confirm_proceed(
    plan: Plan | list[Action] | None = None,
    dry_run: bool = False,
) -> bool:
    """Final go/no-go after the planned-action display.

    When ``dry_run`` is true the user is told no changes will be written and
    the prompt defaults to yes (showing the plan is the whole point of a dry
    run). Otherwise the prompt defaults to yes after the plan is displayed.

    Passing a ``Plan`` (or list of ``Action``) renders the plan first; passing
    ``None`` skips display (caller already showed it).
    """
    if plan is not None:
        actions = plan.actions if isinstance(plan, Plan) else list(plan)
        print_plan(actions)

    if dry_run:
        print(f"\n{cyan('Dry run — no files will be written.')}")
        return confirm("Show plan and exit?", default=True)

    return confirm("\nProceed?", default=True)


def abort(message: str) -> None:
    """Clean exit with a red message on stderr.

    Used for KeyboardInterrupt / EOF and for explicit user-driven aborts.
    Never returns.
    """
    print(f"\n{red('Aborted:')} {message}", file=sys.stderr)
    raise SystemExit(1)


__all__ = [
    "Action",
    "Component",
    "Plan",
    "DEFAULT_WIKI_ROOT",
    "DEFAULT_WIKI_ROOT_NO_PARA",
    "DEFAULT_USER_CONTEXT_ROOT",
    "DEFAULT_SB_OS_PATH",
    "DEFAULT_FINANCE_DASHBOARD_HTML_PATH",
    "detect_wiki_default_root",
    "abort",
    "bold",
    "confirm",
    "confirm_proceed",
    "cyan",
    "dim",
    "display_planned_actions",
    "find_manifest_upward",
    "green",
    "print_plan",
    "print_section",
    "prompt_choice",
    "prompt_components",
    "prompt_finance_dashboard_html_path",
    "prompt_modules",
    "prompt_module_components",
    "prompt_path",
    "prompt_sb_os_path",
    "prompt_target",
    "prompt_user_context_root",
    "prompt_wiki_root",
    "prompt_yes_no",
    "red",
    "section_header",
    "yellow",
]
