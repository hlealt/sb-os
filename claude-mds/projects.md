<!--
sb-os managed file — installs to `{vault}/1-projects/CLAUDE.md`.

Content INSIDE `<!-- sb:start v=1 -->` ... `<!-- sb:end -->` is overwritten
on `python install.py --upgrade`. Edit it in the sb-os source repo.

Content OUTSIDE the markers is yours — add notes about your active project
list, per-project conventions, or pointers to per-project CLAUDE.mds.
-->

<!-- sb:start v=1 -->
# 1-projects/

PARA Projects layer — active goals with deadlines and concrete outcomes.

---

## Definition

A **project** has all three:

1. A defined outcome (what "done" looks like)
2. A deadline or target window
3. Active work happening now

If any of those is missing, it belongs in `2-areas/` (ongoing responsibility) or `3-resources/` (reference). When the outcome is reached or the work stops, move the folder to `4-archives/`.

---

## Folder Convention

| Item | Rule |
|------|------|
| One folder per project | `1-projects/{project-name}/` (lowercase kebab-case) |
| Index file | `{project-name}.md` inside the folder — describes goal, status, deadline, links |
| Task file | `{project-name}-tasks.md` inside the folder — single source of tasks for the project |
| Per-project `CLAUDE.md` | User-owned (sb-os does not manage it). Use it for project-specific agent rules |
| Sub-folders | Free-form per project — phases, deliverables, references — agents follow the project's own `CLAUDE.md` if present |

Examples (replace with your own): `1-projects/project-a/`, `1-projects/project-b/`.

---

## Routing Rules

| Situation | Action |
|-----------|--------|
| New active goal with a deadline | Create `1-projects/{project-name}/` with index + tasks file |
| Project complete or abandoned | Move folder to `4-archives/` (preserves history; deletion is a later step) |
| Work has no deadline / is ongoing | Belongs in `2-areas/`, not here |
| Reference material that may seed a future project | Belongs in `3-resources/`, not here |

---

## Cross-References

- **Areas (`2-areas/`)** — ongoing responsibilities without a finish line. Project may "graduate" to an area when scope outgrows a deadline.
- **Archives (`4-archives/`)** — destination when a project completes or stalls.
- **Workbench (`5-workbench/`)** — for projects backed by an external git repo. The vault project folder holds notes/tasks; the code lives in `5-workbench/{repo-name}/`.

<!-- sb:end -->

<!-- =====================================================================
     User-owned section — preserved on `--upgrade`. Add anything below.
     ===================================================================== -->

## Your Active Projects

<!--
Optional: list your current active projects here as a quick index, or
document any project-set conventions specific to your workflow. Example:

| Project | Folder | Deadline |
|---------|--------|----------|
| {project-name}  | `1-projects/{project-name}/` | YYYY-MM-DD |
-->
