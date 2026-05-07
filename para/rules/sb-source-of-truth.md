---
description: "sb-os source files are overwritten on re-install. Edit in sb-os source repo (location in sb-os.json), then re-run install.py to propagate. Personalization belongs in .user/, never in sb-os source."
---
# sb-os Source of Truth

**MANDATORY. NO EXCEPTIONS.** Every write that touches an installed `.claude/` component OR the sb-os source repo MUST pass the Pre-Edit Gate below before the write executes. Skipping the gate is a rule violation, even for "tiny tweaks" or "I'll port it back later" edits.

sb-os is open-source and shared across vaults. Edits to its source files change behavior for every user who installs or upgrades. Personalization MUST flow through `.user/`, never through sb-os source.

## Pre-Edit Gate

Before EVERY write (Edit, Write, MultiEdit, Bash redirect, etc.) whose target path matches `.claude/**/sb-*`, `{sb_os_path}/**`, or any installed sb-os component, you MUST:

| Step | Question | If YES | If NO |
|------|----------|--------|-------|
| 1. Target | Does the path match `.claude/{rules,skills,commands,agents}/sb-*` or any file under `{sb_os_path}/`? | Continue to step 2 | Gate does not apply — proceed |
| 2. Installed copy? | Is the path under `.claude/` (i.e., an installer-generated loader or copy)? | STOP. Reroute to `{sb_os_path}/{module}/...` per the canonical-locations table below. NEVER edit `.claude/` directly. | Continue to step 3 |
| 3. Personalization? | Does the change encode user-specific data, routing, content, axes, profiles, or behavior that another sb-os user would NOT want? | STOP. Reroute to `.user/` — specifically `{user_context_root}/{workflow-name}/{...}.yaml` for workflow-scoped personalization (per `sb-workflow-context`), or another `.user/` location for non-workflow personalization. NEVER add user-specific content to sb-os source. | Continue to step 4 |
| 4. Behavior or schema change? | Is the change a generic improvement to sb-os behavior, schema, docs, or rule wording that benefits every installer? | Proceed with the edit at the canonical sb-os source path. | STOP. If it is neither personalization nor a generic improvement, ask the user where it belongs before writing. |

The gate fires PER WRITE — every Edit/Write/MultiEdit call against an installer-relevant path triggers a fresh gate.

## Canonical Locations

The canonical source is the sb-os repo. Its path in the target vault is recorded in `sb-os.json` (`sb_os_path` field) at the vault root.

Sources live under per-module folders at the sb-os repo root: `{module}` is `para` or `wiki` depending on which component owns the file.

| What | Edit in sb-os source | Never in target |
|------|----------------------|------------------|
| Rules (`sb-*.md`) | `{sb_os_path}/{module}/rules/<name>.md` | `.claude/rules/sb-*.md` |
| Skills (`sb-*/SKILL.md` and refs) | `{sb_os_path}/{module}/skills/<name>/` | `.claude/skills/sb-*/` |
| Commands (`sb-*.md`) | `{sb_os_path}/{module}/commands/<name>.md` | `.claude/commands/sb-*.md` |
| Workflows | `{sb_os_path}/{module}/workflows/` | *(not installed — referenced via loaders)* |
| Templates | `{sb_os_path}/para/templates/` | `.user/config/templates/` (installed copies) |
| Managed CLAUDE.mds (PARA) | `{sb_os_path}/para/claude-mds/` | Marker-block content in target vault CLAUDE.mds |
| Managed CLAUDE.md (wiki) | `{sb_os_path}/wiki/claude-mds/wiki.md` | Marker-block content in `{wiki_root}/CLAUDE.md` |

## Personalization Routing

sb-os ships generic behavior. User-specific behavior lives in `.user/`. The split:

| Change type | Route to | Example |
|-------------|----------|---------|
| Generic behavior, schema, doc, or rule wording change | `{sb_os_path}/{module}/...` (sb-os source) | Tightening a Pre-Action Gate; renaming a workflow step |
| User-specific instructions for an existing sb-os workflow (axes, content classifiers, routing rules, evaluation criteria) | `{user_context_root}/{workflow-name}/{...}.yaml` (per `sb-workflow-context`) | Tecer-relevance evaluation in `sb-wiki-ingest`; learning-topics capture |
| User profile, preferences, glossary, credentials | `.user/profile/`, `.user/docs/`, `.user/state/` | Personal name glossary; review state |
| User-only workflow that does not ship with sb-os | `.user/workflows/{name}/` plus matching `.claude/` thin loader | accountant, mentor, sb-life-planner |

