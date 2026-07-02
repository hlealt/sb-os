# Context Injection — Schema & Path Resolution Reference

Reference for sb-os user-context injection: the execution surfaces it fires on, how each surface's context-YAML path is resolved, the YAML entry schema, and how the resolver's output is processed.

**Firing is AUTOMATIC.** Context injection runs by itself via the installed Claude Code hook — `install/hooks.py` wires the hook into `.claude/settings.local.json`, and the hook invokes `resolve_context.py --hook` on the relevant tool calls. Agents no longer run the resolver by hand for each surface; this document describes the contract the hook and the resolver implement, not a manual gate.

The resolver `para/workflows/sb-inject-context/resolve_context.py` is the single source of truth for path resolution and loading: it reads `user_context_root` from `sb-os.json`, resolves the YAML path, probes it, and prints each entry's loaded content (or an `AGENT ACTION`), or the single line `NO CONTEXT`. The `sb-inject-context` command consumes the same logic via `--path-only` to locate the file it creates or edits.

## Execution Surfaces

Three surfaces resolve a context YAML under a single `user_context_root`:

| Surface | Fires on | YAML it resolves |
|---------|----------|------------------|
| Skill | A skill invocation (any source — sb-os, RBTV, user, plugin) | `{user_context_root}/skills/{skill-name}.yaml` |
| Workflow step file | Execution of a step `.md` under a workflow root (below) | `{user_context_root}/{path-relative-to-workflow-root}.yaml` |
| Command | An explicit Read of the installed `.claude/commands/{name}.md` file | `{user_context_root}/commands/{name}.yaml` |

A "workflow root" is any directory that contains workflow definitions. Two roots are valid:

| Root | Holds |
|------|-------|
| sb-os repo per-module workflows directories (`{sb_os_path}/{module}/workflows/`, where `{module}` is `para`, `wiki`, or `finance`) | Shippable sb-os workflows installed via the sb-os installer |
| Personal workflows directory (e.g., `.user/workflows/`) | User-owned workflows that ship with the vault but not with sb-os (accountant, mentor, sb-life-planner, therapy-summarizer, etc.) |

## Path Resolution

The base path is ALWAYS resolved through `sb-os.json`: the resolver reads the `user_context_root` field; if `sb-os.json` is missing or the field is unset, it uses the default `.user/context/`. Never hardcoded.

### Skills

1. Take the skill's name (e.g., `rbtv-safe-move`).
2. Result: `{user_context_root}/skills/{skill-name}.yaml`.

The `skills/` namespace keeps a skill's YAML from colliding with a workflow folder of the same name.

| Skill invoked | Resolved YAML (assuming `user_context_root: .user/context/`) |
|---------------|---------------------------------------------------------------|
| `rbtv-safe-move` | `.user/context/skills/rbtv-safe-move.yaml` |
| `rbtv-commit` | `.user/context/skills/rbtv-commit.yaml` |

### Workflow step files

Both workflow roots are treated identically: only the path relative to the workflow root matters.

1. Take the workflow file's path relative to its workflow root (e.g., `{workflow-name}/{phase}/step-01-{name}.md`).
2. Swap the `.md` extension to `.yaml`.
3. Prepend the resolved `user_context_root`.
4. Result: `{user_context_root}/{workflow-name}/{phase}/step-01-{name}.yaml`.

| Workflow file | Path relative to root | Resolved YAML (assuming `user_context_root: .user/context/`) |
|---------------|----------------------|---------------------------------------------------------------|
| `{sb_os_path}/wiki/workflows/sb-tutor/sb-tutor.md` | `sb-tutor/sb-tutor.md` | `.user/context/sb-tutor/sb-tutor.yaml` |
| `.user/workflows/accountant/accountant.md` | `accountant/accountant.md` | `.user/context/accountant/accountant.yaml` |
| `.user/workflows/sb-life-planner/weekly-review/step-04-calendar.md` | `sb-life-planner/weekly-review/step-04-calendar.md` | `.user/context/sb-life-planner/weekly-review/step-04-calendar.yaml` |

