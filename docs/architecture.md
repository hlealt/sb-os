# sb-os Architecture

> This document describes the public architecture of sb-os. For project-internal planning history and design decisions, see the canonical planning document in the source repository.

Open-source architecture for **sb-os**, a PARA-based personal knowledge management system for Obsidian with native Claude Code agent integration.

---

## 1. Concept & Scope

**sb-os** = Second Brain Operating System. An opinionated structure plus an agent layer for knowledge work in Obsidian.

| Element | Decision |
|---------|----------|
| Methodology | PARA + Workbench ("extended PARA") |
| Editor target | Obsidian (any recent version) |
| Agent target | Claude Code (first-class), with portable component conventions |
| Language | English for sb-os system files (canonical repo and any installed instance); vault content language is your choice |
| License | MIT |
| Target user | PKM enthusiasts who use Obsidian and want AI-native workflows over their notes |
| Not a replacement for | Obsidian itself, Tiago Forte's "Building a Second Brain" book, or general task managers |

### What sb-os is

- A directory convention (PARA + Workbench + periodic notes + wiki slot + a config dir)
- A set of installable agent components (skills, commands, rules, sub-agents, workflows)
- An installer that bootstraps the structure into a fresh or existing folder
- A small documentation surface so users and agents share the same mental model

### What sb-os is NOT

- A vault template you copy and edit by hand
- A monolithic personal-everything system (financial automations, journals, etc. stay personal in your `.user/`)
- A dependency on any specific personal-tooling repo

---

## 2. Boundaries

sb-os defines what it owns and what it does not. The contract:

| Layer | Owner | Modified by sb-os? |
|-------|-------|-------------------|
| PARA folder skeleton | sb-os (created on `--fresh`) | Created once; never recreated |
| Managed CLAUDE.mds — content inside markers | sb-os | Rewritten on every `--upgrade` |
| Managed CLAUDE.mds — content outside markers | User | Never touched |
| `.claude/skills/`, `.claude/commands/` (thin loaders) | sb-os | Rewritten on every install |
| `.claude/rules/sb-*.md` | sb-os | Rewritten on every install |
| `.claude/settings.json` | User | **Never** created or modified |
| `sb-os.json` (manifest) | sb-os | Updated each run |
| `.user/` and contents | User | Created on `--fresh`; never written into thereafter |
| User content anywhere in the vault | User | Never touched |

The contract: **sb-os only modifies what sb-os created**, with the marker-block exception.

---

## 3. Installed Vault Shape

What a vault looks like after `python install.py --fresh`:

```
{vault-root}/
├── 0-periodic-notes/
│   ├── daily/
│   ├── weekly/
│   ├── monthly/
│   └── quarterly/
├── 1-projects/
│   └── CLAUDE.md          [managed]
├── 2-areas/
│   └── CLAUDE.md          [managed]
├── 3-resources/
│   └── CLAUDE.md          [managed]
├── 4-archives/
│   └── CLAUDE.md          [managed]
├── 5-workbench/
│   └── CLAUDE.md          [managed]
├── {wiki_root}/           [optional, default: 3-resources/knowledge-base/]
│   └── CLAUDE.md          [managed, conditional]
├── .user/                 [user-owned; sb-os creates the dir on --fresh and never writes inside it thereafter]
│   ├── {user_context_root}/  [configurable path, default `.user/context/`]
│   └── ...                [user's personal extensions — scripts, configs, anything]
├── .claude/
│   ├── skills/            [thin loaders pointing to sb-os repo]
│   ├── commands/          [thin loaders]
│   ├── rules/             [copies of sb-* rules]
│   └── settings.json      [user-managed; sb-os never creates or modifies]
├── sb-os.json             [install manifest at vault root]
├── CLAUDE.md              [managed; markers protect SB section]
└── Home.md                [scaffolding inside sb:start/sb:end markers; refreshed on --upgrade, user content outside preserved]
```

### Notes

- **No legacy `_system/` shipped.** sb-os does not create or touch any `_system/` folder. If a user keeps one for personal scripts and tooling, it is user-owned and untouched.
- **`.user/`** is the user-owned root — holds the user-context folder (read by sb-os at the path declared in `sb-os.json` → `user_context_root`, default `.user/context/`) plus any personal extensions. sb-os creates the `.user/` directory on `--fresh` install (so the configured user-context path resolves), but never writes inside `.user/` thereafter — the configured user-context path is the only sb-os-readable subpath.
- **User-context path is configurable.** The installer prompts for `user_context_root` (default `.user/context/`) and persists the chosen path in `sb-os.json`. All sb-os components that read user context resolve through this manifest field — the path is never hardcoded.
- **`sb-os.json`** at vault root is the sb-os-managed install manifest.
- **`.claude/settings.json`** is user-managed. sb-os never creates or modifies it. Hooks (if any) are distributed as documented snippets in `docs/hooks.md` that users add manually.
- **`Home.md`** uses the same marker pattern as managed CLAUDE.mds. Scaffolding inside `<!-- sb:start v=1 -->...<!-- sb:end -->` is refreshed on `--upgrade`; user content outside the markers is preserved verbatim.

