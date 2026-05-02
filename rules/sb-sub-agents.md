# Sub-Agents

**MANDATORY. NO EXCEPTIONS.** Every Agent tool call MUST pass the Pre-Dispatch Gate below before invocation. Skipping the gate is a rule violation, even for "quick" or "simple" dispatches.

## Default Model

When launching sub-agents via the Agent tool, use `sonnet` as the default model. NEVER use `haiku` unless the user explicitly requests it.

## Pre-Dispatch Gate

Before EVERY Agent tool call, you MUST:

1. **Scan the planned prompt** for trigger keywords (see Mandatory Skill Triggers below).
2. **Identify every matching skill** from the available skill list — both the universal sb-os triggers below and any added via the SB-OS-MANAGED block.
3. **Name each matching skill explicitly** in the sub-agent prompt using the Required Phrasing format.
4. **Include the mandate** — do not just mention the skill; instruct the sub-agent to invoke and follow it.

You MUST NOT dispatch until the prompt contains every required skill directive. If you catch yourself about to dispatch without the gate, STOP and rewrite the prompt.

## Mandatory Skill Triggers

If the planned sub-agent task or prompt contains ANY trigger in a row below, you MUST name the matching installed skill in the prompt. Multiple matching trigger families = multiple skills named.

The trigger families below are universal — they fire on every sb-os install. Plugins (e.g., RBTV) may add their own parallel rule with additional families.

| Trigger family — keywords or task type | Matching skill |
|----------------------------------------|----------------|
| Vault content edits, moves, renames, new files in PARA folders or `.user/` | `sb-vault-ops` |
| Creating, moving, renaming, or deleting any vault file (post-op structural sweep) | `sb-vault-integrity` |

If multiple installed skills match a trigger family, name every match. If no installed skill matches a trigger family for the current dispatch, the family is inactive — do not invent skill names.

<!-- SB-OS-MANAGED START -->
<!-- The sb-os installer injects additional skill triggers here at install time -->
<!-- based on the components selected during install. DO NOT EDIT MANUALLY. -->
<!-- Edits inside this block are overwritten on each `install.py` run. -->
<!-- SB-OS-MANAGED END -->

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
