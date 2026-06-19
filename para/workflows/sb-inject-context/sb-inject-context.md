---
name: sb-inject-context
description: Interactive CRUD for skill and workflow-step context injection entries
---

# Context Injection Manager

Manage user-specific context entries for workflow steps. Creates, updates, and deletes YAML context files under the configured user-context root (resolved from `sb-os.json` → `user_context_root`; default `.user/context/`).

The files this command writes are READ at runtime by the deterministic resolver `resolve_context.py`, fired automatically via the installed Claude Code hook (`install/hooks.py`; `resolve_context.py --hook`). Schema and path-resolution contract: `para/docs/context-injection-schema.md`. To stay in sync, ALWAYS locate a surface's YAML with the resolver instead of computing the path by hand:

```
python {sb_os_path}/para/workflows/sb-inject-context/resolve_context.py --surface skill --name <skill-name> --path-only
python {sb_os_path}/para/workflows/sb-inject-context/resolve_context.py --surface step  --file <step-file-path> --path-only
```

It prints the exact YAML path (whether or not it exists yet) — the single source of truth both this command and the runtime gate share. Emit standard YAML (the resolver parses with a real YAML library); a malformed file the agent hand-writes will be reported as `CANNOT PARSE` at runtime.

**sb-vault-ops exemption:** Context YAML files are structured data validated by this command's own schema (`para/docs/context-injection-schema.md`). This command is the authoritative interface — sb-vault-ops is not needed for context YAML CRUD operations.

## Entry Point

Present:

```
Context Injection Manager

→ [C] Create entry
→ [U] Update entry
→ [D] Delete entry
```

---

## Create Entry

### 1. Resolve target

A context entry targets one of two surfaces — a **skill** or a **workflow step**. Determine which from the user's description; if unclear, ask: "Inject this into a skill (applies whenever that skill is invoked) or a specific workflow step?"

**Skill target:** the user names a skill (e.g., "the `rbtv-safe-move` skill"). Confirm the exact skill name. The context applies every time that skill is invoked.

**Workflow-step target:** ask which workflow and where in it they want to inject context. The user will describe this in natural language (e.g., "this workflow, right before it reads my daily tasks"). Read the workflow's entry point and step files to understand its flow, then map the user's description to the correct step file. Confirm: "That maps to `step-02-{name}.md` — the step where {what it does}. Correct?" If ambiguous, describe 2-3 candidate steps by what they do (not by filename) and ask the user to pick.

### 2. Check existing context

Resolve the context YAML path with the resolver (single source of truth — do NOT compute it by hand):

```
python {sb_os_path}/para/workflows/sb-inject-context/resolve_context.py --surface <skill|step> <--name <skill-name> | --file <step-file-path>> --path-only
```

The printed path is the target. Then:

- If the YAML file exists → show current entries and offer to append
- If not → will create new file at that path

### 3. Define entry

Collect fields interactively:

**a) Name:** Ask the user for a human-readable label.

**b) Type:** Present options:
```
Type:
1. file — vault file or directory
2. script — executable command
3. url — web URL to fetch
4. text — inline text content
5. mcp — MCP server tool call

Select type [number]:
```

After type selection, collect type-specific fields:

| Type | Fields to collect |
|------|-------------------|
| `file` | `path` (required), `glob`, `select`, `count`, `sections` |
| `script` | `command` (required), `args` |
| `url` | `url` (required) |
| `text` | `content` (required) |
| `mcp` | `server` (required), `tool` (required), `params` |

**c) Mode:** Present options with default:
```
Mode:
1. read (default — load content)
2. write (output destination)
3. read-write (load and write back)

Select mode [number, default=1]:
```

**d) Instruction:** Ask what the agent should do with this content.

### 4. Instruction guidance

If the instruction exceeds 3 sentences, suggest:

> "Instructions are typically 1-3 sentences. Complex behaviors may need more. Want to shorten it, or keep as-is?"

Always allow override.

### 5. Review and confirm

Show the complete YAML entry:

```yaml
- name: [name]
  type: [type]
  mode: [mode]
  path: [path]
  instruction: >
    [instruction]
```

Ask: "Add this entry? [Y/N]"

### 6. Write

- If the YAML's parent directory does not exist → create it (`{user_context_root}/skills/` for a skill, `{user_context_root}/{workflow-path}/` for a workflow step)
- If YAML file exists → append entry under existing `context:` key
- If YAML file does not exist → create with `context:` key and this entry
- Reference the template at `{sb_os_path}/para/templates/context/workflow-context.yaml` for structure

### 7. Continue

Ask: "Add another entry to this file? [Y/N]"
- Yes → return to step 4
- No → return to entry point

---

## Update Entry

### 1. Resolve target

Same as Create step 1 — determine the surface (skill or workflow step) and resolve to its YAML path.

### 2. Load existing entries

Resolve the context YAML path. If no YAML exists, inform user and return to entry point. Otherwise show entries as numbered list with names:

```
Entries in [file]:
1. {entry name 1} (file, read)
2. {entry name 2} (script, read)
...

Select entry to update [number]:
```

### 3. Edit fields

Show current values for all fields. Ask which field(s) to change. Collect new values.

### 4. Review and write

Show the updated entry. Ask for confirmation. Write back to the YAML file.

---

## Delete Entry

### 1. Resolve target

Same as Create step 1 — determine the surface (skill or workflow step) and resolve to its YAML path.

### 2. Load existing entries

Same as Update step 2. Show entries, user picks which to remove.

### 3. Confirm

Show the full entry. Ask: "Delete this entry? [Y/N]"

### 4. Write

Remove the entry from the YAML file. If the file becomes empty (no entries under `context:`), delete the file entirely.

---

## Rules

- All YAML output MUST follow the schema in `para/docs/context-injection-schema.md`
- Entries are appended at the end of the `context:` list (processing order = document order)
- When creating new files, include a comment header: `# Context for: skill [skill-name]` (skill target) or `# Context for: [workflow] / [step]` (workflow-step target)
- Never modify workflow step files — this command manages only user-context YAML files under `{user_context_root}`
