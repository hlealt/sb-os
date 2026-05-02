# Workflow Context Injection

When the agent begins executing a workflow step file — a `.md` file under an sb-os workflow root that the agent has been instructed to follow as part of a workflow — check for a matching context YAML before acting on the step's instructions. This check fires per step file, not once per session — every time the agent loads a new step, re-check. If the file exists, read it and process entries top-to-bottom BEFORE the step's native logic. If it does not exist, skip silently and proceed with native workflow logic only.

This rule does NOT apply when merely reading a workflow file for reference, exploration, or analysis.

## Path Resolution

1. Take the workflow file's path relative to its workflow root (e.g., `{workflow-name}/{phase}/step-01-{name}.md`)
2. Swap `.md` extension to `.yaml`
3. Prepend the configured user-context root (default `.user/context/`; resolve from `sb-os.json` → `user_context_root`)
4. Result: `{user_context_root}/{workflow-name}/{phase}/step-01-{name}.yaml`

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
