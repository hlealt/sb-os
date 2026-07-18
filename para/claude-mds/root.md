<!--
sb-os managed file — vault root CLAUDE.md

Content INSIDE the `<!-- sb:start v=1 -->` ... `<!-- sb:end -->` block is
overwritten on every `python install.py`. Edit it in the sb-os
source repo, not here.

Content OUTSIDE the markers is yours — add personal routing rules, your
glossary path declaration, your git repo table, language preference, etc.
The installer never touches it.
-->

<!-- sb:start v=1 -->
# CLAUDE.md

Personal Obsidian vault structured as a second brain using the PARA method, managed by sb-os.

---

## Hard Rules

**Agent capture** — When you (an agent) capture content for the user (annotate, save, store, log, etc.), route DIRECTLY to the matching vault location. Default routing follows the PARA semantics below; the daily note is a fallback for genuinely ambiguous content, not a default.

| Content type | Default destination |
|--------------|---------------------|
| Bounded work with a defined "done" | `1-projects/{project-name}/` |
| Ongoing responsibilities (no defined endpoint) | `2-areas/{area-name}/` |
| Reference material, tools, knowledge bases | `3-resources/{topic}/` |
| Completed, abandoned, or under-review content | `4-archives/` |
| External code repos / project workspaces | `5-workbench/{repo-name}/` |
| Tasks for a specific project or area | `{project-or-area}-tasks.md` inside that folder |
| Genuinely ambiguous / no clear vault home | Daily note (`0-periodic-notes/daily/`) |

Fits an existing file → append. Index files (`{dir-name}.md`) are NEVER content destinations. Unclear destination → ask the user before writing.

**Exception — daily-note override.** When the user explicitly says "add to today", "save to daily", or "add to daily note", route to the daily note regardless of the table above.

**Archives are off-limits.** NEVER read, search, list, or load files under `4-archives/` unless the user explicitly directs you to that folder ("check 4-archives", "look in archives", or names a path inside it). It is a pre-deletion holding zone — its contents are stale or under review and MUST NOT inform agent answers, routing, or context. An explicit instruction lifts this for that request only. **Exception — direct reference:** when a file you are legitimately working with carries a direct path to a specific file under `4-archives/`, you MAY open that referenced file to follow the reference. This lifts the rule for that one referenced path ONLY — never for browsing, searching, or listing the archive.

**Auto-memory.** Claude Code's auto-memory serves ONLY for agent behavior feedback (preferences, corrections, workflow tweaks). Content goes to the vault. When in doubt, vault wins.

**Parallel sessions — write collisions.** On an Edit rejection for "file modified since read" (another session wrote the file), re-read the file and re-apply ONLY your delta to the fresh state — never restore frontmatter or body content from your earlier read. This retry is the canonical discipline; do not add lock or marker machinery.

**Parallel sessions — commit collisions.** Staging a file commits ALL its uncommitted hunks, including other sessions'. Before committing a vault file, diff it against your own session's delta — either confirm the foreign hunks ride along (disclose them in the commit message) or stop and re-scope. NEVER `git commit --amend` in the vault: HEAD may have moved to another session's commit between your read and the rewrite — fix history forward with a new commit, or not at all.

**Parallel sessions — working-tree reverts.** Edit rejection is not the only collision: a parallel session may `git restore` files in a shared repo and silently wipe your applied-but-uncommitted edits (observed 2026-06-05, sb-os). Immediately before staging, `git diff` each file you intend to stage and confirm your delta is still present; if wiped, re-read and re-apply only your delta, then commit without delay — the edit→commit window is the exposure.

**New conventions are owner-gated.** Introducing a NEW structural convention or standard not already covered by documented rules — a new folder *pattern*, file-organization scheme, task/file format, or naming standard — requires BOTH (1) documenting the rule in the owning `CLAUDE.md` or a decisions doc AND (2) the owner's agreement, BEFORE you apply it. Never introduce such structure ad hoc: propose, get agreement, document, then apply. Creating an ordinary project/area folder that follows existing PARA routing is NOT a new convention — this gate is for novel patterns only. An undocumented convention is a defect even when the work it organizes is correct.

Users extend these defaults by adding their own routing rules below the marker block — anything outside the markers wins over the marker-block defaults (agents read top-to-bottom).

---

## Naming Conventions

