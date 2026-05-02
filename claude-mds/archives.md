<!--
sb-os managed file — installs to `{vault}/4-archives/CLAUDE.md`.

Content INSIDE `<!-- sb:start v=1 -->` ... `<!-- sb:end -->` is overwritten
on `python install.py --upgrade`. Edit it in the sb-os source repo.

Content OUTSIDE the markers is yours — list your own archived index,
document a retention policy, or extend the routing rules.
-->

<!-- sb:start v=1 -->
# 4-archives/

PARA Archives layer — holding zone before deletion. Completed projects, abandoned files, and content under review live here until reviewed and either deleted or restored.

---

## Definition

An **archive** is staging — not a permanent record. Content here has all three:

1. No active work happening
2. No ongoing responsibility upholding it
3. Not yet ready for deletion

If content is still actively worked on it belongs in `1-projects/`. If it is still maintained over time it belongs in `2-areas/`. If it is consulted on demand for reference it belongs in `3-resources/`.

---

## How Archives Differ from Deletion

| Stage | What it means |
|-------|---------------|
| In archive | Out of active circulation but recoverable; safe to read, summarize, or restore |
| Deleted | Removed from the vault entirely; recovery only via git history |

Archives let the user defer the deletion decision without polluting active PARA folders. Deletion is a separate, explicit step.

---

## Routing Rules

| Situation | Action |
|-----------|--------|
| Project completes or stalls | Move `1-projects/{project-name}/` → `4-archives/{project-name}/` |
| Area no longer maintained | Move `2-areas/{area-name}/` → `4-archives/{area-name}/` |
| Resource no longer relevant | Move `3-resources/{category}/` (or specific files) → `4-archives/` |
| Archived content needed again | Move back to the appropriate PARA layer; do not duplicate |
| Archived content reviewed and unwanted | Delete (separate step from archiving) |

---

## Conventions

| Item | Rule |
|------|------|
| Direct writes | Agents do NOT write new content directly into `4-archives/`. Files arrive via archive workflows or explicit user move |
| Index file | `archives.md` may serve as an index of what was archived and when — user-owned, not managed by sb-os |
| Sensitive originals | When archived content is sensitive (e.g., personal reflections, financial records, medical notes), agents read or summarize ONLY when the user explicitly requests it |
| Retention | sb-os does not enforce a retention policy. Users define their own review cycle (or none) below the marker block |
| Sub-files | Loose `.md` files at the `4-archives/` root (siblings of archived folders) are user-owned and freeform — sb-os does not manage their structure or naming |

---

## Cross-References

- **Projects (`1-projects/`)**, **Areas (`2-areas/`)**, **Resources (`3-resources/`)** — every PARA layer routes here when its content stops being active. Archives only flow inward; the reverse path is a deliberate "restore" action.

<!-- sb:end -->

<!-- =====================================================================
     User-owned section — preserved on `--upgrade`. Add anything below.
     ===================================================================== -->

<!-- Add your own content below — anything outside the sb:start/sb:end markers survives --upgrade. -->
