---
name: sb-vault-ops
description: Gatekeeper for vault content and system component modifications — indexes, task files, references, logs, personal documents, periodic notes, directories, and `.claude/` files. Enforces format, routing, naming, and structural invariants. Do NOT use for project deliverables (PRDs, architecture docs, specs, plans, stories, code).
---

# Vault Ops

Gatekeeper for vault content and system component modifications. Identify the operation type, then load the corresponding reference file.

## Decision Tree

| # | Question | Action |
|---|----------|--------|
| 1 | Creating, editing, or routing a **task**? | Read `./data/tasks.md` |
| 2 | Creating or editing a **CLAUDE.md** file? | Read `./data/directories.md` — follow the Universal CLAUDE.md Principles |
| 3 | Creating a **new directory** in Projects/Areas/Resources? | Read `./data/directories.md` |
| 4 | Creating, moving, renaming, or deleting a **vault content file** (PARA folders)? | Read `./data/vault-files.md` |
| 5 | Modifying a **system component** (`.claude/`)? | Read `./data/components.md` |

Multiple operations in one task → load all applicable refs.
