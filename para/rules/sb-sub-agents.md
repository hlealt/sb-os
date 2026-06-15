# Sub-Agents

**MANDATORY. NO EXCEPTIONS.** Every Agent tool call MUST pass the Pre-Dispatch Gate below before invocation. Skipping the gate is a rule violation, even for "quick" or "simple" dispatches.

## Default Model

When launching sub-agents via the Agent tool, use `sonnet` as the default model. NEVER use `haiku` unless the user explicitly requests it.

## Pre-Dispatch Gate

Before EVERY Agent tool call, you MUST:

1. **Scan the planned prompt** for trigger keywords (see Mandatory Skill Triggers below).
2. **Identify every matching skill** from the available skill list — sb-os skills below, plus any added via the SB-OS-MANAGED block, plus any non-sb-os skills (user-defined, plugins, third-party) that match the planned task.
3. **Name each matching skill explicitly** in the sub-agent prompt using the Required Phrasing format.
4. **Include the mandate** — do not just mention the skill; instruct the sub-agent to invoke and follow it.

You MUST NOT dispatch until the prompt contains every required skill directive. If you catch yourself about to dispatch without the gate, STOP and rewrite the prompt.

## Mandatory Skill Triggers

If the planned sub-agent task or prompt contains ANY trigger in a row below, you MUST name the matching installed sb-os skill in the prompt. Multiple matching trigger families = multiple skills named.

| Trigger family — keywords or task type | Matching sb-os skill |
|----------------------------------------|----------------------|
| Creating/routing tasks; creating/moving/renaming/deleting vault content (EXCLUDING wiki content — pages, raw sources, and logs in the knowledge base, which `sb-wiki-ingest`/`sb-wiki-lint` govern); creating project/area/resource directories; editing CLAUDE.md; modifying sb-os/.claude/.agents system components | `sb-vault-ops` |
| Moving, renaming, or deleting vault files; creating project/area/resource directories; creating vault files that change routing or dependencies | `sb-vault-integrity` |

Ordinary edits to existing routed files are non-triggers when path, filename, frontmatter type, task format, routing, links, and directory structure are unchanged.

If multiple installed skills match a trigger family, name every match. If no installed skill matches a trigger family for the current dispatch, the family is inactive — do not invent skill names.

<!-- SB-OS-MANAGED START -->
<!-- The sb-os installer injects additional skill triggers here at install time -->
<!-- based on the components selected during install. DO NOT EDIT MANUALLY. -->
<!-- Edits inside this block are overwritten on each `install.py` run. -->
<!-- SB-OS-MANAGED END -->

## Non-sb-os Skills

This rule covers sb-os skills only. Other skills installed in the workspace (user-defined, plugins like RBTV, third-party) have their own scope and triggers. When a non-sb-os skill matches the planned sub-agent task — based on its description in the available skill list — you MUST also name it in the sub-agent prompt using the Required Phrasing below. The Pre-Dispatch Gate fires for ALL applicable skills, regardless of source.

## Required Phrasing

The sub-agent prompt MUST contain a directive in one of these forms. Mere mention of the skill name is INSUFFICIENT. Replace `<skill-name>` with the actual installed skill matched from the trigger families.

| Acceptable | Unacceptable |
|------------|--------------|
| "Invoke the `<skill-name>` skill before any vault edit and follow it exactly." | "You can use the `<skill-name>` skill." |
| "You MUST invoke `<skill-name>` before any edit and follow it exactly." | "Consider checking `<skill-name>`." |
| "Start by invoking `<skill-name>` and execute its checklist." | "See `<skill-name>` for context." |

Directives MUST be imperative ("invoke", "follow exactly", "execute") — never permissive ("may", "consider", "can").

## Red Flags — STOP and Rewrite

If you notice any of these thoughts, you are about to violate this rule:

| Thought | Action |
|---------|--------|
| "The sub-agent will auto-discover the skill" | STOP. Name it explicitly. Auto-discovery is unreliable. |
| "This dispatch is too small to need a skill directive" | STOP. Size does not waive the gate. |
| "I already named the skill last dispatch" | STOP. Each dispatch is independent. Name it again. |
| "The prompt is already long, adding skill directives will bloat it" | STOP. Brevity does not waive the gate. |
| "Specialized sub-agent types (Explore, Plan, general-purpose) don't need this" | STOP. These types need it MOST — they skip skills by default. |
| "No installed skill matches this exact trigger keyword" | STOP. Re-scan the available skill list for partial matches before declaring the family inactive. |

## Scope

This rule applies to EVERY Agent tool invocation, including parallel dispatches and background agents. It does not apply to the `Skill` tool (direct skill invocation by the parent agent).
