# Hooks

Reference snippets for Claude Code hooks that complement sb-os. The installer **auto-wires the context-injection hook** into `.claude/settings.local.json` (see [Auto-installed hook](#auto-installed-hook-context-injection) below). All other snippets in this document remain user-managed — paste them into your own `settings.json` manually.

---

## What Claude Code hooks are

Claude Code supports lifecycle hooks that fire at specific points in an agent session — common event names include `PreToolUse`, `PostToolUse`, and `UserPromptSubmit`. Each hook matches against tool names and/or arguments and runs a configured command. Hooks are configured under the `hooks` key in `.claude/settings.json` (or the user-level settings file).

This document gives example shapes that complement sb-os workflows. The authoritative source for hook syntax, supported events, and matcher semantics is your Claude Code harness documentation — adapt the snippets below to whatever your harness expects.

---

## Recommended hooks for sb-os

### 1. Run `sb-vault-integrity` only after structural vault mutations

Trigger the structural sweep only after operations that move, rename, or delete vault files; create project/area/resource directories; or create vault files that change routing or dependencies.

Do NOT invoke `sb-vault-integrity` on every `Edit`, `Write`, or `MultiEdit`. If your harness cannot filter by operation/path, do not install this hook.

Example shape:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "if": "<structural vault mutation predicate>",
            "command": "claude skill invoke sb-vault-integrity"
          }
        ]
      }
    ]
  }
}
```

### 2. Log work-log entries via an archivist hook

If you keep an archivist workflow that logs edits to a work log, fire it after `Edit`, `Write`, and `MultiEdit`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "claude skill invoke sb-archivist"
          }
        ]
      }
    ]
  }
}
```

### 3. Inject user context on prompt submit

