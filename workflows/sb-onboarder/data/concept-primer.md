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

## Home (preview)

`Home.md` is an **optional** dashboard at the vault root — the surface you see when you open the vault. It aggregates and orients (today's tasks, active projects, recent activity, periodic links). It does NOT store content.

A Home is yours to spec. The onboarder can build one in step 06 if you want — driven by the design doc at `{sb_os_path}/ideas/home-dashboard.md`. Skip it now and build one later anytime.

Home requires the **Dataview** (with JS enabled) and **Templater** Obsidian plugins. The onboarder will print install instructions if you opt in.
