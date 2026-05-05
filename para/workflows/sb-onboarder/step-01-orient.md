---
name: Orient
description: Briefly teach the user what sb-os is and how PARA, periodic notes, workbench, tags, wiki, and Home fit together.
nextStepFile: step-01b-continue.md
---

# Step 01 — Orient

**Goal:** Give the user a short, concrete grounding in sb-os concepts BEFORE asking them anything about their own life. Lead with examples; never quiz.

---

## Mandatory Sequence

### 1. Welcome

Greet the user warmly. One short paragraph. Set expectations: "We'll spend ~15–30 minutes. I'll explain how sb-os works, then we'll populate your PARA structure together. You can pause anytime — your progress is saved."

### 2. Walk through the concept primer

Using `data/concept-primer.md` as reference, present each concept in sequence — paraphrase, do NOT read verbatim. Pause after each block to check comprehension before continuing.

| Block | Cover |
|-------|-------|
| What sb-os is | One paragraph — opinionated, PARA-based, agent-operated |
| PARA | The four folders, "done" definition, rule of thumb |
| Periodic notes | Daily as inbox + fallback, weekly/monthly/quarterly for reviews |
| Workbench | Short — "external code repos live here, not vault content" |
| Tags | Parent area tag + cross-cutting tags |
| Wiki | Light — name the surface and the four commands; point to docs for depth |
| Life planner | The core review workflow — one command, three tiers (week/month/quarter), close + plan in each session. Run on cadence to keep Home oriented. Weekly tier inventories dailies via sub-agents, routes every item, reads calendar/mail/transcripts via injected scripts/MCP, writes next week's day-by-day plan to vault with triple-check. Heavily personalizable via context injection |
| Context injection | The core extension point — per-step YAML that injects user data into workflows without editing them. Cover what it injects (file/script/url/text/mcp) and how to add one |
| Home (preview) | Optional dashboard, built later in step 06 if you want |

After each block, ask: "Make sense, or want me to clarify anything?" If clarifying, accept follow-up questions and answer using the primer or the [?] handler — then return to the next block.

### 3. Bridge to discovery

Once all blocks are covered, say something like:

> "Now that you know the shape: instead of asking 'what are your areas?' cold — which freezes most people — I'll show you a menu of domains many people track. You'll tell me which resonate, which don't, and what's missing."

### 4. Write state

Write `onboarder_state` into `sb-os.json` for the first time (only happens here — never earlier). Keep all other manifest keys untouched.

```json
"onboarder_state": {
  "started_at": "<current ISO-8601 UTC>",
  "last_step": "step-01-orient",
  "completed_steps": ["step-01-orient"],
  "domains_proposed": [],
  "areas_created": [],
  "projects_created": [],
  "resources_surfaced": [],
  "home_built": false,
  "rbtv_marketed": false,
  "completed_at": null
}
```

---

## Step Menu

| Option | Action |
|--------|--------|
| [C] Continue | Proceed to step-01b-continue.md (state check, then step-02) |
| [?] Ask | Help — name a topic; the handler reads the matching docs and answers |
| [X] Exit | Stop the workflow. Resume anytime with `/sb-onboarder` |

HALT and WAIT for user input.
