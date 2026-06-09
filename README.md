# sb-os

> A PARA convention plus a Claude Code agent layer for Obsidian vaults.

## What is sb-os?

sb-os installs an opinionated structure into an Obsidian vault — PARA folders, periodic notes, a workbench layer for code repos, an optional wiki — and ships a set of `/sb-*` slash commands and Claude Code skills that operate against that structure. After install, your agents know where things go, how to capture content, how to run reviews, and how to keep the vault structurally consistent.

The convention is opinionated; the content is yours. sb-os never writes inside `.user/`, never touches `.claude/settings.json`, and never owns your `Home.md`.

## Who is it for?

- Obsidian users who already use PARA (or want to) and run Claude Code over their vault.
- People who keep notes, projects, code repos, and saved reading in one place and want a single set of conventions across all of them.
- Anyone running Claude Code who keeps having to tell the agent where things go.

If you don't use Obsidian or Claude Code, the directory convention is still reusable on its own — the agent layer needs Claude Code.

## What ships

Each module is a bundle of skills, commands, and rules. Core is always installed. The rest are optional and selected at install time.

| Module | What it gives you |
|---|---|
| **core** *(always installed)* | The PARA gatekeepers. Every vault edit routes through `sb-vault-ops` (validates destination, format, naming, structural invariants) and triggers `sb-vault-integrity` (sweeps broken references on rename/move/delete, updates CLAUDE.mds, scaffolds task files for new project/area directories). Always-on rules cover Obsidian-flavored markdown, sub-agent dispatch hygiene, and workflow-context injection. `/sb-onboarder` walks a fresh vault to populated PARA in one session, with state that persists across sessions. Periodic-note templates for daily/weekly/monthly/quarterly. |
| **wiki** *(optional, atomic)* | A Karpathy-style knowledge base — raw sources kept verbatim, synthesis layered on top. `/sb-wiki-ingest` distills a saved article into concept/entity/topic/source pages and stubs out forward references. `/sb-wiki-query` answers questions via grep across your wiki and raw sources — no embeddings, no RAG, your notes are the index. `/sb-wiki-lint` checks structural and citation hygiene. `/sb-archivist` writes a rolling per-day session work-log capturing decisions, rejected alternatives, collaborative refinements, discoveries, and files touched; on runs with nothing to document, it sweeps done tasks out of task files into the work log for the date each task was completed. `/sb-tutor` is a private tutor that delivers material in small pills along a personalized learning path — works on any subject and reads study material you drop into the project context (gitingest exports, technical docs, transcripts); study sessions land in `{wiki_root}/raw/studies/`. |
| **life-planner** *(optional)* | `/sb-life-planner` runs structured weekly, monthly, and quarterly reviews. Closes the prior period, sets intentions for the next, routes scheduled tasks to your daily notes, and keeps projects and areas in sync. |

Adding or removing a module later is a re-install — `python install.py` runs idempotently.

## Vault shape

After install, the vault looks like:

```
{vault-root}/
├── 0-periodic-notes/   daily/ weekly/ monthly/ quarterly/
├── 1-projects/         bounded work with a defined "done"
├── 2-areas/            ongoing responsibilities
├── 3-resources/        reference material, tools, knowledge bases
├── 4-archives/         completed, abandoned, under-review
├── 5-workbench/        external code repos and project workspaces
├── {wiki_root}/        wiki layer (if the wiki module is installed)
├── .user/              your personal extensions — sb-os never writes here after install
├── .claude/            agent loaders, rules, skills
├── sb-os.json          install manifest at vault root
└── CLAUDE.md           agent context, with a managed marker block
```

Every PARA folder has a managed `CLAUDE.md` your agent reads to route content. Marker blocks (`<!-- sb:start v=1 -->...<!-- sb:end -->`) let you add your own routing rules and conventions above and below sb-os's defaults — re-install never touches what's outside the markers.

## Requirements

