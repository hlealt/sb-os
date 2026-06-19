r"""
resolve_context.py — drives sb-os context injection deterministically.

The auto-firing hook calls this; schema and path-resolution contract:
`para/docs/context-injection-schema.md`. Given an execution surface (a skill
name, a command name, OR a workflow step file), this script:

  1. Resolves the surface's context-YAML path (reads `user_context_root` and
     `sb_os_path` from `sb-os.json` at the vault root — NEVER hardcoded).
       - skill -> {user_context_root}/skills/{skill-name}.yaml
       - step  -> the step file's path relative to its workflow root, with the
                  `.md` swapped to `.yaml`, under {user_context_root}.
  2. Probes it. Missing file, or a file with no entries -> prints `NO CONTEXT`
     and exits 0 (an unambiguous "there is none" signal).
  3. Parses the YAML with a real parser. A malformed file prints
     `CANNOT PARSE <path>: <reason>` and exits 3 — never a traceback.
  4. Loads and PRINTS each entry's content as plain text directly to stdout, so
     the corpus lands in the agent's context window from this one call:
       - `text`            -> the `content`, verbatim.
       - `file` (read / read-write), path resolves to a real file/glob match
                           -> the file content (only the named `sections` when
                              `sections:` is set; `glob`+`select`+`count`
                              honoured).
     Entries the script cannot turn into text deterministically are surfaced as
     a clearly-labelled AGENT ACTION (all fields + the instruction printed),
     never silently dropped:
       - `script` / `url` / `mcp`         (agent-native or arg-substituting)
       - `file` in `write` mode           (destination only)
       - `file` whose path/glob does not resolve as-is (likely placeholders the
         agent must substitute, e.g. YYYY-Wnn / {week} / CLOSING_WEEK_MONDAY)

Output is grouped per entry, in document order, prefixed with a directive that
the agent must APPLY each entry's instruction to its content/action before the
surface's native logic runs.

Usage:
    python resolve_context.py --surface skill   --name <skill-name>     [opts]
    python resolve_context.py --surface command --name <command-name>   [opts]
    python resolve_context.py --surface step    --file <path-to-step.md> [opts]
    python resolve_context.py --hook   # read a hook event from stdin (fail-soft)

The --hook mode reads a Claude Code hook event JSON from stdin, derives the
surface from it (a PreToolUse Skill event -> skill surface; a PostToolUse Read
of a workflow-step .md / a .claude/commands/{name}.md / a .claude/skills/{name}/
SKILL.md -> step/command/skill surface), and prints the matching injected
context as a `{"hookSpecificOutput":{"hookEventName":...,"additionalContext":...}}`
envelope. Any non-surface event, missing/empty YAML, or error -> no stdout,
exit 0. The hook NEVER blocks or errors a tool call.

Options:
    --vault-root PATH    Vault root (default: auto-detect by walking up from the
                         CWD / this script for `sb-os.json`; else the CWD). The
                         test seam — all paths resolve under it via its
                         `sb-os.json`, so pointing it elsewhere proves the root
                         is read from config, not baked in.
    --json               Emit a machine-readable JSON report instead of text.

Exit codes:
    0  success (context printed) OR NO CONTEXT
    2  usage / resolution error (e.g. step file not under a workflow root)
    3  the resolved YAML exists but cannot be parsed
"""

import argparse
import fnmatch
import json
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is an sb-os dependency
    sys.stderr.write(
        "resolve_context.py requires PyYAML (an sb-os dependency). "
        "Install it with: pip install pyyaml\n"
    )
    sys.exit(2)

DEFAULT_CONTEXT_ROOT = ".user/context/"
DEFAULT_SB_OS_PATH = "3-resources/tools/sb-os/"
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


# --------------------------------------------------------------------------- #
# Vault root + config
# --------------------------------------------------------------------------- #
def find_vault_root(explicit):
    """Return the vault root. Explicit wins; else walk up for sb-os.json."""
    if explicit:
        return Path(explicit).resolve()
    for base in (Path.cwd(), Path(__file__).resolve().parent):
        p = base.resolve()
        while True:
            if (p / "sb-os.json").exists():
                return p
            if p.parent == p:
                break
            p = p.parent
    return Path.cwd().resolve()