Workflow names are unique across roots; if a collision ever exists, the workflow currently executing is authoritative for path-relative resolution.

### Commands

1. Take the command's name (the slash-command name, e.g., `sb-inject-context`).
2. Result: `{user_context_root}/commands/{command-name}.yaml`.

The `commands/` namespace keeps a command's YAML from colliding with a skill or workflow folder of the same name.

| `.claude/commands/{name}.md` Read | Resolved YAML (assuming `user_context_root: .user/context/`) |
|-----------------------------------|---------------------------------------------------------------|
| `sb-inject-context` | `.user/context/commands/sb-inject-context.yaml` |

**Thin-loader caveat.** The command surface fires ONLY on an explicit Read of the installed `.claude/commands/{name}.md` file. Normal `/{name}` invocation does NOT Read that file — slash expansion inlines the loader body — so the command surface never fires for standard slash usage. When a command is a thin loader that reads a workflow file (`Read and execute {…}/workflows/{name}/{name}.md`), inject context on the **workflow-step** surface of that workflow file instead: that file IS Read every run. Same reasoning applies to the skill surface for a skill invoked only through a thin-loader command.

## Schema Reference

Each YAML file contains a list of entries under a top-level `context:` key. Every entry has these fields:

| Field | Required | Applies to | Description |
|-------|----------|------------|-------------|
| `name` | Yes | All types | Human-readable label for this entry |
| `type` | Yes | All types | One of: `file`, `script`, `url`, `text`, `mcp` |
| `mode` | No | All types | One of: `read` (default), `write`, `read-write` |
| `instruction` | Yes | All types | What the agent must do with this content — the full behavior definition |
| `path` | Conditional | `file`, `script` | Vault-relative path to file or directory |
| `glob` | No | `file` | Glob pattern to match files within `path` directory |
| `select` | No | `file` | Selection strategy: `latest` (by filename lexicographic sort), `all` |
| `count` | No | `file` | Maximum number of files to load (used with `select: latest`) |
| `sections` | No | `file` | List of markdown heading names to extract. Case-sensitive. Matches any heading level (`#`, `##`, `###`, etc.). Loads all content under the matched heading until the next heading of same or higher level. Silently skips sections not found. Reads entire file if omitted. |
| `command` | Conditional | `script` | Path to executable |
| `args` | No | `script` | List of command-line arguments |
| `url` | Conditional | `url` | URL to fetch |
| `content` | Conditional | `text` | Inline text content |
| `server` | Conditional | `mcp` | MCP server name |
| `tool` | Conditional | `mcp` | MCP tool name |
| `params` | No | `mcp` | MCP tool parameters (object) |

"Conditional" means required for that type.

## Processing Rules

The resolver loads and prints entries in document order; each entry's `instruction` is applied to what the resolver printed:

- Entries are printed and applied in document order (top-to-bottom).
- `type: text` and `type: file` (read / read-write) that resolve to an existing file — the resolver prints the loaded content; apply the `instruction` to it. (`read-write` adds a write-back note — load, act, write back per `instruction`.)
- `type: script` / `url` / `mcp`, `mode: write`, and any `file` whose path/glob does NOT resolve as-is (placeholders) — the resolver prints these as a labelled `AGENT ACTION` rather than content; perform the action and apply the `instruction`. Script args / placeholder paths must be substituted before running or loading.
- A source the resolver could not load (missing personal file) is reported, not fatal — continue to the next entry.
- `NO CONTEXT` — no YAML exists or it has no entries; proceed with native logic only.
- `CANNOT PARSE` (invalid YAML, exit 3) — surface the named file and proceed with native logic only; never abort the surface.

## Sub-agents

The hook fires on tool calls inside sub-agents too: a PostToolUse/PreToolUse hook runs for a sub-agent's tool calls, so the hook now covers sub-agents that the previous rule-based gate never reached (sub-agents launched via the Agent tool do not inherit rules). The parent agent still passes context manually ONLY for context a sub-agent needs that none of its own tool calls would trigger the hook on.
