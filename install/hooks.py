"""Context-injection hook wiring for the sb-os installer.

The Phase-1 resolver (`para/workflows/sb-inject-context/resolve_context.py`)
carries a deterministic `--hook` mode: given a Claude Code hook event on stdin,
it derives the execution surface (a PreToolUse `Skill` event -> skill surface; a
PostToolUse `Read` of a workflow-step / command / skill `.md` -> the matching
surface) and emits the injected context. This module wires that resolver into a
target vault's `.claude/settings.local.json` at install time, so context
injection fires DETERMINISTICALLY without any always-on rule telling the agent to
run the resolver. This REVERSES the prior "installer never touches settings"
policy (owner-approved, decision D7).

Two hook entries are managed (both invoke the SAME resolver command):

  * **PreToolUse**, matcher ``"Skill"``  — fires before a Skill invocation.
  * **PostToolUse**, matcher ``"Read"``  — fires after a Read.

Markdown scoping of the PostToolUse entry is delegated to the resolver, NOT to a
settings field. Claude Code's hook ``matcher`` filters by TOOL name only (it is
the bare tool name ``"Read"`` here). Claude Code DOES honor a per-handler ``if``
field using permission-rule syntax (e.g. ``"Read(*.md)"``) that could pre-filter
the Read by path at the harness level — but this module deliberately does NOT use
it: the resolver already classifies every read path and exits silently (no stdout,
exit 0) for any non-`.md` / non-surface read, so a harness-level ``if`` filter
would be redundant, and keeping the single scoping authority in the script (which
must classify the path regardless) avoids two places that can disagree about what
``.md`` paths count as a surface. The `.md` restriction therefore lives only in
the script. (Adding ``if: "Read(*.md)"`` is a safe-but-redundant future option;
it is intentionally omitted, not overlooked.)

This module MIRRORS the proven, round-trip-safe RBTV pattern in
``rbtv/admin/install/installer/orchestration.py`` (``sync_hook_entry`` /
``_is_rbtv_hook_entry`` / ``remove_hook_entry``): sentinel-plus-command-signature
identity, a cwd-independent command (a small Python resolver reading
``CLAUDE_PROJECT_DIR`` and walking up to the nearest ``.git`` ancestor — see
`_build_command`), foreign-entry preservation, fail-soft on a malformed settings
file, idempotency. It does NOT import from the RBTV repo (a separate repo) — the
structure is reproduced here.

Identity is keyed on EITHER the injected sentinel key (fast path, present when
preserved) OR an intrinsic command-path signature on ``resolve_context.py``
(harness-robust: survives the sentinel being stripped when Claude Code
re-serializes ``settings.local.json`` — there is no documented guarantee that an
unknown top-level entry key survives that round-trip). So neither this wire's
idempotency nor the unwire can orphan an entry whose key was dropped.

Pure stdlib (json, pathlib).
"""
from __future__ import annotations

import json
from pathlib import Path

from . import loaders


# The sb-managed hook entries are identified by this stable sentinel so the
# unwire removes ONLY them and never touches hand-added entries.
_HOOK_SENTINEL = "sb:context-injection"

# Path to the resolver script, relative to the sb-os repo root.
_RESOLVE_CONTEXT_RELATIVE = (
    Path("para") / "workflows" / "sb-inject-context" / "resolve_context.py"
)

# Stable command-path signature of the sb hook (the sb-owned script the entry
# always invokes). Used as a HARNESS-ROBUST fallback identifier so a
# sentinel-stripped entry is still recognized — exactly as RBTV does with
# ``__rbtv__``. POSIX (forward slashes), matching the command string.
_HOOK_COMMAND_SIGNATURE = _RESOLVE_CONTEXT_RELATIVE.as_posix()

# The two managed entries, by hook event name + tool matcher. Markdown scoping
# of the Read entry is delegated to the resolver (see module docstring), so the
# matcher is the bare tool name.
_PRE_EVENT = "PreToolUse"
_PRE_MATCHER = "Skill"
_POST_EVENT = "PostToolUse"
_POST_MATCHER = "Read"


# --------------------------------------------------------------------------- #
# Identity helpers (mirror orchestration._entry_commands / _is_rbtv_hook_entry)
# --------------------------------------------------------------------------- #

