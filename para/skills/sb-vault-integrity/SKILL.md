---
name: sb-vault-integrity
description: Use after structural vault mutations: moving, renaming, or deleting vault files; creating project/area/resource directories; or creating vault files that change routing or dependencies. Do NOT use for ordinary edits to existing routed files. Same-file proactive fixes are not an invocation trigger.
---

# Vault Integrity

Structural hygiene checks for the vault.

## When to Use

| Signal | Action needed |
|--------|---------------|
| Created a new file in PARA folders that changes routing or dependencies | CLAUDE.md update |
| Moved or renamed a file | CLAUDE.md update + reference sweep |
| Deleted a file | CLAUDE.md update + reference sweep |
| Created a new project or area directory | CLAUDE.md creation + tasks file creation |

## Non-Triggers

| Signal | Action |
|--------|--------|
| Ordinary edit to an existing routed file | Do not invoke this skill |
| Same-file format issue noticed during ordinary edit | Fix only if already in scope for the requested edit; otherwise flag briefly |
| User asks to lint or clean one file | Read `./refs/proactive-fix.md`; do not run structural checks |

## Checks

| Check | When | Action |
|-------|------|--------|
| CLAUDE.md update | File changes routing, constraints, or dependencies in its directory | Update rules in that CLAUDE.md. Do NOT add file listings — CLAUDE.md contains rules, not file maps (see the `sb-vault-ops` workflow's `data/directories.md` for principles) |
| CLAUDE.md creation | New directory in Projects, Areas, Resources | Create CLAUDE.md following the template in the `sb-vault-ops` workflow's `data/directories.md` |
| Reference sweep | Move, rename, or delete | Grep entire vault (including `.claude/`, `Home.md`) for old filename/path. Update ALL references with Edit `replace_all`. No subagents — just Grep then Edit. Include partial matches — wikilinks use bare names |
| Tasks file | New project or area directory | Create `{name}-tasks.md` following `sb-vault-ops` task format (invoke `sb-vault-ops` for the creation) |
| Proactive fix | User explicitly asks to lint/clean one file, or this skill is already active for a structural mutation | Read `./refs/proactive-fix.md` and apply per its scope rules |
