# sb-os

> Open-source PARA-based personal knowledge management system for Obsidian with native Claude Code agent integration.

sb-os is an opinionated directory convention plus an installable agent layer for knowledge work in Obsidian. It ships a PARA + Workbench folder structure, a small set of vault-native skills and commands, and an idempotent installer that bootstraps new vaults or upgrades existing ones.

---

## Quick Install

```bash
git clone https://github.com/hlealt/sb-os.git
cd sb-os
python install.py
```

The installer is fully interactive:

1. Walks upward from your current directory looking for an existing `sb-os.json`. If found, it offers to upgrade that install.
2. Otherwise it prompts for a target vault path. If the path holds an `sb-os.json` it runs upgrade; otherwise it bootstraps a fresh vault.
3. On a fresh install, it offers a dry-run preview before any writes, then bootstraps the vault and **moves the running sb-os clone into `{target}/3-resources/tools/sb-os/`** as the final step.

After install, point Obsidian at the vault path. Then open the vault in Claude Code and run:

```
/sb-onboarder
```

The onboarder is an interactive workflow that explains how sb-os works (PARA, periodic notes, workbench, tags, wiki, Home), then walks you through populating your `2-areas/`, `1-projects/`, and (optionally) `3-resources/` folders. It can also build a `Home.md` dashboard and point you at the optional RBTV plugin. State persists in `sb-os.json` so you can pause and resume across sessions.

## Prerequisites

| Requirement | Detail |
|-------------|--------|
| Python | 3.9+ (stdlib only — no `pip install` step) |
| Obsidian | Any recent version |
| Claude Code | Required to consume the agent layer; the directory convention works without it |
| Git on the target vault | **Strongly recommended** before running the installer |

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

## Obsidian Setup

After install, open Obsidian and point it at the vault root (the folder where you ran `python install.py`). Then configure the following:

### Core plugins

Enable in **Settings → Core plugins**:

| Plugin | Setting | Value |
|--------|---------|-------|
| Daily notes | Folder | `0-periodic-notes/daily/` |
| Daily notes | Date format | `YYYY-MM-DD` |
| Daily notes | Template | path to your daily template (optional) |
| Templates | Template folder | `3-resources/tools/sb-os/templates/` or your `.user/templates/` |
| Unique note creator | *(disable)* | Not needed — sb-os uses predictable paths |

### Recommended community plugins

