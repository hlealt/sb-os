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
| Task file | `{project-name}-tasks.md` inside the folder — single source of tasks for the project (tasks carry their own dates) |
| Per-project `CLAUDE.md` | User-owned (sb-os does not manage it). Use it for project-specific agent rules |
| Sub-folders | Free-form per project — phases, deliverables, references — agents follow the project's own `CLAUDE.md` if present |
| Sub-files | Loose `.md` files at the `1-projects/` root (siblings of project folders) are user-owned and freeform — sb-os does not manage their structure or naming |

Use evocative folder names that describe the work itself: `marketing-launch-2027/`, `office-relocation/`, `thesis-q3/`. Treat those as illustrations only — pick names that match your projects.

---

## Frontmatter Convention

Each project's index file SHOULD carry YAML frontmatter linking it to its parent area:

```yaml
---
area: tech         # parent area this project rolls up to (single string)
due: 2027-03-15    # OPTIONAL — projects MAY have due dates
---
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `area` | string | recommended | Single parent area (the directory name under `2-areas/`) |
| `due` | date | optional | Use it if a deadline helps you; omit it freely |

The `area:` field lets dashboards and agents group projects by domain without a manual index. Adding `due:` is purely optional — projects without a due date are still projects, as long as they have a defined endpoint.

---

## Routing Rules

| Situation | Action |
|-----------|--------|
| New bounded work with a defined "done" | Create `1-projects/{project-name}/` with index (frontmatter + body) + tasks file |
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