---

## 4. sb-os Repo Layout

```
sb-os/
├── install.py              [entry point]
├── admin/
│   └── install/            [installer internals: cli.py, manifest.py, markers.py, ...]
├── workflows/              [source of truth for sb-* workflows]
│   └── sb-{name}/
│       ├── sb-{name}.md
│       ├── step-NN-*.md
│       └── data/, scripts/, templates/
├── templates/              [source of truth for templates]
├── skills/                 [source files for sb-* skill loaders]
├── commands/               [source files for sb-* command loaders]
├── rules/                  [sb-* rule files, copied verbatim into .claude/rules/]
├── claude-mds/             [source files for managed CLAUDE.mds; filename encodes install destination]
├── dashboards/             [source files for marker-managed dashboard scaffolds (e.g., Home.md); filename encodes install destination]
├── docs/                   [architecture, conventions, user-facing docs]
├── CLAUDE.md               [repo's own agent context]
├── README.md
├── LICENSE                 [MIT]
└── .gitignore
```

### Loader pattern

Skills and commands installed into `.claude/` are **thin loaders** that point back to `sb-os` source files. Editing installed loaders is forbidden — the source is the repo. Re-running the installer regenerates loaders.

Rules are **copied verbatim** from `sb-os/rules/` to `.claude/rules/` because Claude Code auto-loads rules from that path natively.

### Managed CLAUDE.md sources

Source files in `claude-mds/` are named for their install destination. The installer reads each file, replaces marker-block content (per §6 marker block protocol), and writes to the mapped path:

| Source file | Install destination |
|-------------|---------------------|
| `claude-mds/root.md` | `{vault}/CLAUDE.md` |
| `claude-mds/projects.md` | `{vault}/1-projects/CLAUDE.md` |
| `claude-mds/areas.md` | `{vault}/2-areas/CLAUDE.md` |
| `claude-mds/resources.md` | `{vault}/3-resources/CLAUDE.md` |
| `claude-mds/archives.md` | `{vault}/4-archives/CLAUDE.md` |
| `claude-mds/workbench.md` | `{vault}/5-workbench/CLAUDE.md` |
| `claude-mds/wiki.md` | `{vault}/{wiki_root}/CLAUDE.md` (conditional on wiki feature) |

Editing the installed file directly is forbidden — the source is the repo. Re-running the installer regenerates the marker-block content from the source.

### Marker-managed dashboard sources

Source files in `dashboards/` are named for their install destination. Same install semantics as `claude-mds/` — the installer reads each file, replaces marker-block content, writes to the mapped path:

| Source file | Install destination |
|-------------|---------------------|
| `dashboards/home.md` | `{vault}/Home.md` (marker-managed per §3) |

---

## 5. Component Inventory (v1)

### Skills

| Skill | Purpose |
|-------|---------|
| `sb-vault-ops` | Gatekeeper for vault content and component modifications |
| `sb-vault-integrity` | Post-operation structural sweep after file moves/renames/deletes |

### Commands

| Command | Purpose |
|---------|---------|
| `/sb-archivist` | Knowledge-base ingestion and routing |
| `/sb-tutor` | Tutor persona for guided learning sessions |
| `/sb-inject-context` | Manual context injection helper |

### Rules (auto-loaded)

| Rule | Purpose |
|------|---------|
| `sb-obsidian-markdown.md` | Obsidian-flavored markdown reference |
| `sb-user-preferences.md` | Loads `.user/preferences.md` if present |
| `sb-workflow-context.md` | YAML context injection on workflow steps |
| `sb-sub-agents.md` | Mandatory skill directives in Agent dispatches |

---

## 6. Install Flow

### Modes

| Flag | Behavior |
|------|----------|
| `--fresh` | Bootstrap a clean vault: create PARA folders, root `CLAUDE.md`, all managed CLAUDE.mds, install thin loaders, ship `Home.md`, optionally create `{wiki_root}/`. |
| `--upgrade` | Update an existing sb-os install: rewrite `.claude/` loaders, replace marker blocks in managed CLAUDE.mds and `Home.md`, refresh rules. **Never** create new top-level folders or modify user-edited content outside markers. **Default mode** when `sb-os.json` is found at the vault root. |
| `--dry-run` | Print every planned action without executing. Combinable with the above. |

### Mode detection

If `sb-os.json` exists at vault root → default to `--upgrade`.
Otherwise → default to `--fresh`. User can override either way.

### Installer interactivity

The installer is interactive: it prompts before any vault-modifying action and shows a planned-action list. v1 ships without a separate module system — the component count is small enough to ship one bundle by default. Users may opt out of any individual component during the install prompts.

### Out of v1 scope

- `--integrate` (interactive merge into a non-sb-os existing PARA-like structure). README recommends manual setup if the vault has pre-existing PARA folders.
- Backup and rollback flags. Users should `git tag` before running the installer; rollback is `git reset` to that tag.

### Manifest schema (`sb-os.json`)