| Plugin | Purpose |
|--------|---------|
| [Calendar](https://github.com/liamcain/obsidian-calendar-plugin) | Visual week/day navigation for periodic notes |
| [Dataview](https://github.com/blacksmithgu/obsidian-dataview) | Dynamic queries across vault content |
| [Templater](https://github.com/SilentVoid13/Templater) | Advanced templating for periodic notes and new files |

### Vault settings

In **Settings → Files & Links**:

- **Default location for new notes** — set to `Same folder as current file` or a specific inbox folder; avoid vault root to keep PARA folders clean.
- **Attachment folder path** — set to a dedicated assets folder (e.g., `3-resources/assets/`) to keep binaries out of content folders.
- **Use [[Wikilinks]]** — leave enabled; sb-os rules and agent components expect Obsidian-flavored wikilinks.

---

## Vault Shape

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
│   ├── CLAUDE.md          [managed]
│   └── tools/sb-os/       [the sb-os clone, relocated here on fresh install]
├── 4-archives/
│   └── CLAUDE.md          [managed]
├── 5-workbench/
│   └── CLAUDE.md          [managed]
├── {wiki_root}/           [optional, default: 3-resources/knowledge-base/]
│   └── CLAUDE.md          [managed, conditional]
├── .user/                 [user-owned; sb-os creates the dir on the initial install and never writes inside it thereafter]
│   ├── {user_context_root}/  [configurable, default: .user/context/]
│   └── ...                [your personal extensions — scripts, configs, anything]
├── .claude/
│   ├── skills/            [thin loaders pointing at the sb-os repo]
│   ├── commands/          [thin loaders]
│   ├── rules/             [verbatim copies of sb-* rules]
│   └── settings.json      [user-managed; sb-os never creates or modifies]
├── sb-os.json             [install manifest at vault root]
└── CLAUDE.md              [managed; markers protect the sb-os section]
```

`Managed` files use HTML-comment marker blocks (`<!-- sb:start v=1 -->...<!-- sb:end -->`). Content inside markers is rewritten on every install run; content outside is yours and preserved verbatim.

---

## Configurable Paths

Two install paths are configurable and persisted in `sb-os.json` at the vault root. They are never hardcoded — every sb-os component resolves them from the manifest.

| Field | Default | Purpose |
|-------|---------|---------|
| `wiki_root` | `3-resources/knowledge-base/` | Optional wiki slot. The installer creates the folder and a managed CLAUDE.md if you opt in. |
| `user_context_root` | `.user/context/` | Where sb-os reads per-step user context (YAML files consumed by `sb-workflow-context`). |

The installer writes both fields with their defaults on a fresh install and preserves the recorded values on subsequent re-installs. Edit `sb-os.json` directly if you want different paths — every sb-os component reads them from the manifest.

---

## Install Modes

The installer auto-detects mode from the presence of `sb-os.json` at the resolved target:

| Detected | Mode | Behavior |
|----------|------|----------|
| No `sb-os.json` | Fresh | Bootstrap a clean vault: create PARA folders, root `CLAUDE.md`, all managed CLAUDE.mds, install thin loaders, write the manifest, and relocate the running sb-os clone into `{target}/3-resources/tools/sb-os/` as the final step. Offers a dry-run preview before any writes. |
| `sb-os.json` present | Upgrade | Refresh the existing install: rewrite `.claude/` loaders, replace marker-block content in managed CLAUDE.mds, refresh rules. Never creates new top-level folders. |

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

### Your Home.md is yours

sb-os does not ship a canonical `Home.md`. The installer never touches it — no managed file, no marker block. Instead, sb-os ships an idea doc describing what a home dashboard is for, what it could surface, and what patterns to avoid. You (or your AI agent) build the actual `Home.md` to your spec. Start with [`ideas/home-dashboard.md`](./ideas/home-dashboard.md), or invoke `/sb-onboarder` and let it build one with you.

---

## Repository Layout

The repo is small. The installer at `install.py` runs the interactive flow and dispatches to `admin/install/` mode handlers. Source files for everything that ships into a vault live in named top-level folders.

| Path | Contents |
|------|----------|
| `install.py` | Entry point — interactive target detection, mode auto-detection, dispatch |
| `admin/install/` | Installer internals (CLI, manifest, marker handling, mode handlers) |
| `workflows/` | Source of truth for `sb-*` workflows |
| `templates/` | Source of truth for ship-to-vault templates |
| `skills/` | Source files for `sb-*` skill loaders |
| `commands/` | Source files for `sb-*` command loaders |
| `rules/` | `sb-*` rule files; copied verbatim into `.claude/rules/` |
| `claude-mds/` | Managed CLAUDE.md sources; filename encodes install destination |
| `docs/` | Architecture, conventions, hooks reference |

Detail and rationale: [`docs/architecture.md`](./docs/architecture.md).

---

## Customization Model

sb-os is opinionated, not invasive. Two principles govern what is yours and what is sb-os's:

1. **Managed marker blocks are sb-os's.** Every managed CLAUDE.md contains a region wrapped in `<!-- sb:start v=1 -->...<!-- sb:end -->`. The installer rewrites that region verbatim on every install run. Edit it and your changes will be lost on the next run.
2. **Everything outside the markers is yours.** Content above and below the marker block is preserved. Add your own routing rules, conventions, and notes — sb-os will not touch them.

Thin loaders in `.claude/skills/` and `.claude/commands/`, and rule copies in `.claude/rules/`, are rewritten on every install. **Edit the source in this repo, not the installed copy.** Re-run `python install.py` after editing.

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
python install.py
```

Architecture and design rationale: [`docs/architecture.md`](./docs/architecture.md).
