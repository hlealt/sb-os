# Monthly Review

## Purpose

Close the ending month and set intentions for the next one. Produces objectives, goals, traps, and an intentions list that surfaces on the Home page. Scope: all life areas (work, health, family, personal). Process context injection per `sb-workflow-context.md` before proceeding.

## Output document

Default monthly note path: `0-periodic-notes/monthly/{month}.md`. If context YAML provides `path.monthly.note`, use that value. `{month}` expands to `YYYY-MM`.

Default template path: `.user/templates/periodic-notes/Monthly.md`. If context YAML provides `path.monthly.template`, use that value. If neither the configured path nor the default exists, skip the template and create the note from scratch.

## Output taxonomy

The monthly note has four canonical subsections inside the monthly-intention block. Default headings shown below; each can be overridden via the listed YAML key.

| Subsection | Default heading | YAML key | What it contains | Illustrative example |
|------------|-----------------|----------|------------------|----------------------|
| Objectives | `Objectives` | `section.objectives.heading` | Thematic directions — what to build or change | "build a running habit", "shift from builder to seller" |
| Goals | `Goals` | `section.goals.heading` | Measurable targets — how you know you advanced | "run 3x/week", "contact 10 potential clients" |
| Traps | `Traps` | `section.traps.heading` | Patterns to avoid — behaviors that sabotage | "staying up past midnight coding", "avoiding sales calls by doing product work" |
| Intentions list | `Intentions` | `section.intentions-list.heading` | 3–5 synthesized compass items for Home — bold theme + brief elaboration | Same format as weekly intentions list (see `weekly-review/step-03-intention.md` step 6) |

The illustrative examples are shape guidance only — the user defines the actual content during step 4.

## Month boundaries

Months run 1st to last day.

| Today is | Closing month | Planning month |
|----------|---------------|----------------|
| Day 1–25 of month M | M−1 | M |
| Day 26+ of month M | M | M+1 |

All date ranges in this workflow (weekly note selection, therapy transcript search, planning proposals) are locked to the closing month's first and last day. Do NOT read inputs from outside the closing month.

## Steps

### 1. Identify the month

Apply the month boundaries table above to determine the closing and planning months. Present to the user for confirmation. Do not ask open-ended "which month?"

### 2. Read inputs

**Weekly notes from the closing month:**

Resolve the weekly note path template. Default `0-periodic-notes/weekly/{week}.md`. If context YAML provides `path.weekly.note`, use that value. Glob the resolved directory and keep only weeks that overlap the closing month.

From each weekly note, read:
- The week-review section (default heading `Week review`; overridable via `section.week-review.heading`) — retrospective (accomplishments, blockers, learnings)
- The weekly-intention section (default heading `Week intention ({week})`; overridable via `section.weekly-intention.heading`) → its intentions-list subsection (default heading `Intentions`; overridable via `section.intentions-list.heading`) — weekly compass items

Context injection provides therapy session transcripts for the closing month, if configured (key `Therapy session transcripts (month)`).

### 3. Synthesize and present

Present a synthesis of the month:
- Patterns across weeks (recurring themes, progression or regression)
- Recurring themes from therapy
- What improved vs. what didn't
- Cross-axis view: which life areas got attention, which were neglected

### 4. Interactive discussion

This is the core of the review. The agent acts as a **critical partner**, not an accommodating assistant.

**Behaviors:**
- Push back on unconscious avoidance ("you said you'd sleep better in W13 and W14 — what actually changed?")
- Surface fear-driven goal-dodging ("you're not setting a client acquisition target — is that because you're afraid of missing it?")
- Connect therapy themes to behavioral patterns
- Challenge the user to set ambitious but honest intentions
- Name patterns the user might not see ("three weeks in a row you planned exercise and did zero — is the plan wrong or the commitment?")
- Do NOT be accommodating — be direct and challenging

**Discussion scope:** All life areas. Context injection provides the user's active projects and life areas (key `Active projects and areas`).

### 5. Write to monthly note

Create the monthly note at the resolved path using the resolved template (when available). Fill in:

- The "weeklies reviewed" section (default heading `Weeklies reviewed`; overridable via `section.weeklies-reviewed.heading`) — links to all weekly notes read
- The month-review section (default heading `Month review`; overridable via `section.month-review.heading`) — synthesized from discussion
- The monthly-intention section (default heading `Month intention ({month})`; overridable via `section.monthly-intention.heading`) with the four subsections defined in the Output taxonomy table above
- The role-dimension section (default heading `Role dimension`; overridable via `section.role-dimension.heading`) — per-role summaries

Apply the YAML-provided heading text whenever the corresponding key is present.

### 6. Discuss Home summary

The intentions-list subsection (default heading `Intentions`; overridable via `section.intentions-list.heading`) is what the vault Home displays. Discuss with the user which items make it there.

**Clarity rules** (same as weekly — see `weekly-review/step-03-intention.md` step 6):
- Each item starts with a **bold theme** followed by " — " and brief elaboration
- Each item must be self-explanatory when read cold
- No shorthand, no unnamed references, no jargon from the review conversation
- Name the patterns, explain the why
- 3–5 items

Default bad/good examples table (English):

| Bad | Good |
|-----|------|
| "stay focused" | **Sales before product** — drift back into building when meant to sell |
| "take care of health" | **Body sustains everything** — 3 weeks no exercise, sleep dysregulated |

If context YAML provides `text.monthly.intentions-examples`, use that locale-specific table instead.

## Execution rules

1. This is a single-file workflow — no step subdirectory, no session log
2. Discussion is interactive — do NOT rush to write. Spend time in step 4
3. The user defines the final content of objectives, goals, traps, and intentions — the agent proposes and challenges, never decides alone
4. After writing the monthly note, present a summary of what was recorded and confirm with the user
