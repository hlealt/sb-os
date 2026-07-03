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
| `.claude/settings.local.json` | User + sb-os | sb-os auto-wires the context-injection hook (sentinel `__sb__: sb:context-injection`); opt-out via `excluded_components: ["context-injection-hook"]`. Rest of the file is user-owned and preserved |
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
│   ├── settings.json      [user-managed; sb-os never creates or modifies]
│   └── settings.local.json [sb-os auto-wires the context-injection hook here]
├── sb-os.json             [install manifest at vault root]
└── CLAUDE.md              [managed; markers protect SB section]
```

### Notes

- **No legacy `_system/` shipped.** sb-os does not create or touch any `_system/` folder. If a user keeps one for personal scripts and tooling, it is user-owned and untouched.
- **`.user/`** is the user-owned root — holds the user-context folder (read by sb-os at the path declared in `sb-os.json` → `user_context_root`, default `.user/context/`) plus any personal extensions. sb-os creates the `.user/` directory on the initial fresh install (so the configured user-context path resolves), but never overwrites files inside `.user/` thereafter. **Single carve-out:** templates declared in the module manifest are installed at their manifest-declared targets inside `.user/` using **install-if-missing** semantics — the file is written only when the target path does not exist. Core periodic-note templates land under `.user/config/templates/`; the finance module's investor policy skeletons land at their live policy paths `.user/finance/investor/{source-policy,research-policy}.md` (the skeleton IS the bootstrapped file — structure ships, content is the user's). User edits to an installed template survive every subsequent install run. New templates added to sb-os in later versions are bootstrapped on the next install (because the target does not exist yet); previously-installed templates are never touched.
- **User-context path is configurable.** The installer prompts for `user_context_root` (default `.user/context/`) and persists the chosen path in `sb-os.json`. All sb-os components that read user context resolve through this manifest field — the path is never hardcoded.
- **`sb-os.json`** at vault root is the sb-os-managed install manifest.
- **`.claude/settings.json`** is user-managed. sb-os never creates or modifies it.
- **`.claude/settings.local.json`** — the installer AUTO-WIRES the context-injection hook here (sentinel `"__sb__": "sb:context-injection"`; two entries — PreToolUse/Skill + PostToolUse/Read — calling `resolve_context.py --hook`). Opt out via `excluded_components: ["context-injection-hook"]`. The rest of the file is user-owned and preserved. All OTHER hooks are distributed as documented snippets in `docs/hooks.md` that users add manually.

---

## 4. sb-os Repo Layout

```
sb-os/
├── install.py              [entry point]
├── install/                [installer internals: cli.py, manifest.py, markers.py, module-manifest.json, mode handlers]
├── para/                   [PARA module — vault structure, periodic notes, life planner]
│   ├── commands/           [sb-* command loader sources]
│   ├── rules/              [sb-* rule files, copied verbatim into .claude/rules/]
│   ├── skills/             [sb-* skill loader sources]
│   ├── workflows/          [sb-{name}/ step files + data, scripts, templates]
│   ├── claude-mds/         [managed CLAUDE.md sources for PARA structure]
│   ├── templates/          [periodic-notes, work-log, context, subfolder seeds]
│   ├── ideas/              [user-facing intent docs (e.g., home-dashboard.md); not installed]
│   └── docs/               [PARA-scoped reference docs, e.g. obsidian-markdown/]
├── wiki/                   [wiki module — ingest/query/lint/tutor; mirrors the module layout]
│   ├── claude-mds/wiki.md  [managed CLAUDE.md source for {wiki_root}/CLAUDE.md]
│   ├── scripts/            [wiki tool layer: sb-wiki-search.py, lint + capture scripts]
│   └── docs/wiki-schema.md [wiki schema reference]
├── finance/                [finance module — bookkeeper/investor agents, companions, dashboard]
│   ├── scripts/            [finance tool layer + registry tools-index.md]
│   ├── wiki-ext/           [investment wiki extension data files]
│   ├── dashboard/          [finance dashboard assets]
│   └── ...                 [commands/, rules/, skills/, workflows/, templates/, docs/ mirror the module layout]
├── docs/                   [repo-level architecture, conventions, hooks reference]
├── hooks/                  [git hooks shipped for manual activation (pre-commit-doc-currency)]
├── CLAUDE.md               [repo's own agent context]
├── README.md
├── LICENSE                 [MIT]
└── .gitignore
```

### Loader pattern

Skills and commands installed into `.claude/` are **thin loaders** that point back to `sb-os` source files. Editing installed loaders is forbidden — the source is the repo. Re-running the installer regenerates loaders.

A **skill or command** loader's `description:` frontmatter is read from that component's own source frontmatter (`{module}/skills/<name>/SKILL.md` or `{module}/commands/<name>.md`) at install time, **never** from `module-manifest.json`. The manifest carries no skill or command descriptions — only **rules and modules** keep a manifest `description`. A component's description thus has one source of truth (its own file), so editing it there propagates on the next install with no manifest sync; a component whose source lacks a description triggers an installer warning rather than shipping a stale or blank loader. Descriptions are emitted YAML-safe (single-quoted when they contain a colon or other indicator). The same `{component}/<name>` source frontmatter is what `codex-mirror.py` reads when mirroring commands into agent skills, so the description has a single home across the installer and the mirror.

Rules are **copied** from a module's `rules/` folder (`sb-os/{module}/rules/` — shipped today by `para` and `finance`) to `.claude/rules/`, with install-time `{sb_os_path}` placeholder substitution, because Claude Code auto-loads rules from that path natively.

### Module Layout

Shippable components live under module folders at the repo root: `para/` (PARA-aligned components — vault structure, periodic-notes templates, life planner), `wiki/` (knowledge-base layer — wiki ingest/query/lint, tutor), and `finance/` (personal-finance system — bookkeeper/investor agents, companion workflows, tool scripts, dashboard). Each module folder follows the same internal layout (`commands/`, `rules/`, `skills/`, `workflows/`, plus module-specific folders such as `claude-mds/`, `docs/`, `templates/`, `scripts/`). The manifest's `module` field on each component encodes which folder owns its source.

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
| ~~`sb-workflow-context.md`~~ | **Retired.** Context injection no longer fires via an active rule — it is auto-wired as a hook in `.claude/settings.local.json` (PreToolUse/Skill + PostToolUse/Read) calling `resolve_context.py --hook`. Schema: `para/docs/context-injection-schema.md` |
| `sb-source-of-truth.md` | Edit-source-not-installed-copies reminder |
| `sb-sub-agents.md` | Mandatory skill directives in Agent dispatches |
| `sb-no-task-forgotten.md` | Job-end gate: capture deferred loose ends as cold-start-sufficient vault tasks |

The `"stale"` manifest mechanism that retires rules like `sb-user-preferences` is described in §6 "Stale components".

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

### Orphaned rules

Rules are not thin loaders — they install verbatim into `.claude/rules/` with no embedded `Read and execute` directive, so the orphaned-loader scan above never sees them. A rule removed from `module-manifest.json` *entirely* while its owning module stays selected therefore evades both cleanup paths: selection-aware `_clear_orphans` only deletes rules whose `target` is still in the manifest but deselected (or flagged `stale`), and the loader scan skips `.claude/rules/`. An upgrade run closes this with a parallel scan (`loaders.find_orphaned_rules`): it scans `.claude/rules/sb-*.md` and deletes any file whose vault-relative path has no `target` entry anywhere in the manifest (stale included). Because rules carry no source pointer, the reserved `sb-` filename prefix is the ownership signal — `rbtv-*` and user rules are never flagged, and the scan never reaches outside `.claude/rules/`. `excluded_components` targets are never deleted. Planned deletions appear in the upgrade plan before the confirm prompt.

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
| `.claude/rules/` files | sb-os | Always rewritten; sb-os-shaped rules (`sb-*.md`) with no manifest entry are deleted (orphan pruning, §6) |
| `.claude/settings.json` | User | sb-os never creates or modifies |
| `.claude/settings.local.json` | User + sb-os | Context-injection hook entries auto-wired (sentinel `__sb__: sb:context-injection`); opt-out via `excluded_components`; rest preserved |
| `sb-os.json` | sb-os | Updated each run |
| `{user_context_root}/**/*.yaml` (default `.user/context/`; includes `skills/{skill-name}.yaml`) | User | Read by sb-os; never written |
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
| Hooks that auto-write `.claude/settings.json` | `settings.json` stays user-managed (per §8) — sb-os never writes it. The context-injection hook is auto-wired into `.claude/settings.local.json` instead (sentinel `__sb__: sb:context-injection`; opt-out via `excluded_components: ["context-injection-hook"]`). Other hook snippets ship as docs (`docs/hooks.md`); users add them manually. |
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
| wiki v5 | `wiki` | Questions layer: a dedicated `{wiki_root}/questions.md` (queue-style user agenda) + answer-scan wired into both `/sb-wiki-ingest` (active `PROPOSED ANSWERS` block at Stage-1, covering both homes) and `/sb-wiki-lint` (periodic sweep, graduation proposals, prune). Two-homes model: topic `Open questions` stay on topic pages; `questions.md` is the user's agenda only. No-op when `questions.md` is absent — ingest/lint identical to today. Silent-mode change: `/sb-wiki-ingest silent` now applies FIRM topic updates (append-only) and audits each to the silent-summary `Flags` channel; rejects speculative updates and proposed answers and audits each the same way (NOT to the `logs/` queues — its `topic-updated` type is retired and the applied page is its own durable record); counts surface in the `ingest-all` report. Schema canonical reference: `wiki/docs/wiki-schema.md` v5 (questions-layer). |
| wiki v6 | `wiki` | Retrieval tiers: wiki retrieval becomes availability-gated. New deterministic helper `wiki/scripts/sb-wiki-search.py` maintains a local hybrid index (SQLite FTS5 keyword + Voyage embedding vectors, RRF-fused) at `{wiki_root}/.sb-wiki-search/index.db` and self-syncs incrementally on every search. Consumers: `/sb-wiki-query` Step 3 (semantic tier first, grep floor when unavailable), `/sb-wiki-lint` Step 7.7a answer-sweep, `sb-wiki-create-topic` Step 1.5 scope-overlap, `sb-fin-create-thesis` Step 1.3 scope-overlap (finance ext), and the `{wiki_root}/CLAUDE.md` Retrieval rule for all agents. Zero new REQUIRED dependencies: no `VOYAGE_API_KEY` → FTS5-only keyword mode (no API calls); helper unavailable → grep floor, identical to pre-v6 behavior. The index artifact is derived data — installer never touches it, lint never walks it, gitignore it. Replaces the v≤5 "never embeddings/RAG" lock. Schema canonical reference: `wiki/docs/wiki-schema.md` v6 (retrieval-tiers). |
| wiki v7 | `wiki` | Retrieval-first: the v6 tier becomes the DEFAULT retrieval path instead of a fallback. `/sb-wiki-query` runs the helper on EVERY query (unioned with deterministic picks — direct hits + filename matching, no leaf-index reads when the tier is available; leaf-index scoring + grep remain the floor). `/sb-wiki-ingest` becomes a consumer: near-duplicate stub probe (same-referent test before stub creation, reroutes to the append-only update path), speculative topic-update semantic fires, and answer-scan semantic membership check — all tier-gated, default-reject/user-gated. Firm topic-update detection stays 100% mechanical but swaps the full `wiki/topics/` page walk for a deterministic read-shortlist (slug listing + ONE grep alternation pass; the semantic tier is FORBIDDEN as a firm shortlist per the schema's mechanical-fire invariant). Speculative `Scope` text sources from the topics leaf index (one read) instead of per-page walks. Tier absent → identical pre-v7 mechanical behavior. Schema canonical reference: `wiki/docs/wiki-schema.md` v7 (retrieval-first). |
| wiki v7.1 | `wiki` | Key resolution for the semantic tier gains a file fallback: `sb-wiki-search.py` resolves the Voyage key from the `VOYAGE_API_KEY` env var first, else from `{vault_root}/.user/config/env/.env` (line `VOYAGE_API_KEY=...`; missing file or empty value → silent skip, FTS5-only mode unchanged). Lets vaults keep keys in one gitignored user-owned file instead of requiring OS-level env vars. No new dependencies; availability ladder otherwise identical to v6. |
| wiki v8 | `wiki` | `/sb-wiki-lint` gains broken-link REPAIR and deterministic Disputed-callout aging. `sb-wiki-lint-deterministic.py` now classifies each broken wikilink (Step 5): `bucket A` = unique casefold+accent+curly-quote/dash fold-match to an existing file (auto-fixable, exact `suggestion`); `needs-judgment` = LLM splits into bucket B (genuinely-missing concept/entity → author a web-verified stub) or bucket C (unresolvable, reported only). Step 9 surfaces a USER-GATED `LINK-FIX PROPOSAL` (accept → new `--execute-link-fixes <plan.json>` executor rewrites `[[old…]]`→`[[new…]]` preserving `#anchor`/`\|alias`, scoped to `wiki/**`, never `raw/`) and a `MISSING-PAGE PROPOSAL` (accept → author stub per `stub-policy.md`). Step 3 (unresolved Disputed callouts) moves from an LLM walk to deterministic detection — flagged date = first `YYYY-MM-DD` in the callout body, resolution = a referenced topic page exists. Replaces the one-off broken-wikilinks repair prompt. Schema canonical reference: `wiki/docs/wiki-schema.md` § "/sb-wiki-lint". |
| wiki v9 | `wiki` | Backfill (`/sb-wiki-ingest-all`) drops multi-source batching for **one sub-agent per source, run strictly sequentially** — removing the 60k-token batch budget, wave scheduling, cross-origin parallelism, and the concurrent shared-write collision machinery (sequential = no collisions). Per-file model routing replaces all-Opus: **Sonnet by default, Opus only when a source's `token_estimate` > 30000** (`sb-wiki-ingest-all-manifest.py` `build_plan` + `assign_model`; the dispatch plan is now a flat `plan.files[]`). `/sb-wiki-ingest` Step 2 gains a **Substance coverage discipline** (scale depth to source breadth; every load-bearing signal class present — decision criteria, tradeoff/comparison tables kept AS compact tables, quantified specifics — survives into `Substance`; density over length) and routes **author-flagged "needs validation" confidence to `Counterpoints`**. Motivation: multi-source batches diluted per-source attention, thinning the synthesis of dense compendium sources to a table-of-contents. Schema canonical reference: `wiki/docs/wiki-schema.md` (Source page §). |
| wiki v11 | `wiki` | `/sb-wiki-ingest` Step 1.5 PDF text-twin extraction swaps the lossy `pypdf` path for a table-aware **structured extractor** `wiki/scripts/sb-wiki-pdf-twin.py` (PyMuPDF `find_tables()` + block reading-order): tables survive as markdown tables and multi-column body text de-interleaves into reading order, so dense papers stop losing their tables and quantitative results at the first ingest step. The structured twin OVERWRITES the `pypdf` twin **in place** under the same filename `raw/{origin}/{title-slug}.md` and BECOMES the ingest input (Step 2 reads it) — not a separate detector-only `.twin.md` (OD-3 owner override of the synthesis's supplement-only rec). Adds **vision-piggyback** (the agent's native figure/chart observations — captions + axis numbers — persisted into the twin at zero new compute, beating OCR) and a **`twin_fidelity` fail-loud flag** (PyMuPDF empty/garbled tables on a table-bearing page, or a scanned PDF → twin frontmatter banner "untrustworthy — table/chart content NOT checked" + `escalate_pages` + tool exit 3; the page-set escalates unconditionally, never silently cleared). The raw-immutability rule is amended in `wiki/workflows/shared/{naming-convention,folder-structure}.md`: a PDF's derived text twin MAY be regenerated from the still-immutable PDF (PDF = untouchable original, twin = regenerable derivative). New dependency: **PyMuPDF** (`fitz`). **`marker` OCR fallback SHIPPED (OD-3 secondary; task 1.5)** — the `--marker` path in `sb-wiki-pdf-twin.py` (own `.venv-marker`: torch + surya OCR, fully local, never `--use_llm`) auto-fires ONLY on suspect pages PyMuPDF's `find_tables()` cannot grid (BORDERLESS tables), recovering their structure; registered in the root CLAUDE.md capability inventory + `2-areas/tech/my-setup/dev-environment.md`. **Step-1.5 contract hardening (task 1.6):** a vision-less twin now emits a visible `> [!note]` "vision not supplied — figure numbers not captured" (no silent omission of chart/figure numbers), and `escalate_pages` + the fail-loud banner label page numbers **FILE ORDER (may differ from the printed page by the cover-page offset)** so a reviewer opens the right page. No manifest change (the script is a tool, not an installed component). Schema canonical reference: `wiki/workflows/shared/naming-convention.md` § "Raw PDF Title-Conformance". |
| wiki v10 | `wiki` | `/sb-wiki-ingest` Step 2 "Substance coverage discipline" is reframed from a CLOSED checklist of signal classes into a **reconstruction PRINCIPLE**: the binding definition is that a reader of `Substance`, without the source, can reconstruct every load-bearing claim, decision rule, quantified fact, distinction, and author caveat the source makes — including kinds the examples do not enumerate (a closed list could not demand a kind it omits). The five signal classes survive as labelled ILLUSTRATIVE EXAMPLES, retuned for the dominant source type (dense scientific papers): research question/hypothesis + specific contribution vs prior work; method/dataset/sample; specific quantitative results (effect sizes, significance, benchmarks); tradeoff/comparison tables; limitations / threats to validity / author-flagged confidence. The "scale depth to source breadth" clause is preserved (single-thesis sources stay short). Source-side complement to the thin-page detector — reduces thin synthesis at generation instead of catching it after. No new component; no manifest change. Schema canonical reference: `wiki/docs/wiki-schema.md` (Source page §, `Substance` row). |
| wiki v13 | `wiki` | Thin-page detector **composite escalation ladder + adversarial AI verifier + OD-6 no-worse gate** (the top of the detector ladder; spec Behavior #4–#6, OD-4/5/6/7/8). Two new `wiki/scripts/` tools wire the certified lower layers (typed-retention `thin_detector_typed.py` + density/chunked-recall `thin_detector_density.py`) into one verdict — both ADDITIVE, the lower layers' tests stay green. (1) `thin_detector_composite.py`: an **OR-of-thresholds composite** (flag if ANY single signal trips its recall-biased cut — NOT a fitted blend, OD-4: defer a learned blend until ≥~40 gold labels) PLUS **unconditional escalation** of every `kind==paper` and every `twin_fidelity==false` page (twin-blind layers may never clear a paper); a **worst-first ranked suspect queue** (OD-7, severity = typed-loss-fraction dominant + uncovered_mass, with a configurable per-run `--cap`, default 100) VALIDATED monotone on the graded-deletion ablations (g05<g25<g50 ⇒ ranked worse); a **5% random non-flagged audit** (measures the false-negative rate the cheap layers miss); the **structured NLI packet** (codex schema — only missing atoms + uncovered windows + raw-sentence context + native PDF page numbers, NEVER the whole page, D-2); and the **adversarial LLM/NLI judge** (a STRONG general AI — claude-opus-4-8 — with FRESH context, prompted to hunt omissions and default-missing-on-doubt, fed the packet + the native PDF for papers). `--judge anthropic` fires when an Anthropic key resolves (`ANTHROPIC_API_KEY`/`CLAUDE_API_KEY`, env-or-`.env`); `--judge stub` is a documented deterministic placeholder that exercises the packet path otherwise — the real LLM call is the ingest pipeline's runtime dependency. (2) `thin_detector_reingest_gate.py`: the **OD-6 no-worse gate** `/sb-wiki-reingest` (task 3.1) consumes — a re-do is accepted only if ≥ old on EVERY measured retention class (T2–T6) AND on `uncovered_mass` AND it clears a minimum improvement delta; papers/borderline calls require the adversarial AI no-loss confirm (the gate returns `needs_ai_confirm`; the caller drives the judge). **OD-6 guardrail:** a re-do worse on a class the mechanical checker does NOT measure (the calibration set seeds `reasoning_chain` as exactly this bait) is SURFACED and ADDED to the measured set, never silently passed. Both are tools, not installed components — no manifest change (consistent with v11/v12). Thresholds calibrated on `gold_cal()`+ablations ONLY (never `gold_test()`); all detection runs against a SCRATCH `--db` (Layer-1b embeds the page's raw into whatever `--db` resolves to — the LIVE index is never populated by detection). Cheap-layer recall on atom-ablations = 100% (24/24); gold-thin SPECIFIC-omission against an UNSTRUCTURED raw source is the LLM-layer's job (the typed floor needs a structured raw; chunked recall sees these as topically-covered — D-4), surfaced via the audit + the unconditional escalation. Schema canonical reference: `wiki/scripts/calibration/README.md` + the script docstrings. |
| wiki v14 | `wiki` | New `/sb-wiki-reingest` command (loader `wiki/commands/sb-wiki-reingest.md` → workflow `wiki/workflows/sb-wiki-reingest/`) — the first clean RE-ingest path for an ALREADY-ingested source (today's ingest/ingest-all deliberately skip existing pages). Flow: resolve targets via the ingest-all manifest's `classify_targets` (`#reingest` marks with no arg / origin / file list); **preview-gated `git rm` of ONLY the target's source page** (`wiki/sources/{origin}/{stem}.md` — never the raw, leaf index, or any concept/entity/topic page) requiring explicit owner confirmation; dispatch `/sb-wiki-ingest-all` on the same targets to rebuild (it owns the one-sub-agent-per-source sequencing + the final lint heal + the SINGLE commit — re-ingest adds NEITHER); gate each re-do with the **OD-6 no-worse gate** (`thin_detector_reingest_gate.py`): accept only when ≥ old on every measured retention class (T2–T6) AND `uncovered_mass` AND it clears a per-kind min-delta (**papers `0.25`, articles/podcasts `0.15`** — "don't replace for a marginal gain"; ANY measured-class regression is rejected regardless of delta), passing `--uncovered-old/--uncovered-new` explicitly (the standalone composite's uncovered arm is dormant for `sources/`-page raw refs) and `--loss-class` from the first-ingest-vs-re-do diff (fires the unmeasured-class guardrail); **RE-EVALUATE linked concept/entity pages** against the rebuilt page rather than blindly preserving a thin first-ingest entity; strip `#reingest` from consumed leaf indexes. **No-key AI-confirm degradation:** when the gate returns `needs_ai_confirm` (papers/borderline/surfaced-unmeasured) but no Anthropic key + `anthropic` SDK resolves, re-ingest degrades to the mechanical verdict + an explicit `AI confirm deferred (no key)` note and surfaces the page as conditionally-accepted for owner decision — NEVER a silent pass and NEVER the stub as confirmation. Detection/gate runs never touch the live search index (scratch `--db`); the gate's typed layer is embedding-free. Manifest change: the `sb-wiki-reingest` command is registered in the `wiki` module (a loader IS an installed component, unlike the detector scripts). Schema canonical reference: `wiki/claude-mds/wiki.md` § "OD-6 re-ingest no-worse gate" + the workflow file. |
| wiki v12 | `wiki` | Thin-page detector **calibration / validation harness** lands under `wiki/scripts/calibration/` (the keystone every detector threshold calibrates on — OD-1). Two products merged into one consumable manifest `data/ground-truth-manifest.json`: (1) a **silver-ablation generator** (`silver_ablation.py`) that turns a faithful `(page, raw)` pair into KNOWN-THIN fixtures by DELETING real failure-mode signal classes (numeric atoms, table rows, rule/framework labels, named entities, author caveats, reasoning chains — never random sentences) from the detector compare-set (`Substance`+`Counterpoints`+`Methodology`+`Notable quotes`) and emits the exact removed-item ground truth, GRADED at 5/25/50% with strict-superset monotonicity so OD-7 worst-first ranking is validatable; fixtures are provenance-stamped `DO NOT INGEST` and the generator REFUSES to write under `wiki/`/`raw/` (calibration fixtures, never corpus); (2) a **stratified hand-checked gold set** (`data/gold-set.yaml` → `build_gold_set.py`) of ~25 real pairs labelled thin/faithful with the specific missing items, stratified by source kind (paper/article/podcast, both labels per kind — the two faithful podcasts are anti-shortcut anchors), with a HELD-OUT test split thresholds are never tuned on. Consumers read via `load_manifest.py` (enforces the cal/test split). The `reasoning_chain` class is deliberately ablated though the typed-retention layer does not measure it — the OD-6 unmeasured-class guardrail bait. New dev dependency: PyYAML (already present). `calibration/data/` is derived data — installer never touches it, lint never walks it; no installed component, no manifest change (the scripts are tooling). Docs: `wiki/scripts/calibration/README.md`. |
| wiki v15 | `wiki` | Thin-page detector + adversarial judge + OD-6 no-worse gate **REMOVED** (retired per decision — re-ingestion becomes edit-in-place **ingest healing**, no old-vs-new gate). Deletes `thin_detector_typed.py`, `thin_detector_density.py`, `thin_detector_composite.py` (which held the `--judge anthropic` LLM-API path + `_resolve_llm_key`), `thin_detector_reingest_gate.py`, and their `*_test.py`: the wiki now carries **no thin-page-detection code and no `anthropic`/LLM-API call** under `wiki/scripts/` (the Voyage *embedding* API in `sb-wiki-search.py` is a vector API, not an agentic-AI dispatch — untouched). The labeled **calibration/gold dataset** (`wiki/scripts/calibration/**`, v12) is **KEPT** — repurposed to measure healing quality. `/sb-wiki-reingest`'s no-worse-gate references are stripped here pending the command's rework into ingest healing. The detector scripts were tooling, not installed components — **no manifest change**. Supersedes the detector behavior recorded in v12/v13/v14. |
| wiki v16 | `wiki` | Orphan cleanup: the **raw-source embedding sub-feature** in `wiki/scripts/sb-wiki-search.py` is REMOVED — the `index-raw` command, the `walk_raw`/`window_raw`/`sync_raw`/`_delete_raw_paths` helpers, the `raw_files`/`raw_chunks` tables in `open_db`, and the `status` `raw_*` fields. It was built in task 2.3 ONLY as the thin-page detector's chunked-recall embedding backend; the detector was deleted in v15, leaving this path with no consumer (still functional, but orphaned — it shared the file with the live page/query search index). The **page index + search + the Voyage page/query embedding tier** (`/sb-wiki-query`) are UNCHANGED — only the raw-source path is gone (46/46 search tests still green). Existing `.sb-wiki-search/index.db` raw tables become dormant derived data (gitignored, rebuilt on demand; the code never reads them again). The script is tooling, not an installed component — **no manifest change, no `install.py`**. Recoverable from commit `44bb7af`. Schema reference unchanged. |
| wiki v17 | `wiki` | Re-ingestion becomes **ingest healing** (edit-in-place). The `/sb-wiki-reingest` command (loader + workflow folder) is renamed → **`/sb-wiki-ingest-healing`** (`wiki/commands/sb-wiki-ingest-healing.md` → `wiki/workflows/sb-wiki-ingest-healing/sb-wiki-ingest-healing.md`) and its delete-rebuild-gate body is REPLACED: instead of deleting the source page and rebuilding through `/sb-wiki-ingest-all` behind an OD-6 no-worse gate, an agent **re-reads the source and EDITS the existing page in place** to the reconstruction standard — augmenting ONLY the agent-authored sections (`Substance`/`Connections`/`Counterpoints`/`Methodology`/`Notable quotes`), preserving `My take` + every human edit **byte-identical**, never deleting or rebuilding (so there is no old-vs-new regression to gate). For a PDF source it reads the **original PDF** (not the text twin), recovering what extraction dropped (a borderless table the twin could not grid). Healing repairs the **whole graph** the source feeds — re-evaluating + augmenting linked concept/entity pages (append-only, ingest Step 4), creating new concept/entity stubs the recovered detail warrants (Step 5), and reconciling topic updates + candidate-topic triggers (Steps 4.5 + 6 + `/sb-wiki-update-backfill`, incl. re-judging the first ingest's topic suggestions) — REUSING the `/sb-wiki-ingest` machinery, never forking a parallel graph builder. **Firing:** a new **Step 10.5 PDF auto-heal hook** in `/sb-wiki-ingest` fires healing AUTOMATICALLY (hands-off, no checkpoint) after every **PDF-format** source's first ingest, post-Stage-1-commit (riding that commit) — **PROBATIONARY** (kept automatic for now; may demote to on-demand if `marker`-improved first ingests prove consistently faithful); **non-PDF** sources heal **on-demand only**. An on-demand heal previews before its OWN single commit. **No judge / gate / detector / LLM-API anywhere in the path** — the healing pass is the sole quality check (the in-session workflow agent reasoning over page + source; no separate model dispatch, no orchestration-routing dependency). The kept calibration/gold set (v12/v15) can later measure healing quality. Manifest change: the command is re-registered under its new name (a loader IS an installed component). Supersedes the v14 `/sb-wiki-reingest` command behavior and completes the v15 pivot. Schema canonical reference: the `sb-wiki-ingest-healing` workflow + `wiki/claude-mds/wiki.md` Operations row. |
| wiki v18 | `wiki` | Backfill model split + **size-scoped runs**. `sb-wiki-ingest-all-manifest.py` lowers `OPUS_TOKEN_THRESHOLD` from `30_000` → `5_000` and makes `assign_model` inclusive (`>=`): a source at or above 5k tokens (or un-estimable) routes to **Opus**, below to **Sonnet** (supersedes the v9 `> 30000` split). New **`large`/`small` size keyword** for `/sb-wiki-ingest-all`: pulled out of the positional targets before mode classification (`extract_size_filter`) so it composes with `all`/`origin`/`files`, then `apply_size_filter` restricts the run to one bucket — `large` = the Opus set (≥ threshold or un-estimable), `small` = the Sonnet set — and recomputes `origins` + `totals.missing`, adding `totals.size_excluded` and a top-level `size_filter`. The size boundary is the SAME constant as the model split, so `large`/`small` always equal the Opus/Sonnet sets. Guards: two size keywords, or a keyword colliding with an origin folder of that name (`--origin <name>` disambiguates), exit non-zero and ingest nothing. The manifest is tooling, not an installed component — **no manifest change**. Workflow doc + command description updated. Schema reference unchanged. |
| wiki v19 | `wiki` | **sb-tutor visual learning library.** `/sb-tutor` now builds a Lumen-themed HTML library of taught topics — one page per topic + a knowledge-map `index.html` — at module checkpoints (R6) and session close (R9), ADDITIONAL to the R9 study-note markdown (which still feeds the wiki). New deterministic builder `wiki/scripts/sb-tutor-build-library.py` (PyYAML + `markdown`) renders per-topic markdown **page-sources** (`{library_root}/topics/{slug}.md`; schema `wiki/scripts/learning-library/page-source-schema.md`) into self-contained pages with CSS/JS inlined from `wiki/scripts/learning-library/assets/` (no CDN). Pages persist the R3 starting level + lesson sources and carry collapsible sections, an auto scroll-spy in-topic nav, related-topics, and **interactive-light** visuals (click-to-explain concept graph, hover charts, go-deeper expanders, a quick-check). New tutor protocol `wiki/workflows/sb-tutor/library-protocol.md` (CREATE + ENRICH modes), wired via `sb-tutor.md` activation (enrich branch) + `step-01-boot.md` R12. **Enrich loop:** every page block has a hover copy-button emitting `/sb-tutor expand the item [X] of the topic [Y].`; the tutor deepens that item in the page-source (append-only) and rebuilds. `{library_root}` resolves from a new `Learning library destination` context entry. Builder/protocol/assets/schema are tooling referenced by the live workflow — **no manifest change** (no `install.py` required); PyYAML present, **`markdown` is a runtime dependency** (already installed; builder fails loud with `pip install markdown` if absent). |
| wiki v20 | `wiki` | **sb-tutor enrich → orchestrated pipeline + precise copy-payload + hover glossary.** ENRICH mode (`wiki/workflows/sb-tutor/library-protocol.md`) is rewritten from a single in-place edit into an ORCHESTRATED run (invokes `rbtv-orchestrating` + `rbtv-sub-agents`): tutor-conductor → deterministic **locator** → RESEARCH agent (wiki + internet, structured findings, edits nothing) → UPDATE agent (append-only deepen of the one located section) → builder `--topic {slug}` → report. New stdlib-only locator `wiki/scripts/sb-tutor-locate-item.py` — given `--source topics/{slug}.md --item <anchor-id\|title>` it returns that section's current markdown block + 1-based line range + slug (`--json`), and rejects an unknown item with the page's section list; its anchor contract `s-{slugify(title)}` mirrors the builder. **Precise copy-payload:** the builder injects `data-source="topics/{file}.md"` on `<body>` and `app.js`'s hover copy-string now carries the page-source filepath + section anchor-id + title + the `/sb-tutor expand` invocation (supersedes the v19 `[item]`/`[topic]`-only prompt) so enrich targets the EXACT source block, not brittle rendered HTML. **Glossary highlight + hover tooltip:** glossary terms render highlighted with a plain-language HOVER/FOCUS tooltip (pure-CSS `.gloss::after`, replacing the click `#pop` popover; keyboard/touch via `tabindex`+`:focus`), applied to prose AND interactive-graph click-to-explain panels (node/edge `desc`s glossary-linked through a `data-desc` double-encode; SVG labels stay glossary-free). The authoring quality bar gains a mandatory "define every technical term in plain language" rule; the schema's `glossary:` note is updated. Fixed a latent glossary bug — a definition containing another glossary term corrupted the `data-def` attribute (inserted spans are now parked at tag indices so later terms never match inside them). Builder/locator/protocol/assets are tooling referenced by the live workflow — **no manifest change** (no `install.py`); the locator is stdlib-only. |
| wiki v21 | `wiki` | **Wiki sources hyperlink to their Obsidian note.** In a built library page's **Light sources** box, each wiki source now renders as a link that opens that wiki note in Obsidian — `obsidian://open?vault=<vault>&file=<note>`, resolved BY NOTE NAME so the link survives the wiki reorganizing folders; the display stays the human-readable subject. Page-source `sources.wiki` entries gain an optional `{subject, page}` form (`page` = the wiki note's name or path; a plain string still renders unlinked — e.g. a raw-article citation). The builder finds the vault root by walking parents up to `sb-os.json` (its folder name = the Obsidian vault name) and renders the link; absent a vault root or a `page`, it degrades to plain subject text. Schema (`page-source-schema.md`) + `library-protocol.md` (CREATE + ENRICH: the tutor records each wiki note in `page` at authoring time) updated. Tooling/content live via the loader — **no manifest change, no `install.py`**. |
| wiki v22 | `wiki` | `/sb-wiki-ingest-healing` gains **count-based orchestration**. The resolved-target count selects the path: **1 target → in-session self-heal** (unchanged — previews, then its own single commit); **≥2 targets** (incl. the `heal all` / no-args `#reingest` sweep) **→ the ingest-all orchestration shell** — one sub-agent per source, strictly sequential, per-file Sonnet/Opus at the SAME 5k threshold, each sub-agent running ONLY the healing per-source unit (Steps 2–3: edit the page in place + propagate the graph; NEVER `/sb-wiki-ingest`, which creates a page), then one final `/sb-wiki-lint` + EXACTLY ONE git commit (hands-off, no per-target preview; every worker still hard-verifies the human half byte-identical and HALTs rather than clobber it). Healing is now a **delta layer ON ingest-all, not a fork**. `sb-wiki-ingest-all-manifest.py` gains a **`--healing` flag** (backed by a dedicated `collect_healing`) that INVERTS the selection: it resolves ALREADY-ingested **source pages** in the source-page namespace — a page's stem need NOT match its raw filename, so targets are never matched against `raw/` — and estimates each from the raw its `raw:` frontmatter names, building the model-routed `plan.files[]` (reusing `assign_model` + `OPUS_TOKEN_THRESHOLD`); a ref resolving to no page reports under `skipped_not_ingested` and NEVER halts the run. The `#reingest` sweep passes a **bare origin name** for a tagged leaf index (the manifest expands it to that origin's pages) and `{origin}/{stem}.md` for a tagged page. The existing `large`/`small` **size keyword** composes with healing too (shared `extract_size_filter`/`apply_size_filter`) — scoping the heal to the Opus (`large`) or Sonnet (`small`) bucket; alone it is the `#reingest` sweep filtered to that bucket, never heal-everything (empty `--healing` is rejected). The prior contract phrasing "no `anthropic`/HTTP/SDK LLM-API call / in-session-agent" is REMOVED (the orchestrated path dispatches sub-agents); "no judge, no gate, no detector" stays. Manifest is tooling, not an installed component — **no manifest.json change**; command loader description + `wiki/claude-mds/wiki.md` operations row updated. Supersedes the v17 single-agent healing flow. Schema reference unchanged. |
| wiki v24 | `wiki` | **Marker-based PDF-twin recognition** (Trinity misfire fix). Twin recognition drops the same-stem `.pdf` requirement: a regenerable twin `.md` is now recognized whenever it carries a twin marker (`twin_extractor:`/`source_pdf:` frontmatter or a legacy `Original PDF:` ref) AND resolves to a `.pdf` in its folder — via `source_pdf:`, same-stem, an `Original PDF:` ref, or a sole in-folder PDF (new `resolve_twin_pdf`, mirrored in `sb-wiki-ingest-all-manifest.py._resolve_twin_pdf` + `sb-wiki-lint-deterministic.py.resolve_twin_pdf`). A title-conformance PDF rename (Step 1.5/7.6) that diverges the twin's stem from the PDF's no longer un-recognizes the twin, so lint no longer gives it a `\| … \| No \|` row, ingest-all discovery no longer surfaces it as missing (the ingested-set builder resolves the twin's PDF stem-agnostically), U10 `detect_md_duplicate_raws` never flags it, and ingest Step 1.7 skips it (never `Duplicate`). **Complementary (Option B):** the title-conformance rename executor (`execute_renames`, `--execute-renames`) renames a same-stem twin `.md` in lockstep with its PDF and refreshes its `source_pdf:`, keeping the pair aligned so recognition rarely has to rescue a divergence. New regression suite `wiki/scripts/tests/test_sb_wiki_twin_marker_recognition.py` (Trinity-shaped, 6 tests); full wiki suite green (358). Scripts + workflow prose (`sb-wiki-ingest.md` Step 1.7 + `extensions/silent-mode.md`) + `wiki/docs/wiki-schema.md` D1 updated. Scripts are tooling — **no manifest change, no `install.py`**; the workflow/rule copies regenerate on install. |
| wiki v25 | `wiki` | **Silent-mode injected capture-only guard** (tecer no-auto-write hardening). The silent-mode firm-tier auto-apply (`extensions/silent-mode.md` Step 10) is made explicitly SUBORDINATE to any injected-context directive that marks a topic (or topic family) **capture-only / no-auto-write**: before applying a firm topic update the worker MUST hard-skip a protected target's body write and route to the capture destination the directive names — closing the gap where a mechanical firm fire (related-links driven) wrote a protected topic body before the worker weighed a directive buried in loaded context. The `/sb-wiki-ingest-all` dispatch prompt now carries this imperatively (a loaded capture-only entry OVERRIDES the mechanical firm apply). The mechanism is GENERIC (no user specifics in sb-os source per `sb-source-of-truth`); the tecer-specific policy (`tecer-*` family → `tecer-relevant.md`) stays in the user's `.user/context/sb-wiki-ingest/sb-wiki-ingest.yaml`, tightened to declare `tecer-*` capture-only and to cover the firm-tier path (not only the tecer-relevance fire). Origin: a `findrive` subagent auto-applied firm updates to two `tecer-*` topics during `/sb-wiki-ingest-all small` (commit `ba964ecd`, 2026-06-29). Prose-only — **no manifest change, no `install.py`**; the workflow copies regenerate on install. |
| wiki v23 | `wiki` | Heal queue moves from the **`#reingest` inline tag** to **`3-resources/knowledge-base/heal-index.md`** (`heal=yes` rows). `/sb-wiki-ingest-healing` multi-target / "heal all" now selects targets from the heal-index (sources whose row carries `heal=yes`) instead of sweeping the vault for the `#reingest` tag; close-out flips each healed row to `heal=no` (instead of stripping `#reingest`). New **`scan`/`check` mode** runs `sb-wiki-heal-scan.py` (depth-scan → refreshes the per-source metrics sidecar and merges updated entries into the heal-index; no healing pass). The `#reingest` inline tag is **RETIRED**. New `wiki-heal-triage` dashboard reads and writes the heal-index. `wiki/claude-mds/wiki.md` operations row + `wiki/docs/wiki-schema.md` Terminology table updated. Supersedes the v22 `#reingest` sweep selection. |
| wiki v26 | `wiki` | **sb-tutor session mode + multi-question calibration.** The front-door calibration (`wiki/workflows/sb-tutor/front-door.md`) stage-3 pill gains (a) a mandatory **session-mode question** — `interactive` (pill lesson) vs `direct-to-page` (no lesson; the tutor authors the FULL library page in one pass) — emitted as a new `session-mode` field in the stage-4 calibration result, and (b) a **1–3-question frontier probe** in a single round (supersedes the exactly-one-question probe; extra questions only when the frontier is ambiguous or spans sub-areas; new "mixed answers" branch). New **R14 Direct-to-page mode** in `step-01-boot.md`: after R4 plan approval, an OPTIONAL one-round depth/background probe (≤3 questions), then library-protocol CREATE/UPDATE authoring of all sections at once (`mastery` omitted — builder defaults it), R9 study note opt-in; R1/R2/R5/R6 suspended, C6 wiki check + R-c gap handling + R13 still apply. `library-protocol.md` CREATE/UPDATE notes the one-pass path. Prose-only — **no manifest change, no `install.py`** (workflow files load via the existing loader). |
| v0.2.0 | `core` | `module-manifest.json` gains a `"stale"` component flag (+ optional `"stale_reason"`), enforced at `loaders._flatten`. Stale components are never installed or surfaced and are removed on upgrade; sources are preserved. Rules `sb-source-of-truth` and `sb-user-preferences` retired as stale — source-of-truth's principle lives in the managed CLAUDE.md + README; preference loading moves to host CLAUDE.md (cross-cutting) and per-workflow context-injection (workflow-scoped). |
| v0.2.1 | `core` | `sb-source-of-truth` un-retired — `"stale"` flag removed from its `module-manifest.json` entry, so the installer ships the always-on rule again. `sb-user-preferences` stays stale. |
| v0.3.2 | `para` | Context injection generalized from workflow steps to a second execution surface: **skill invocation**. The `sb-workflow-context` rule (title → "Context Injection") now fires its Pre-Action Gate both per workflow step file AND on every skill invocation — invoking any skill (sb-os, RBTV, user, plugin) probes `{user_context_root}/skills/{skill-name}.yaml` and applies its `context:` entries before the skill body runs. `/sb-inject-context` gains a skill target alongside workflow steps (Step 1 surface branch; skill YAML at `{user_context_root}/skills/{skill-name}.yaml`). Schema, processing rules, and workflow-step resolution unchanged; graceful file-not-found skip means zero behavior change where no skill YAML exists. Rule file name (`sb-workflow-context.md`) and manifest entry are unchanged — no rename. |
| v0.3.4 | `para` | Context injection made deterministic. New tooling script `para/workflows/sb-inject-context/resolve_context.py` collapses the `sb-workflow-context` rule's per-surface gate from agent-reasoned **resolve path → probe → load → process** into ONE call: given a surface (`--surface skill --name <skill>` or `--surface step --file <step.md>`), it reads `user_context_root` from `sb-os.json`, resolves the YAML path (mirroring a step file's path-relative-to-workflow-root, `.md`→`.yaml`), probes it, and PRINTS each entry's `instruction` with its loaded content directly to stdout — `text` + `file`(read, with `sections`/`glob`/`select`/`count`) fully loaded as corpus (a loaded file is labelled fully-loaded — no re-read needed, the path is informative for editing/reference — or PARTIAL when only `sections` were extracted; `read-write` labels the content as the edit-and-write-back target); `script`/`url`/`mcp`/`write`-mode/unresolved-placeholder entries surfaced as a labelled `AGENT ACTION` (never executed — args carry agent-substituted placeholders); `NO CONTEXT` (exit 0) when no/empty YAML; `CANNOT PARSE <file>` (exit 3, real PyYAML parse, no traceback) on malformed YAML. `--path-only` prints just the resolved path (exists or not) — the single source of truth the `/sb-inject-context` command now consumes to locate the file it creates/edits, so author-side and runtime can never drift on resolution. The rule's Pre-Action Gate, Red Flags, Path Resolution, and Processing Rules are rewritten to "run the resolver, act on its output"; the agent no longer computes paths or parses YAML by hand. Schema and the YAML contract are unchanged; graceful `NO CONTEXT` preserves zero-behavior-change where no YAML exists. Motivation: cut agent cognitive load and eliminate silent path-resolution misses. The script is tooling, not an installed component — no `module-manifest.json` change; PyYAML is an existing sb-os dependency. The rule copy regenerates on `install.py`; the command (loader→live workflow) and the script are live without re-install. |
| v0.3.5 | `para` | Context injection becomes hook-driven and auto-installed. The `sb-workflow-context` rule is RETIRED as an active rule — context injection now fires via a hook the installer AUTO-WIRES into `.claude/settings.local.json` (sentinel `"__sb__": "sb:context-injection"`; two entries — PreToolUse/Skill + PostToolUse/Read — calling `para/workflows/sb-inject-context/resolve_context.py --hook`). Opt out with `excluded_components: ["context-injection-hook"]`; the rest of `settings.local.json` is user-owned and preserved (`settings.json` stays untouched). The context-injection schema/YAML contract is unchanged and now documented at `para/docs/context-injection-schema.md`. Supersedes the rule-driven injection recorded in v0.3.2/v0.3.4. |
| v0.3.3 | `para` | Sweep fail-safe — skip-not-delete on doubt (the safety floor the author-side enforcement below builds on). `sweep_done_tasks.py`'s Done-Task Sweep now SKIPS — never deletes — any column-0 `- [x]` block it cannot route with confidence: a missing `✅` date, an invalid or non-zero-padded `✅ YYYY-MM-DD`, two distinct `✅` dates in one block, or a source `*-tasks.md` that will not decode as UTF-8. A skipped block stays byte-for-byte in its source (never written to any work-log) and is reported with its file + reason (`tasks_skipped`/`skipped` in `--json`); the sweep never deletes on doubt. The strict completed-task contract it keys on: `para/workflows/sb-vault-ops/data/tasks.md` § Sweep Contract. The script is tooling, not an installed component — no `module-manifest.json` change; script/content edits are live without re-install. |
| v0.3.3 | `para` | Author-side enforcement of the task-format Sweep Contract. `sweep_done_tasks.py` gains a `--validate-line "<line>"` mode (new `validate_completion_line()`) that checks ONE completed-task line against the SAME contract the sweep keys on — REUSING `routed_date`/`valid_iso_date` so author-side and sweep-side can never drift — exiting `0` = CONFORMING, `1` = VIOLATION (column-0 `- [x]` but missing/malformed/ambiguous `✅` date), `2` = NOT-A-TASK (not a column-0 `- [x] ` line). `sb-vault-ops` (`para/workflows/sb-vault-ops/data/tasks.md` § Sweep Contract → Write-Time Validation + the Lifecycle Completion row) now MUST run the checker when it completes a task and **BLOCK** a non-conforming completion (fix-and-revalidate), scoped to genuine completions ONLY — never indented subtasks, `~~strikethrough~~` relocation cross-refs, or tracking checkboxes (the dumb checker would flag a column-0 one, so the workflow gates invocation). Completes approach (c) of the sweep-safety work: the sweep-side fail-safe (skip-not-delete) is the safety floor; this is the active author-side half, so malformed done-tasks no longer accumulate unswept. The script is tooling, not an installed component — no `module-manifest.json` change; content-only edits are live without re-install. |
| v0.3.1 | `core` | Upgrade no-op signal: `install.py` now reports how many installed files actually changed on an upgrade run. `upgrade._execute_upgrade` wraps every managed write (marker-block CLAUDE.md sections, skill/command loaders, rules, templates, finance dashboard) and counts only writes whose on-disk content differs from before. A run that changes nothing prints `Upgrade complete — already up to date (0 files changed).`; otherwise it prints the count and lists each changed path. Makes idempotence a single-run assertion instead of a cross-run diff. The `sb-os.json` `installed_at` refresh is bookkeeping and is excluded from the count. No new dependencies; pure stdlib. |
| v0.3.0 | `core` | New always-on rule `sb-no-task-forgotten` (`para/rules/`): at job finalization, deferred loose ends (deferred / discovered-out-of-scope / partial-completion / surfaced-blocker) MUST be written as vault tasks via `sb-vault-ops` before a done-claim, then disclosed in the closing message; speculative nice-to-haves and trivial jobs are exempt. `sb-vault-ops`'s task spec (`para/workflows/sb-vault-ops/data/tasks.md`) gains a **Cold-Start Sufficiency** standard + self-check so any task is executable by an agent with zero session memory. The rule owns WHEN to capture; format, routing, and the standard stay in `sb-vault-ops`. |
| v0.2.0 | `finance` | Installer renders the finance dashboard entry HTML (p1-3/p1-13): `finance/dashboard/dashboard.html.template` → `finance_dashboard_html_path` (prompted on fresh, default `.user/finance/dashboard.html`, persisted in `sb-os.json`, install-if-missing on upgrade). Asset URLs substituted vault-root-absolute from `sb_os_path` via `{{DASHBOARD_ASSET_BASE}}`; data fetches fixed vault-root-absolute at `/.user/finance/bookkeeper/...` via `shared.js` `FIN_DATA_BASE`. See §6 Finance dashboard entry HTML. |
| v0.2.0 | `finance` | Investor policy bootstrap: the finance module ships user-agnostic policy skeletons `finance/templates/{source-policy,research-policy}.md`, installed via the standard manifest-template mechanism to `.user/finance/investor/{source-policy,research-policy}.md` (install-if-missing — fresh installs bootstrap the §3-carve-out structure with `_Fill in_` slots; upgrade never overwrites; personal rows never ship). `research.md` Step 3 item 4's seed-rubric fallback remains the unfilled-policy degradation. |
| v0.2.0 | `finance` | Finance data-access packaging: always-on rule `finance/rules/sb-finance-data-access.md` → `.claude/rules/` (first non-`para` rule; binds every session to tools-only reads/writes for `.user/finance/bookkeeper/` data via the `scripts/tools-index.md` registry — dry-run-first mutations, corrections append-only, missing capability = deviation). Companion workflows gain user-invocable skill front doors `sb-tool-builder` / `sb-doc-maintainer` (`finance/skills/`): the Skill tool loads the companion workflow in-session and the invoking agent becomes the caller-broker — an entry-point addition, not a runtime-model change; sibling Agent-tool dispatch (bookkeeper gatekeeper Seams 1/2) unchanged. |

---

## 12. License

MIT. See `LICENSE` at the repo root.
