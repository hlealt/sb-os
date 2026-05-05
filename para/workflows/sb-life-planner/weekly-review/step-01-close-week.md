# Step 01 — Init + Close Week

## Purpose

Detect state, create weekly note, create session log, produce daily inventories via sub-agents, and build the retrospective. The user talks about their week WITHOUT bias — no vault or calendar data is presented in this step.

## Execution

### 1. Init

1. Determine the closing week (the week being reviewed):
   - If today is Friday, Saturday, or Sunday → closing week = current week
   - If today is Monday, Tuesday, Wednesday, or Thursday → closing week = previous week
   Planning week = the week after the closing week. Use ISO week numbers.

2. Resolve the weekly note path. Default `0-periodic-notes/weekly/{week}.md` where `{week}` = `yyyy-Wnn`. If context YAML provides `path.weekly.note`, use that value. Check if the resolved file already exists:
   - If it exists AND has `stepsCompleted` in frontmatter → session being resumed
     - Report last completed step
     - Present menu with option to continue from the next step
     - **Stop here — do not re-execute the retrospective**
   - If it does not exist → create the weekly note with frontmatter:
     ```yaml
     ---
     type: log
     tags: []
     stepsCompleted: []
     closingWeek: 'Wnn'
     planningWeek: 'Wnn+1'
     date: 'YYYY-MM-DD'
     ---
     # Closing Wnn — dd/mm to dd/mm
     ```

3. **Create session log.** Default path `0-periodic-notes/weekly/{week}-session-log.md`. If context YAML provides `path.weekly.session-log`, use that value. Use the template defined in the orchestrator (includes "Daily inventory" section).

4. Identify dailies for the week. Default daily-notes directory `0-periodic-notes/daily/`. If context YAML provides `path.daily.dir`, use that value.
   - Week = closing week's first day through last day (see `## Week boundaries` in `weekly-review.md`)
   - Use Glob to list which files exist — do NOT read any daily notes in the main agent context

### 2. Daily inventory (sub-agents)

Launch one sub-agent per daily found. The sub-agent checks its own frontmatter and decides whether to produce an inventory. Do NOT pre-filter by reading dailies in the main context — the entire point is to keep daily note content out of the orchestrator's context window.

**Sub-agent prompt:**
```
Read the daily note at [path].

FIRST: check frontmatter for `reviewed` and/or `routed` tags.
- If the daily has the `reviewed` tag → return ONLY: "ALREADY REVIEWED" and stop.
- If NOT → produce the full inventory below.

STRUCTURE CHECK: Before inventorying, assess the daily's structure.
- "Structured" = content lives inside the template sections (sections list provided by context injection — `Daily note template sections`)
- "Unstructured" = content exists OUTSIDE sections (before the first ##, or in a flat dump with no section headings, or everything dumped in the inbox section when it clearly belongs in other sections)
- "Mixed" = some content is in sections, some is not
- IGNORE the habits callout when assessing structure — it lives before the first ## by design and is handled separately in step 3 below
Report the structure type at the top of your output.

1. SUMMARY (3-5 sentences): what the user did/thought/recorded that day.

2. INVENTORY — table with EACH piece of content from the daily:
| # | Section found in | Content (1-line summary) | Suggested type | Suggested destination | Confidence |
|---|------------------|--------------------------|----------------|-----------------------|------------|
| 1 | (template section name) / FLAT | ... | Routable / Review note / Task | file path or — | High / Medium / Low |

Confidence rules:
- HIGH: content is in the correct template section AND the type is unambiguous (e.g., a URL in Reading List → Routable to reading-list.md)
- MEDIUM: content is in a section but could reasonably belong elsewhere (e.g., a task-like item in Work Notes)
- LOW: content is in the inbox section, in a flat dump, or outside any section — classification is inferred from context. These items WILL be surfaced to the user for triage in step 05

3. HABITS — extract from the daily's habits callout. This is an Obsidian callout block where every line is prefixed with `> `. Checked checkboxes look like `> - [x] {category-item}`, unchecked like `> - [ ] {category-item}`. Categories are bold headers (e.g., `> **Exercise**`). For each category provided by context injection (`text.habit-categories`), list ONLY the checked (`[x]`) items:
| Category | Checked items |
|----------|---------------|
(use the categories from context injection)
If the habits callout is missing or all checkboxes are unchecked, report "No habits tracked".

Rules:
- EACH paragraph, bullet, link, or content block = one row in the table
- Nothing can be left out. Total rows = total distinct items in the daily
- "Routable" = content that should live in a permanent vault file (includes links, ideas, insights, discarded decisions)
- "Review note" = self-observations, patterns, session recaps, reflections → weekly note dedicated section (monthly review may promote to structured files)
- "Task" = action mentioned that should become a checkbox in some `{name}-tasks.md`
- Links (URLs) are ALWAYS Routable — the user captures them intentionally. Infer link type from domain when possible. Default heuristics: `dev.to`/`medium.com` → article, `github.com` → repo/tool, `youtube.com` → video, `x.com` → social post. If context YAML provides `routing.link-heuristics`, use that block instead.
- Use the routing destinations provided by context injection (`Content routing destinations`) to suggest file-level destinations for each item
- Nothing in a daily note is ephemeral. Every item must be classified into one of the three types above
- For UNSTRUCTURED or MIXED dailies: be extra granular. Break long paragraphs into individual items when they contain multiple distinct topics. Err on the side of more rows, not fewer
```

Write the inventories in the "Daily inventory" section of the session log. One sub-heading per daily. For already-reviewed dailies, note: `Already reviewed and routed.`

### 3. Retrospective

1. Present daily summaries (produced by sub-agents) and any additional context summaries loaded via context injection — NOT the full inventories
2. Ask the user:
   - **What did you accomplish this week?**
   - **What was blocked?**
   - **Learnings?**
3. Write in the weekly note:

```markdown
## Dailies reviewed
- [[yyyy-mm-dd]]
- ...

## Week review

### What did I accomplish?
- ...

### What was blocked?
- ...

### Learnings
- ...
```

### 4. Finalize

1. Note in the session log: decisions, tasks and priorities mentioned by the user during the retrospective
2. **Reconciliation:** check if something mentioned by the user in the retrospective is not in the session log
3. Update `stepsCompleted: [step-01-close-week.md]`

## Menu

```
Weekly note created. Session log active. Inventories produced.
Dailies for the week: [list] ([N] inventoried, [M] already reviewed)
{meeting-source-line}

→ [C] Continue to Step 02 (Axis check + emotional context)
→ [X] Pause review
```

`{meeting-source-line}`: if context YAML provides `meeting.source.label`, render a line of the form `{meeting.source.label}: [N] summaries read` (the value may already include the count placeholder). If the key is absent, omit the line entirely.
