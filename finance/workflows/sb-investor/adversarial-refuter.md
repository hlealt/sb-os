---
stepId: investor-adversarial-refuter
runtime: agent-loop
---

# Adversarial Refuter (shared, optional, cross-mode)

The `/sb-investor` shared refuter-dispatch workflow. An **independent second model** that can ONLY refute the drafted argument the calling mode is about to present — it never generates its own findings. `review` / `thesis` / `decision` read-and-follow this file at their present-and-confirm checkpoint when the user elects `[R]`; the refutation is surfaced beside the draft as a distinct critique block, and the user still decides `[S] / [E] / [N]`. This file owns the CONTRACT, the DISPATCH MECHANISM, the BACKENDS, and the INVARIANTS. Each calling mode owns its own rubric and passes it in.

**Loaded by:** a calling mode reads-and-follows this file ONLY after the user elects `[R]` at that mode's checkpoint. Read `./investor-loop.md` before acting.

**Opt-in, never auto-fires.** This workflow runs ONLY on an explicit `[R]` election (or an always-on `research-policy.md` key, schema settled in `p4-2` — until then `[R]` is the sole trigger). It is never the default path and never blocks the checkpoint: if the refuter is not elected, or fails, the mode presents its draft unchanged.

---

## What the refuter IS and IS NOT

| The refuter MUST | The refuter MUST NEVER |
|------------------|------------------------|
| Read the drafted artifact + its already-cited sources in its OWN context | Fetch the web, run a search, or read ANYTHING outside the closed read-set |
| Return a structured per-rubric-item verdict + the disconfirming reason | Generate a new finding, source, claim, or evidence item |
| Run exactly once (single-pass), then return | Loop, re-draft, or iterate on its own output |
| Stay read-only and persist nothing | Write any file, page, ledger, policy, or capture |
| Feed its critique to the existing checkpoint for the user to weigh | Auto-act on its verdict, edit the draft, or bypass `[S]/[E]/[N]` |

Reading already-cited sources is NOT generating findings — the refuter weighs evidence the draft already rests on; it acquires nothing new. The no-generation contract holds because the refuter's input set is closed (artifact + its citations) and it returns only a verdict over that set.

---

## Step 1 — Assemble the dispatch input (the calling mode does this before dispatch)

The calling mode hands the refuter a CLOSED input set. Assemble all four; pass nothing else:

| Input | What it is | Source |
|-------|-----------|--------|
| **Drafted artifact** | The exact draft the mode is about to present at its checkpoint (thesis draft / review verdict block / decision record) | The calling mode's pre-checkpoint output |
| **Cited sources** | Every source the draft cites, passed as a CLOSED READ-SET in one of two transports: **inline** (full text in the prompt — small payloads) or **by path** (the explicit list of cited file paths — the default for large payloads, e.g. multi-MB raw captures). Path transport authorizes the refuter to read the LISTED files ONLY — never anything beyond the list. Either transport keeps the input set closed and the full text out of the parent (anti-context-rot) | The captured `raw/` + wiki source/entity pages the draft references |
| **The calling mode's rubric** | The per-rubric-item list of attack questions THIS mode defines (thesis rubric / review rubric / decision rubric) — see § Rubric schema | The calling mode (`review`/`thesis`/`decision`), never this file |
| **`research-policy` scope** | The scope / exclusions loaded at the mode's Step 1 policy gate — bounds what the refuter treats as in-scope | Already loaded by the calling mode per `./investor-loop.md` § Policy read-rules wiring |

The calling mode supplies the rubric text. This file NEVER hard-codes the thesis/review/decision rubric — it references "the calling mode's rubric" and defines only its SHAPE (below).

## Step 2 — Select the backend (`auto`)

Selection is `auto`: the default backend is a fresh-context Claude sub-agent. The Codex CLI backend is used ONLY when BOTH hold: (a) the user has opted into Codex (via the always-on key once `p4-2` defines it, or an explicit per-run request), AND (b) Codex is present and runnable on this machine. In every other case — Codex not selected, absent, slow, or erroring — the refuter runs on the sub-agent.

| Condition | Backend |
|-----------|---------|
| Codex not opted into | **Sub-agent** (default) |
| Codex opted into AND `codex` resolves AND the exec call returns within timeout | **Codex CLI** |
| Codex opted into BUT absent / non-runnable / times out / errors | **Sub-agent** (auto-fallback) + a one-line note: `Refuter ran on the Claude sub-agent backend (Codex {unavailable | timed out | errored}).` |

A Codex failure NEVER blocks the checkpoint and NEVER aborts the mode — it falls back to the sub-agent. If the sub-agent ALSO cannot run (no dispatch capability in the current context), surface that per `./investor-loop.md` § Issue-surfacing as a deferrable note and present the draft WITHOUT a refutation — the user still gets the `[S]/[E]/[N]` choice. The refuter is additive; its absence degrades gracefully.

