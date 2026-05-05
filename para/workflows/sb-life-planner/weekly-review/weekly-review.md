# Weekly Review v3 — Orchestrator

## Purpose

Close the ending week and plan the next one, ensuring the vault Home reflects exactly what was planned.

## Problem this workflow solves

The vault's Home aggregates all tasks (`- [ ]`) from all `.md` files and organizes them by date in columns. For the Home to be useful:

1. **Every planned task must exist as `- [ ]` with the correct date** in the corresponding project/area file
2. **Unplanned tasks (backlog) have no date** — they appear in "No Date"
3. **Review notes (weekly notes) do NOT use checkboxes** — they use simple bullets with `[[links]]` to the files where the actual task lives
4. **Zero duplication** — each task exists in ONE file only

## Session Log

The agent creates a tracking file at the start of every review.

Default path: `0-periodic-notes/weekly/{week}-session-log.md`. If context YAML provides `path.weekly.session-log`, use that value instead. `{week}` expands to `yyyy-Wnn`.

**Rules:**
1. Create in step 01, before any other action
2. Every turn, BEFORE responding to the user, check if something mentioned should be added to the log
3. Use as checklist in steps 06 (plan) and 07 (verify)
4. At the end of the review: reconcile with vault, then archive to the archive path

Default archive path: `0-periodic-notes/weekly/archive/{week}-session-log.md`. If context YAML provides `path.weekly.session-log-archive`, use that value instead.

**Session log sections:**

```markdown
# Session Log — Weekly Review Wnn

## Decisions made
- [item] — [decision] — [affected file]

## Tasks mentioned (for reconciliation)
- [ ] [task] — [expected destination in vault]

## Name/term corrections
- [wrong] → [correct] — [context]

## Items not to forget
- [anything the user asked that hasn't been done yet]

## Priorities defined (Must/Should)
- Must: [list]
- Should: [list]

## Habits inventory
<!-- Produced by sub-agents in Step 01. Aggregated in Step 02 for axis check. -->
### Daily YYYY-MM-DD
| Category | Checked items |
|----------|---------------|
| (categories from context injection) | ... |

## Daily inventory
<!-- Produced by sub-agents in Step 01. Used by Step 05 for routing. -->
### Daily YYYY-MM-DD
| # | Content (summary) | Classification | Destination |
|---|-------------------|----------------|-------------|
| 1 | ... | Routable / Review note / Task | file or — |
```

Habit category labels for the inventory table come from the context-injection key `text.habit-categories` (also redeclared in the step-01 and step-02 YAMLs for their own scope).

## Week boundaries

Default first day of the week: **Monday**. If context YAML provides `config.week.start-day`, use that value (`monday` or `sunday`). The boundary table below assumes a Monday-to-Sunday week; if the configured start day is `sunday`, the agent shifts the table by one day accordingly.

| Today is | Closing week | Planning week |
|----------|-------------|---------------|
| Friday, Saturday, or Sunday | Current week | Next week |
| Monday, Tuesday, Wednesday, or Thursday | Previous week | Current week |

All date ranges in this workflow (calendar reads, daily note scans, planning proposals) use the closing/planning week's first day as Day 1 and the seventh day as the last.

## Task conventions

Format, prioritization (MoSCoW), sub-bullets and lifecycle: invoke the `sb-vault-ops` skill (tasks path). Every task created or edited during the review MUST follow this format.

### Review-specific conventions

| Type | Convention |
|------|-----------|
| **Review item** | Date on the last day of the review week + sub-bullet `_Review:_ prioritize in Wnn closing / Wnn+1 planning` |
| **Rescheduling** | Sub-bullet `_Rescheduled Nx (origin: 📅 YYYY-MM-DD)_`. When N >= 2 → chronic straggler: force a decision other than rescheduling |

## Output document

Default weekly note path: `0-periodic-notes/weekly/{week}.md`. If context YAML provides `path.weekly.note`, use that value. `{week}` expands to `yyyy-Wnn` of the week being CLOSED (not the next one).

State tracking in frontmatter:

```yaml
---
type: log
tags: []
stepsCompleted: []
closingWeek: 'Wnn'
planningWeek: 'Wnn+1'
date: 'YYYY-MM-DD'
---
```

