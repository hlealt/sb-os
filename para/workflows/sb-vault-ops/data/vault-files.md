# Vault File Operations

Rules for creating, moving, renaming, and deleting files in the vault. Includes content type definitions for frontmatter.

## Content Types

Every `.md` file in the vault has a `type` field in frontmatter. The type determines what content belongs in the file.

### index

Directory dashboard for a project, area, or resource folder. The main `{dir-name}.md` file.

**Contains:**

| Section | Detail |
|---------|--------|
| Opening paragraph | Scope, purpose, or context of the directory (1-3 sentences, current state) |
| Structured context | Optional domain-specific sections agents need to understand the area |
| `## Linked Projects` / `## Active Projects` | Areas with linked projects — table with project and scope |
| `## Tasks` | Link to `[[{name}-tasks]]` — only when the tasks file exists; never link a tasks file that was not created |
| `## Files` | File inventory — table with `File` and `Description` (~280-char summaries) |
| Dataview query | Recently modified files in the directory |

> Section-name examples above are illustrative; actual section names are defined per-vault in the vault's CLAUDE.md or templates.

**Frontmatter:** `type: index`, `tags` (FIRST tag = the directory's own name — the identity tag). Projects add `area` (parent area directory name under `2-areas/`), `status`, and optional `due`.

**Never in an index:**

| Excluded | Where it belongs |
|----------|-----------------|
| Tasks | `{name}-tasks.md` (always separate) |
| User content dumps | Daily note or routed file |
| Long-form text | `type: document` file |
| History, migration notes, changelogs | Nowhere — git tracks history. Index reflects current state only |

### tasks

MoSCoW-prioritized tasks for a directory. At most one `{name}-tasks.md` per area or project folder — the file is OPTIONAL: create it when the first task lands, never preemptively (dashboards discover task files; empty ones only add noise).

**Frontmatter:** `type: tasks`, `tags` (FIRST tag = the directory's own name — the identity tag). Project task files add `area` (parent area), mirroring the index.

Full format, routing, and lifecycle: read `./tasks.md`.

### reference

Structured information for consultation — not narrative, not temporal.

Examples: lists, rules, catalogs, prompts, comparisons, checklists, tool inventories, configuration docs.

### log

Temporal records bound to a time period or event.

Examples: monthly reports, meeting notes, session transcripts, review checklists.

### document

Long-form text — narrative, reflective, or analytical.

Examples: essays, reflections, articles, analyses, memos.

## Periodic Notes

Time-bound notes in `0-periodic-notes/`. Content type is `log`. Filename and folder by level:

| Level | Filename | Folder |
|-------|----------|--------|
| Daily | `yyyy-mm-dd.md` | `0-periodic-notes/daily/` |
| Weekly | `yyyy-Wnn.md` | `0-periodic-notes/weekly/` |
| Monthly | `yyyy-mm.md` | `0-periodic-notes/monthly/` |
| Quarterly | `yyyy-Qn.md` | `0-periodic-notes/quarterly/` |

Daily notes have section-routing rules in `0-periodic-notes/daily/CLAUDE.md` when present. Templates ship with sb-os and live at `{sb_os_path}/para/templates/`. Daily notes are typically created by Obsidian's daily-notes plugin.

## Before Creating a File

1. **Verify location** — match content to the correct destination folder. Operational personal data (configs, credentials, accounts) → user's `.user/` folder, never in Areas or `.claude/`
2. **Check redundancy** — search for existing files on the same topic. Append instead of creating
3. **Set `type` frontmatter** — follow the content types above
4. **Verify parent directory** — if in Projects/Areas/Resources, confirm CLAUDE.md exists (read `./directories.md` if needed)

## Before Deleting

List ALL affected files in chat. Wait for explicit user confirmation.

## Cross-linking

When creating or editing a note (except dailies and templates), add 1-3 bidirectional `[[links]]` to related notes. Prioritize: same-area connected topics, cross-area shared context, unlinked references in text.

## Aliases

Add `aliases` in frontmatter with alternative names for Quick Switcher (Ctrl+O).

## Do Not Touch

- `.obsidian/` — never modify
- `workspace.json` — never commit unless user asks