## Step 3a — Backend: Claude sub-agent (default)

Dispatch ONE sub-agent (per `./investor-loop.md`; default model per `sb-sub-agents`). Its prompt MUST be SELF-CONTAINED — it requires NO web skill and NO vault skill; with inline transport it reads ONLY what the prompt carries and needs NO tool access; with path transport its ONLY tool access is read-only (Read/Grep) on the listed read-set paths. The prompt MUST:

1. State the refute-only role: *"You are an adversarial reviewer. You may ONLY refute the argument below. You MUST NOT add new findings, fetch anything, run a search, or rewrite the draft. Read the draft and its cited sources, then return a verdict for each rubric item."*
2. Carry the four inputs from Step 1 (drafted artifact, cited sources — inline text OR the closed read-set path list per § Step 1, the rubric items, the policy scope). With path transport, state the closure explicitly: *"You may Read/Grep ONLY the files listed below; reading ANY other path is forbidden."*
3. Demand the § Output schema verbatim — one verdict row per rubric item, nothing else: the response MUST BEGIN with the `## Adversarial critique` heading and END after the last verdict; any preamble or trailing prose is a contract violation.
4. Forbid generation explicitly: *"If a rubric item cannot be judged from the draft + cited sources alone, mark it `survives` and note 'not assessable from the cited evidence' — NEVER hunt for new evidence."*

The sub-agent returns ONLY the structured verdict. Full source text stays in the sub-agent's context; only the verdict crosses back to the parent (anti-context-rot — the parent context stays clean, the same pattern as the `research` Disconfirm wave).

## Step 3b — Backend: Codex CLI (opt-in)

Run Codex non-interactively via Bash, in read-only sandbox, prompt on stdin, final message on stdout. **Verified on this machine (codex-cli 0.129.0, 2026-06-01):**

```bash
codex exec \
  --sandbox read-only \
  --skip-git-repo-check \
  --ephemeral \
  --color never \
  -m "$CODEX_MODEL" \
  -o "$LAST_MSG_FILE" \
  -
```

| Flag | Why |
|------|-----|
| `exec` | The non-interactive subcommand (alias `e`). Runs once and exits — no TUI, no session loop. |
| `--sandbox read-only` | The refuter MUST NOT write. `read-only` forbids all model-generated writes at the backend level — the no-generation/read-only contract holds even if the prompt were ignored. |
| `--skip-git-repo-check` | The refuter operates on passed-in TEXT, not a repository; allows running outside a git repo. |
| `--ephemeral` | No session files persisted — the refuter leaves no on-disk trace (own-workspace-writes boundary). |
| `--color never` | Clean, parseable stdout (no ANSI escapes). |
| `-m "$CODEX_MODEL"` | The opt-in second model (a DIFFERENT model than the drafting agent — the independence the refuter exists for). |
| `-o "$LAST_MSG_FILE"` | Writes ONLY the agent's final message to a file for clean capture; stdout still streams progress. Read this file for the verdict. (Omit to read the final message from stdout directly.) |
| `-` (trailing) | Read the prompt from stdin — pipe the same self-contained refute-only prompt as Step 3a (role + four inputs + output schema + no-generation clause). |

**Timeout:** wrap the call at **120 s**. On timeout, SIGTERM the process and fall back to the sub-agent per Step 2 + emit the one-line note. The prompt piped to stdin is the SAME self-contained refute-only prompt the sub-agent receives — with inline transport Codex reads everything from the prompt; with path transport its read-only sandbox reads the LISTED read-set files only (the prompt forbids any path beyond the list); it never reads the web either way.

> If `codex` does not resolve on a given machine (a non-Codex installer), Step 2 routes to the sub-agent automatically. The command above is the verified invocation where Codex IS present; its absence is a documented, graceful fallback, NOT an error.

## Step 4 — Return the critique to the calling mode (single-pass)