| Requirement | Detail |
|---|---|
| Python | 3.9+ — the installer and the **core** module use the standard library only (no `pip install`). The optional **wiki** and **finance** modules ship Python tools that need the libraries under [Python dependencies](#python-dependencies) below |
| Obsidian | Any recent version |
| Claude Code | Required for the agent layer; the directory convention works without it |
| Git on the target vault | Strongly recommended before install — gives you a rollback tag |

## Python dependencies

Core and the installer are standard-library only. The **wiki** and **finance** modules call Python tools that depend on third-party libraries. Imports are lazy — a missing library disables or degrades a single tool rather than breaking the module — so install only what the tools you use need.

### Wiki module

Used by `sb-wiki-capture-source` (article + PDF capture) and `sb-wiki-search` (semantic search). No `requirements.txt` ships for these — install as needed:

| Package | Tool | Role |
|---|---|---|
| `trafilatura` | capture | **Primary** article extractor — purpose-built readability library for diverse sites |
| `beautifulsoup4` | capture | **Fallback** article extractor — richest-container `bs4` logic runs when trafilatura is unavailable or returns near-empty output |
| `httpx` | capture | HTTP fetch — required for the URL / fetch capture modes |
| `pypdf` | capture, ingest | PDF text extraction for `--pdf-text` and PDF ingest (`PyPDF2` is accepted as a fallback) |
| `numpy` | search | Vector math for the semantic-search tier — imported only when a Voyage API key is configured (see below) |

The capture tool degrades gracefully `trafilatura → bs4 → regex tag-strip`; a missing extractor is recorded in `extraction_note` in the result JSON. Semantic search needs both `numpy` and a Voyage API key — `VOYAGE_API_KEY` as an environment variable, or a `VOYAGE_API_KEY=...` line in `.user/config/env/.env` at the vault root (gitignored; a tracked `.env.example` documents it). Without the key, search runs keyword-only with zero API calls and `numpy` is never imported. The Voyage call uses the standard library — there is no `voyageai` package to install.

### Finance module

Used by the bookkeeper statement parsers, investment calculations, and price/market-data tools:

| Package | Role |
|---|---|
| `pdfplumber` | Text & table extraction from bank and broker statement PDFs |
| `pikepdf` | Decrypt / repair password-protected statement PDFs before parsing |
| `openpyxl` | Read `.xlsx` broker exports (B3, fixed-income products) |
| `scipy` | XIRR root-finding (`scipy.optimize.brentq`) in the IRR calculator |
| `yfinance` | Live market quotes in the price fetcher (lazy — only when live pricing is requested) |
| `requests` | HTTP for the price fetcher and the SEC filing-finder tool |
| `PyYAML` | Reads finance config — standing rules, field-ownership, and the doc-currency manifest |

Install both manifests from the repo root:

```bash
pip install -r finance/scripts/shared/requirements.txt -r finance/scripts/investimentos/requirements.txt
```

`finance/scripts/investimentos/requirements.txt` also lists `httpx` and `trafilatura` — the investor research flow shells out to the wiki capture tool above, so its environment needs that tool's libraries too.

## Install

```bash
git clone https://github.com/hlealt/sb-os.git
cd sb-os
python install.py
```

The installer is interactive. It will:

1. Walk upward from the current directory looking for an existing `sb-os.json`. If found, it offers to upgrade that install.
2. Otherwise prompt for a target vault path. Presence of `sb-os.json` at the target decides the mode — fresh install or upgrade.
3. **On a fresh install:** ask which optional modules to enable, show a dry-run preview before any writes, then bootstrap the vault and **relocate the running sb-os clone into `{target}/3-resources/tools/sb-os/`** as the final step. You don't end up with a stray repo elsewhere on disk.
4. **On an upgrade:** refresh `.claude/` loaders, rewrite marker-block content in managed CLAUDE.mds, refresh rule copies. It never creates new top-level folders and never touches content outside markers.

After install, open the vault in Obsidian, then in Claude Code run:

```
/sb-onboarder
```

The onboarder walks you through populating `2-areas/`, `1-projects/`, and (optionally) `3-resources/` based on how you actually work. It can build a `Home.md` dashboard with you and point you at the optional [RBTV](https://github.com/tecer-ai/rbtv) plugin. State persists in `sb-os.json` so you can pause and resume across sessions.

### Pre-install rollback tag (recommended)

```bash
cd /path/to/vault
git init && git add -A && git commit -m "pre-sb-os state"
git tag pre-sb-os-install
```

Rollback path is `git reset --hard pre-sb-os-install`. **Vaults without git have no rollback** — the installer will still run, but a bad install must be reversed by hand.

## Obsidian setup

Open Obsidian on the vault root and configure:

| Plugin | Setting | Value |
|---|---|---|
| Daily notes (core) | Folder | `0-periodic-notes/daily/` |
| Daily notes (core) | Date format | `YYYY-MM-DD` |
| Templates (core) | Template folder | `.user/config/templates/` |
| Unique note creator (core) | — | Disable. sb-os uses predictable paths. |
| [Calendar](https://github.com/liamcain/obsidian-calendar-plugin) (community) | — | Week/day navigation for periodic notes |
| [Dataview](https://github.com/blacksmithgu/obsidian-dataview) (community) | — | Required if you build a Home dashboard |
| [Templater](https://github.com/SilentVoid13/Templater) (community) | — | Required if you build a Home dashboard |

In **Settings → Files & Links**: set "Default location for new notes" to `Same folder as current file` (avoid vault root); set "Attachment folder path" to a dedicated assets folder (e.g., `3-resources/assets/`); leave "Use [[Wikilinks]]" enabled; set "New link format" to `Shortest path when possible` (REQUIRED — sb-os relies on filename-based wikilink resolution so pages remain linkable across folder reorganizations like wiki by-kind subdivision; without this, new wikilinks include path segments that break when pages move).

## Configurable paths

Two install paths persist in `sb-os.json` and resolve at runtime — never hardcoded.

| Field | Default | Purpose |
|---|---|---|
| `wiki_root` | `3-resources/knowledge-base/` | Wiki layer location. Created when the wiki module is selected. |
| `user_context_root` | `.user/context/` | Where workflows read per-step user-context YAML files. |

Edit `sb-os.json` directly to change either — every sb-os component reads them from the manifest.

The wiki also supports an optional `{wiki_root}/purpose.md` focus lens for `/sb-wiki-ingest` — start from [`wiki/workflows/shared/purpose-template.md`](./wiki/workflows/shared/purpose-template.md); full behavior in the installed `{wiki_root}/CLAUDE.md` § "Regulatory Layer — purpose.md".

## Customization model

Two principles govern what is yours and what is sb-os's:

1. **Marker-block content is sb-os's.** Inside `<!-- sb:start v=1 -->...<!-- sb:end -->`, the installer rewrites verbatim every run. Edit it and your changes are lost on the next run.
2. **Everything else is yours.** Content outside markers, your `.user/` folder, your `Home.md`, `.claude/settings.json` — never touched.

Thin loaders in `.claude/skills/` and `.claude/commands/`, and rule copies in `.claude/rules/sb-*.md`, are rewritten on every install. **Edit the source in this repo, not the installed copy.** Re-run `python install.py` after editing.

`.claude/settings.json` is user-managed. The installer never creates or modifies it. See [`docs/hooks.md`](./docs/hooks.md) for snippets to paste in.

### Your Home.md is yours

sb-os does not ship a canonical `Home.md` — no managed file, no marker block. It ships an idea doc describing what a home dashboard is for, what it could surface, and what to avoid. You (or `/sb-onboarder`) build the actual one. Start with [`ideas/home-dashboard.md`](./ideas/home-dashboard.md).

## Updating

```bash
cd /path/to/vault/3-resources/tools/sb-os
git pull
```

For workflow-content changes, that's enough — agents read directly from the source. Re-run `python install.py` only when:

- Adding or removing a module
- The component manifest, loader templates, or rule copies have changed in this repo

## Source of truth

Files in `.claude/skills/sb-*`, `.claude/commands/sb-*.md`, and `.claude/rules/sb-*.md` are regenerated on every install. **Do not edit them in your vault** — edit the source in this repo and re-install. The always-on `sb-source-of-truth` rule restates this every session.

## Retired components

Some components ship in this repo but carry `"stale": true` in `install/module-manifest.json`. The installer never installs or offers them, and an upgrade removes any previously-installed copy; the source files remain for reference and history. Revive one by removing its `stale` flag and re-running `python install.py`.

| Component | Module | Why retired |
|---|---|---|
| `sb-user-preferences` (rule) | core | Superseded by host CLAUDE.md prefs (cross-cutting) + per-workflow context-injection via `sb-workflow-context` (workflow-scoped). The always-on monolithic loader cost context on every turn for content most turns don't need. |

## Architecture notes

- **Thin loaders.** Skills and commands installed into `.claude/` are short files that point back to this repo via the path recorded in `sb-os.json`. No content duplication.
- **Rule exception.** Rule files are copied as content, not loaders, because rules load passively into Claude's context and indirection is unreliable.
- **Marker blocks.** Managed CLAUDE.mds use `<!-- sb:start v=1 -->...<!-- sb:end -->`. Content inside is rewritten on every install run; content outside is preserved verbatim.
- **Settings.json is user-managed.** The installer never creates or modifies `.claude/settings.json`. Hooks ship as snippets in [`docs/hooks.md`](./docs/hooks.md).
- **Wiki search is semantic-first when available, grep floor always.** Retrieval is tiered: with a Voyage key available (`VOYAGE_API_KEY` env var, or a `VOYAGE_API_KEY=...` line in `.user/config/env/.env` at the vault root — the standard home for local API keys, gitignored, with a tracked `.env.example` for new machines), `sb-wiki-search.py` gives agents hybrid semantic+keyword search over your wiki (local SQLite index, self-syncing, read-only) — and it runs on every `/sb-wiki-query` plus inside ingest (near-duplicate stub detection, topic-update and answer-scan candidates). Without a key it runs keyword-only with zero API calls; without the helper at all, everything falls back to leaf indexes + ripgrep — exactly the old behavior. The semantic tier is never a required dependency, never decides a mechanical rule's fire, and raw sources are always grep-only.
- **Templates are install-if-missing.** Periodic-note templates copy on fresh install and on upgrade only when the target file does not exist. Your customizations survive upgrades.

Detail and design rationale: [`docs/architecture.md`](./docs/architecture.md).

## Repository layout

Shippable components live under per-module folders at the repo root: `para/` (PARA-aligned components), `wiki/` (knowledge-base layer), and `finance/` (personal-finance system). Each module folder follows the same internal layout.

| Path | Contents |
|---|---|
| `install.py` | Entry point — interactive target detection, mode auto-detection, dispatch |
| `install/` | Installer internals (CLI, manifest, marker handling, mode handlers) |
| `para/commands/`, `para/skills/`, `para/rules/`, `para/workflows/` | PARA module sources for `sb-*` commands, skills, rules, workflows |
| `para/claude-mds/` | Managed CLAUDE.md sources for PARA structure (root, projects, areas, resources, archives, workbench) |
| `para/templates/` | Templates that ship to a vault on install (periodic notes, work-log, context, para subfolder seeds) |
| `para/ideas/` | Design notes for things sb-os ships an idea for, not a file (e.g., `home-dashboard.md`) |
| `para/docs/` | PARA-scoped reference docs (e.g., `obsidian-markdown/`) |
| `wiki/commands/`, `wiki/skills/`, `wiki/workflows/` | Wiki module sources for `sb-wiki-*` components |
| `wiki/workflows/shared/` | Cross-workflow conventions (folder structure, frontmatter schemas, citation format, etc.) |
| `wiki/claude-mds/wiki.md` | Managed CLAUDE.md source for `{wiki_root}/CLAUDE.md` |
| `wiki/scripts/` | Wiki tool layer (`sb-wiki-search.py`, lint + capture scripts) |
| `wiki/docs/wiki-schema.md` | Wiki schema reference |
| `finance/commands/`, `finance/skills/`, `finance/rules/`, `finance/workflows/` | Finance module sources for the bookkeeper/investor agents and companion workflows |
| `finance/scripts/`, `finance/dashboard/`, `finance/templates/` | Finance tool layer (+ registry `tools-index.md`), dashboard assets, install-if-missing policy templates |
| `finance/wiki-ext/` | Investment wiki extension data files (page types, schemas, lint rules) merged into the wiki when `finance` is registered |
| `docs/` | Repo-level architecture and conventions |

## License

MIT — see [`LICENSE`](./LICENSE).

## Contributing

Contributions welcome — issues and PRs both.

- Edit source files in this repo, never installed loaders or rule copies in a target vault.
- Behavior changes require updating [`docs/architecture.md`](./docs/architecture.md) first; the architecture doc is the spec.
- Workflow directories contain only step files, data, scripts, and templates — documentation lives in `docs/`.
- Adding, removing, or renaming a component? Update `install/module-manifest.json` to match, then re-run `python install.py`.

```bash
git clone https://github.com/hlealt/sb-os.git
cd sb-os
python install.py
```
