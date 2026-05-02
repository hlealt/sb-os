---
name: sb-vault-integrity
description: Post-operation structural checks after creating, moving, renaming, or deleting any vault file. Also runs same-file proactive fixes when an edited file violates a verifiable rule from `.claude/rules/` or its parent CLAUDE.md chain. Updates CLAUDE.md rules when routing or dependencies change, sweeps broken references, and creates task files for new directories.
---

# Vault Integrity

Structural hygiene checks for the vault.

## When to Use

| Signal | Action needed |
|--------|---------------|
| Created a new file in PARA folders | CLAUDE.md update (only if routing or dependencies change) |
| Moved or renamed a file | CLAUDE.md update + reference sweep |
| Deleted a file | CLAUDE.md update + reference sweep |
| Created a new project or area directory | CLAUDE.md creation + tasks file creation |
| Edited a file that violates a verifiable rule from `.claude/rules/` or a parent CLAUDE.md | Read `./refs/proactive-fix.md` |

## Checks

| Check | When | Action |
|-------|------|--------|
| CLAUDE.md update | File changes routing, constraints, or dependencies in its directory | Update rules in that CLAUDE.md. Do NOT add file listings — CLAUDE.md contains rules, not file maps (see the `sb-vault-ops` workflow's `data/directories.md` for principles) |
| CLAUDE.md creation | New directory in Projects, Areas, Resources | Create CLAUDE.md following the template in the `sb-vault-ops` workflow's `data/directories.md` |
| Reference sweep | Move, rename, or delete | Grep entire vault (including `.claude/`, `Home.md`) for old filename/path. Update ALL references with Edit `replace_all`. No subagents — just Grep then Edit. Include partial matches — wikilinks use bare names |
| Tasks file | New project or area directory | Create `{name}-tasks.md` following `sb-vault-ops` task format (invoke `sb-vault-ops` for the creation) |
| Proactive fix | Editing a file, agent notices it violates a verifiable rule | Read `./refs/proactive-fix.md` and apply per its scope rules |
