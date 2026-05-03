# Step 06 — Context + Reconciliation

## Purpose

Load vault context, cross-reference with step 03 intentions and step 04 calendar, identify gaps and chronic stragglers. This is the moment where the agent brings the "vault reality" into the conversation.

## Context loading (Block C start)

This step begins the final context block. If `stepsCompleted` includes 01-05 — this is a fresh session. Load context before proceeding:

1. Read the **weekly note**. Default path `0-periodic-notes/weekly/{week}.md`. If context YAML provides `path.weekly.note`, use that value. Read all sections, including the agent-notes section (heading from `section.agent-notes.heading`, default `Agent notes`) — patterns from Block A + routing context from Block B.
2. Read the **session log**. Default path `0-periodic-notes/weekly/{week}-session-log.md`. If context YAML provides `path.weekly.session-log`, use that value. Read decisions, tasks mentioned, daily inventories with destinations, pending items.

The agent-notes section contains the challenges and patterns the Block A agent surfaced — use them to challenge the user during planning (e.g., if the agent noted "8/80 pattern active — user overloaded Must priorities", watch for the same pattern in task distribution).

## Execution

### 1. Vault scan (silent — do NOT present to the user yet)

Search for ALL `- [ ]` tasks in the vault (recursive grep). Default exclusions: `.user/config/templates/`, weekly notes, session logs. If context YAML provides `vault-scan.exclude-paths`, extend the default list with the configured patterns.

Categorize internally:
- **With date in the week being planned** — already scheduled
- **Overdue** — date before today, still `- [ ]`
- **Review items** — sub-bullet contains `_Review:_ prioritize in Wnn closing` where Wnn = week being closed
- **With future date** — after the week being planned
- **No date** — backlog

### 2. Chronic straggler detection

**Primary method — weekly note comparison:**

1. Read the previous weekly note (one week before the current weekly note path). The path follows the same `path.weekly.note` template with `{week}` decremented by one ISO week.
2. Extract tasks that appeared as "overdue" or "rescheduled" in that review
3. Cross-reference with current overdue tasks (from sub-step 1 scan)
4. If a task appears overdue in BOTH reviews → **chronic straggler**, regardless of having the `_Rescheduled_` tag

**Secondary method — `_Rescheduled Nx_` tag:**

For overdue tasks that were NOT in the previous review (or when the previous note doesn't exist):
- If it has sub-bullet `_Rescheduled Nx_` with N >= 2 → **chronic straggler**
- If N = 1 → warn that it's overdue for the second time
- If N = 0 → first time overdue, normal handling

**Rule for chronic stragglers (both methods):**

Do NOT accept simple rescheduling. Force one of these options:
- Break into a smaller, more concrete task
- Cancel (no longer relevant)
- Demote to backlog (no date)
- Delegate to someone else

### 3. Cross-reference intentions (step 03) with vault reality

For each Must/Should priority defined in step 03, check:
- Does a corresponding `- [ ]` task exist in the vault?
- If YES → note the match
- If NO → flag as "priority without task" (gap to resolve in step 06)

### 4. Present context to the user — ONE GROUP AT A TIME

Present each group below as a separate turn. After each group, wait for the user's decisions before presenting the next. Never dump all groups in one message.

**Group order:**

**a) Gaps between intentions and vault:**
```
These step 03 priorities have no corresponding task in the vault:
- "[Priority from step 03]" → no task in [project].md
Will create in step 07.
```
→ Wait for user confirmation/discussion. Then present (b).

**b) Chronic stragglers** (force decision):
```
These tasks have been rescheduled 2+ times:
- [Task name] 📅 [date] (Rescheduled 3x, origin: 📅 [date])
For each: break into smaller, cancel, demote to backlog, or delegate?
```
→ Wait for decisions. Then present (c).

**c) Review items** — explicitly marked for this review:
```
Items marked for review this week:
- [task] (file.md)
For each: include in plan, defer to next week, or remove from queue?
```
→ Wait for decisions. Then present (d).

**d) Overdue tasks** (not chronic):
```
Tasks with past due date:
- [task] 📅 dd/mm (file.md)
For each: reschedule, remove date, or cancel?
```
When rescheduling: increment or create sub-bullet `_Rescheduled Nx (origin: 📅 original-date)_`
→ Wait for decisions. Then present (e).

**e) Relevant backlog** — only what seems connected to the priorities. Do not dump the entire list:
```
These backlog tasks seem related to your plan:
- [task] (file.md)
Should any of them go into the week?
```
→ Wait for decisions. Then present (f).

**f) "Out of scope"** — confirm with the user.
→ Wait for confirmation.

### 5. Habits, metrics and axis tracking

**Important:** If the user asks to add an "intention" during this step, it goes to the intentions-list subsection (written in step 03), NOT to the Priorities section. The default trigger word is `intention`. If context YAML provides `text.intention.aliases`, treat any of those locale-specific words as equivalent triggers.

The intentions list is what the vault Home displays daily. Edit the existing intentions-list subsection in the weekly note. The subsection heading comes from `section.intentions-list.heading` (default `Intentions`) and MUST match the value used in step-03.

If the user mentioned habits in step 03, present as context:
```
Week habits: [what the user mentioned]
Want to define measurable metrics? (e.g.: gym 3x, reading X/day)
```

Capture the axis status for the week being CLOSED (step 01 collected via retrospective + axis coverage check). Update the weekly note frontmatter with axis and habit values.

The frontmatter key for axis values defaults to `axes`. If context YAML provides `frontmatter.axes-key`, use that key name instead.

The axis status uses three default semaphore labels: `green`, `yellow`, `red`. If context YAML provides `text.axis.semaphore`, use the locale-specific labels instead — preserving the same three-state semantics.

Context injection provides the axis definitions, semaphore criteria, and YAML template (these come from the per-step context YAML — typically keyed under `Annual goals and axis semaphore definitions` and `Axis names and YAML template`).

### 6. Record in the weekly note

Append to the weekly note:

```markdown
## Priorities Wnn+1 (dd/mm–dd/mm)

### Must
1. ...

### Should
1. ...

### Out of scope (review in Wnn+1 closing)
- ...
```

Note: Calendar already recorded in step 04. Do not duplicate.

**Default date rule:** Tasks for the week without a specific day receive the last day of the planning week (per `## Week boundaries` in `weekly-review.md`). They appear in "This Week" on the kanban without forcing a specific weekday. Apply automatically when creating tasks during the review.

7. Note in the session log: all decisions about overdue tasks, review items, chronic stragglers
8. **Continuous reconciliation:** check session log for pending items from previous steps that should have been handled
9. Update `stepsCompleted`

## Menu

```
Context loaded. X priorities, Y overdue handled, Z review items decided.

→ [C] Continue to Step 07 (Plan and write day by day)
→ [X] Pause review
```
