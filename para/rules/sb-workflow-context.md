# Context Injection

**MANDATORY. NO EXCEPTIONS.** Every workflow step file you execute AND every skill you invoke MUST pass the Pre-Action Gate below before you act on its instructions. Skipping the gate is a rule violation, even for "single-file" workflows, "trivial" skills, or surfaces that "obviously don't need user context."

## Pre-Action Gate

Before executing ANY instruction in a workflow step file, OR running the body of a skill you just invoked, you MUST:

| Step | Requirement |
|------|-------------|
| 1. Resolve | Compute the YAML path per Path Resolution below. NEVER hardcode `user_context_root` — read `sb-os.json`. |
| 2. Probe | Attempt to read the resolved YAML. File not found → skip silently and proceed to step 4. |
| 3. Process | If the file exists, process its `context:` entries top-to-bottom — load sources, apply each `instruction` — BEFORE any of the surface's native logic runs. |
| 4. Execute | Only now act on the workflow step file's, or the skill's, own instructions. |

The gate fires PER EXECUTION SURFACE — every time you load a new workflow step `.md`, AND every time you invoke a skill, re-check. A single run may cross many surfaces; each gets its own gate.

The gate does NOT fire when merely reading a workflow file or a skill for reference, exploration, or analysis (no execution = no gate).

## Execution Surfaces

| Surface | Fires when | YAML it resolves |
|---------|-----------|------------------|
| Workflow step file | You execute a step `.md` under a workflow root (below) | `{user_context_root}/{path-relative-to-workflow-root}.yaml` |
| Skill | You invoke a skill (any source — sb-os, RBTV, user, plugin), before running its body | `{user_context_root}/skills/{skill-name}.yaml` |

A "workflow root" is any directory that contains workflow definitions. Two roots are valid:

| Root | Holds |
|------|-------|
| sb-os repo per-module workflows directories (`{sb_os_path}/{module}/workflows/`, where `{module}` is `para`, `wiki`, or `finance`) | Shippable sb-os workflows installed via the sb-os installer |
| Personal workflows directory (e.g., `.user/workflows/`) | User-owned workflows that ship with the vault but not with sb-os (accountant, mentor, sb-life-planner, therapy-summarizer, etc.) |

## Red Flags — STOP and Run the Gate

If you catch ANY of these thoughts, you are about to violate this rule. Delete the thought and run the gate.

| Thought | Action |
|---------|--------|
| "This workflow is single-file, no per-step context needed" | STOP. Single-file workflows still have a YAML at `{user_context_root}/{workflow-name}/{workflow-name}.yaml`. Probe it. |
| "I already loaded the YAML earlier in the session" | STOP. The gate fires per step file load, not once per session. Re-probe. |
| "The step looks self-contained, the YAML probably doesn't apply" | STOP. The YAML's existence — not your judgment of relevance — decides. Probe it. |
| "I'll execute the step now and check the YAML if something seems missing" | STOP. The YAML's `instruction` may add behaviors the step file never mentions. Probe FIRST. |
| "There's no `.user/context/` folder visible in the repo" | STOP. Probe the resolved path anyway — graceful skip on file-not-found is the correct outcome, not preemptive skip. |
| "The user just wants the result fast — gate adds latency" | STOP. The gate is one file read. Speed is not a waiver. |
| "I'm just invoking a skill, not running a workflow — the gate doesn't apply" | STOP. Skill invocation is an execution surface. Probe `{user_context_root}/skills/{skill-name}.yaml` before the skill body runs. |

## Path Resolution

Both surfaces resolve a YAML under a single `user_context_root`. Read `sb-os.json` at the vault root and extract the `user_context_root` field; if `sb-os.json` is missing or `user_context_root` is unset, use the default `.user/context/`. The base path MUST always be resolved through `sb-os.json` — never hardcoded in any agent reasoning, prompt, or downstream tool call.

### Workflow step files

The resolution treats both workflow roots identically: only the path relative to the workflow root matters.

1. Take the workflow file's path relative to its workflow root (e.g., `{workflow-name}/{phase}/step-01-{name}.md`)
2. Swap `.md` extension to `.yaml`
3. Prepend the resolved `user_context_root`.
4. Result: `{user_context_root}/{workflow-name}/{phase}/step-01-{name}.yaml`

| Workflow file | Path relative to root | Resolved YAML (assuming `user_context_root: .user/context/`) |
|---------------|----------------------|---------------------------------------------------------------|
| `{sb_os_path}/wiki/workflows/sb-tutor/sb-tutor.md` | `sb-tutor/sb-tutor.md` | `.user/context/sb-tutor/sb-tutor.yaml` |
| `.user/workflows/accountant/accountant.md` | `accountant/accountant.md` | `.user/context/accountant/accountant.yaml` |
| `.user/workflows/sb-life-planner/weekly-review/step-04-calendar.md` | `sb-life-planner/weekly-review/step-04-calendar.md` | `.user/context/sb-life-planner/weekly-review/step-04-calendar.yaml` |

Workflow names are unique across roots; if a collision ever exists, the agent treats the workflow it is currently executing as authoritative for path-relative resolution.

### Skills

1. Take the skill's name — the name you invoked (e.g., `rbtv-safe-move`).
2. Result: `{user_context_root}/skills/{skill-name}.yaml`.

The `skills/` namespace keeps a skill's YAML from colliding with a workflow folder of the same name.

| Skill invoked | Resolved YAML (assuming `user_context_root: .user/context/`) |
|---------------|---------------------------------------------------------------|
| `rbtv-safe-move` | `.user/context/skills/rbtv-safe-move.yaml` |
| `rbtv-commit` | `.user/context/skills/rbtv-commit.yaml` |

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

- Entries are processed sequentially in document order (top-to-bottom)
- `mode: read` — resolve the source, load content, follow `instruction`
- `mode: write` — the entry defines an output destination; follow `instruction` to create/write content there
- `mode: read-write` — load existing content AND write back per `instruction`
- If a source cannot be resolved (file not found, script fails, URL unreachable), log a warning and continue to the next entry — never abort the workflow step
- If the YAML file exists but contains invalid syntax, log a warning and skip context injection entirely for that step — proceed with native workflow logic only

## Limitations

- Sub-agents launched via the Agent tool do not inherit rules. If a sub-agent needs user context, the parent agent must pass relevant information in the sub-agent's prompt.
