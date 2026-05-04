# Hooks

Reference snippets for Claude Code hooks that complement sb-os. The sb-os installer **never** writes to `.claude/settings.json` — paste these snippets into your own settings.json manually.

---

## What Claude Code hooks are

Claude Code supports lifecycle hooks that fire at specific points in an agent session — common event names include `PreToolUse`, `PostToolUse`, and `UserPromptSubmit`. Each hook matches against tool names and/or arguments and runs a configured command. Hooks are configured under the `hooks` key in `.claude/settings.json` (or the user-level settings file).

This document gives example shapes that complement sb-os workflows. The authoritative source for hook syntax, supported events, and matcher semantics is your Claude Code harness documentation — adapt the snippets below to whatever your harness expects.

---

## Recommended hooks for sb-os

### 1. Run `sb-vault-integrity` after vault file mutations

Trigger the structural sweep after any tool call that creates, moves, renames, or deletes a vault file. Example shape:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          {
            "type": "command",
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

---

## Maintenance

These hooks are user-managed. sb-os will never modify your `settings.json`. Re-run `python install.py` after editing settings.json — the upgrade does not touch your hooks.

If you remove sb-os from a vault, delete the corresponding hook entries by hand.

---

## Status

Hook auto-write into `.claude/settings.json` is deferred to v2 — see [`known-issues.md`](./known-issues.md) for the current row tracking this. The v1 contract is documented snippets only; users opt in by pasting.
