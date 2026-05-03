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

**Auto-memory.** Claude Code's auto-memory serves ONLY for agent behavior feedback (preferences, corrections, workflow tweaks). Content goes to the vault. When in doubt, vault wins.

Users extend these defaults by adding their own routing rules below the marker block — anything outside the markers wins over the marker-block defaults (agents read top-to-bottom).

---

## Naming Conventions

- Main file per directory = `{dir-name}.md` (e.g., a folder named `project-a/` has its index file `project-a.md`)
- Never use `README.md` as a vault index
- Folders, files, and tags use lowercase kebab-case in English. Proper nouns and acronyms are exempt
- Component prefixes: `sb-` (sb-os shippable), `rbtv-` (RBTV plugin if installed), no prefix (personal). Details: `docs/component-prefixes.md` in the sb-os repo

---

## Tags

Every file gets its parent area tag (the directory name under `2-areas/`). Cross-cutting tags combine with the area tag (examples: `decision`, `meeting`, `idea`). Resources may add topic tags (example: `ai-tools`). Periodic note status tags: `reviewed`, `routed`.

---

## Vault Structure

| Folder | Purpose |
|--------|---------|
| `0-periodic-notes/` | Periodic notes (Daily=inbox, Weekly, Monthly, Quarterly) |
| `1-projects/` | Bounded work — projects with a beginning and an end |
| `2-areas/` | Ongoing responsibilities (e.g., `area-personal/`, `area-work/`, `area-learning/`) |
| `3-resources/` | Reference content (e.g., `tools/`, `knowledge-base/`) |
| `4-archives/` | Holding zone before deletion — completed projects, abandoned files, content under review |
| `5-workbench/` | Project workspaces with their own git repos and structures |
| `.user/` | User-owned root: user-context folder + personal extensions (sb-os creates this directory on the initial install and never writes inside it thereafter) |

**Vault file** = any `.md` in PARA folders (`0-` through `4-`). **System component** = files under `.claude/` or the sb-os repo. `5-workbench/` contains independent repos — not vault files.

**Vault content** = vault files governed by sb-os conventions: indexes (`{dir-name}.md`), task files (`{name}-tasks.md`), references, logs, periodic notes. **Project deliverables** = technical documents governed by per-project workflows (PRDs, specs, plans, code) — sb-os does not police their format.

Loose `.md` files placed directly under any PARA folder (siblings of subfolders) are user-owned and freeform — sb-os does not manage their structure or naming.

`.claude/` contains ONLY what Claude Code recognizes natively (rules, skills, commands, settings).

---

## Component Placement

System component conventions ship with sb-os under the sb-os repo. Skills and commands installed into `.claude/` are ALWAYS thin loaders pointing to workflow files in the sb-os repo — never edit them in `.claude/` (overwritten on every install run).

The sb-os repo path on this vault is recorded in `sb-os.json` at the vault root (`sb_os_path` field). Edit sb-os components in the source repo, then re-run `python install.py`.

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
