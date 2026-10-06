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
| Overview file | `{project-name}.md` inside the folder — describes goal, current status, optional due date and useful links; retains its index metadata |
| Overview frontmatter | YAML frontmatter on the overview SHOULD declare `area:` (the parent area this project rolls up to) and MAY declare `due:` (an optional due date) — see Frontmatter Convention below |
| Task file | `{project-name}-tasks.md` inside the folder — single source of tasks for the project (tasks carry their own dates). OPTIONAL: create it when the project's first task lands — a project with no tasks has no tasks file (dashboards discover task files; empty ones only add noise) |
| Per-project `CLAUDE.md` | User-owned (sb-os does not manage it). It owns project-specific instructions and conditions for reading or acting on records |
| Sub-folders | Nest planning and build-record artifacts under one `build/` folder; keep the root to the living set (see Root Layout). Other reference sub-folders are free-form — agents follow the project's own `CLAUDE.md` if present |
| Sub-files | Loose `.md` files at the `1-projects/` root (siblings of project folders) are user-owned and freeform — sb-os does not manage their structure or naming |

Use evocative folder names that describe the work itself: `marketing-launch-2027/`, `office-relocation/`, `thesis-q3/`. Treat those as illustrations only — pick names that match your projects.

---

## Root Layout — keep the root scannable

Keep the current working set at the project root. Put planning and build records under `build/`, in a named subfolder per run or topic; do not leave records loose at the root of `build/`.

| Current working set | Build and historical records |
|---|---|
| `{project-name}.md` — overview, purpose and status | `build/<run-or-topic>/` — plans, designs, specifications, dispatch prompts and evidence |
| `{project-name}-tasks.md` — unfinished tasks | `build/old/` — superseded states and completed work records |
| Current product and authoritative workflow, state or decisions used to continue work | Preserved historical runs and their decisions, with working references |

Each changing fact has one maintained home. If a workflow or status file owns execution state, the overview links it; otherwise the overview states current status. The tasks file lists unfinished work, not a second status narrative. Folder instructions own directions for when agents read or act; an overview may link useful records without duplicating their maintained inventories or instructions.

Move a record to history only when it is superseded or no longer authoritative; a completed producing run does not retire a still-current decision or plan. Preserve the record and update current links in the same change. Keep the workspace's task-file locations and metadata, and add a board or other artifact only when the work needs it. Do not create empty standard files.

---

## Frontmatter Convention

Each project's overview file SHOULD carry YAML frontmatter identifying it and linking it to its parent area:

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
| New bounded work with a defined "done" | Create `1-projects/{project-name}/` with overview (frontmatter + body); add `{project-name}-tasks.md` when the first task lands |
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
