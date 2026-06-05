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
| PARA folder skeleton | sb-os (created on the initial install) | Created once; never recreated |
| Managed CLAUDE.mds — content inside markers | sb-os | Rewritten on every install run |
| Managed CLAUDE.mds — content outside markers | User | Never touched |
| `.claude/skills/`, `.claude/commands/` (thin loaders) | sb-os | Rewritten on every install |
| `.claude/rules/sb-*.md` | sb-os | Rewritten on every install |
| `.claude/settings.json` | User | **Never** created or modified |
| `sb-os.json` (manifest) | sb-os | Updated each run |
| `.user/` and contents | User | Created on the initial install; never written into thereafter |
| User content anywhere in the vault | User | Never touched |

The contract: **sb-os only modifies what sb-os created**, with the marker-block exception.

---

## 3. Installed Vault Shape

What a vault looks like after a fresh `python install.py`:

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
├── .user/                 [user-owned; sb-os creates the dir on the initial install and never writes inside it thereafter]
│   ├── {user_context_root}/  [configurable path, default `.user/context/`]
│   └── ...                [user's personal extensions — scripts, configs, anything]
├── .claude/
│   ├── skills/            [thin loaders pointing to sb-os repo]
│   ├── commands/          [thin loaders]
│   ├── rules/             [copies of sb-* rules]
│   └── settings.json      [user-managed; sb-os never creates or modifies]
├── sb-os.json             [install manifest at vault root]
└── CLAUDE.md              [managed; markers protect SB section]
```

### Notes

- **No legacy `_system/` shipped.** sb-os does not create or touch any `_system/` folder. If a user keeps one for personal scripts and tooling, it is user-owned and untouched.
- **`.user/`** is the user-owned root — holds the user-context folder (read by sb-os at the path declared in `sb-os.json` → `user_context_root`, default `.user/context/`) plus any personal extensions. sb-os creates the `.user/` directory on the initial fresh install (so the configured user-context path resolves), but never overwrites files inside `.user/` thereafter. **Single carve-out:** templates declared in the module manifest are installed at their manifest-declared targets inside `.user/` using **install-if-missing** semantics — the file is written only when the target path does not exist. Core periodic-note templates land under `.user/config/templates/`; the finance module's investor policy skeletons land at their live policy paths `.user/finance/investor/{source-policy,research-policy}.md` (the skeleton IS the bootstrapped file — structure ships, content is the user's). User edits to an installed template survive every subsequent install run. New templates added to sb-os in later versions are bootstrapped on the next install (because the target does not exist yet); previously-installed templates are never touched.
- **User-context path is configurable.** The installer prompts for `user_context_root` (default `.user/context/`) and persists the chosen path in `sb-os.json`. All sb-os components that read user context resolve through this manifest field — the path is never hardcoded.
- **`sb-os.json`** at vault root is the sb-os-managed install manifest.
- **`.claude/settings.json`** is user-managed. sb-os never creates or modifies it. Hooks (if any) are distributed as documented snippets in `docs/hooks.md` that users add manually.

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
├── docs/                   [architecture, conventions, user-facing docs]
├── ideas/                  [user-facing intent docs (e.g., home-dashboard.md); not installed]
├── CLAUDE.md               [repo's own agent context]
├── README.md
├── LICENSE                 [MIT]
└── .gitignore
```

### Loader pattern

Skills and commands installed into `.claude/` are **thin loaders** that point back to `sb-os` source files. Editing installed loaders is forbidden — the source is the repo. Re-running the installer regenerates loaders.

Rules are **copied verbatim** from a module's `rules/` folder (`sb-os/{module}/rules/`, where `{module}` is `para` or `wiki`) to `.claude/rules/` because Claude Code auto-loads rules from that path natively.

### Module Layout

Shippable components live under one of two module folders at the repo root: `para/` (PARA-aligned components — vault structure, periodic-notes templates, life planner, tutor) and `wiki/` (knowledge-base layer). Each module folder follows the same internal layout: `commands/`, `rules/`, `skills/`, `workflows/`, `claude-mds/`, optional `docs/`, and (for `para/`) `templates/`. The manifest's `module` field on each component encodes which folder owns its source.

### Managed CLAUDE.md sources

Source files live under each module's `claude-mds/` folder, named for their install destination. The installer reads each file, replaces marker-block content (per §6 marker block protocol), and writes to the mapped path:

| Source file | Install destination |
|-------------|---------------------|
| `para/claude-mds/root.md` | `{vault}/CLAUDE.md` |
| `para/claude-mds/projects.md` | `{vault}/1-projects/CLAUDE.md` |
| `para/claude-mds/areas.md` | `{vault}/2-areas/CLAUDE.md` |
| `para/claude-mds/resources.md` | `{vault}/3-resources/CLAUDE.md` |
| `para/claude-mds/archives.md` | `{vault}/4-archives/CLAUDE.md` |
| `para/claude-mds/workbench.md` | `{vault}/5-workbench/CLAUDE.md` |
| `wiki/claude-mds/wiki.md` | `{vault}/{wiki_root}/CLAUDE.md` (conditional on wiki feature) |

Editing the installed file directly is forbidden — the source is the repo. Re-running the installer regenerates the marker-block content from the source.

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
| `/sb-archivist` | Rolling per-day session work-log (decisions, refinements, discoveries, files touched); on fresh-session runs, sweeps done tasks from task files into date-correct work logs |
| `/sb-tutor` | Tutor persona for guided learning sessions |
| `/sb-inject-context` | Manual context injection helper |
| `/sb-onboarder` | Post-install interactive onboarding — orient the user, populate PARA, optionally build Home, optionally point at RBTV |

### Rules (auto-loaded)

| Rule | Purpose |
|------|---------|
| `sb-obsidian-markdown.md` | Obsidian-flavored markdown reference |
| ~~`sb-user-preferences.md`~~ | **Retired (stale).** Loaded `.user/profile/preferences.md` — superseded by host CLAUDE.md prefs + per-workflow context-injection |
| `sb-workflow-context.md` | YAML context injection on workflow steps |
| `sb-sub-agents.md` | Mandatory skill directives in Agent dispatches |

`sb-source-of-truth.md` (the edit-source-not-installed-copies reminder) is also **retired (stale)** — its principle is documented in the managed CLAUDE.md and the README. Retired rules carry `"stale": true` in `module-manifest.json`; see §6 "Stale components".

---

## 6. Install Flow

### Modes

| Detected | Mode | Behavior |
|----------|------|----------|
| No `sb-os.json` at the resolved target | Fresh | Bootstrap a clean vault: create PARA folders, root `CLAUDE.md`, all managed CLAUDE.mds, install thin loaders, optionally create `{wiki_root}/`, render the finance dashboard entry HTML (finance module selected — see Finance dashboard entry HTML below), write the initial manifest, then relocate the running sb-os clone into `{target}/3-resources/tools/sb-os/`. |
| `sb-os.json` present | Upgrade | Refresh an existing install: rewrite `.claude/` loaders, replace marker blocks in managed CLAUDE.mds, refresh rules, install missing install-if-missing artifacts (user templates, finance dashboard entry HTML). **Never** creates new top-level folders or modifies user-edited content outside markers. |

### Mode detection

The installer walks upward from cwd looking for `sb-os.json`. If found, it offers to upgrade that install. Otherwise it prompts for a target vault path; if the typed path holds an `sb-os.json` it runs upgrade, otherwise fresh. Flags: `--target PATH` skips the upward search and resolves mode directly against that path; `--modules a,b` pins the module selection without the interactive picker; `--non-interactive` reuses the prior selection from `sb-os.json` and skips every prompt.

### Installer interactivity

The installer prompts before any vault-modifying action and shows a planned-action list. Under `--non-interactive` the planned-action list still prints, but every prompt — including the final proceed confirm in both fresh and upgrade modes — is skipped. On a fresh install it offers a dry-run preview before any writes. v1 ships without a separate module system — the component count is small enough to ship one bundle by default; defaults are baked, advanced overrides live in `sb-os.json` and can be edited after install.

### Stale components

A component entry in `module-manifest.json` may carry `"stale": true` (with an optional `"stale_reason"`). Stale components are retired: the installer never installs them, never surfaces them in the interactive picker, and an upgrade run removes any previously-installed copy. Their source files remain in the repo for reference and history. Reviving one is a manifest edit (remove the flag) plus a re-install. Staleness is enforced at a single chokepoint (`loaders._flatten`), so every reader — fresh install, upgrade, orphan-cleanup, and tests — treats stale entries identically.

### Orphaned loaders

Renaming or removing a component in `module-manifest.json` leaves the previously-installed loader behind — no manifest entry remains to match it against, so selection-aware cleanup cannot see it. An upgrade run closes this gap: it scans the vault's installed loaders (`.claude/commands/*.md`, `.claude/skills/*/SKILL.md`) and deletes any loader that (a) is sb-os-shaped — its `Read and execute` directive resolves into the install's `sb_os_path` — and (b) has no `target` entry anywhere in the manifest (stale entries count as known). Loaders pointing anywhere else (user, RBTV, personal) are never touched. Targets listed in `excluded_components` are never deleted — exclusion is an explicit user signal. Planned deletions appear in the upgrade plan before the confirm prompt.

### Out of v1 scope

- `integrate` mode (interactive merge into a non-sb-os existing PARA-like structure). README recommends manual setup if the vault has pre-existing PARA folders.
- Backup and rollback. Users should `git tag` before running the installer; rollback is `git reset` to that tag.

### Post-install onboarding

`install.py` handles structural setup only — folders, managed CLAUDE.mds, thin loaders, manifest. It does **not** populate user content (areas, projects, resources). That work happens in Claude Code via `/sb-onboarder`, which is an interactive workflow shipped under the `core` module and registered in `module-manifest.json`.

The onboarder is resumable. State persists in `sb-os.json` under the `onboarder_state` key (started_at, last_step, completed_steps, domains_proposed, areas_created, projects_created, resources_surfaced, home_built, rbtv_marketed, completed_at). The installer's manifest module preserves unknown keys verbatim across upgrades, so onboarder state survives `--upgrade` runs without any installer code path dedicated to it.

The onboarder NEVER writes inside `.user/` — `.user/` is user-owned per §2 boundaries. State lives in `sb-os.json` (sb-os-owned, vault root). All vault writes (folders, indexes, tasks files — created only for areas/projects with tasks elicited during onboarding, per the tasks-file-optional convention — optional `Home.md`, optional CLAUDE.md routing-rule appends) go through the `sb-vault-ops` skill and are followed by a `sb-vault-integrity` post-op sweep.

### Finance dashboard entry HTML

When the finance module is selected, the installer renders
`finance/dashboard/dashboard.html.template` to the vault (`install/finance.py`).
The rendered page is the only finance artifact whose content is
install-specific, so it cannot ship verbatim:

- **Asset base substitution.** The template's `{{DASHBOARD_ASSET_BASE}}`
  placeholder becomes `/{sb_os_path}/finance/dashboard` — vault-root-absolute,
  derived from the install's `sb_os_path` (the dashboard server serves the
  vault root as docroot; there is no `/sb-os/` route alias).