If the temptation is "let me bake my preference into the sb-os rule/workflow," the answer is almost always: write a YAML under `{user_context_root}/` instead. The workflow-context-injection rule (`sb-workflow-context`) is the supported extension point.

## Why

Edits in `.claude/` are overwritten on every install run — they vanish silently. Edits to sb-os source that encode personalization leak into every other user's vault on the next git pull. The gate exists to prevent both failure modes.

For managed CLAUDE.mds: content INSIDE marker blocks (`<!-- sb:start v=1 -->...<!-- sb:end -->`) is overwritten on every install run; content OUTSIDE markers is preserved.

## Red Flags — STOP and Run the Gate

If you catch ANY of these thoughts, you are about to violate this rule.

| Thought | Action |
|---------|--------|
| "I'll just edit `.claude/rules/sb-foo.md` directly — it's faster" | STOP. The next install overwrites it. Edit `{sb_os_path}/{module}/rules/sb-foo.md`. |
| "I'll patch the sb-os source to add the user's specific routing rule" | STOP. That ships to every sb-os user. Reroute to `{user_context_root}/{workflow}/{file}.yaml`. |
| "This user-specific axis really belongs IN the workflow definition" | STOP. The workflow defines mechanism; the YAML defines policy. Use the YAML. |
| "It's just a small personal tweak — no one else will notice" | STOP. sb-os is open-source. Every personalization in source is a leak into other vaults. |
| "I'll edit sb-os now and port to `.user/` later" | STOP. "Later" means "never." Reroute now. |
| "The install hasn't run yet, so editing `.claude/` is safe this once" | STOP. The next install will run. Reroute now. |
| "There's no matching `.user/context/` directory yet" | STOP. Create it. The graceful-skip semantics in `sb-workflow-context` mean an empty path is fine; what is NOT fine is leaking personalization upstream. |

## After Editing

For content changes (workflows, skill bodies referenced by loaders, templates), just `git pull` in the sb-os source — changes are live immediately for files referenced via loaders.

When a skill, command, rule, or subagent is created, deleted, or renamed, update `install/module-manifest.json` to reflect the change, then re-run the installer:

```bash
python install.py
```

## Canonical Locations

The canonical source is the sb-os repo. Its path in the target vault is recorded in `sb-os.json` (`sb_os_path` field) at the vault root.

Sources live under per-module folders at the sb-os repo root: `{module}` is `para` or `wiki` depending on which module owns the component.

| What | Edit in sb-os source | Never in target |
|------|----------------------|------------------|
| Rules (`sb-*.md`) | `{sb_os_path}/{module}/rules/<name>.md` | `.claude/rules/sb-*.md` |
| Skills (`sb-*/SKILL.md` and refs) | `{sb_os_path}/{module}/skills/<name>/` | `.claude/skills/sb-*/` |
| Commands (`sb-*.md`) | `{sb_os_path}/{module}/commands/<name>.md` | `.claude/commands/sb-*.md` |
| Workflows | `{sb_os_path}/{module}/workflows/` | *(not installed — referenced via loaders)* |
| Templates | `{sb_os_path}/para/templates/` | `.user/config/templates/` (installed copies) |
| Managed CLAUDE.mds (PARA) | `{sb_os_path}/para/claude-mds/` | Marker-block content in target vault CLAUDE.mds |
| Managed CLAUDE.md (wiki) | `{sb_os_path}/wiki/claude-mds/wiki.md` | Marker-block content in `{wiki_root}/CLAUDE.md` |

## Why

Skills, commands, rules, and subagents are thin loaders or copies in `.claude/` that point back to the sb-os source at `{sb_os_path}`. Edits in `.claude/` are lost on the next re-install. The sb-os source is the only durable location.

For managed CLAUDE.mds: content INSIDE marker blocks (`<!-- sb:start v=1 -->...<!-- sb:end -->`) is overwritten on every install run; content OUTSIDE markers is preserved.

## After Editing

For content changes (workflows, skill bodies referenced by loaders, templates), just `git pull` in the sb-os source — changes are live immediately for files referenced via loaders.

When a skill, command, rule, or subagent is created, deleted, or renamed, update `install/module-manifest.json` to reflect the change, then re-run the installer:

```bash
python install.py
```
