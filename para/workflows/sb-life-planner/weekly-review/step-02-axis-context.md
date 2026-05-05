# Step 02 — Axis Check + Emotional Context

## Purpose

Complete the week's picture: check which life axes the user did not cover in the retrospective and read therapy/psychiatry session context. Process context injection per `sb-workflow-context.md` before proceeding.

## Execution

### 1. Habits summary

Read the "Habits inventory" section from the session log. Using the habit categories provided by context injection (`text.habit-categories`), aggregate into a weekly summary table and present to the user:

| Day | (columns from context injection habit categories) |
|-----|---------------------------------------------------|
| 1   | ... |
| ... | ... |

Then add a patterns summary based on the tracked categories.

Write the summary table and patterns to the weekly note under `## Habits`. Use this data to inform the axis check below — pay extra attention to axes whose mapping to habit categories is provided via `text.axis.example-mapping` (when configured).

### 2. Axis coverage

Check which life axes (provided by context injection — `text.life-axes`) were mentioned in the step 01 retrospective.

For each axis NOT mentioned, ask directly. Default prompt:

> "You didn't mention **{axis}** — how was this week in that area?"

If context YAML provides `prompt.step-02.axis-not-mentioned`, use that text instead. Replace `{axis}` with the actual axis name.

No need to go deep — one sentence is enough. The goal is to ensure a complete picture for axis tracking.

### 3. Finalize

1. Note in the session log: axis statuses mentioned and any insights loaded via context injection
2. Update `stepsCompleted`

## Menu

```
Habits summary: [N]/7 days tracked. Axes covered: 7/7.

→ [C] Continue to Step 03 (Week intention)
→ [X] Pause review
```
