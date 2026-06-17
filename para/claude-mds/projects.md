<!--
sb-os managed file — installs to `{vault}/1-projects/CLAUDE.md`.

Content INSIDE `<!-- sb:start v=1 -->` ... `<!-- sb:end -->` is overwritten
on `python install.py`. Edit it in the sb-os source repo.

Content OUTSIDE the markers is yours — add notes about your active project
list, per-project conventions, or pointers to per-project CLAUDE.mds.
-->

<!-- sb:start v=1 -->
# 1-projects/

PARA Projects layer — work with a beginning and an end.

---

## Definition

A **project** has a beginning and an end — a defined outcome that, once reached, retires the project. **Areas** (`2-areas/`) are (almost) always on; projects are bounded.

A due date is OPTIONAL on a project. Use one if it helps you, but the defining trait is bounded lifespan, not the deadline. Tasks (which DO have dates) live inside a project's tasks file — never confuse a dated task for a project.

When the outcome is reached or the work stops, move the folder to `4-archives/`.

---

## Folder Convention

| Item | Rule |
|------|------|
| One folder per project | `1-projects/{project-name}/` (lowercase kebab-case). The folder is already inside `1-projects/` — do NOT prefix names with `project-` |
| Index file | `{project-name}.md` inside the folder — describes goal, status, optional due date, links |
| Index frontmatter | YAML frontmatter on the index SHOULD declare `area:` (the parent area this project rolls up to) and MAY declare `due:` (an optional due date) — see Frontmatter Convention below |
| Task file | `{project-name}-tasks.md` inside the folder — single source of tasks for the project (tasks carry their own dates). OPTIONAL: create it when the project's first task lands — a project with no tasks has no tasks file (dashboards discover task files; empty ones only add noise) |
| Per-project `CLAUDE.md` | User-owned (sb-os does not manage it). Use it for project-specific agent rules |
| Sub-folders | Nest planning and build-record artifacts under one `build/` folder; keep the root to the living set (see Root Layout). Other reference sub-folders are free-form — agents follow the project's own `CLAUDE.md` if present |
| Sub-files | Loose `.md` files at the `1-projects/` root (siblings of project folders) are user-owned and freeform — sb-os does not manage their structure or naming |

Use evocative folder names that describe the work itself: `marketing-launch-2027/`, `office-relocation/`, `thesis-q3/`. Treat those as illustrations only — pick names that match your projects.

---

## Root Layout — keep the root scannable

Only files navigated constantly stay at the project root; everything that records *how* the work was planned and built drops into a single `build/` folder.

| At the root (living) | One level down, in `build/` |
|----------------------|------------------------------|
| `{project-name}.md` — index, carries current **status** | plan, design, decisions, deliverables |
| `{project-name}-tasks.md` — open tasks | run log, state snapshots, specs, phase folders |
| the current product (code package, main document) | dispatch prompts, evidence sheets, review mockups |

Status lives in the index, open work in the tasks file — mutually exclusive and jointly complete: the index states *where the work stands* (never re-listing tasks); the tasks file lists *what is left*. A root accumulating planning/record files is the signal to move them into `build/`.

---

## Frontmatter Convention

Each project's index file SHOULD carry YAML frontmatter identifying it and linking it to its parent area:

```yaml
---
type: index
tags:
  - marketing-launch-2027   # identity tag — the project's own folder name
area: tech                  # parent area this project rolls up to (single string)
status: active
due: 2027-03-15             # OPTIONAL — projects MAY have due dates
---
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `tags` | list | recommended | FIRST entry = the project's identity tag (defaults to the folder name). Further entries are free topic tags |
| `area` | string | recommended | Single parent area (the directory name under `2-areas/`) |
| `due` | date | optional | Use it if a deadline helps you; omit it freely |

The `{project-name}-tasks.md` file carries the same `tags` + `area` pair — dashboards read task files directly. The `area:` field lets dashboards and agents group projects by domain without a manual index. Adding `due:` is purely optional — projects without a due date are still projects, as long as they have a defined endpoint.

---

## Routing Rules

| Situation | Action |
|-----------|--------|
| New bounded work with a defined "done" | Create `1-projects/{project-name}/` with index (frontmatter + body); add `{project-name}-tasks.md` when the first task lands |
| Project complete or abandoned | Move folder to `4-archives/` (preserves history; deletion is a later step) |
| Work has no defined endpoint / is ongoing | Belongs in `2-areas/`, not here |
| A single dated to-do (not a project) | Add it to the relevant project or area's tasks file — do NOT create a project folder for it |
| Reference material that may seed a future project | Belongs in `3-resources/`, not here |

---

## Cross-References

- **Areas (`2-areas/`)** — ongoing responsibilities. Projects roll up to an area via the `area:` frontmatter field.
- **Archives (`4-archives/`)** — destination when a project completes or stalls.
- **Workbench (`5-workbench/`)** — for projects backed by an external git repo. The vault project folder holds notes/tasks; the code lives in `5-workbench/{repo-name}/`.

<!-- sb:end -->

<!-- Add your own content below — anything outside the sb:start/sb:end markers survives re-install. -->
