# No Task Forgotten

**MANDATORY. NO EXCEPTIONS.** When a job finalizes with a deferred loose end, you MUST resolve that loose end — execute it inline if it passes the Execute-Inline Test below, otherwise write it to the vault as a task carrying enough context that a fresh agent with no memory of this session can execute it — BEFORE declaring the job done or handing it back. A loose end left in chat or memory is a forgotten task.

## Trigger and Scope

**Activates when** a job finalizes — the moment you are about to report a unit of work complete, hand it back, or end your turn on it — AND at least one **deferred loose end** exists. A "job" is any substantive task, dispatch, or user request.

A deferred loose end is one of these — and ONLY these:

| Class | Means |
|-------|-------|
| Deferred | Work you explicitly put off ("do X later", "out of scope for now") |
| Discovered out-of-scope | A real, needed unit of work you found while working that is not part of this job |
| Partial completion | The job is closing with a known piece unfinished |
| Surfaced blocker/bug | A defect or blocker you hit and left unaddressed |

**Does NOT activate when:**

- The job is fully complete with no loose end of the four classes above.
- The only candidates are speculative improvements or nice-to-haves nobody requested — these are NOT loose ends.
- Triviality floor: the job itself was trivial (typo, formatting, lookup, single rename).
- The loose end is ALREADY a task — never duplicate; enrich the existing task via `sb-vault-ops`.

## The Gate

Sequencing gate plus required output. You MUST NOT declare the job done or hand it back until every deferred loose end is executed inline or captured or surfaced.

| Phase | Requirement |
|-------|-------------|
| 1. Triage | Run EACH loose end through the Execute-Inline Test below. Pass → execute it now and verify it in-session. Fail → capture it. |
| 2. Capture | For each loose end NOT executed inline, write it as a task via `sb-vault-ops` — which routes it to the correct `{name}-tasks.md` and enforces cold-start sufficiency (a fresh agent can execute it from the task text alone). Capture directly; ask the user only if routing is genuinely ambiguous. |
| 3. Disclose | In the closing message, name each executed fix AND each captured task with its file — e.g. "Fixed inline: stale path in `dashboard.md`. Logged 1 follow-up: `finance-system-tasks.md` → Reconcile April broker statement." This visible line is the compliance artifact for both branches. |

## Execute-Inline Test

A loose end is executed inline INSTEAD of captured ONLY when ALL three hold:

1. **Mechanical and unambiguous** — no design decision, no judgment call, one obviously correct fix.
2. **Minutes, with context already loaded** — completable in a few minutes using the files and understanding already in this session; no new investigation.
3. **Verifiable in-session** — the fix's correctness can be confirmed before closing (a re-read, a re-run, a lint).

**Never execute inline, regardless of size** — always capture (or ask) instead:

- Destructive or irreversible actions (deletes, archive moves, git history changes).
- Anything whose fix depends on an owner decision, preference, or open question.

**Bail-out:** if an inline fix turns out bigger than the test predicted, STOP — revert the partial work and capture the loose end as a task, recording what the attempt revealed.

**Orchestrated runs:** the agent that owns vault writes performs the capture. A worker without vault-write MUST surface each loose end in its structured return so the owning agent captures it — a loose end may never vanish at a dispatch boundary.

## Anti-Patterns

| Type | Thought | Action |
|------|---------|--------|
| Skip | "The work's basically done — I'll just mention the follow-up in chat" | Chat is ephemeral; a mentioned-but-unwritten loose end IS a forgotten task. Write it as a task. |
| Skip | "This loose end is too small to capture" | The triviality floor exempts the JOB, not the loose end. A real deferred unit is executed inline or captured — never dropped. |
| Game | "It's smallish — I'll call it inline-eligible and skip the capture ceremony" | The Execute-Inline Test is three conjunctive checks, not a vibe. Any doubt on any check → capture. |
| Game | "The inline fix grew, but I've started — I'll just finish it" | Finishing an oversized fix is scope creep. Bail out: revert and capture. |
| Game | "I'll write a stub task now and fill in the context later" | Later is never. Meet cold-start sufficiency at write time — the next agent has only the task text. |
| Game | "The next agent will figure out the context from the code" | The next agent has zero memory of this session. Encode what you know now: paths, decisions made and why, the state work was left in, what was tried and ruled out. |
| Game | "To be safe I'll capture every idea I had" | Over-capture. Only the four loose-end classes qualify — speculative nice-to-haves do not. |
| Game | "I'll just say there were no loose ends" | If the job deferred, discovered, left-partial, or hit a blocker, "none" is false. The four classes make this checkable. |

## Scope

All-work and forward-looking: this rule resolves what was deliberately NOT done so no follow-up is lost. It owns ONLY the execute-vs-capture triage, when to capture, and the disclosure; it delegates task format, routing, and the cold-start sufficiency standard to `sb-vault-ops`. An inline execution remains subject to every other gate that governs the touched path (source-of-truth, vault-ops, commit discipline). It does not change how existing tasks are written, and it does not govern proving that completed work works.
