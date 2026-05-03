# Adaptive Templates — Idea

A periodic note template is a static file. It cannot know the date, the day of the week, the active projects in the vault, or the habits the user is currently tracking. It ships the same structure every time, regardless of context.

Adaptive templates flip this: the agent generates the note fresh at creation time from a schema plus live context, instead of copying a static file. This document describes the idea and what it enables.

The unit shipped here is **intent**. The materialization is yours.

---

## The problem with static templates

A static Daily template ships the same exercise options every day, even if you stopped going to the gym three weeks ago. A static Monthly template lists the same roles every month, even after you wound down a project. A static Weekly template has no way to know it's the last week of the quarter — so it cannot prompt you to start a quarterly review.

The template is a good default. It is a poor context-aware note.

---

## The core idea

Replace the static file with a **schema** — a document that describes what the note should contain and what decisions the agent must make at creation time. The agent reads the schema, queries the vault for live context, and generates the note. The result looks like a template-generated note but reflects the actual state of the world on that day.

Live context the agent has access to at creation time:

| Context signal | What it enables |
|----------------|-----------------|
| Date (year, month, week, day-of-year) | Date-relative prompts, auto-filled period labels |
| Day of week | Different structure for Mondays (planning mode) vs Fridays (reflection mode) vs weekends |
| Transition detection | First daily of a new week, last daily of the month, first week of a new quarter |
| Active projects | Pre-fill the Work Notes section with project names already in context |
| Tracked habits | Generate only the habit checkboxes for habits currently active, not a stale list |
| Last note in series | Link to yesterday's daily, last week's weekly, etc. — resolved at creation time |

---

## What changes for each note type

### Daily

**Static:** the same habits checklist, the same sections, every day.

**Adaptive:**
- Habits block generated from a preferences file, not hardcoded. Add a habit → it appears tomorrow. Remove one → it disappears.
- Friday daily gets a "Week retrospective prompt" block — one or two sentences, pre-filled with the week number and a pointer to this week's weekly note.
- First daily of a new month gets a "Month intention check" prompt.
- Transition days carry a lightweight nudge; non-transition days do not.

### Weekly

**Static:** the same sections with empty bullet points.

**Adaptive:**
- "Dailies reviewed" block pre-filled with links to this week's daily notes that already exist.
- Active projects pre-listed under the retrospective section — the agent resolves `1-projects/` at creation time and inserts the names. You write a one-liner per project; you don't have to remember the list.
- Last week of the quarter: includes a nudge to open a quarterly review.

### Monthly

**Static:** the same roles section every month.

**Adaptive:**
- "Weeklies reviewed" pre-filled with links to this month's weekly notes.
- Roles section generated from active areas in `2-areas/` at creation time. Wind down an area → it disappears from next month's template.
- Projects section lists only projects with active work in the last 30 days, not every project in the vault.

### Quarterly

**Static:** review structure with empty bullets.

**Adaptive:**
- "Monthlies reviewed" pre-filled.
- Completed projects (moved to `4-archives/` this quarter) auto-listed under "Projetos concluídos."
- Next-quarter planning section seeded with projects that are in-flight and carried forward.

---

## Schema structure

A schema for each note type is a markdown file (e.g., `daily-schema.md`) that describes:

1. **Frontmatter fields** — what goes in YAML and what values are valid
2. **Sections** — each section with its heading, its purpose comment, and any generation rules
3. **Conditional blocks** — sections that appear only on specific days, transition points, or when a condition holds (e.g., "include Month Check block if `day_of_month <= 3`")
4. **Live queries** — instructions to the agent to query the vault before generating (e.g., "list active projects from `1-projects/`")

The schema is co-evolved by the user and the agent. Start with the static template and annotate it with rules. The schema grows as you discover what you actually want at creation time.

---

## Design principles

| Principle | Why |
|-----------|-----|
| Static fallback | If the agent is not available, the static template still works. Adaptive templates augment, not replace |
| Schema is readable by humans | The schema is a plain markdown file with instructions, not code. You should be able to read it and understand what the agent will do |
| Idempotent generation | Running the schema twice on the same day produces the same note. Live queries are deterministic for a given vault state |
| No pre-fill that overwrites intent | The agent pre-fills optional prompts, not required content. The user's own words are never overwritten |
| Schema lives in `.user/` | Schemas are personal, like preferences. They do not ship with sb-os. Users extend the base templates with their own schema files |

---

## What this is not

Adaptive templates are not:
- A replacement for the review workflow (the schema can pre-fill structure; it cannot run the review)
- A RAG system (no embeddings, no similarity search — just vault queries and date logic)
- A dynamic dashboard (the note is generated once at creation time and is then a static file like any other)

Once the note exists, it is a regular markdown file. It does not update itself. The adaptation happens at the moment of creation, not on every open.

---

## Build approach

1. Start with your existing static template for one note type (daily is the best first candidate).
2. Identify what you wish were pre-filled at creation time — active projects? Habit list? Links to existing notes?
3. Write a schema file that annotates the template with generation rules for those fields.
4. Tell the agent to use the schema when creating next week's note. Evaluate the result.
5. Iterate. The schema evolves as you discover what context you actually want.

You do not need to replace all templates at once. One adaptive daily, used for a month, will teach you more than planning the full system upfront.