- **Data paths are NOT rendered.** Data fetches are fixed vault-root-absolute
  at `/.user/finance/bookkeeper/{ledgers,config}/...`, hardcoded in the
  dashboard JS (`shared.js` `FIN_DATA_BASE`) per the finance module's
  fixed-data-paths contract. Identical for every install — nothing to render.
- **One knob.** The destination, `finance_dashboard_html_path`, is prompted on
  interactive fresh installs (default `.user/finance/dashboard.html`) and
  persisted in `sb-os.json`. This is the single carve-out to the never-write-
  inside-`.user/` rule beyond templates: the entry HTML uses the same
  install-if-missing semantics — rendered when absent, never overwritten.
- **Upgrade.** Reuses the persisted `finance_dashboard_html_path` (back-filling
  the field with the default on manifests predating it) and renders only when
  the file is missing.

The render is wired in `fresh.py`/`upgrade.py` gated on module selection — it
is not a `module-manifest.json` entry, because manifest templates copy
verbatim to a fixed target while this artifact needs substitution and a
configurable destination.

### Manifest schema (`sb-os.json`)

```json
{
  "version": "0.2.0",
  "installed_at": "2026-05-01T12:00:00Z",
  "mode": "fresh",
  "wiki_root": "3-resources/knowledge-base/",
  "user_context_root": ".user/context/",
  "sb_os_path": "3-resources/tools/sb-os/",
  "finance_dashboard_html_path": ".user/finance/dashboard.html",
  "selected_modules": ["core", "wiki"],
  "excluded_components": [],
  "created_paths": [
    "0-periodic-notes/",
    "1-projects/",
    "2-areas/",
    "3-resources/",
    "4-archives/",
    "5-workbench/",
    "CLAUDE.md"
  ]
}
```