def load_config(vault_root):
    """Read user_context_root + sb_os_path from sb-os.json (with defaults)."""
    cfg = {}
    f = vault_root / "sb-os.json"
    if f.exists():
        try:
            cfg = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            cfg = {}
    return (
        cfg.get("user_context_root", DEFAULT_CONTEXT_ROOT),
        cfg.get("sb_os_path", DEFAULT_SB_OS_PATH),
    )


# --------------------------------------------------------------------------- #
# YAML path resolution
# --------------------------------------------------------------------------- #
def resolve_skill_yaml(vault_root, ucr, name):
    return (vault_root / ucr / "skills" / f"{name}.yaml").resolve()


def resolve_command_yaml(vault_root, ucr, name):
    return (vault_root / ucr / "commands" / f"{name}.yaml").resolve()


def resolve_step_yaml(vault_root, ucr, sb_os_path, step_file):
    """Mirror a workflow step file to its context YAML under user_context_root.

    Returns (yaml_path, error). The step file's path relative to its workflow
    root is reused verbatim (only .md -> .yaml), per the Path Resolution in
    `para/docs/context-injection-schema.md`. Workflow roots: .user/workflows/
    and each {sb_os_path}/<module>/workflows/.
    """
    step = Path(step_file)
    if not step.is_absolute():
        step = vault_root / step
    step = step.resolve()

    roots = [(vault_root / ".user" / "workflows").resolve()]
    sb_dir = (vault_root / sb_os_path).resolve()
    if sb_dir.exists():
        roots.extend(sorted(p.resolve() for p in sb_dir.glob("*/workflows")))

    for root in roots:
        try:
            rel = step.relative_to(root)
        except ValueError:
            continue
        yaml_rel = rel.with_suffix(".yaml")
        return (vault_root / ucr / yaml_rel).resolve(), None

    return None, (
        "step file is not under a known workflow root "
        "(.user/workflows/ or {sb_os_path}/<module>/workflows/): %s" % step
    )


# --------------------------------------------------------------------------- #
# Content loading
# --------------------------------------------------------------------------- #
def extract_sections(text, names):
    """Return the content under each named heading (any level), in request
    order. A heading's section runs until the next heading of the same or
    higher level. Names not found are silently skipped (per schema)."""
    lines = text.splitlines(keepends=True)
    n = len(lines)
    chunks = []
    for name in names:
        for idx, line in enumerate(lines):
            m = HEADING_RE.match(line.rstrip("\r\n"))
            if m and m.group(2).strip() == name:
                level = len(m.group(1))
                seg = [lines[idx]]
                j = idx + 1
                while j < n:
                    m2 = HEADING_RE.match(lines[j].rstrip("\r\n"))
                    if m2 and len(m2.group(1)) <= level:
                        break
                    seg.append(lines[j])
                    j += 1
                chunks.append("".join(seg).rstrip())
                break
    return "\n\n".join(chunks)


def resolve_file_matches(vault_root, entry):
    """Resolve a `file` entry to the list of existing files to load.

    Existence is the deterministic gate: a concrete path/glob that resolves is
    loaded; one that does not (placeholders, missing personal file) returns []
    so the caller surfaces it as an agent action."""
    path = entry.get("path", "")
    base = (vault_root / path)
    glob = entry.get("glob")

    if glob:
        if not base.is_dir():
            return []
        names = sorted(f for f in os.listdir(base) if fnmatch.fnmatch(f, glob))
        select = entry.get("select")
        if select == "latest":
            count = entry.get("count", 1)
            try:
                count = int(count)
            except (TypeError, ValueError):
                count = 1
            names = names[-count:] if count > 0 else names
        # select == "all" or unset -> keep all matches
        return [base / nm for nm in names]

    return [base] if base.is_file() else []