## Steps

| Step | File | Purpose |
|------|------|---------|
| 01 | `step-01-close-week.md` | Init + retrospective + session log creation |
| 02 | `step-02-axis-context.md` | Life axis coverage check + therapy/psychiatry context reading |
| 03 | `step-03-intention.md` | "Good week" reflection without bias — clean room, objective-driven |
| 04 | `step-04-calendar.md` | Calendar reading (past + future) |
| 05 | `step-05-route-dailies.md` | Review and route daily note content |
| 06 | `step-06-context.md` | Vault scan + cross-reference with intentions + chronic stragglers + axis tracking |
| 07 | `step-07-plan-and-write.md` | Daily distribution with immediate vault writing |
| 08 | `step-08-verify.md` | Triple check (5 verifications) + archive session log |

## Context boundaries

The weekly review is split into context blocks. At each boundary, the user starts a **new session** with the slash command from `command.entry-point` (default `/sb-life-planner`) → Week. The fresh agent reads `stepsCompleted` in the weekly note frontmatter and resumes from the next step.

| Block | Steps | Nature | What the agent reads |
|-------|-------|--------|----------------------|
| **A** | 01–03 | Reflective/strategic | Inputs from `text.block-a.inputs` (defaults: therapy/self-knowledge/goals/meeting summaries when configured). Heavy personal context, discussion, challenging |
| **B** | 04–05 | Calendar + routing | Weekly note (from Block A), session log. Calendar events, daily notes for routing |
| **C** | 06–08 | Planning + verification | Weekly note (from A+B), session log (with daily inventory from B). Vault task files for planning |

**Handoff mechanism:**

Each block writes its conclusions to two places:
1. **Weekly note** — structured output (retrospective, axes, intention, intentions list) + agent-notes section (temporary section with patterns, challenges, and planning context — deleted in step 08). Default heading: `## Agent notes`. If context YAML provides `section.agent-notes.heading`, use that value.
2. **Session log** — operational state (decisions, tasks mentioned, daily inventory, pending items)

The next block's agent reads both and has full context without re-reading source files (therapy transcripts, self-knowledge notes, daily note raw content).

**Hard boundaries:** Steps 03→04 and 05→06. At each boundary the agent instructs the user to start a new session. Do NOT present the next step's menu.

## Agent vs. user scope

The agent NEVER categorizes user priorities as Must/Should on its own.

| Agent can | Agent CANNOT |
|-----------|--------------|
| Ask the user to separate Must/Should | Decide the categorization alone |
| Suggest ("this looks like Must given that X") | Present as fact |
| Question ("deadline is tomorrow — is it really Should?") | Ignore the user's categorization |

The final priority decision ALWAYS belongs to the user.

## Execution rules

1. Design history and rationale: `weekly-review/context.md` (read only if you need to understand or evolve the workflow)
2. Load only the current step. Never pre-load the next one
3. Each step ends with a menu. Wait for the user's choice
4. Steps execute in order. No skipping
5. After completing each step, update `stepsCompleted` in the weekly note frontmatter
6. Append-only: never modify sections already written in the weekly note
7. If the session is interrupted, step-01 detects `stepsCompleted` and resumes from the next pending step
8. Every turn, check if something should be added to the session log BEFORE responding
9. **Continuous reconciliation** — at the end of each step, BEFORE presenting the menu, cross-reference the session log with what has already been processed. If there are items in "Tasks mentioned" or "Items not to forget" that should have been handled in this step but were not → flag immediately to the user
10. Every task created or edited during the review MUST follow the `sb-vault-ops` skill (tasks path)
11. **Context flush at block boundaries** — at the end of steps 03 and 05 (hard boundaries), BEFORE ending the session:
    - Ensure EVERYTHING done during the block is saved in the session log (decisions, tasks created/edited, structural changes, pending items for next steps)
    - Update `stepsCompleted` in the weekly note frontmatter
    - Write the agent-notes section to the weekly note (step 03) or update it (step 05) with routing decisions and daily inventory context
    - Instruct the user to start a new session and run the entry-point command (`command.entry-point`, default `/sb-life-planner`) → Week to continue
    - Within a block (e.g., steps 04-05), steps flow normally without requiring `/clear`
