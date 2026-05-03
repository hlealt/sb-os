# Step 04 — Calendar (Past + Future)

## Purpose

Read the calendar to complement the retrospective (past week) and inform planning (next week). Runs AFTER the unbiased reflections from steps 01 and 02.

## Context loading (Block B start)

This step begins a new context block. If `stepsCompleted` includes 01, 02, 03 — this is a fresh session. Load context before proceeding:

1. Read the **weekly note**. Default path `0-periodic-notes/weekly/{week}.md`. If context YAML provides `path.weekly.note`, use that value. Read all sections written so far, including the agent-notes section (default heading from `section.agent-notes.heading`) for patterns, challenges, and planning context.
2. Read the **session log**. Default path `0-periodic-notes/weekly/{week}-session-log.md`. If context YAML provides `path.weekly.session-log`, use that value. Read decisions, tasks mentioned, pending items.

After loading, proceed directly to the calendar steps below. Do NOT re-discuss the retrospective or intentions — that work is done.

## Why after and not before

If the past week's calendar were read before the "good week" reflection (step 02), the user would see meetings they had and this could bias their intentions for the next week. The reflection must come from within, without external stimulus.

## Execution

### 1. Read calendar — past week

Read the past week's calendar events (closing week's first day through last day). Context injection provides the calendar script invocations and account configuration.

### 2. Cross-reference with retrospective

Compare calendar meetings with what the user mentioned in step 01. Present only what is NEW:

```
The calendar shows these meetings you didn't mention in the retrospective:
- [Day Date HH:MM]: [Event title]
- [Day Date HH:MM]: [Event title]

Did any of these generate tasks, decisions, or information that should go into the review?
```

If everything was already covered → say "past calendar matches your retrospective, nothing new."

### 3. Read calendar — next week

Read the planning week's calendar events (first day through last day). Context injection provides the calendar script invocations.

### 4. Present next week's agenda

```
Next week's meetings:

| Day | Time | Event | Account |
|-----|------|-------|---------|
| ... | ... | ... | ... |

Does any event need preparation? Anything to add or cancel?
```

### 5. Note in the session log

- Past week meetings that generated new tasks
- Next week meetings as context for planning
- Any preparation task mentioned by the user

### 6. Record in the weekly note

Add as a new section (after the week intention section from step 03):

```markdown
## Calendar

| Day | Time | Commitment |
|-----|------|------------|
| ... | ... | ... |
```

7. Update `stepsCompleted`

## If the calendar is not available

If the scripts fail or are not configured → ask the user manually. Default prompt:

> **"What meetings/commitments do you have next week?"**

If context YAML provides `prompt.step-04.no-calendar`, use that text instead.

The step does NOT block if the calendar is not accessible.

## Menu

```
Calendar reviewed: X events past week, Y events next week.

→ [C] Continue to Step 05 (Route dailies)
→ [X] Pause review
```