def read_text_file(p):
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# Entry -> structured record (drives both text and JSON output)
# --------------------------------------------------------------------------- #
def build_record(vault_root, entry):
    """Turn one YAML entry into a record dict the renderers consume."""
    etype = (entry.get("type") or "").strip()
    mode = (entry.get("mode") or "read").strip()
    rec = {
        "name": entry.get("name", "(unnamed)"),
        "type": etype or "(missing type)",
        "mode": mode,
        "instruction": (entry.get("instruction") or "").strip(),
        "kind": None,        # "content" | "action"
        "content": None,     # loaded corpus (kind == content)
        "sources": [],       # provenance file list (kind == content)
        "partial": False,    # True when only `sections` were loaded, not the whole file
        "section_names": [], # the sections loaded (kind == content, partial)
        "action": None,      # agent-action descriptor (kind == action)
    }

    if etype == "text":
        rec["kind"] = "content"
        rec["content"] = (entry.get("content") or "").rstrip()
        return rec

    if etype == "file" and mode != "write":
        matches = resolve_file_matches(vault_root, entry)
        if matches:
            sections = entry.get("sections")
            parts = []
            for p in matches:
                raw = read_text_file(p)
                body = extract_sections(raw, sections) if sections else raw.rstrip()
                if sections and not body:
                    body = "(none of the requested sections were found in this file)"
                parts.append(body)
                rec["sources"].append(str(p.relative_to(vault_root)).replace("\\", "/"))
            rec["kind"] = "content"
            rec["content"] = "\n\n".join(parts)
            rec["partial"] = bool(sections)
            rec["section_names"] = list(sections) if sections else []
            if mode == "read-write":
                rec["writeback"] = entry.get("path", "")
            return rec
        # Path/glob did not resolve as-is -> agent must substitute & load.
        rec["kind"] = "action"
        rec["action"] = {
            "verb": "load file after substituting any placeholders",
            "detail": entry.get("glob")
            and "path=%s glob=%s" % (entry.get("path", ""), entry.get("glob"))
            or "path=%s" % entry.get("path", ""),
            "note": "did not resolve to an existing file as-is",
        }
        return rec

    # All remaining cases -> agent action (surfaced, never dropped).
    rec["kind"] = "action"
    if etype == "file":  # write mode
        rec["action"] = {
            "verb": "write output to this destination",
            "detail": "path=%s" % entry.get("path", ""),
            "note": "mode=write",
        }
    elif etype == "script":
        args = entry.get("args") or []
        rec["action"] = {
            "verb": "run command",
            "detail": " ".join([entry.get("command", "")] + [str(a) for a in args]).strip(),
            "note": "type=script (substitute any placeholder args before running)",
        }
    elif etype == "url":
        rec["action"] = {
            "verb": "fetch URL",
            "detail": entry.get("url", ""),
            "note": "type=url",
        }
    elif etype == "mcp":
        rec["action"] = {
            "verb": "call MCP tool",
            "detail": "server=%s tool=%s params=%s"
            % (entry.get("server", ""), entry.get("tool", ""), entry.get("params", {})),
            "note": "type=mcp",
        }
    else:
        rec["action"] = {
            "verb": "handle entry",
            "detail": "type=%s" % etype,
            "note": "unrecognised type — apply the instruction manually",
        }
    return rec


# --------------------------------------------------------------------------- #
# Renderers
# --------------------------------------------------------------------------- #
def _indent(text, pad="      "):
    return "\n".join(pad + ln for ln in (text or "").splitlines()) or (pad + "(empty)")


def render_text(surface_label, yaml_path, records, vault_root):
    src = str(yaml_path.relative_to(vault_root)).replace("\\", "/") \
        if _under(yaml_path, vault_root) else str(yaml_path)
    out = []
    out.append("=== sb-os context injection ===")
    out.append("surface: %s" % surface_label)
    out.append("source:  %s" % src)
    out.append("entries: %d" % len(records))
    out.append(
        "DIRECTIVE: apply each entry's `instruction` to its content/action "
        "below, in order, BEFORE this surface's native logic."
    )
    for i, rec in enumerate(records, 1):
        out.append("-" * 60)
        out.append("[%d] %s" % (i, rec["name"]))
        out.append("    type: %s | mode: %s" % (rec["type"], rec["mode"]))
        out.append("    instruction:")
        out.append(_indent(rec["instruction"]))
        if rec["kind"] == "content":
            srcs = ", ".join(rec["sources"])
            if rec.get("writeback"):
                out.append("    content — current contents of %s (mode: read-write; "
                           "edit this and write back to that path):" % rec["writeback"])
            elif rec["sources"] and rec.get("partial"):
                out.append("    content — sections %s of %s (PARTIAL — only these "
                           "sections are loaded; re-read the file for anything outside "
                           "them; the path is for editing/reference):"
                           % (rec["section_names"], srcs))
            elif rec["sources"]:
                out.append("    content — full file %s (already loaded in full; no need "
                           "to re-read it; the path is informative, for editing/reference "
                           "only):" % srcs)
            else:
                out.append("    content:")
            out.append(_indent(rec["content"]))
        else:
            a = rec["action"]
            out.append("    AGENT ACTION — %s:" % a["verb"])
            out.append(_indent(a["detail"]))
            out.append("      (%s)" % a["note"])
    out.append("=== end context ===")
    return "\n".join(out)