> **SUPERSEDED — do NOT install.** This is the historical MANUAL `UserPromptSubmit` snippet from before context-injection was auto-wired. It is now replaced by the [Auto-installed hook: context-injection](#auto-installed-hook-context-injection) below, which the installer wires into `.claude/settings.local.json` (sentinel `"__sb__": "sb:context-injection"`) on every `python install.py` run. Do NOT install this snippet alongside the auto hook — it is retained only as a reference for the old manual approach.

Run `sb-inject-context` on every user prompt so the configured `user_context_root` is consulted for the active workflow step:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "claude skill invoke sb-inject-context"
          }
        ]
      }
    ]
  }
}
```

These snippets show the **shape** of the config; adapt the `command` field to whatever invocation form your harness supports.

### 4. Finance — structural non-overlap (ME) gate (pre-commit + quarterly)

If the finance module is installed, run the structural non-overlap gate as a pre-commit check so a commit that introduces a **second store for an already-tracked concept** (a new vendor→category dict when `suppliers.json` already owns it, a parallel tag file, etc.) is refused before it lands. The gate detects overlap at the SEMANTIC level against the 23 p2-7 sources-of-truth domains — not a filesystem existence check. Exit 0 = no overlap (allow), exit 1 = overlap (block).

Pre-commit, sweeping a manifest of the stores a change proposes (a JSON list of `{ "concept": "...", "target": "...", "keys": [...], "store_name": "..." }`):

```bash
python 3-resources/tools/sb-os/finance/scripts/shared/me_gate.py --manifest proposed-stores.json
```

The same command is the **quarterly** drift sweep: run it over the full set of stores/configs to confirm no overlapping store crept in between closes. Pair it with the deferred cross-config duplicate auditor (`audit-data-duplication.py`, plan task p5-12) once that ships — the gate composes it automatically and reports it as not-yet-built until then. This is distinct from the doc-currency hard-block hook (§5 below), which blocks on stale docs, not on store overlap.

### 5. Finance — doc-currency HARD BLOCK (pre-commit)

If the finance module is installed, run the doc-currency check as a pre-commit hook so a commit that changes a **coupled code/config surface without updating the doc that describes it** is refused before it lands. This is **layer 3** of the documentation-currency Option D Hybrid mechanism (`finance/CLAUDE.md` § Documentation Currency). It is a HARD block, not advisory: an advisory hook lets documentation drift accumulate exactly when it matters. The block message names the stale doc + the fix; the only pass-path is reconciling the doc (run the `doc-maintainer` companion, stage the doc, re-commit) — there is no per-hook bypass flag.

The checker reads the shared coupling manifest (`finance/docs/doc-currency-manifest.yaml` — the same manifest the layer-2 `docs_potentially_stale` audit signal reads) and the staged diff. Exit 0 = no coupled change is missing its doc (allow); exit 1 = a coupled code/config change has no staged doc (block); exit 2 = the manifest is unreadable (block — a broken gate must not silently allow).

A TRACKED hook wrapper ships at `hooks/pre-commit-doc-currency`. As with every sb-os hook, the installer **never** writes to `.git/hooks/` — activate it deliberately:

```bash
# from the sb-os repo root:
chmod +x hooks/pre-commit-doc-currency
ln -s ../../hooks/pre-commit-doc-currency .git/hooks/pre-commit
```

Or invoke the checker directly (what the wrapper runs):

```bash
python finance/scripts/shared/doc_currency_check.py
```

**If a pre-commit hook already exists** (e.g. the ME gate from §4), do NOT overwrite it — chain both from a single `.git/hooks/pre-commit` so each runs and any non-zero exit blocks:

```sh
#!/usr/bin/env sh
# .git/hooks/pre-commit — run both finance gates; first failure blocks.
REPO_ROOT=$(git rev-parse --show-toplevel) || exit 2
# ME structural non-overlap gate (§4) — pass it the manifest your change proposes:
# python "$REPO_ROOT/finance/scripts/shared/me_gate.py" --manifest proposed-stores.json || exit $?
sh "$REPO_ROOT/hooks/pre-commit-doc-currency" || exit $?
```

> **Activation safety.** Before activating this hook, verify the CURRENT working tree passes it (`python finance/scripts/shared/doc_currency_check.py`); a stale doc would otherwise block your next commit until reconciled. The hook only inspects STAGED changes, so it never blocks a commit that touches no coupled code/config surface (a docs-only or unrelated commit always passes).

---

## Auto-installed hook: context-injection

The context-injection hook is the ONE hook sb-os auto-wires into a target vault. The installer writes it into `.claude/settings.local.json` (the `.local.` variant, not `settings.json` proper) on every fresh install and upgrade.

### What it does

The hook fires `para/workflows/sb-inject-context/resolve_context.py --hook` to inject per-surface user context automatically — replacing the retired `sb-workflow-context` rule. It installs two entries:

| Event | Matcher | Effect |
|-------|---------|--------|
| `PreToolUse` | `Skill` | Fires before any skill invocation; injects the skill's YAML context before the skill body runs |
| `PostToolUse` | `Read` | Fires after every file read inside a workflow or skill; injects step-level user context |

Both entries call `python "$CLAUDE_PROJECT_DIR/{sb_os_path}/para/workflows/sb-inject-context/resolve_context.py" --hook`, substituting `{sb_os_path}` with the path recorded in `sb-os.json`.

Schema and YAML contract reference: `para/docs/context-injection-schema.md`.

### Sentinel and idempotence

Each installed entry carries `"__sb__": "sb:context-injection"` as a sentinel key. The installer uses this sentinel (plus a command-path-signature fallback) to identify and manage its own entries — adding them on install, removing them on uninstall. Foreign keys and entries in `settings.local.json` are preserved unchanged. Re-running `python install.py` is idempotent.

### Opt out

Add `"context-injection-hook"` to `excluded_components` in the target vault's `sb-os.json`:

```json
{
  "excluded_components": ["context-injection-hook"]
}
```

On the next `python install.py` run, the installer calls `remove_context_hook` and strips the two sentinel-tagged entries from `settings.local.json`.

---

## Maintenance

The example snippets above (§1–§5) are user-managed — sb-os will never modify your `settings.json`. Add or remove them by hand. The context-injection hook in `settings.local.json` is the sole exception: it is managed by the installer and should be controlled via `excluded_components`, not edited by hand.

If you remove sb-os from a vault, delete any remaining hook entries in `settings.local.json` by hand (or run `python install.py` with `excluded_components: ["context-injection-hook"]` first to let the installer strip them cleanly).