The refuter runs ONCE and returns its structured verdict to the calling mode. This file does NOT present to the user — it hands the verdict back; the calling mode renders it as a distinct **"Adversarial critique"** block beside its draft at the EXISTING checkpoint (per the calling mode's own step). Per `shape.md` § 2026-06-01 decision #5:

- The refutation reaches the user **RAW + flagged** — intact, as its own block; the investor may add a one-line agree/disagree per item but NEVER edits or suppresses it.
- The refuter NEVER loops. Valid points the user accepts fold into the draft via the EXISTING `[E]` edit path at the mode's checkpoint — not by re-running the refuter.
- The user's `[S]/[E]/[N]` decision is unchanged: the critique informs it; it does not replace it.

---

## Rubric schema (the SHAPE; the calling mode supplies the items)

Each calling mode passes a rubric = an ordered list of attack questions. The refuter returns one verdict per item. This file defines ONLY the shape; the item text lives in `review.md` / `thesis.md` / `decision.md`.

**Input shape (per rubric item):** a single attack question — "what about this draft, tested against its own cited evidence, would falsify or weaken it?"

**Output schema (the verdict the refuter returns — verbatim):**

```
## Adversarial critique ({backend} backend)

1. {rubric item, restated in one line}
   Verdict: overturned | weakened | survives
   Reason: {the disconfirming reason — what in the draft or its cited sources falsifies/weakens the item; for `survives`, why the item holds against its own evidence}
   [Source: #{n}]   ← cite the draft's existing footnote when the reason rests on a cited source

2. {next rubric item}
   ...
```

| Verdict | Meaning |
|---------|---------|
| `overturned` | The draft's own cited evidence, or an internal-logic gap, falsifies this item |
| `weakened` | The item is not falsified but is materially undercut — evidence is thinner, hedged, or partly contradicted |
| `survives` | The item holds against the draft + its cited sources (including "not assessable from the cited evidence" — never a prompt to hunt) |

The refuter returns NOTHING beyond this block — the response BEGINS at the `## Adversarial critique` heading and ENDS after the last verdict: no prose preamble, no closing remarks, no recommendation, no new sources, no draft edits.

---

## Invariant preservation (each consuming mode inherits this by reference)

A calling mode that dispatches this refuter inherits ALL of the following — it does NOT re-state them; it references this section. Re-checked at the Phase 4 checkpoints against `./investor-loop.md`.

| Invariant | How the refuter preserves it |
|-----------|------------------------------|
| **Read-only** (`./investor-loop.md` § Read-only invariant) | Reads the artifact + already-cited sources only. No position data, no ledger, no `portfolio.json`, no dashboard — directly or via any path. The Codex backend enforces this with `--sandbox read-only`. |
| **No-generation** (plan Architectural-Constraints refuter row) | Closed input set (artifact + its citations). Returns ONLY verdicts. Never fetches the web, runs a search, reads outside the read-set, or emits a new finding/source/claim. An unjudgeable item is `survives`, never a hunt. |
| **Tools-only data access** (`./investor-loop.md` § Tools-only) | The refuter touches NO position data, so no read tool is involved. It reads ONLY the markdown the calling mode passed in or listed (the closed read-set) — not the store. |
| **Own-workspace-writes / delegate-not-replace** (`./investor-loop.md` § Own-workspace-writes boundary) | The refuter persists NOTHING — no page, source, policy, capture, or session file (`--ephemeral`). It produces a critique; the calling mode and its scribe own all persistence. |
| **Present-and-confirm** (`./investor-loop.md` § Present-and-confirm) | The critique feeds the EXISTING checkpoint as a distinct block; the user still decides `[S]/[E]/[N]`. The refuter never persists or acts on its verdict and never collapses the checkpoint. |
| **Single-pass / interactive rhythm** (plan Architectural-Constraints) | Runs exactly once and returns; never loops. It is one informational block at one already-present checkpoint — it adds no new STOP and buries no rhythm. |
| **Anti-context-rot** (`shape.md` Constraints) | Full source text stays in the refuter's own context (sub-agent or Codex process); only the structured verdict crosses back. With path transport the full text never even transits the parent — the refuter reads the listed files in its own context. The parent context stays clean — same pattern as the `research` Disconfirm wave. |
| **Portability** (`sb-source-of-truth`; `shape.md` § 2026-06-01 #1) | Backend-agnostic: default Claude sub-agent needs no plugin; Codex is opt-in with auto-fallback. A non-Codex installer is never broken — the refuter runs on the sub-agent. |
| **Rule A / per-step checkpoint / watchlist** (`./investor-loop.md`) | Untouched. The refuter introduces no out-of-structure act, no watchlist change, and runs inside the calling mode's existing checkpoint. |

A failed or unavailable refuter NEVER blocks the checkpoint: the calling mode presents its draft unchanged and the user proceeds. The refuter is strictly additive — it can sharpen a decision but can never gate, persist, or act.

---

## Boundaries (this workflow)

- Read-only: reads ONLY the passed-in artifact + its cited sources (inline or via the closed read-set paths); never position/ledger/dashboard data, never the web, never any file outside the read-set.
- Refute-only / no-generation: returns ONLY a per-rubric-item verdict; never a new finding, source, draft edit, or persisted file.
- Backend-agnostic: Claude sub-agent default; Codex CLI opt-in via the verified `codex exec --sandbox read-only` invocation; absent/slow/error → sub-agent fallback + a one-line note.
- Single-pass: runs once, returns the critique, never loops. Accepted points fold in via the calling mode's `[E]` path, never a re-run.
- The critique only feeds the calling mode's existing present-and-confirm checkpoint; the user decides `[S]/[E]/[N]`. The refuter never bypasses, collapses, or gates that checkpoint.
- A request that would let the refuter generate findings, persist, call a tool, fetch the web, or bypass the checkpoint is out-of-structure → Rule A in `./investor-loop.md`.