def render_json(surface_label, yaml_path, records, vault_root):
    src = str(yaml_path.relative_to(vault_root)).replace("\\", "/") \
        if _under(yaml_path, vault_root) else str(yaml_path)
    return json.dumps(
        {"status": "ok", "surface": surface_label, "source": src, "entries": records},
        ensure_ascii=False,
        indent=2,
    )


def _under(p, root):
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# YAML -> records (shared by the CLI surfaces and the hook mode)
# --------------------------------------------------------------------------- #
def load_records(vault_root, yaml_path):
    """Probe + parse a resolved context YAML and build its records.

    Returns (status, payload):
      ("none",  None)     -> missing file, or no/empty `context:` entries
      ("parse", reason)   -> the file exists but cannot be parsed
      ("ok",    records)  -> a list of build_record() dicts (possibly empty
                             only if every entry was non-dict, treated as none)
    """
    if not yaml_path.exists():
        return ("none", None)
    try:
        doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return ("parse", str(e).replace("\n", " "))
    entries = (doc or {}).get("context") if isinstance(doc, dict) else None
    if not entries:
        return ("none", None)
    records = [build_record(vault_root, e) for e in entries if isinstance(e, dict)]
    return ("ok", records)


# --------------------------------------------------------------------------- #
# Hook mode
# --------------------------------------------------------------------------- #
def _extract_skill_name(event):
    """Best-effort skill-name extraction from a PreToolUse Skill event.

    The exact location of the skill name in a Claude Code `Skill` tool event is
    not contractually documented, so check BOTH the tool_input keys (the
    documented home for a tool's arguments) AND a few tool_name-adjacent
    top-level fields, defensively, in priority order. First non-empty wins."""
    ti = event.get("tool_input")
    if isinstance(ti, dict):
        # `skill_name` is the documented key (Claude Code hooks reference);
        # the others are defensive fallbacks against schema drift.
        for key in ("skill_name", "skill", "name", "command"):
            val = ti.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    # tool_name-adjacent fallbacks (top-level), in case the harness lifts it out.
    for key in ("skill", "skill_name", "name"):
        val = event.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _classify_read_path(vault_root, ucr, sb_os_path, file_path):
    """Classify a Read'd file path into a context surface.

    Returns (surface, yaml_path, surface_label) or (None, None, None) when the
    path is not a workflow-step / command / skill surface (the silent-exit gate).
    """
    fp = Path(file_path)
    if not fp.is_absolute():
        fp = (vault_root / fp)
    fp = fp.resolve()
    name = fp.name

    # 1. Slash-command source: **/.claude/commands/{name}.md
    parts = fp.parts
    if name.endswith(".md") and ".claude" in parts:
        idx = parts.index(".claude")
        if idx + 1 < len(parts) and parts[idx + 1] == "commands" and fp.parent.name == "commands":
            cmd = fp.stem
            return ("command", resolve_command_yaml(vault_root, ucr, cmd),
                    "command %s" % cmd)
        # 2. Skill source: **/.claude/skills/{name}/SKILL.md
        if name == "SKILL.md" and idx + 1 < len(parts) and parts[idx + 1] == "skills":
            skill = fp.parent.name
            return ("skill", resolve_skill_yaml(vault_root, ucr, skill),
                    "skill %s" % skill)

    # 3. Workflow-step file under a known workflow root, ending .md
    if name.endswith(".md"):
        yaml_path, err = resolve_step_yaml(vault_root, ucr, sb_os_path, str(fp))
        if not err and yaml_path is not None:
            return ("step", yaml_path, "step %s" % file_path)

    return (None, None, None)


