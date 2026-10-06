<!--
sb-os managed file — installs to `{vault}/2-areas/CLAUDE.md`.

Content INSIDE `<!-- sb:start v=1 -->` ... `<!-- sb:end -->` is overwritten
on `python install.py`. Edit it in the sb-os source repo.

Content OUTSIDE the markers is yours — list your own areas, document
per-area conventions, or extend the routing rules.
-->

<!-- sb:start v=1 -->
# 2-areas/

PARA Areas layer — ongoing responsibilities without a finish line.

---

## Definition

An **area** is a domain you maintain over time. Unlike a project, an area has:

1. No defined "done" state
2. No deadline
3. A standard of performance you uphold continuously

If a thread of work has a deadline and a defined outcome, it belongs in `1-projects/`. If it is reference material with no active stewardship, it belongs in `3-resources/`.

---

## Folder Convention

| Item | Rule |
|------|------|
| One folder per area | `2-areas/{area-name}/` (lowercase kebab-case) |
| Overview file | `{area-name}.md` inside the folder — describes scope, current state and standing notes; retains its index metadata |
| Task file | `{area-name}-tasks.md` inside the folder — single source of recurring or open tasks for the area. OPTIONAL: create it when the area's first task lands — an area with no tasks has no tasks file (dashboards discover task files; empty ones only add noise) |
| Per-area `CLAUDE.md` | User-owned (sb-os does not manage it). Use it for area-specific agent rules and routing |
| Sub-folders | One per ongoing sub-topic, each with its own `{sub-topic}.md` overview. When build records describe a separately bounded effort, follow Project-Shaped Work below. Agents follow the area's own `CLAUDE.md` if present |
| Sub-files | Loose `.md` files at the `2-areas/` root (siblings of area folders) are user-owned and freeform — sb-os does not manage their structure or naming |

Use evocative folder names that describe the responsibility itself: `health/`, `finance/`, `home/`. Treat those as illustrations only — pick names that match your areas.

---

## Current records and history

Keep the named overview and established task-file locations and metadata. Folder instructions own the conditions for reading or acting on records. The overview states current status or links its authoritative workflow/status file; it does not maintain a second inventory of tasks or instructions.

Where an area already needs planning or build records, keep them under `build/` in named run or topic folders, with superseded states and completed records in `build/old/`. Preserve history and update current routes when moving it. Keep authoritative decisions and standing instructions for the ongoing practice in their established homes. A producing run ending does not by itself make its still-current records historical. Add no empty standard artifacts or compulsory board.

## Project-Shaped Work in an Area

When work inside an area has a bounded outcome with a defined "done", it is project-shaped work. Plans, numbered phase folders, dispatch prompts and evidence sheets can help identify a separately bounded effort; records supporting an ongoing practice alone do not change its placement.

On identifying a separately bounded effort — when creating such work, or when encountering it in an existing sub-folder — surface it: name what was detected, recommend extracting it to `1-projects/{name}/` (with `area:` frontmatter pointing back to this area), and offer to keep it as an area topic instead. Proceed on the owner's decision; this is an advisory default, not a hard block.

An ongoing *practice* that happens to spawn bounded efforts (e.g. a continuous benchmarking topic) stays in the area — only the bounded efforts it spawns extract to `1-projects/`.

---

## Tag Convention

Every file inside `2-areas/{area-name}/` gets `{area-name}` as a tag (the directory name). The area's overview and tasks files carry it as the FIRST tag — the identity tag dashboards key on. Cross-cutting tags (examples: `decision`, `meeting`, `idea`) combine with the area tag — never replace it.

---

## Routing Rules

| Situation | Action |
|-----------|--------|
| New ongoing responsibility | Create `2-areas/{area-name}/` with overview; add `{area-name}-tasks.md` when the first task lands |
| Area gains a deadline + defined outcome | Spin up `1-projects/{project-name}/` for the time-bound work; the area folder remains for the ongoing thread |
| Area no longer maintained | Move folder to `4-archives/` (preserves history; deletion is a later step) |
| Reference material with no active stewardship | Belongs in `3-resources/`, not here |

---

## Cross-References

- **Projects (`1-projects/`)** — when an area generates work with a deadline, that work becomes a project. The area itself stays.
- **Resources (`3-resources/`)** — passive reference content. Areas are *active* responsibilities; resources are *passive* references.
- **Archives (`4-archives/`)** — destination when an area is no longer maintained.

<!-- sb:end -->

<!-- Add your own content below — anything outside the sb:start/sb:end markers survives re-install. -->
