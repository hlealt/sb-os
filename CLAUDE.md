# sb-os/

Source repository for **sb-os** — an opinionated, PARA-based personal knowledge management system for Obsidian with native Claude Code agent integration. This file gives an agent the context it needs to work inside the sb-os codebase. It does NOT describe an installed sb-os vault — that is the user's environment, not this repo.

> Full architecture, install flow and customization model `docs/architecture.md`.

## What sb-os ships

| Surface | What it is |
|---------|------------|
| Directory convention | PARA + Workbench + periodic notes + optional wiki slot, installed into a target vault |
| Installable agent components | Skills, commands, rules, workflows distributed to a vault's `.claude/` and consumed at runtime |
| Installer (`install.py`) | Bootstraps fresh vaults and upgrades existing installs idempotently |
| Managed CLAUDE.md sources | Marker-block-managed agent-context files installed into the vault |

## Install Model — Just-in-Time

The installer (`install.py`) is fast and idempotent, so users install components just-in-time — only when they need them. Any given vault therefore carries only a SUBSET of components at once: `sb-os.json` records `selected_modules` and `excluded_components`, and a component absent or excluded there is NORMAL, not an error. Check `sb-os.json` for what is actually installed before assuming a component is missing.

## Repo Layout

Shippable components live under per-module folders at the repo root: `para/` (PARA-aligned components), `wiki/` (knowledge-base layer), and `finance/` (personal-finance system). Each module folder mirrors the same internal layout (`commands/`, `rules/`, `skills/`, `workflows/`, plus module-specific folders such as `claude-mds/`, `docs/`, `templates/`, `scripts/`).

| Path | Contents |
|------|----------|
| `install.py` | Entry point — interactive target detection, mode auto-detection, dispatch |
| `install/` | Installer internals (CLI, manifest, marker handling, mode handlers). `module-manifest.json` declares each component's owning module via the `module` field |
| `para/` | PARA module sources: `commands/`, `rules/`, `skills/`, `workflows/`, `claude-mds/` (PARA-structure CLAUDE.mds), `templates/`, `ideas/`, `docs/` (PARA-scoped reference, e.g. `obsidian-markdown/`) |
| `wiki/` | Wiki module sources: `commands/`, `skills/`, `workflows/` (with `shared/` for cross-workflow conventions), `claude-mds/wiki.md`, `docs/wiki-schema.md` |
| `finance/` | Finance module sources: `commands/`, `rules/`, `skills/`, `workflows/` (bookkeeper, investor, companions), `scripts/` (tool layer + registry `scripts/tools-index.md`), `dashboard/`, `templates/`, `wiki-ext/`, `docs/` |
| `docs/` | Repo-level architecture, conventions, hooks reference. Module-scoped docs live under each module's own `docs/` folder |

## Editing Conventions

| Rule | Detail |
|------|--------|
| Source-of-truth principle | Every component installed to a vault has its source here. Edit the source — never the installed copy. The installer overwrites loaders and rule copies on every run |
| Architecture doc is the spec | Behavior changes require updating `docs/architecture.md` first |
| Marker-block protocol | Managed CLAUDE.mds use `<!-- sb:start v=1 -->...<!-- sb:end -->` markers. Content inside is owned by sb-os; outside is preserved on every install run |
| `user_context_root` is configurable | Components that read user context resolve the path from `sb-os.json` via the manifest module — never hardcoded |
| Settings.json is user-managed | The installer never creates or modifies `.claude/settings.json` in a target vault. Hooks ship as documented snippets in `docs/hooks.md` |
| Workflow directory contents | Each workflow directory contains ONLY step files, data, scripts, and templates — no README, no design docs |
| Documentation home | Documentation about a component lives in `docs/`, not alongside the component |

## Component Naming

All shippable components carry the `sb-` prefix. The prefix marks a component as vault-native and shareable across sb-os installs. Components without the prefix do not ship from this repo.

## Out of Scope (this repo)

| Boundary | Lives elsewhere |
|----------|-----------------|
| User content | A user's vault — never imported here |
| Personal extensions | A user's `.user/` folder in their installed vault — never shipped from this repo |
| Other agent harnesses | Components are written portable where possible; only Claude Code is currently a validated target |

> Codex mirror note: do not read the sibling `AGENTS.md`. It is an auto-generated mirror for Codex agents. This `CLAUDE.md` file is the source of truth.
