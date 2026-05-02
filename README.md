# sb-os

> Open-source PARA-based personal knowledge management system for Obsidian with native Claude Code agent integration.

sb-os is an opinionated directory convention plus an installable agent layer for knowledge work in Obsidian. It ships a PARA + Workbench folder structure, a small set of vault-native skills and commands, and an idempotent installer that bootstraps new vaults or upgrades existing ones.

---

## Quick Install

```bash
git clone https://github.com/hlealt/sb-os.git
cd sb-os
python install.py --fresh --target /path/to/vault
```

Replace `/path/to/vault` with the absolute path to your Obsidian vault. The installer is interactive — it prints a planned-action list and prompts before any destructive operation.

After install, point Obsidian at the same path and open `Home.md`.

## Prerequisites

| Requirement | Detail |
|-------------|--------|
| Python | 3.9+ (stdlib only — no `pip install` step) |
| Obsidian | Any recent version |
| Claude Code | Required to consume the agent layer; the directory convention works without it |
| Git on the target vault | **Strongly recommended** before running `--fresh` or `--upgrade` |

### Git on the target vault — recommended

Before running the installer, initialize git in the target vault and tag the pre-install state:

```bash
cd /path/to/vault
git init
git add -A
git commit -m "pre-sb-os state"
git tag pre-sb-os-install
```

Rollback path is `git reset --hard pre-sb-os-install`. **Vaults without git have no rollback** — the installer will still run, but a bad install must be reversed by hand.

---

## Vault Shape

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
│   ├── {user_context_root}/  [configurable, default: .user/context/]
│   └── ...                [your personal extensions — scripts, configs, anything]
├── .claude/
│   ├── skills/            [thin loaders pointing at the sb-os repo]
│   ├── commands/          [thin loaders]
│   ├── rules/             [verbatim copies of sb-* rules]
│   └── settings.json      [user-managed; sb-os never creates or modifies]
├── sb-os.json             [install manifest at vault root]
├── CLAUDE.md              [managed; markers protect the sb-os section]
└── Home.md                [scaffolding inside markers; user content outside preserved]
```

`Managed` files use HTML-comment marker blocks (`<!-- sb:start v=1 -->...<!-- sb:end -->`). Content inside markers is rewritten on `--upgrade`; content outside is yours and preserved verbatim.

---

## Configurable Paths

Two install paths are configurable and persisted in `sb-os.json` at the vault root. They are never hardcoded — every sb-os component resolves them from the manifest.

| Field | Default | Purpose |
|-------|---------|---------|
| `wiki_root` | `3-resources/knowledge-base/` | Optional wiki slot. The installer creates the folder and a managed CLAUDE.md if you opt in. |
| `user_context_root` | `.user/context/` | Where sb-os reads per-step user context (YAML files consumed by `sb-workflow-context`). |

The installer prompts for both on `--fresh`. On `--upgrade`, the recorded values are reused — pass `--wiki-root` or `--user-context-root` to override.

---

## Install Modes

| Flag | Behavior |
|------|----------|
| `--fresh` | Bootstrap a clean vault: create PARA folders, root `CLAUDE.md`, all managed CLAUDE.mds, install thin loaders, ship `Home.md`, optionally create `{wiki_root}/`. |
| `--upgrade` | Refresh an existing install: rewrite `.claude/` loaders, replace marker-block content in managed CLAUDE.mds and `Home.md`, refresh rules. Never creates new top-level folders. Default mode when `sb-os.json` is found at the vault root. |
| `--dry-run` | Print every planned action without executing. Combinable with `--fresh` and `--upgrade`. |

Mode is auto-detected from the presence of `sb-os.json` at the target root. Pass an explicit flag to override.

---

## Plugin Recommendations

sb-os ships scaffolding that benefits from two community plugins. Both are **soft requirements** — `Home.md` degrades gracefully when either is missing, replacing live queries with static "missing plugin" notices.

| Plugin | Why |
|--------|-----|
| [Dataview](https://github.com/blacksmithgu/obsidian-dataview) | Powers task aggregation and dashboards in `Home.md`. |
| [Tasks](https://github.com/obsidian-tasks-group/obsidian-tasks) | Date parsing for `📅`, `✅`, `🔁` task emoji. |

No other plugins are required.

---

## What sb-os Is

- A directory convention — PARA + Workbench + periodic notes + an optional wiki slot + a config dir
- A small set of installable agent components — skills, commands, rules, workflows
- An installer that bootstraps a clean vault or upgrades an existing install idempotently
- A documentation surface so users and agents share the same mental model

## What sb-os Is NOT

- A vault template you copy and edit by hand
- A monolithic personal-everything system — financial automations, journals, and per-life-area workflows stay in your `.user/` folder, not in sb-os
- A replacement for Obsidian, for the original "Building a Second Brain" methodology, or for a general task manager

---

## Repository Layout

The repo is small. The installer at `install.py` parses flags and dispatches to `admin/install/` mode handlers. Source files for everything that ships into a vault live in named top-level folders.

| Path | Contents |
|------|----------|
| `install.py` | Entry point — flag parsing, mode auto-detection, dispatch |
| `admin/install/` | Installer internals (CLI, manifest, marker handling, mode handlers) |
| `workflows/` | Source of truth for `sb-*` workflows |
| `templates/` | Source of truth for ship-to-vault templates |
| `skills/` | Source files for `sb-*` skill loaders |
| `commands/` | Source files for `sb-*` command loaders |
| `rules/` | `sb-*` rule files; copied verbatim into `.claude/rules/` |
| `claude-mds/` | Managed CLAUDE.md sources; filename encodes install destination |
| `dashboards/` | Marker-managed dashboard scaffolds (e.g., `Home.md`) |
| `docs/` | Architecture, conventions, hooks reference |

Detail and rationale: [`docs/architecture.md`](./docs/architecture.md).

---

## Customization Model

sb-os is opinionated, not invasive. Two principles govern what is yours and what is sb-os's:

1. **Managed marker blocks are sb-os's.** Every managed CLAUDE.md and `Home.md` contains a region wrapped in `<!-- sb:start v=1 -->...<!-- sb:end -->`. The installer rewrites that region verbatim on every `--upgrade`. Edit it and your changes will be lost on the next run.
2. **Everything outside the markers is yours.** Content above and below the marker block is preserved. Add your own routing rules, conventions, and notes — sb-os will not touch them.

Thin loaders in `.claude/skills/` and `.claude/commands/`, and rule copies in `.claude/rules/`, are rewritten on every install. **Edit the source in this repo, not the installed copy.** Re-run `python install.py --upgrade` after editing.

`.claude/settings.json` is user-managed. The installer never creates or modifies it. See [`docs/hooks.md`](./docs/hooks.md) for snippets to paste in manually.

---

## License

MIT — see [`LICENSE`](./LICENSE).

---

## Contributing

Contributions welcome — issues and pull requests both.

**Editing rules:**
- Edit source files in this repo, never installed loaders or rule copies in a target vault.
- Behavior changes require updating `docs/architecture.md` first; the architecture doc is the spec.
- Workflow directories contain only step files, data, scripts, and templates — documentation lives in `docs/`.

**To get started:**

```bash
git clone https://github.com/hlealt/sb-os.git
cd sb-os
python install.py --help
```

Architecture and design rationale: [`docs/architecture.md`](./docs/architecture.md).