def _entry_commands(entry: dict) -> list[str]:
    """Every ``command`` string inside a hook matcher entry's ``hooks`` list.

    Tolerates a malformed-but-parseable entry (missing/empty/oddly-typed
    ``hooks``) without raising — returns ``[]`` so the caller's membership test
    is simply False.
    """
    if not isinstance(entry, dict):
        return []
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return []
    out: list[str] = []
    for h in hooks:
        if isinstance(h, dict):
            cmd = h.get("command")
            if isinstance(cmd, str):
                out.append(cmd)
    return out


def _is_sb_hook_entry(entry: dict) -> bool:
    """True when a hook entry is the sb-managed context-injection one.

    Matches on EITHER the injected sentinel key (fast path) OR the intrinsic
    sb script-path signature in any of its commands (harness-robust: survives
    the sentinel being stripped on a settings re-serialize). A foreign hook
    invoking an unrelated command matches neither and is left untouched.
    """
    if not isinstance(entry, dict):
        return False
    if entry.get("__sb__") == _HOOK_SENTINEL:
        return True
    return any(_HOOK_COMMAND_SIGNATURE in cmd for cmd in _entry_commands(entry))


def _build_command(sb_os_path: str | Path) -> str:
    """Return a cwd-independent resolver command string.

    Claude Code sets ``$CLAUDE_PROJECT_DIR`` to the SESSION's cwd, not necessarily
    the repo root — a session one or more levels below the repo root (a worktree,
    a per-seat subfolder) gets a non-existent joined path and a plain
    ``$CLAUDE_PROJECT_DIR``-relative command errors on every matched tool call
    (observed 2026-07-24, a team-kit run with per-seat working directories). This
    wraps the invocation in a small Python resolver that reads
    ``CLAUDE_PROJECT_DIR`` from ``os.environ`` directly (shell-syntax independent
    — the same command runs under sh/bash/cmd/PowerShell), walks up from there to
    the nearest ancestor holding a ``.git`` directory (the real repo root), then
    joins the sb-os install path + the resolver's repo-relative location. No
    match (e.g. a differently laid out machine) exits 0 silently — never a hard
    error. Mirrors RBTV's `_build_cwd_independent_command`
    (`rbtv/admin/install/installer/orchestration.py`) without importing it (a
    separate repo — see module docstring).
    """
    base = loaders._normalize_sb_os_path(sb_os_path)
    script_posix = (Path(base) / _RESOLVE_CONTEXT_RELATIVE).as_posix()
    code = (
        "import os,sys,subprocess as s;"
        "c=os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd();"
        "parts=c.split(os.sep);"
        "cands=[os.sep.join(parts[:len(parts)-i]) or os.sep for i in range(0,len(parts))];"
        "d=next((x for x in cands if x and os.path.isdir(os.path.join(x,'.git'))),None);"
        f"p=os.path.join(d,{script_posix!r}) if d else None;"
        "sys.exit(s.call([sys.executable,p,'--hook']) if p and os.path.isfile(p) else 0)"
    )
    return f'python -c "{code}"'


def _build_entry(matcher: str, command_str: str) -> dict:
    """The sb-managed hook entry for a given matcher, carrying the sentinel."""
    return {
        "__sb__": _HOOK_SENTINEL,
        "matcher": matcher,
        "hooks": [{"type": "command", "command": command_str}],
    }