`finance_dashboard_html_path` is present only when the finance module is
selected; an upgrade never overwrites an existing value (same back-fill-only
rule as `sb_os_path`).

The manifest tracks **what the installer created**, not file hashes. With thin loaders + marker blocks + one-shot files, no checksumming is needed.

Components MAY add their own top-level keys to the manifest (e.g., `onboarder_state` written by `/sb-onboarder`). The installer preserves unknown keys verbatim on upgrade — components own their state without coupling to installer code.

### Marker block protocol

Every managed CLAUDE.md uses HTML-comment markers:

```markdown
<!-- sb:start v=1 -->
[managed content — replaced verbatim on every install run]
<!-- sb:end -->
```

- An upgrade run replaces content **between markers** verbatim.
- Content **outside markers** is user-owned and preserved.
- If markers are missing during an upgrade (user removed them), the installer aborts with a clear error and instructions.
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

### Convention

| Item | Rule |
|------|------|
| Markers | Mandatory in every managed CLAUDE.md |
| Subfolder CLAUDE.mds (e.g., `2-areas/health/CLAUDE.md`) | User-owned. sb-os never creates, never touches. |
| Any other CLAUDE.md outside the managed set | User-owned; sb-os never creates and never touches. |

Contents of each managed CLAUDE.md are defined in the source files under `sb-os/claude-mds/`.

