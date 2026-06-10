---
stepId: investor-log
runtime: agent-loop
---

# Log Mode (B7 — Resolve the investor log)

The `/sb-investor` capability that reads the investor's actionable log, resolves each entry WITH the user, and DELETES it on resolution. The investor log is a self-executing queue: every entry states why it is there, the exact next action, and why it wasn't done on the spot — a reader works the entry, then the entry is gone (resolution = entry deleted; no resolved history is retained).

**Loaded by:** `./investor.md` reads-and-follows this file when `./capability-manifest.md` routes the `log` intent (an explicit "resolve my log" request) OR when a BARE `/sb-investor` invocation accepts the proactive offer (`./investor.md` § Activation). Read `./investor-loop.md` before acting on any step below.

**Target file:** `.user/finance/investor/log.md` — the investor's own-workspace actionable log (the cross-mode writers append to it via `./investor-loop.md` § Issue-surfacing and § Rule A).

---

## Entry schema (canonical home)

Every entry the investor writes to `.user/finance/investor/log.md` is an actionable H2 entry in this shape — the cross-mode writers (`./investor-loop.md` § Issue-surfacing, § Rule A; `./research.md` deferred captures) emit it, and this mode reads and resolves it:

```
## [YYYY-MM-DD HH:MM] <brief>
- why:      <what surfaced this — the source/run/context>
- action:   <the exact next step an agent or the owner would do>
- deferred: <why it wasn't done on the spot — out of investor scope, needs a build, blocked, etc.>
```

Resolution = the entry is **DELETED** when its `action` is done (or the entry is dismissed). No resolved history; the log holds ONLY unresolved items. NEVER append a `RESOLVED (…)` note — deletion is resolution.

## Read-rule (when this log is read)

Read `.user/finance/investor/log.md` ONLY when:

- a BARE `/sb-investor` invocation fires (the agent proactively offers to work the log — `./investor.md` § Activation), OR
- the user explicitly asks to resolve the log ("resolve my log", "work through my log", "what's in my investor log").

NEVER read it during `research` / `review` / `thesis` / `portfolio` / `decision` / `policy` reasoning — those modes only WRITE deferrable items to it (via Issue-surfacing / Rule A); they never read or resolve it. Reading-to-resolve is exclusive to this mode.

## Flow

### Step 1 — Read and count

Read `.user/finance/investor/log.md`. Parse its H2 entries. File absent or empty → tell the user the log is clear; nothing to resolve; end. Count the unresolved entries (every H2 entry is unresolved — there is no resolved history).

### Step 2 — Present each actionable entry

Present the entries as a numbered list, each showing its `why` / `action` / `deferred` so the user (or you) can act WITHOUT opening the file:

```
You have N unresolved log items:

1. <brief>
   why:      <…>
   action:   <…>
   deferred: <…>
2. …
```

### Step 3 — Resolve each entry (present-and-confirm)

For each entry, run `./investor-loop.md` § Present-and-confirm and propose ONE resolution path:

| Path | When | What happens |
|------|------|--------------|
| **do-in-scope** | The `action` is an investor capability (`research` / `review` / `thesis` / `portfolio` / `decision` / `policy`) | Route/chain to that capability and run it under the loop (each keeps its own checkpoint per `./capability-manifest.md` § Multi-mode chaining); on completion the entry is resolved |
| **route to a companion** | The `action` is out of the investor's read-only structure (a ledger fix, a missing tool to build, a doc to maintain) | Run `./investor-loop.md` § Rule A `[A]` — name the correct owner (`sb-bookkeeper`, the build, a companion); the investor NEVER does the out-of-structure work itself |
| **dismiss** | The item is no longer needed | Record nothing further; the entry is resolved by deletion |

The agent NEVER auto-resolves an entry: each resolution path is confirmed via present-and-confirm before acting. A `do-in-scope` path that itself reaches a persisting/acting step keeps that capability's own checkpoint — this mode does not collapse it.

### Step 4 — Delete the resolved entry

On a confirmed resolution (action done, routed, or dismissed), DELETE that entry (header + body) from `.user/finance/investor/log.md`. This is a targeted entry removal, not an append — honor the parallel-session write discipline in the workspace `CLAUDE.md` (re-read the fresh file state before removing if another session may have written it; remove ONLY the resolved entry, never another session's tail). Deletion IS the resolution record; write no resolved note.

### Step 5 — Close

When every entry the user chose to work is resolved (deleted), report what was resolved and what remains. Items the user deferred again stay in the log unchanged for a future invocation. End at an Investor Checkpoint per `./investor-loop.md` § Per-Step Checkpoint.

---

## Boundaries (this mode)

The loop invariants (`./sb-investor-loop.md` § Read-only invariant, § Tools-only data access, § Own-workspace-writes boundary, § Per-Step Checkpoint) are in force.

- Writes ONLY to `.user/finance/investor/log.md` (deleting resolved entries) inside the own-workspace boundary (`./sb-investor-loop.md` § Own-workspace-writes boundary). Any in-scope action that persists routes through the owning capability's scribe/tool — this mode never hand-writes a thesis, decision, or raw source.
