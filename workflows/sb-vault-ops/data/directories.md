# Directory Documentation

## Universal CLAUDE.md Principles

These principles apply to any repository — not just this vault.

### Purpose

A CLAUDE.md contains only what an agent cannot derive from the filesystem or file contents. Agents can `ls` directories and read files. CLAUDE.md adds the context they'd miss.

### Include

| Content | Example |
|---------|---------|
| Content routing | "Tasks for sub-topic X route to `area-x-sub-tasks.md`, not here" |
| Content routing boundaries | "Items of kind Y go in `subdir-y.md` only — never inline in narratives" |
| Constraints and warnings | "Sensitive content — never summarize in chat without user request" |
| Hidden dependencies | "`subdir-y.md` is read by `index.md` via line numbers — preserve section structure" |
| Guard triggers | "Before editing, read `docs/some-architecture.md`" |
| Directory-specific conventions | "One file per prospect when enough context accumulates" |
| Non-obvious operational info | Sync paths, design intent, dev setup quirks |

### Exclude

| Content | Why |
|---------|-----|
| File and subdirectory listings | `ls` provides this — always current, zero maintenance |
| File content summaries | Agent can read the file to see what it contains today |
| Conventions from parent CLAUDE.md | Agents walk the hierarchy |
| Standard language/framework patterns | Agent already knows |
| Frequently changing information | Goes stale, causes wrong behavior |

### Writing Guidelines

| Guideline | Detail |
|-----------|--------|
| Every line must earn its place | "Would removing this cause the agent to make mistakes?" — if not, cut it |
| State positives, not negatives | "Use X" over "Do NOT use Y" — negation activates the concept |
| Conciseness | Target <30 lines for leaf directories, <100 for complex project roots |
| Progressive disclosure | Point to files by path — don't embed their content |
| Sparse emphasis | Reserve IMPORTANT/NEVER for genuinely critical constraints |

### Minimal Valid CLAUDE.md

Directory with no special rules:

```markdown
# {dir-name}/

One-line purpose of this directory.
```

Directory with rules:

```markdown
# {dir-name}/

One-line purpose.

## Rules

- Content routing, constraints, dependencies, conventions
```

---

## Vault-Specific Conventions

Additions for an Obsidian vault using sb-os.

### PARA Folders (Projects, Areas, Resources)

Header: `# {dir-name}/` followed by one-line purpose. Projects add `Status: active/completed`.

Rules section covers: content routing, guard triggers, hidden dependencies, directory-specific conventions. Only include sections that carry non-derivable information.

### User-owned System Directories

When the user maintains a personal `.user/` folder with subdirectories, the same CLAUDE.md structure applies. Additionally document:
- `.claude/` vs `.user/` boundary when relevant
- Consumer relationships when files are loaded by specific workflows (frame as dependencies, not file tables)

### Exclusions (no CLAUDE.md needed)

`0-periodic-notes/weekly/`, `0-periodic-notes/monthly/`, `0-periodic-notes/quarterly/`, `5-workbench/` (nested repos with their own CLAUDE.md). `0-periodic-notes/daily/` and `4-archives/` DO have CLAUDE.md.