```json
{
  "version": "0.1.0",
  "installed_at": "2026-05-01T12:00:00Z",
  "mode": "fresh",
  "wiki_root": "3-resources/knowledge-base/",
  "user_context_root": ".user/context/",
  "created_paths": [
    "0-periodic-notes/",
    "1-projects/",
    "2-areas/",
    "3-resources/",
    "4-archives/",
    "5-workbench/",
    "Home.md",
    "CLAUDE.md"
  ]
}
```

The manifest tracks **what the installer created**, not file hashes. With thin loaders + marker blocks + one-shot files, no checksumming is needed.

### Marker block protocol

Every managed CLAUDE.md and the shipped `Home.md` use HTML-comment markers:

```markdown
<!-- sb:start v=1 -->
[managed content — replaced verbatim on --upgrade]
<!-- sb:end -->
```

- `--upgrade` replaces content **between markers** verbatim.
- Content **outside markers** is user-owned and preserved.
- If markers are missing on `--upgrade` (user removed them), installer aborts with a clear error and instructions.
- The `v=1` marker version allows future migration if marker syntax changes.

---

## 7. Managed CLAUDE.md Files

Vault (7 files):

1. `CLAUDE.md` (root)
2. `1-projects/CLAUDE.md`
3. `2-areas/CLAUDE.md`
4. `3-resources/CLAUDE.md`
5. `4-archives/CLAUDE.md`
6. `5-workbench/CLAUDE.md`
7. `{wiki_root}/CLAUDE.md` *(conditional on wiki feature)*

Plus the **sb-os repo's own root `CLAUDE.md`** — agent context for anyone working in the sb-os codebase.

`Home.md` uses the same marker pattern (per §3, §6) but is not a CLAUDE.md.

### Convention

| Item | Rule |
|------|------|
| Markers | Mandatory in every managed CLAUDE.md and in `Home.md` |
| Subfolder CLAUDE.mds (e.g., `2-areas/health/CLAUDE.md`) | User-owned. sb-os never creates, never touches. |
| Any other CLAUDE.md outside the managed set | User-owned; sb-os never creates and never touches. |

Contents of each managed CLAUDE.md are defined in the source files under `sb-os/claude-mds/`.

---

## 8. Customization & Override Model

| Layer | Owned by | Behavior on `--upgrade` |
|-------|----------|-------------------------|
| Folders created on `--fresh` | sb-os | Never recreated; user can delete/rename freely |
| `Home.md` content **inside markers** | sb-os | Replaced verbatim |
| `Home.md` content **outside markers** | User | Preserved |
| Managed CLAUDE.md content **inside markers** | sb-os | Replaced verbatim |
| Managed CLAUDE.md content **outside markers** | User | Preserved |
| `.claude/` thin loaders | sb-os | Always rewritten |
| `.claude/rules/` files | sb-os | Always rewritten |
| `.claude/settings.json` | User | sb-os never creates or modifies |
| `sb-os.json` | sb-os | Updated each run |
| `{user_context_root}/*.yaml` (default `.user/context/`) | User | Read by sb-os; never written |
| `.user/` (other contents) | User | Never touched |
| User-created files anywhere | User | Never touched |

The contract: **sb-os only modifies what sb-os created**, with the marker-block exception.

---

## 9. Plugin Dependencies

| Plugin | Status | Reason |
|--------|--------|--------|
| Dataview | Soft requirement, recommended | Powers `Home.md` task aggregation and dashboards |
| Tasks | Soft requirement, recommended | Date parsing for 📅, ✅, 🔁 emoji |

`Home.md` degrades gracefully if either is missing (static content replaces queries with a "missing plugin" notice). README recommends installing both for full experience.

No other Obsidian plugins required.

---

## 10. Out of Scope / v2

| Item | Reason |
|------|--------|
| Wiki contents and schema | v1 ships only the config slot (`wiki_root`), the empty default folder, and a placeholder managed CLAUDE.md. The wiki feature itself ships in v2. |
| `sb-onboarding` skill | Interactive PARA bootstrap deferred to v2; v1 ships static structure only. |
| Generic life-planner workflow | Generalization deferred to v2; v1 leaves life-planner as a personal-only workflow that lives in a user's `.user/` if they want one. |
| `subagents/` source folder | No v1 sub-agents to ship; folder reintroduced in v2 with the first sb-* sub-agent. |
| Hooks that auto-write `.claude/settings.json` | Hook snippets ship as docs (`docs/hooks.md`); users add manually. Auto-write deferred indefinitely (settings.json is user-managed per §8). |
| Personal-only workflows (financial, therapy, journaling) | Stay in user's `.user/`, not part of sb-os. |
| `--integrate` install mode | Deferred until real users hit non-sb-os PARA-like folders and request it. |
| Automatic backup / rollback flags | Deferred. `git tag` covers rollback for v1. |
| Cross-vault sync, multi-vault management | Out of scope. |
| Non-Claude-Code agent harnesses | Components are written portable where possible, but Claude Code is the only validated target. |

---

## 11. License

MIT. See `LICENSE` at the repo root.
