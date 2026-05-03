# Concept Primer

Short, direct teaching content for the sb-onboarder. Each section is one block the onboarder reads aloud, paraphrasing as needed for tone — never reading verbatim.

---

## What sb-os is

sb-os is an opinionated personal knowledge system for Obsidian, structured around the **PARA** method and operated by AI agents (primarily Claude Code). The folders are simple. The agents do the heavy lifting — capture, routing, periodic reviews, knowledge synthesis.

You bring intent. The agents handle materialization.

---

## PARA — the four content folders

| Folder | What lives here | "Done" definition |
|--------|-----------------|-------------------|
| `1-projects/` | Bounded efforts with a defined finish line | Yes — there is a clear "done" |
| `2-areas/` | Ongoing responsibilities you maintain over time | No — they continue indefinitely |
| `3-resources/` | Reference material, tools, knowledge bases | Consulted on demand |
| `4-archives/` | Completed, abandoned, or under-review content | Holding zone before deletion |

**Rule of thumb:** if the work has a finish line, it's a **project**. If it's a standard you maintain forever, it's an **area**. If it's material you reach for occasionally, it's a **resource**.

When a project finishes → archive it. When an area stops being relevant → archive it. When a resource seeds a goal → spin up a project from it.

---

## Periodic notes (`0-periodic-notes/`)

Daily notes act as the **inbox**. Capture happens here when nothing else fits. Weekly, monthly, and quarterly notes hold reviews — produced by the `sb-life-planner` workflow.

Daily ≠ default destination. The agent routes captured content directly to its PARA home most of the time; the daily note is the fallback for genuinely ambiguous content.

---

## Workbench (`5-workbench/`)

Project workspaces with their own git repos and conventions — code repos, technical project trees. They live inside the vault for proximity but are NOT vault content. Each maintains its own git history; the vault gitignores them.

---

## Tags

Every file gets its **parent area tag** (the directory name under `2-areas/`). Cross-cutting tags layer on top: `decision`, `meeting`, `idea`. Resources may add topic tags. Periodic notes use status tags: `reviewed`, `routed`.

Tags answer "what kind of thing is this?" Folders answer "what does it belong to?"

---

## Wiki (light overview)

The wiki lives at the configured `wiki_root` (default `3-resources/knowledge-base/`). It splits external content into two layers:

- **Raw** (`{wiki_root}/raw/`) — articles, transcripts, papers captured verbatim. Immutable.
- **Synthesis** (elsewhere under `{wiki_root}/`) — your notes derived from raw sources. Evolves freely.

Commands: `/sb-wiki-ingest` (capture a source), `/sb-wiki-query` (ask the wiki a question), `/sb-wiki-create-topic` (promote a topic page), `/sb-wiki-lint` (structural check).

For deeper wiki guidance, run `/sb-tutor` on the topic, or read `{sb_os_path}/docs/wiki-schema.md`.

---

## Life planner — recurring reviews

`/sb-life-planner` is the **core review workflow** of sb-os. It runs at three tiers — weekly, monthly, quarterly — and in each tier it does two things: **closes** the prior period and **plans** the next one. It is designed to be run on a recurring cadence; running it consistently is the single highest-leverage habit in sb-os.

| Tier | Closes | Plans | Tone | Cadence |
|------|--------|-------|------|---------|
| **Weekly** | Last week's dailies + tasks | Next week's day-by-day plan | Tactical — what gets done | End of every week |
| **Monthly** | Last month's weeklies | Month intentions | Thematic — what to build or change | End of every month |
| **Quarterly** | Last quarter's monthlies | Quarter intentions | Strategic — where you're heading | End of every quarter |

The workflow produces weekly/monthly/quarterly notes in `0-periodic-notes/{period}/` using the templates at `.user/config/templates/periodic-notes/`. **It does not produce daily notes** — dailies are inputs.

### What the weekly review actually does

The weekly tier is the most operationally dense. In one session it:

