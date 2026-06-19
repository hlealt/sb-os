# System Component Conventions

Micro-file architecture for sb-os. These conventions govern all system components shipped by sb-os and any user-defined components in `.claude/`.

## Core Principles

| Principle | Rule |
|-----------|------|
| Micro-file design | Each file has one responsibility. Max 250 lines. |
| Token efficiency | Every line must earn its place. Use tables over prose, single sentences over paragraphs, references over repetition. When output quality and token cost conflict, output wins — but never add weight without added value. |
| Sequential enforcement | Numbered steps execute in order. No skipping. |
| Just-in-time loading | Load only the current step. Never pre-load the next. |
| Self-contained files | Each file must be interpretable without reading other files first. |
| Mandatory language | Use "must", "never", "always". Never use "should", "consider", "may". |

## Context Separation (`sb-` Components)

`sb-` prefixed components must be user-agnostic — no personal paths, names, or routing inside the component file. User-specific content lives in YAML files at the user-context root (resolved from `sb-os.json` → `user_context_root`, default `.user/context/`) and is injected automatically by the context-injection hook (schema: `para/docs/context-injection-schema.md`). Applies to both creating and editing `sb-` components.

| User-specific (extract to YAML) | Component-native (keep in file) |
|---------------------------------|---------------------------------|
| File paths to personal data | Workflow logic and step sequence |
| Names, accounts, credentials | Decision trees and menus |
| Routing tables with personal entries | Format templates and schemas |
| Examples built from personal data | Generic examples |
| Sync targets, guard entries | Instructions and rules |

Components must degrade gracefully when context YAML files are missing — no errors, skip silently.

## File Locations

Source-of-truth locations inside the sb-os repo:

| Component | Source location |
|-----------|-----------------|
`{module}` is the on-disk module folder owning the component (`para` or `wiki`).

| Component | Source location |
|-----------|-----------------|
| Workflow entry point | `{sb_os_path}/{module}/workflows/{id}/{id}.md` |
| Workflow step files | `{sb_os_path}/{module}/workflows/{id}/step-{nn}-{name}.md` |
| Workflow data files | `{sb_os_path}/{module}/workflows/{id}/data/` |
| Skills (auto-discoverable) | `{sb_os_path}/{module}/skills/{id}/SKILL.md` |
| Commands (manually invoked) | `{sb_os_path}/{module}/commands/{id}.md` |
| Rules | `{sb_os_path}/{module}/rules/{id}.md` |
| Templates | `{sb_os_path}/para/templates/` |
| Repo-level reference docs | `{sb_os_path}/docs/` |
| Module-scoped reference docs | `{sb_os_path}/{module}/docs/` |

Installed locations in a user's vault:

| Component | Installed location |
|-----------|--------------------|
| Skills (thin loaders) | `.claude/skills/{id}/SKILL.md` |
| Commands (thin loaders) | `.claude/commands/{id}.md` |
| Rules (copied verbatim) | `.claude/rules/{id}.md` |

Docs files document **final state only** — never logs or planning artifacts. Workflow directories must NOT contain documentation — repo-level docs live in `{sb_os_path}/docs/`; module-scoped docs live in `{sb_os_path}/{module}/docs/`.

## Workflow Entry Point Format

```yaml
---
name: {Workflow Name}
description: {one-line description}
nextStep: {sb_os_path}/{module}/workflows/{id}/step-01-{first-step}.md
---
```

Body: purpose statement + activation sequence (knowledge files to load, then proceed to step 01).

## Step File Format

```yaml
---
stepNumber: {n}
stepId: {kebab-case-id}
nextStepFile: step-{n+1}-{next-id}.md
---
```

Body structure:
1. `# Step {n}: {Name}` — heading
2. `**Goal:**` — one sentence
3. `## Mandatory Sequence` — numbered steps, executed in exact order
4. `## Step Menu` — `[C] Continue` / `[X] Exit` (last step uses `[D] Done`)

## Naming Conventions

| Component | Named after | Examples |
|-----------|-------------|----------|
| Skills | The **activity** to be performed | `vault-ops`, `vault-integrity` |
| Commands | The **role** that executes the work | `archivist`, `tutor`, `inject-context` |

## Command Format

Commands are manually invoked by the user with `/{name}`. Named after the role. Thin loaders that delegate to a workflow — all deep instructions live in the workflow body.

```markdown
Read and execute `{sb_os_path}/{module}/workflows/{target}.md`.
```

No frontmatter required. Body is a one-line delegation. Exception: commands with very light instructions (short menus, simple routing) may inline them when the token cost is trivial.

## Skill Format (Auto-Discoverable)

Skills are auto-discovered by Claude Code — the agent matches user intent against skill descriptions and invokes the right skill without the user explicitly requesting it. Named after the activity.

```yaml
---
name: {activity-name}
description: Use when {triggering conditions and symptoms — never summarize the workflow}.
---
```

| Rule | Requirement |
|------|-------------|
| `name` | Letters, numbers, hyphens only — describes the activity |
| `description` | Starts with "Use when..." — triggering conditions only, never workflow summary |
| Overview | 1-2 sentence purpose statement |
| When to Use | Table or bullets with signals/examples. Include "do NOT use" exclusions |
| Quick reference | Optional — component types, options, or key concepts |
| Execution | Delegation line or inline instructions. Deep instructions live in the workflow body |
| Size | 20-40 lines for thin loaders. Unlimited for self-contained skills with inline knowledge |

## Rule Format

```markdown
# {Rule Name}

{Purpose in one sentence.}

## Rules

| Rule | Detail |
|------|--------|
```

No frontmatter. Always-loaded — keep concise. If content is only needed on specific triggers, use a skill instead.

## Size Guidelines

| Component | Target | Max |
|-----------|--------|-----|
| Workflow entry point | 15-30 lines | 60 |
| Step file | 80-150 lines | 250 |
| Agent file | 55-76 lines | 100 |
| Rule file | 30-50 lines | 80 |
| Skill SKILL.md (thin loader) | 20-30 lines | 40 |
| Command .md | 1-60 lines | 80 |

## Language

All shipped sb-os components must be written in English. Vault Areas, Projects, and tags MUST also be in English (proper nouns and acronyms exempt). Prose content within a user's vault files may be any language the user chooses.
