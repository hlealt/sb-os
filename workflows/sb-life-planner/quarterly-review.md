# Quarterly Review

## Purpose

Close the ending quarter and set strategic intentions for the next one. Produces strategic-tier objectives, goals, traps, and an intentions list that surfaces on the Home page. Scope: all life areas. Process context injection per `sb-workflow-context.md` before proceeding.

## Output document

Default quarterly note path: `0-periodic-notes/quarterly/{quarter}.md`. If context YAML provides `path.quarterly.note`, use that value. `{quarter}` expands to `YYYY-QN`.

Default template path: `.user/config/templates/periodic-notes/Quarterly.md`. If context YAML provides `path.quarterly.template`, use that value. If neither the configured path nor the default exists, skip the template and create the note from scratch.

## Output taxonomy

Same categories as the monthly review but at the **strategic tier**. Default headings shown below; each can be overridden via the listed YAML key.

| Subsection | Default heading | YAML key | What it contains | Illustrative example |
|------------|-----------------|----------|------------------|----------------------|
| Objectives | `Objectives` | `section.objectives.heading` | Strategic directions — where you're heading | "get good at running", "become a seller not a builder" |
| Goals | `Goals` | `section.goals.heading` | Quarterly measurable targets | "close 3 clients", "run a half-marathon" |
| Traps | `Traps` | `section.traps.heading` | Quarterly-scale traps — recurring patterns | "over-engineering instead of shipping", "avoiding a hard conversation with a co-founder" |
| Intentions list | `Intentions` | `section.intentions-list.heading` | 3–5 strategic compass items for Home — bold theme + brief elaboration | Same format and clarity rules as weekly/monthly |

The illustrative examples are shape guidance only — the user defines the actual content during step 4.

## Quarter boundaries

Quarters run Q1 (Jan–Mar), Q2 (Apr–Jun), Q3 (Jul–Sep), Q4 (Oct–Dec).

| Today is | Closing quarter | Planning quarter |
|----------|-----------------|------------------|
| Month 3 of quarter Q, day 21+ | Q | Q+1 |
| Any other day in quarter Q | Q−1 | Q |

"Month 3" = March, June, September, December. "Day 21+" gives a 10-day tolerance at the end of the quarter.

All date ranges in this workflow (monthly note selection, therapy transcript search, planning proposals) are locked to the closing quarter's 3 months. Do NOT read inputs from outside the closing quarter.

## Steps

### 1. Identify the quarter

Apply the quarter boundaries table above to determine the closing and planning quarters. Present to the user for confirmation. Do not ask open-ended "which quarter?"

### 2. Read inputs

**Monthly review notes from the closing quarter:**

Resolve the monthly note path template. Default `0-periodic-notes/monthly/{month}.md`. If context YAML provides `path.monthly.note`, use that value. Read all monthly notes for the closing quarter (e.g., Q1 = January, February, March → `{YYYY-01}.md`, `{YYYY-02}.md`, `{YYYY-03}.md`).

From each monthly note, read:
- The month-review section (default heading `Month review`; overridable via `section.month-review.heading`)
- The monthly-intention section (default heading `Month intention ({month})`; overridable via `section.monthly-intention.heading`) — full block including the intentions-list subsection

Do NOT read weeklies directly — the monthly reviews already synthesize them.

Context injection provides therapy session transcripts for the closing quarter, if configured (key `Therapy session transcripts (quarter)`).

### 3. Synthesize and present

Present a strategic synthesis of the quarter:
- Trajectory across months — what direction did life actually move?
- Goals set vs. goals achieved across the 3 months
- Recurring therapy themes at the quarter scale
- Projects started, completed, abandoned, or stalled
- Which life areas improved, which degraded

### 4. Interactive discussion

Same critical partner stance as the monthly review, but at the **strategic level**.

**Behaviors:**
- Challenge whether stated goals match actual behavior over 3 months ("you said Q1 was about selling — you spent 80% of the time building")
- Surface strategic avoidance patterns (use concrete examples from the user's quarterly data)
- Connect quarterly therapy arc to life direction
- Push for honest strategic priorities, not aspirational lists
- Question whether the user's identity matches their actions (use context injection examples when available — key `Active projects and identity themes`)
- Do NOT be accommodating — be direct and challenging

**Discussion scope:** All life areas at the strategic level — career trajectory, health trends, relationship patterns, financial trajectory, personal growth arc.

### 5. Write to quarterly note

Create the quarterly note at the resolved path using the resolved template (when available). Fill in:

- The "monthlies reviewed" section (default heading `Monthlies reviewed`; overridable via `section.monthlies-reviewed.heading`) — links to all monthly notes read
- The quarter-review section (default heading `Quarter review`; overridable via `section.quarter-review.heading`) — synthesized from discussion
- The quarterly-intention section (default heading `Quarter intention ({quarter})`; overridable via `section.quarterly-intention.heading`) with the four subsections defined in the Output taxonomy table above
- The next-quarter planning section (default heading `Next-quarter planning`; overridable via `section.next-quarter-planning.heading`) — forward-looking notes

Apply the YAML-provided heading text whenever the corresponding key is present.

### 6. Discuss Home summary

The intentions-list subsection (default heading `Intentions`; overridable via `section.intentions-list.heading`) is what the vault Home displays. Discuss with the user which items make it there.

**Clarity rules** (same as weekly/monthly — see `weekly-review/step-03-intention.md` step 6):
- Each item starts with a **bold theme** followed by " — " and brief elaboration
- Each item must be self-explanatory when read cold
- No shorthand, no unnamed references, no jargon from the review conversation
- Name the patterns, explain the why
- 3–5 items
- Strategic tier: these must be directional, not tactical

Default bad/good examples table (English):

| Bad | Good |
|-----|------|
| "focus on sales" | **Seller identity** — 3 months saying "I'll start selling", 80% of the time coding. The transition has to be real |
| "improve health" | **Health is the foundation** — when health drops, everything drops with it. Exercise and sleep are non-negotiable |

If context YAML provides `text.quarterly.intentions-examples`, use that locale-specific table instead.

## Execution rules

1. This is a single-file workflow — no step subdirectory, no session log
2. Discussion is interactive — do NOT rush to write. Spend time in step 4
3. The user defines the final content — the agent proposes and challenges, never decides alone
4. After writing the quarterly note, present a summary of what was recorded and confirm with the user
5. Monthly reviews must exist before running a quarterly review — if a month is missing, flag it and ask the user whether to proceed or run the monthly first
