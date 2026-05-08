---
name: sb-vault-ops
description: Gatekeeper for vault content and system component modifications — indexes, task files, references, logs, personal documents, periodic notes, directories, and `.claude/` files. Enforces format, routing, naming, and structural invariants. Do NOT use for project deliverables (PRDs, architecture docs, specs, plans, stories, code).
---

# Vault Ops

Gatekeeper for vault content and system component modifications. Identify the operation type, then load the corresponding reference file.

## Fast Path

Do NOT load any reference file for an ordinary edit to an existing routed file when ALL are true:

| Check | Required state |
|-------|----------------|
| File state | Existing file only; no create, move, rename, or delete |
| Location | Destination is already correct and not being reconsidered |
| Metadata | Filename, folder, frontmatter type, tags, and aliases are unchanged |
| Structure | No task format, CLAUDE.md, wikilink, or directory structure change |
| Scope | Edit is content-only and not a system component change |

If every check passes, proceed with the requested edit only.

## Decision Tree

| # | Question | Action |
|---|----------|--------|
| 1 | Creating, routing, reprioritizing, rescheduling, completing, or changing the canonical fields of a **task**? | Read `./data/tasks.md` |
| 2 | Creating or editing a **CLAUDE.md** file? | Read `./data/directories.md` — follow the Universal CLAUDE.md Principles |
| 3 | Creating a **new directory** in Projects/Areas/Resources? | Read `./data/directories.md` |
| 4 | Creating, moving, renaming, or deleting a **vault content file** (PARA folders)? | Read `./data/vault-files.md` |
| 5 | Modifying a **system component** (`.claude/`, `.agents/`, or sb-os source)? | Read `./data/components.md` |

Multiple operations in one task → load all applicable refs.
