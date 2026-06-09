# No Task Forgotten

**MANDATORY. NO EXCEPTIONS.** When a job finalizes with a deferred loose end, you MUST write that loose end to the vault as a task — carrying enough context that a fresh agent with no memory of this session can execute it — BEFORE declaring the job done or handing it back. A loose end left in chat or memory is a forgotten task.

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

Sequencing gate plus required output. You MUST NOT declare the job done or hand it back until every deferred loose end is captured or surfaced.

| Phase | Requirement |
|-------|-------------|
| 1. Capture | For EACH loose end, write it as a task via `sb-vault-ops` — which routes it to the correct `{name}-tasks.md` and enforces cold-start sufficiency (a fresh agent can execute it from the task text alone). Capture directly; ask the user only if routing is genuinely ambiguous. |
| 2. Disclose | In the closing message, name each captured task and its file — e.g. "Logged 2 follow-ups: `finance-system-tasks.md` → Reconcile April broker statement; Fix duplicate-dividend parse." This visible line is the compliance artifact. |

**Orchestrated runs:** the agent that owns vault writes performs the capture. A worker without vault-write MUST surface each loose end in its structured return so the owning agent captures it — a loose end may never vanish at a dispatch boundary.

## Anti-Patterns

| Type | Thought | Action |
|------|---------|--------|
| Skip | "The work's basically done — I'll just mention the follow-up in chat" | Chat is ephemeral; a mentioned-but-unwritten loose end IS a forgotten task. Write it as a task. |
| Skip | "This loose end is too small to capture" | The triviality floor exempts the JOB, not the loose end. A real deferred unit gets captured regardless of size. |
| Game | "I'll write a stub task now and fill in the context later" | Later is never. Meet cold-start sufficiency at write time — the next agent has only the task text. |
| Game | "The next agent will figure out the context from the code" | The next agent has zero memory of this session. Encode what you know now: paths, decisions made and why, the state work was left in, what was tried and ruled out. |
| Game | "To be safe I'll capture every idea I had" | Over-capture. Only the four loose-end classes qualify — speculative nice-to-haves do not. |
| Game | "I'll just say there were no loose ends" | If the job deferred, discovered, left-partial, or hit a blocker, "none" is false. The four classes make this checkable. |

## Scope

All-work and forward-looking: this rule captures what was deliberately NOT done so no follow-up is lost. It owns ONLY when to capture and the disclosure; it delegates task format, routing, and the cold-start sufficiency standard to `sb-vault-ops`. It does not change how existing tasks are written, and it does not govern proving that completed work works.
