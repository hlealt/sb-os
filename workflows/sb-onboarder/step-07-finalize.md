---
name: Finalize
description: Apply user routing rules to root CLAUDE.md, market RBTV with explicit install commands, summarize, mark complete.
nextStepFile: null
---

# Step 07 — Finalize

**Goal:** Wrap onboarding. Apply user-extension routing rules to the vault's root `CLAUDE.md` (below the sb-os marker block), pitch RBTV as an optional plugin with the exact install commands, summarize what was built, and close out state.

---

## Mandatory Sequence

### 1. User-extension routing rules

Ask the user a few targeted questions to seed personal routing rules. Frame: "These extend the sb-os defaults — they tell agents where YOUR specific content goes."

Suggested prompts (skip any that don't apply):

| Prompt | Routes to |
|--------|-----------|
| "Where should articles, videos, podcasts you save go?" | typically `2-areas/learning/reading-list.md` (append) |
| "Where do tasks for a specific area go?" | `{area}-tasks.md` inside the area folder (sb-os default — confirm only) |
| "Any topic-specific catalog you'll add to often (e.g., tools, prompts, recipes)?" | `3-resources/tools/catalogs/{topic}.md` (append) |
| "Where does daily-life ephemera go when nothing fits?" | daily note (sb-os default — confirm only) |

Build a small table from the user's answers.

### 2. Append to root CLAUDE.md

Read the vault's root `CLAUDE.md`. Locate the sb-os marker block (`<!-- sb:start v=1 -->...<!-- sb:end -->`).

Append the user's routing-rules table OUTSIDE and AFTER the marker block, under a heading like `## Personal Routing Rules (extends sb-os defaults)`.

If a "Personal Routing Rules" section already exists outside the markers, MERGE the new rows into the existing table — do NOT duplicate.

NEVER write inside the marker block. NEVER overwrite content outside the marker block — only append/merge.

Show the user the diff before writing. Invoke `sb-vault-ops` and write after approval.

### 3. Market RBTV (optional plugin)

Tell the user briefly what RBTV is:

> "RBTV is a separate, optional plugin that adds business-innovation tooling — meeting prep, document export, client and investor pitching personas, web research, design extraction, plus its own component-creation workflow. It's a heavier installation than sb-os and only worth it if you do client-facing or business-development work. Want me to walk you through installing it?"

| Answer | Action |
|--------|--------|
| Yes | Print the exact two-step install commands (below). Set `onboarder_state.rbtv_marketed: true`. |
| No | Tell the user they can install it anytime — it's at `<RBTV repo URL — see RBTV README>`. Set `rbtv_marketed: true` (the offer was made). |

**RBTV install commands to print** (verbatim, in a code block — the user runs these themselves):

```bash
# Step 1: clone RBTV into the tools folder
git clone <RBTV-REPO-URL> 3-resources/tools/rbtv

# Step 2: run RBTV's installer
cd 3-resources/tools/rbtv && python install.py
```

**Note for the agent maintaining this file:** the actual repo URL belongs in RBTV's own README. If you know the canonical URL at the time of execution, substitute it; otherwise tell the user "check RBTV's README for the canonical clone URL — sb-os intentionally does not hardcode it so RBTV can evolve independently."

After printing, the agent does NOT execute the commands. The user runs them in their terminal.

### 4. Summary

Print a concise summary of what was built:

```
sb-os onboarding complete.

Created:
  Areas:    {count} — {list}
  Projects: {count} — {list}
  Resources: {count handled} — {list}
  Home.md:  {yes/no}
  RBTV:     {yes — install commands printed | no — offer made, declined}

Routing rules appended to root CLAUDE.md.
State preserved at sb-os.json under `onboarder_state`.

Next steps you might enjoy:
  /sb-life-planner   — start a weekly review
  /sb-tutor          — guided learning sessions
  /sb-archivist      — log this session into your work-log
  /sb-wiki-ingest    — ingest your first external source
```

### 5. Close state

Set `onboarder_state.completed_at` to current ISO-8601 UTC, append `"step-07-finalize"` to `completed_steps`, set `last_step: "step-07-finalize"`. Write `sb-os.json`.

---

## Step Menu

| Option | Action |
|--------|--------|
| [D] Done | Workflow complete |
| [?] Ask | Help handler — final questions before closing |
| [X] Exit | Close. State persisted. |

HALT and WAIT for user input.