---

## 8. Customization & Override Model

| Layer | Owned by | Behavior on upgrade run |
|-------|----------|-------------------------|
| Folders created on the initial fresh install | sb-os | Never recreated; user can delete/rename freely |
| Managed CLAUDE.md content **inside markers** | sb-os | Replaced verbatim |
| Managed CLAUDE.md content **outside markers** | User | Preserved |
| `.claude/` thin loaders | sb-os | Always rewritten; sb-os-shaped loaders with no manifest entry are deleted (orphan pruning, §6) |
| `.claude/rules/` files | sb-os | Always rewritten |
| `.claude/settings.json` | User | sb-os never creates or modifies |
| `sb-os.json` | sb-os | Updated each run |
| `{user_context_root}/*.yaml` (default `.user/context/`) | User | Read by sb-os; never written |
| `.user/` (other contents) | User | Never touched |
| User-created files anywhere | User | Never touched |

The contract: **sb-os only modifies what sb-os created**, with the marker-block exception.

---

## 9. Plugin Dependencies

No Obsidian plugins are required by sb-os. Users who build their own `Home.md` per `ideas/home-dashboard.md` may opt into Dataview and Tasks to power user-built dashboards; sb-os ships intent, not implementation.

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
| `integrate` install mode | Deferred until real users hit non-sb-os PARA-like folders and request it. |
| Automatic backup / rollback | Deferred. `git tag` covers rollback for v1. |
| Cross-vault sync, multi-vault management | Out of scope. |
| Non-Claude-Code agent harnesses | Components are written portable where possible, but Claude Code is the only validated target. |

---

## 11. Behavior Changes

| Version | Module | Change |
|---------|--------|--------|
| wiki v4 | `wiki` | `/sb-wiki-ingest` gains an optional `{wiki_root}/purpose.md` regulatory-layer focus lens (Step 0.5). When present, the lens modulates discretionary synthesis surfaces (depth, optional sections, stub bias, topic ranking, Stage-1 classification). When absent, ingest is identical to today. Schema canonical reference: `wiki/docs/wiki-schema.md`. |
| wiki v5 | `wiki` | Questions layer: a dedicated `{wiki_root}/questions.md` (queue-style user agenda) + answer-scan wired into both `/sb-wiki-ingest` (active `PROPOSED ANSWERS` block at Stage-1, covering both homes) and `/sb-wiki-lint` (periodic sweep, graduation proposals, prune). Two-homes model: topic `Open questions` stay on topic pages; `questions.md` is the user's agenda only. No-op when `questions.md` is absent — ingest/lint identical to today. Silent-mode change: `/sb-wiki-ingest silent` now applies FIRM topic updates (append-only) and audits each to the silent-summary `Flags` channel; rejects speculative updates and proposed answers and audits each the same way (NOT to `log.md` — its `topic-updated` type is retired and the applied page is its own durable record); counts surface in the `ingest-all` report. Schema canonical reference: `wiki/docs/wiki-schema.md` v5 (questions-layer). |
| v0.2.0 | `core` | `module-manifest.json` gains a `"stale"` component flag (+ optional `"stale_reason"`), enforced at `loaders._flatten`. Stale components are never installed or surfaced and are removed on upgrade; sources are preserved. Rules `sb-source-of-truth` and `sb-user-preferences` retired as stale — source-of-truth's principle lives in the managed CLAUDE.md + README; preference loading moves to host CLAUDE.md (cross-cutting) and per-workflow context-injection (workflow-scoped). |
| v0.2.0 | `finance` | Installer renders the finance dashboard entry HTML (p1-3/p1-13): `finance/dashboard/dashboard.html.template` → `finance_dashboard_html_path` (prompted on fresh, default `.user/finance/dashboard.html`, persisted in `sb-os.json`, install-if-missing on upgrade). Asset URLs substituted vault-root-absolute from `sb_os_path` via `{{DASHBOARD_ASSET_BASE}}`; data fetches fixed vault-root-absolute at `/.user/finance/bookkeeper/...` via `shared.js` `FIN_DATA_BASE`. See §6 Finance dashboard entry HTML. |
| v0.2.0 | `finance` | Investor policy bootstrap: the finance module ships user-agnostic policy skeletons `finance/templates/{source-policy,research-policy}.md`, installed via the standard manifest-template mechanism to `.user/finance/investor/{source-policy,research-policy}.md` (install-if-missing — fresh installs bootstrap the §3-carve-out structure with `_Fill in_` slots; upgrade never overwrites; personal rows never ship). `research.md` Step 3 item 4's seed-rubric fallback remains the unfilled-policy degradation. |

---

## 12. License

MIT. See `LICENSE` at the repo root.
