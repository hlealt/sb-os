# No Task Forgotten

**MANDATORY. NO EXCEPTIONS.** When a job finalizes with a deferred loose end, you MUST resolve that loose end — execute it inline if it passes the Execute-Inline Test below; if it fails the test AND clears the Materiality Bar, write it to the vault as a task carrying enough context that a fresh agent with no memory of this session can execute it; below the bar, name it in the closing disclosure — BEFORE declaring the job done or handing it back. An above-bar loose end left only in chat or memory is a forgotten task.

## Trigger and Scope

**Activates when** a job finalizes — the moment you are about to report a unit of work complete, hand it back, or end your turn on it — AND at least one **deferred loose end** exists. A "job" is any substantive task, dispatch, or user request.

A deferred loose end is one of these — and ONLY these:

| Class | Means |
|-------|-------|
| Deferred | Work you explicitly put off ("do X later", "out of scope for now") |
| Discovered out-of-scope | A real, needed unit of work you found while working that is not part of this job |
| Partial completion | The job is closing with a known piece unfinished |
| Surfaced blocker/bug | A defect or blocker you hit and left unaddressed |

**In-scope work is never a loose end.** Work required to meet the current job's success criteria IS the job — finish it regardless of size or complexity, or, if it genuinely cannot proceed, close it as a surfaced blocker. Reclassifying hard-but-in-scope work as "partial completion" in order to capture it instead of doing it is a violation.

**Does NOT activate when:**

- The job is fully complete with no loose end of the four classes above.
- The only candidates are speculative improvements or nice-to-haves nobody requested — these are NOT loose ends.
- Triviality floor: the job itself was trivial (typo, formatting, lookup, single rename).
- The loose end is ALREADY a task — never duplicate; enrich the existing task via `sb-vault-ops`.

## The Gate

Sequencing gate plus required output. You MUST NOT declare the job done or hand it back until every deferred loose end is executed inline, captured, or disclosed.

| Phase | Requirement |
|-------|-------------|
| 1. Triage | Run EACH loose end through the Execute-Inline Test below. Pass → execute it now and verify it in-session. Fail → run it against the Materiality Bar. |
| 2. Capture | Capture as a task ONLY a loose end that clears the Materiality Bar below. Write it via `sb-vault-ops` — which routes it to the correct `{name}-tasks.md` and enforces cold-start sufficiency (a fresh agent can execute it from the task text alone). Capture directly; ask the user only if routing is genuinely ambiguous. A loose end BELOW the bar that was not executed inline gets one line in the closing disclosure — visibly named, but it does NOT mint a task. |
| 3. Disclose | In the closing message, name each executed fix, each captured task with its file, AND each below-bar find left undone — e.g. "Fixed inline: stale path in `dashboard.md`. Logged 1 follow-up: `finance-system-tasks.md` → Reconcile April broker statement. Below-bar, not done: two stale wiki-links in `notes.md`." This visible line is the compliance artifact for all three branches. |

## Materiality Bar

A loose end that failed the Execute-Inline Test becomes a task ONLY when at least one holds:

1. **Owner decision** — its resolution depends on an owner decision, preference, or open question.
2. **Destructive** — executing it is destructive or irreversible (deletes, archive moves, git history changes).
3. **Standalone unit of work** — it is a genuine, self-contained piece of work with its own outcome, not a nit riding on this job's context.
4. **Blocker** — it blocks this or other known work.

Below the bar → disclosure line only. The backlog is a cost: every captured task is owner attention spent later; the bar exists so small finds are executed or disclosed, never accumulated.

## Execute-Inline Test

A loose end is executed inline INSTEAD of captured ONLY when ALL three hold:

1. **Mechanical and unambiguous** — no design decision, no judgment call, one obviously correct fix.
2. **No new investigation** — executable with the files and understanding already loaded in this session. Size alone is NOT a reason to capture: a fix that stays mechanical is executed even when it takes more than a few minutes.
3. **Verifiable in-session** — the fix's correctness can be confirmed before closing (a re-read, a re-run, a lint).

**Default is EXECUTE.** For a find that is mechanical, non-destructive, and verifiable, execution is the default and capture is the exception — doubt about size resolves toward executing; only doubt about whether the fix is truly mechanical, destructive, or decision-dependent resolves toward the Materiality Bar.

**Never execute inline, regardless of size** — always capture (or ask) instead:

- Destructive or irreversible actions (deletes, archive moves, git history changes).
- Anything whose fix depends on an owner decision, preference, or open question.

**Bail-out:** if an inline fix turns out non-mechanical or needs investigation the test did not predict, STOP — revert the partial work and run the loose end against the Materiality Bar (what the attempt revealed usually clears it; record that context in the task).

**Orchestrated runs:** the agent that owns vault writes performs the capture. A worker without vault-write MUST surface each loose end in its structured return so the owning agent resolves it — a loose end may never vanish at a dispatch boundary. The owning agent runs the full triage (Execute-Inline Test, then Materiality Bar) on each surfaced loose end; blind capture of everything a worker surfaces is a violation, not diligence.

## Anti-Patterns

| Type | Thought | Action |
|------|---------|--------|
| Skip | "The work's basically done — I'll just mention the follow-up in chat" | An ABOVE-bar loose end mentioned only in chat IS a forgotten task — write it. A below-bar find belongs in the closing disclosure line deliberately, not lost mid-conversation. |
| Skip | "This is hard, so I'll log it and call the job done" | In-scope work is never a loose end. Finish it or close it as a blocker — capture is not an exit from the job's own success criteria. |
| Game | "This loose end is too small to bother with" | Small and mechanical → execute it inline. Small and below the bar → disclose it. Neither branch is "drop it silently". |
| Game | "Capturing is safer than executing" | Inverted. For a mechanical, non-destructive, verifiable find, EXECUTE is the default; a minted task spends owner attention later. Capture is for above-bar loose ends only. |
| Game | "The inline fix grew, but I've started — I'll just finish it" | Finishing an oversized fix is scope creep. Bail out: revert and capture. |
| Game | "I'll write a stub task now and fill in the context later" | Later is never. Meet cold-start sufficiency at write time — the next agent has only the task text. |
| Game | "The next agent will figure out the context from the code" | The next agent has zero memory of this session. Encode what you know now: paths, decisions made and why, the state work was left in, what was tried and ruled out. |
| Game | "To be safe I'll capture every idea I had" | Over-capture. Only the four loose-end classes qualify — speculative nice-to-haves do not. |
| Game | "I'll just say there were no loose ends" | If the job deferred, discovered, left-partial, or hit a blocker, "none" is false. The four classes make this checkable. |

## Scope

All-work and forward-looking: this rule resolves what was deliberately NOT done so no follow-up is lost. It owns ONLY the execute-vs-capture triage, when to capture, and the disclosure; it delegates task format, routing, and the cold-start sufficiency standard to `sb-vault-ops`. An inline execution remains subject to every other gate that governs the touched path (source-of-truth, vault-ops, commit discipline). It does not change how existing tasks are written, and it does not govern proving that completed work works.