def run_hook():
    """Read a Claude Code hook event from stdin, emit injected context for a
    recognised surface, and ALWAYS exit 0 (fail-soft). Any error -> silent 0."""
    try:
        raw = sys.stdin.read()
        event = json.loads(raw)
        if not isinstance(event, dict):
            return 0

        event_name = event.get("hook_event_name")
        tool_name = event.get("tool_name")

        vault_root = find_vault_root(None)
        ucr, sb_os_path = load_config(vault_root)

        yaml_path = None
        surface_label = None

        if event_name == "PreToolUse" and tool_name == "Skill":
            skill = _extract_skill_name(event)
            if not skill:
                return 0
            yaml_path = resolve_skill_yaml(vault_root, ucr, skill)
            surface_label = "skill %s" % skill
        elif event_name == "PostToolUse" and tool_name == "Read":
            ti = event.get("tool_input")
            file_path = ti.get("file_path") if isinstance(ti, dict) else None
            if not file_path:
                return 0
            _surface, yaml_path, surface_label = _classify_read_path(
                vault_root, ucr, sb_os_path, file_path
            )
            if yaml_path is None:
                return 0  # not a context surface -> silent
        else:
            return 0  # any other event/tool -> silent

        status, payload = load_records(vault_root, yaml_path)
        if status != "ok" or not payload:
            return 0  # NO CONTEXT / CANNOT PARSE / no usable entries -> no stdout

        rendered = render_text(surface_label, yaml_path, payload, vault_root)
        print(json.dumps(
            {"hookSpecificOutput": {
                "hookEventName": event_name,
                "additionalContext": rendered,
            }},
            ensure_ascii=False,
        ))
        return 0
    except Exception:
        # A hook must NEVER block or error a tool call. Swallow everything.
        return 0


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description="Deterministic sb-os context-injection resolver.")
    ap.add_argument("--surface", choices=["skill", "step", "command"],
                    help="execution surface (required unless --hook)")
    ap.add_argument("--name", help="skill/command name (with --surface skill|command)")
    ap.add_argument("--file", help="workflow step .md path (with --surface step)")
    ap.add_argument("--vault-root", help="vault root override (test seam)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument(
        "--hook",
        action="store_true",
        help="run as a Claude Code hook: read a hook event JSON from stdin, "
        "derive the surface from it, and print the matching injected context "
        "as a hookSpecificOutput envelope. Always exits 0 (fail-soft).",
    )
    ap.add_argument(
        "--path-only",
        action="store_true",
        help="print the resolved context-YAML path (exists or not) and exit — "
        "the single source of truth for path resolution, consumed by the "
        "sb-inject-context command to locate the file to create/edit.",
    )
    args = ap.parse_args(argv)

    # UTF-8 stdout (Portuguese accents, ✅, etc. on Windows consoles).
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    # Exactly one of {--hook, --surface} drives the run.
    if args.hook:
        if args.surface:
            ap.error("--hook and --surface are mutually exclusive")
        return run_hook()
    if not args.surface:
        ap.error("one of --surface {skill,step,command} or --hook is required")

    vault_root = find_vault_root(args.vault_root)
    ucr, sb_os_path = load_config(vault_root)

    if args.surface == "skill":
        if not args.name:
            ap.error("--surface skill requires --name")
        yaml_path = resolve_skill_yaml(vault_root, ucr, args.name)
        surface_label = "skill %s" % args.name
    elif args.surface == "command":
        if not args.name:
            ap.error("--surface command requires --name")
        yaml_path = resolve_command_yaml(vault_root, ucr, args.name)
        surface_label = "command %s" % args.name
    else:
        if not args.file:
            ap.error("--surface step requires --file")
        yaml_path, err = resolve_step_yaml(vault_root, ucr, sb_os_path, args.file)
        if err:
            if args.json:
                print(json.dumps({"status": "error", "reason": err}, ensure_ascii=False))
            else:
                print("ERROR: %s" % err)
            return 2
        surface_label = "step %s" % args.file

    if args.path_only:
        out = str(yaml_path.relative_to(vault_root)).replace("\\", "/") \
            if _under(yaml_path, vault_root) else str(yaml_path)
        print(json.dumps({"status": "ok", "path": out,
                          "exists": yaml_path.exists()}, ensure_ascii=False)
              if args.json else out)
        return 0

    status, payload = load_records(vault_root, yaml_path)
    if status == "none":
        print(json.dumps({"status": "none"}) if args.json else "NO CONTEXT")
        return 0
    if status == "parse":
        reason = payload
        msg = "CANNOT PARSE %s: %s" % (yaml_path, reason)
        print(json.dumps({"status": "parse_error", "source": str(yaml_path),
                          "reason": reason}, ensure_ascii=False) if args.json else msg)
        return 3

    records = payload
    if args.json:
        print(render_json(surface_label, yaml_path, records, vault_root))
    else:
        print(render_text(surface_label, yaml_path, records, vault_root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