- Main file per directory = `{dir-name}.md` (e.g., a folder named `project-a/` has its index file `project-a.md`)
- Never use `README.md` as a vault index
- Folders, files, and tags use lowercase kebab-case in English. Proper nouns and acronyms are exempt
- Component prefixes: `sb-` (sb-os shippable), `rbtv-` (RBTV plugin if installed), no prefix (personal). Details: `docs/component-prefixes.md` in the sb-os repo

---

## Tags

Index (`{dir-name}.md`) and task (`{name}-tasks.md`) files carry their own directory name as the FIRST tag — the identity tag dashboards and agents key on. Projects declare their parent area via `area:` frontmatter on those two files, not via an area tag. Every other file gets its parent area tag (the directory name under `2-areas/`). Cross-cutting tags combine with these (examples: `decision`, `meeting`, `idea`). Resources may add topic tags (example: `ai-tools`). Periodic note status tags: `reviewed`, `routed`.

---

## Vault Structure

| Folder | Purpose |
|--------|---------|
| `0-periodic-notes/` | Periodic notes (Daily=inbox, Weekly, Monthly, Quarterly) |
| `1-projects/` | Bounded work — projects with a beginning and an end |
| `2-areas/` | Ongoing responsibilities (e.g., `area-personal/`, `area-work/`, `area-learning/`) |
| `3-resources/` | Reference content (e.g., `tools/`, `knowledge-base/`) |
| `4-archives/` | Holding zone before deletion — completed projects, abandoned files, content under review |
| `5-workbench/` | The single home for ALL workbenches — project workspaces with their own git repos and structures, external repo clones, and git worktrees. A workbench (including a worktree of the vault repo itself) is NEVER created anywhere else in the vault |
| `.user/` | User-owned root: user-context folder + personal extensions (sb-os creates this directory on the initial install and never writes inside it thereafter) |

**Vault file** = any `.md` in PARA folders (`0-` through `4-`). **System component** = files under `.claude/` or the sb-os repo. `5-workbench/` contains independent repos and worktrees — not vault files.

**Vault content** = vault files governed by sb-os conventions: indexes (`{dir-name}.md`), task files (`{name}-tasks.md`), references, logs, periodic notes. **Project deliverables** = technical documents governed by per-project workflows (PRDs, specs, plans, code) — sb-os does not police their format.

Loose `.md` files placed directly under any PARA folder (siblings of subfolders) are user-owned and freeform — sb-os does not manage their structure or naming.

`.claude/` contains ONLY what Claude Code recognizes natively (rules, skills, commands, settings).

---

## Component Placement

System component conventions ship with sb-os under the sb-os repo. Skills and commands installed into `.claude/` are ALWAYS thin loaders pointing to workflow files in the sb-os repo — never edit them in `.claude/` (overwritten on every install run).

The sb-os repo path on this vault is recorded in `sb-os.json` at the vault root (`sb_os_path` field). Edit sb-os components in the source repo, then re-run `python install.py`.

---

## Periodic Notes Templates

Templates for daily, weekly, monthly, and quarterly notes live at `.user/config/templates/periodic-notes/`:

| Template | Path |
|----------|------|
| Daily | `.user/config/templates/periodic-notes/Daily.md` |
| Weekly | `.user/config/templates/periodic-notes/Weekly.md` |
| Monthly | `.user/config/templates/periodic-notes/Monthly.md` |
| Quarterly | `.user/config/templates/periodic-notes/Quarterly.md` |

When the user says "log this to my daily note" (or weekly/monthly/quarterly), use the matching template's structure to create or append to the note in `0-periodic-notes/{period}/`. The note filename follows the Obsidian daily-notes plugin convention (e.g., `YYYY-MM-DD.md` for daily). Templates are user-owned and editable — sb-os bootstraps them on install but never overwrites them on upgrade.

<!-- sb:end -->

<!-- Add your own content below — anything outside the sb:start/sb:end markers survives re-install. -->

## Name Glossary

<!--
If you want agents to apply name corrections from a glossary file, declare the
path here. Example:

Glossary path: `.user/profile/glossary.md`. Loaded per `.claude/rules/sb-audio-aware.md` (if installed).
-->

## Git Repositories

<!--
List in-vault nested git repos so commit/PR skills can resolve repo paths.
In-vault repos must be gitignored from the vault's own git (see vault root `.gitignore`).
Example:

| Project | Repo path | Entry point |
|---------|-----------|-------------|
| {project-name} | `5-workbench/{repo-name}/` | `5-workbench/{repo-name}/CLAUDE.md` |
-->

## Language

<!--
State a default language preference for agent output. Example:
> Language: English by default. When the conversation is in {your-language}, write content in {your-language}.
-->