1. **Inventories every daily note of the closing week** via sub-agents — each piece of content is summarized, classified (Routable / Review note / Task), and given a suggested destination
2. **Runs an unbiased retrospective** — what shipped, what got blocked, what was learned — before the agent loads any vault or calendar data, so reflection is not contaminated by the backlog
3. **Reads your calendar** (past + next week) via scripts/MCP wired through context injection — the agent cross-references meetings against the retrospective and surfaces what was missed
4. **Routes every item from every daily** to the correct project/area `*-tasks.md` files, reading lists, learning notes, etc. — leaves zero loose content behind
5. **Detects chronic stragglers** — tasks that have been rescheduled 2+ times — and forces a decision (break down, cancel, demote, delegate) instead of accepting another reschedule
6. **Writes the next week's day-by-day plan** as actual `- [ ]` tasks with dates in the right files (so your Home dashboard reflects exactly what was planned), then triple-checks plan ↔ vault ↔ priorities ↔ session log

Monthly and quarterly tiers follow the same close-then-plan structure but at thematic and strategic horizons.

### Intentions feed your Home

Every tier produces an **Intentions list** subsection (4–7 short compass items, bold-headed). This is exactly what a `Home.md` dashboard parses to render the "this week / this month / this quarter" intention block. Run the review consistently → your Home stays oriented; skip a review → Home goes stale.

### Context injection makes it yours

Every external input (calendar accounts, mail, meeting transcripts, therapy summaries, self-knowledge notes, WhatsApp self-chat) plugs in via `/sb-inject-context`. Same goes for paths, headings, life-axis names, semaphore labels, prompt language. The default workflow runs unmodified out of the box; with a few YAML entries it reads your inbox and your calendar and pre-populates the routing pass with items you captured outside Obsidian.

Boundaries are date-locked: today's date determines which week/month/quarter is closing. No manual selection needed.

---

## Context injection — how you personalize sb-os

Workflows that ship with sb-os are generic. **Context injection** is how you inject your own data into them without editing the workflow itself. It is the core extension point of sb-os.

For every workflow step file (e.g., `.user/workflows/accountant/gastos/step-04-categorize.md`), you can place a sibling YAML under `{user_context_root}/` (default `.user/context/`) at the same relative path with `.yaml` extension. Example: `.user/context/accountant/gastos/step-04-categorize.yaml`. When the agent loads the step, it reads the YAML first and processes its entries top-to-bottom **before** running the step's native logic.

A YAML entry can inject:

| Type | What it does | Example use |
|------|--------------|-------------|
| `file` | Loads file contents (whole file or named sections) | Your bank account list, your category rules |
| `script` | Runs a script and feeds the output to the agent | A Python script that fetches today's calendar |
| `url` | Fetches a URL and feeds the body | A live RSS feed, a public API |
| `text` | Inline content baked into the YAML | A short reminder or instruction |
| `mcp` | Calls an MCP server tool | A Gmail search, a calendar query |

Each entry has a `mode` (`read`, `write`, `read-write`) and an `instruction` field telling the agent what to do with the loaded content. Schema reference: `.claude/rules/sb-workflow-context.md`.

**Why this matters:** the same `sb-life-planner` workflow runs differently for every user — one injects their Google Calendar via MCP, another injects a static list of life areas, another runs a script to pull project status from a database. The workflow does not change. Only the YAML changes.

**How to add one:** run `/sb-inject-context` — an interactive CRUD command that asks you which workflow and step to attach to, walks you through the entry fields (type, mode, instruction, source), and writes the YAML at the right path. You never have to remember the path resolution rules or the schema. The command also handles update and delete on existing entries.

You can also write the YAML by hand at the matching path if you prefer. Either way, the next workflow run picks it up automatically. No workflow edit, no redeploy.

Full rule and schema: `.claude/rules/sb-workflow-context.md`. Command: `/sb-inject-context`.

---

## Home (preview)

`Home.md` is an **optional** dashboard at the vault root — the surface you see when you open the vault. It aggregates and orients (today's tasks, active projects, recent activity, periodic links). It does NOT store content.

A Home is yours to spec. The onboarder can build one in step 06 if you want — driven by the design doc at `{sb_os_path}/ideas/home-dashboard.md`. Skip it now and build one later anytime.

Home requires the **Dataview** (with JS enabled) and **Templater** Obsidian plugins. The onboarder will print install instructions if you opt in.