def _read_settings(settings_path: Path) -> tuple[dict | None, str | None]:
    """Read + JSON-parse the settings file.

    Returns ``(settings_dict, None)`` on success (or ``({}, None)`` when the
    file is absent), or ``(None, error_message)`` on a malformed/non-object
    file — so the caller fails soft rather than clobbering it.
    """
    if not settings_path.is_file():
        return {}, None
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, (
            f"could not parse {settings_path.as_posix()} ({exc}) — "
            "fix the file and re-run"
        )
    if not isinstance(settings, dict):
        return None, (
            f"{settings_path.as_posix()} is not a JSON object — "
            "fix the file and re-run"
        )
    return settings, None


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def sync_context_hook(
    target_root: Path | str, sb_os_path: str | Path
) -> tuple[bool, str]:
    """Wire BOTH context-injection hook entries into ``.claude/settings.local.json``.

    Mirrors the RBTV ``sync_hook_entry()`` read->merge->write pattern, extended to
    TWO entries (PreToolUse/Skill + PostToolUse/Read):

    - Reads the settings file (or starts from ``{}``).
    - For each managed event (PreToolUse, PostToolUse), removes any existing
      sb-managed entry (identified by sentinel OR command signature) from that
      event's list and inserts exactly one fresh entry at the end.
    - Preserves every foreign key and foreign hook entry.
    - Writes back.

    Idempotent: a second call with identical inputs leaves the file
    byte-equivalent (the stale entry is replaced in place, never duplicated), so
    the upgrade ``_track`` reports it unchanged. Fails soft (returns
    ``(False, message)``) on a malformed settings file.

    Returns ``(changed, message)`` — ``changed`` feeds the upgrade ``_track``.
    """
    target_root = Path(target_root)
    settings_path = target_root / ".claude" / "settings.local.json"

    settings, err = _read_settings(settings_path)
    if err is not None:
        return False, f"hook sync skipped: {err}"

    command_str = _build_command(sb_os_path)

    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return False, (
            f"hook sync skipped: 'hooks' in {settings_path.as_posix()} is not "
            "an object — fix the file and re-run"
        )

    managed = (
        (_PRE_EVENT, _PRE_MATCHER),
        (_POST_EVENT, _POST_MATCHER),
    )
    for event_name, matcher in managed:
        event_list = hooks.setdefault(event_name, [])
        if not isinstance(event_list, list):
            return False, (
                f"hook sync skipped: 'hooks.{event_name}' in "
                f"{settings_path.as_posix()} is not a list — fix the file and re-run"
            )
        without_sb = [e for e in event_list if not _is_sb_hook_entry(e)]
        hooks[event_name] = without_sb + [_build_entry(matcher, command_str)]

    new_text = json.dumps(settings, indent=2) + "\n"
    before = (
        settings_path.read_text(encoding="utf-8")
        if settings_path.is_file()
        else None
    )
    if before == new_text:
        return False, (
            f"hook sync: entries already current "
            f"({settings_path.relative_to(target_root).as_posix()})"
        )

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(new_text, encoding="utf-8")
    return True, (
        f"hook sync: wired PreToolUse/Skill + PostToolUse/Read context-injection "
        f"entries in {settings_path.relative_to(target_root).as_posix()}"
    )


def remove_context_hook(target_root: Path | str) -> tuple[bool, str]:
    """Unwire the sb-managed context-injection hook entries from ``.claude/settings.local.json``.

    Mirrors the RBTV ``remove_hook_entry()`` pattern but removes from BOTH
    managed events:

    - Reads the settings file (or returns a no-op success when absent).
    - Drops every entry where ``_is_sb_hook_entry`` is True (sentinel OR command
      signature — never key-only) from PreToolUse and PostToolUse.
    - Writes back, preserving every foreign key/entry.

    No-op success when the file does not exist, the ``hooks`` key is absent, or
    no sb-managed entry is present (already-unwired / idempotent). Fails soft
    (returns ``(False, message)``) on a malformed settings file.

    Returns ``(changed, message)`` — ``changed`` feeds the upgrade ``_track``.
    """
    target_root = Path(target_root)
    settings_path = target_root / ".claude" / "settings.local.json"

    if not settings_path.is_file():
        return False, "hook unwire: no settings file — nothing to remove"

    settings, err = _read_settings(settings_path)
    if err is not None:
        return False, f"hook unwire skipped: {err}"

    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False, "hook unwire: no hooks object — nothing to remove"

    n_removed = 0
    for event_name in (_PRE_EVENT, _POST_EVENT):
        event_list = hooks.get(event_name)
        if not isinstance(event_list, list):
            continue
        without_sb = [e for e in event_list if not _is_sb_hook_entry(e)]
        n_removed += len(event_list) - len(without_sb)
        if len(without_sb) != len(event_list):
            hooks[event_name] = without_sb

    if n_removed == 0:
        return False, (
            f"hook unwire: no sb context-injection entry found — already absent "
            f"({settings_path.relative_to(target_root).as_posix()})"
        )

    settings_path.write_text(
        json.dumps(settings, indent=2) + "\n", encoding="utf-8"
    )
    return True, (
        f"hook unwire: removed {n_removed} sb context-injection "
        f"{'entry' if n_removed == 1 else 'entries'} from "
        f"{settings_path.relative_to(target_root).as_posix()}"
    )


__all__ = ["sync_context_hook", "remove_context_hook"]
