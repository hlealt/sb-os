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
| Index file | `{area-name}.md` inside the folder — describes the area's scope, current state, and standing notes |
| Task file | `{area-name}-tasks.md` inside the folder — single source of recurring or open tasks for the area |
| Per-area `CLAUDE.md` | User-owned (sb-os does not manage it). Use it for area-specific agent rules and routing |
| Sub-folders | Free-form per area — agents follow the area's own `CLAUDE.md` if present |
| Sub-files | Loose `.md` files at the `2-areas/` root (siblings of area folders) are user-owned and freeform — sb-os does not manage their structure or naming |

Use evocative folder names that describe the responsibility itself: `health/`, `finance/`, `home/`. Treat those as illustrations only — pick names that match your areas.

---

## Tag Convention

Every file inside `2-areas/{area-name}/` gets `{area-name}` as a tag (the directory name). Cross-cutting tags (examples: `decision`, `meeting`, `idea`) combine with the area tag — never replace it.

---

## Routing Rules

| Situation | Action |
|-----------|--------|
| New ongoing responsibility | Create `2-areas/{area-name}/` with index + tasks file |
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
