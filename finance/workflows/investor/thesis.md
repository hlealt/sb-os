---
stepId: investor-thesis
runtime: agent-loop
---

# Thesis Mode (B1 — Capture)

The `/investor` reasoning mode that turns an informal investment idea into a structured, falsifiable thesis, then delegates persistence to `sb-fin-create-thesis`. **This mode NEVER writes a thesis page** — it reasons; the scribe persists (delegate-not-replace).

**Loaded by:** `./investor.md` reads-and-follows this file when `./capability-manifest.md` routes the `thesis` (B1) intent. The invariants, policy read-rules wiring, present-and-confirm pattern, issue-surfacing, Rule A, and the per-step Investor Checkpoint in `./investor-loop.md` are already in force when this file runs — this file does NOT restate them. Read `./investor-loop.md` before acting on any step below.

**Division of labour (read once, then act):**

| Layer | Owns |
|-------|------|
| This mode (the thinker) | reasoning: claim, hypotheses, causal mechanism, evidence-for AND evidence-against, risks, invalidation criteria; entity selection + position mapping; the present-and-confirm checkpoint |
| `sb-fin-create-thesis` (the scribe) | persistence: slug + collision check, scope-overlap (`extend`/`new`/`abort`), frontmatter, the eight required sections, citation discipline, entity cross-linking, candidate-thesis log resolution, theses index update, `status: active` gating. The agent NEVER re-implements these checks |

---

## Step 1 — Policy gate (MANDATORY)

Before ANY reasoning, load the policy file(s) `../../CLAUDE.md` § Policy Read-Rules requires for an action that REASONS about an investment — per `./investor-loop.md` § Policy read-rules wiring. Authoring a thesis is such an action: `research-policy.md` is required; load `source-policy.md` too when the thesis will cite or weigh sources. NEVER restate the read-rules table — read it.

If `research-policy.md` marks the thesis topic out-of-scope or excluded, say so and STOP, or offer to widen scope via the `policy` thin mode — do not reason past an exclusion (`./investor-loop.md` § Policy read-rules wiring; Rule A).

## Step 2 — Reason the thesis

Develop the thesis content through reasoning. The thesis is a single falsifiable argument; build every required section below. Both-sided evidence and invalidation criteria are NOT optional — they are what makes a thesis falsifiable and what gates `status: active` at the scribe.

| Element | What to reason |
|---------|----------------|
| Claim | The single falsifiable statement the thesis defends — written first |
| Hypotheses | The sub-claims that, if true, make the claim hold — populated from the Step 2a Assumption Audit's testable questions |
| Causal mechanism | WHY the claim would play out — the chain from cause to outcome |
| Evidence for | Concrete, sourced support; tie each item to a captured source filename where one exists |
| Evidence against | MANDATORY and substantive — the strongest disconfirming evidence and counter-arguments; never an empty placeholder. Populated by the Step 2b Disconfirm dispatch (not reasoned from context alone) |
| Risks | What could break the thesis or the position independent of the core claim |
| Invalidation criteria | MANDATORY and substantive — the specific, observable conditions under which the thesis is wrong and must be retired — seeded from the Step 2a Assumption Audit's testable questions on weak assumptions |

The Assumption Audit (Step 2a) is the METHOD that fills `Hypotheses`, `Invalidation criteria`, and the Disconfirm targets; the Disconfirm dispatch (Step 2b) is the METHOD that fills `Evidence against`. They are not new output sections — they are how the elements above get reasoned. Run Step 2a, then Step 2b, then complete the remaining elements.

Surface a problem with the reasoning or its inputs (a source failing the `source-policy` trust bar, a contradicted premise) per `./investor-loop.md` § Issue-surfacing — never pass it silently.

### Step 2a — Assumption Audit (first-principles lens)

The claim rests on hidden assumptions; left implicit, they become the thesis's blind spots. Run this lens as a SINGLE inline pass over the Claim (written first, above) — surface the assumptions, classify each, and rewrite each as a testable question. This is a reasoning lens, NOT a discovery wave: it fetches nothing, writes nothing, and dispatches no sub-agent. Depth is optional — a light pass on a simple claim, a deeper one when the user asks; never a multi-turn interrogation.

1. **List** — surface the assumptions the Claim and its Causal mechanism take for granted (the conditions that must hold for the claim to be true but that the claim does not itself argue).
2. **Classify** — tag each assumption with exactly one class:

   | Class | Meaning |
   |-------|---------|
   | `true` | well-established; holds on current evidence |
   | `partial` | holds only under conditions or in part |
   | `unproven` | plausible but unverified — no evidence either way yet |
   | `outdated` | was true; superseded by newer facts |
   | `convenience` | assumed because it makes the thesis work, not because it is supported |

3. **Rewrite as testable questions** — turn each assumption into a specific, checkable question (what evidence would confirm or break it). Route those questions into the Step 2 elements:
   - Each testable question becomes (or sharpens) a `Hypotheses` sub-claim.
   - The questions on weak assumptions (`unproven` / `convenience`, plus any `partial` / `outdated` worth testing) become candidate `Invalidation criteria` — the observable conditions that would falsify the claim.
   - The SAME weak-assumption questions are the explicit input to the Step 2b Disconfirm dispatch (its anchor assumptions).

Surface any assumption the audit cannot resolve from reasoning alone (e.g. a `convenience` assumption with no supporting basis) per `./investor-loop.md` § Issue-surfacing — do not bury it. The audit produces classified assumptions as testable questions; it does NOT produce a project plan — never append owners, timelines, metrics, or next-action lists (alien to this read-only reasoning mode, which never executes).

### Step 2b — Populate `Evidence against` via a Disconfirm dispatch

Populate `Evidence against` by HUNTING for the sources that would overturn the claim — not by reasoning counter-arguments from context alone. The discovery lives in `research`; this mode DISPATCHES it (it does NOT re-implement discovery, re-specify the search mechanics, or restate the cost cap — `./research.md` owns all of that). This mirrors the `review`→`research` sub-agent dispatch precedent (`./review.md` Step 3).

For the audit's weak assumptions (the `unproven` / `convenience` testable questions from Step 2a), dispatch the Disconfirm wave. Dispatch one sub-agent whose prompt MUST direct it to:

1. **Read-and-follow `./research.md` and execute its Step 7a Disconfirm wave exactly**, passing — per the Step 7a documented input contract — the anchor assumption(s) (the weak testable questions from Step 2a), the entity(ies) the thesis touches, and the `research-policy` scope/exclusions loaded in Step 1. `./research.md` owns the wave's discovery mechanics, its plugin-agnostic web-search skill directive, and its cost cap — this mode names none of them.
2. **Retain `./research.md`'s propose→approve checkpoint** for any source that would enter the wiki — the user still approves which disconfirming sources are captured. ONLY the hunt is automatic; there are NO silent web writes and NO bypassed approval.
3. **Return only the structured result `./research.md` produces** — the ranked disconfirming candidates + metadata + each candidate's why-it-would-overturn note (Step 7a's documented output). Full source text MUST NOT return to this mode (anti-context-rot — the parent context stays clean).

Fold the returned disconfirming candidates into `Evidence against`, each tied to its source per the element table. If the dispatch returns no disconfirming candidate that clears the `source-policy` trust bar, `Evidence against` is still filled by reasoning (the element stays MANDATORY and substantive — never an empty placeholder), and the empty hunt is surfaced per `./investor-loop.md` § Issue-surfacing. The agent NEVER hand-writes a raw source or wiki page from this dispatch — `./research.md`'s own tool and ingest sub-agents persist anything captured (delegate-not-replace).

## Step 3 — Select related entities + position mapping

1. Identify the investment entity(ies) the thesis touches (companies, assets, sectors, countries). These become the scribe's `related_companies` / `related_assets` / `related_sectors` / `related_countries` cross-links.
2. Read a single company's `## Financials` table off its wiki entity page directly when fundamentals inform the reasoning (no fundamentals tool in v1).
3. Map owned positions ONLY if the user maps a belief to real exposure — these become `related_positions`. Inspect position data ONLY through a registered `class: read` tool in `../../scripts/tools-index.md` (tools-only invariant); NEVER read `portfolio.json`/ledgers directly. Leave `related_positions` empty when the user does not map exposure.

## Step 4 — Present-and-confirm checkpoint

Run `./investor-loop.md` § Present-and-confirm before the handoff. State the proposed thesis (claim + the sections developed + entities to cross-link + sources to cite + proposed `status`/`conviction`/`time_horizon`) and STOP for the user's choice.

This is the mode's single user-facing checkpoint. Per the handoff contract there is NO second checkpoint at the scribe — the agent's confirm here covers the invocation. The one carve-out is the scribe's own scope-overlap interrupt (Step 5).

| User choice | Action |
|-------------|--------|
| `[R]` Refutar | Run a second-model refutation of this proposed thesis before deciding (§ Adversarial refuter below); re-present THIS checkpoint with the critique added — `[R]` never persists, never auto-acts, never replaces `[S]/[E]/[N]` |
| `[S]` Aprovar | Proceed to Step 5 — invoke the scribe |
| `[E]` Editar | Apply the user's edits to the reasoning; re-present; loop until `[S]` or `[N]` |
| `[N]` Rejeitar | Persist nothing; take the user's alternative path or halt |

### Adversarial refuter (`[R]`) — dispatch with the thesis rubric

On `[R]`, read-and-follow `./adversarial-refuter.md` (the shared refuter-dispatch workflow; registered as a cross-mode mechanism). This mode DISPATCHES it — it adds NO discovery engine, NEVER re-runs the Step 2b Disconfirm, and NEVER re-implements the refutation logic; `./adversarial-refuter.md` owns the backend, single-pass, read-only, and no-generation mechanics. Hand it the CLOSED input set its § Step 1 requires:

| Input | What this mode passes |
|-------|------------------------|
| Drafted artifact | the Step 4 proposed-thesis block above — the Claim, Hypotheses, Causal mechanism, Evidence for, Evidence against, Risks, and Invalidation criteria exactly as drafted, plus the proposed `status`/`conviction`/`time_horizon` |
| Cited sources | the full text of every source the thesis cites (the Step 2–2b evidence already in hand) — passed inline so the refuter reads it in its OWN context; full text never re-enters this mode (anti-context-rot) |
| The thesis rubric | the ordered attack questions below — this mode OWNS its rubric; `./adversarial-refuter.md` never hard-codes it |
| `research-policy` scope | the scope / exclusions loaded at Step 1 |

**Thesis rubric (the attack questions the refuter tests this proposed thesis against):**

1. Is the strongest counter-case to the Claim actually engaged in `Evidence against`, or does a stronger disconfirmer in the cited sources go unaddressed?
2. Are the `Invalidation criteria` observable conditions — specific and checkable — rather than hedged or unfalsifiable restatements of the Claim?
3. Did the Step 2a Assumption Audit miss an assumption the Claim or Causal mechanism silently rests on?
4. Is EACH `Evidence for` item actually supported by its cited source, or does a citation overstate or misread what the source shows?

The refuter returns its § Output schema verbatim — one `overturned | weakened | survives` verdict per rubric item. Render that returned block RAW + flagged as a distinct **"Adversarial critique"** block beside the proposed thesis, then RE-PRESENT this SAME checkpoint with the critique added:

- The critique is shown intact; this mode may add a one-line agree/disagree per item but NEVER edits or suppresses it.
- It is single-pass — the refuter runs ONCE and never loops. Points the user accepts fold into the thesis via the existing `[E]` path, NOT by re-running the refuter.
- The `[S]/[E]/[N]` choice then follows unchanged — the critique informs the decision; the user still decides. A failed or unavailable refuter NEVER blocks this checkpoint: present the proposed thesis unchanged and proceed (`./adversarial-refuter.md` § Step 2).

## Step 5 — Delegate persistence to `sb-fin-create-thesis`

On `[S]`, invoke `sb-fin-create-thesis` in its **investor-orchestrated mode** (Skill tool). Pass these inputs; the scribe runs its steps without re-prompting:

| Input | Source |
|-------|--------|
| Proposed thesis slug | derived from the claim per the scribe's naming convention |
| Candidate-thesis timestamp | the `candidate-thesis` log entry's timestamp if this thesis promotes one; omit for a fresh proposal |
| The claim | the falsifiable Claim reasoned in Step 2 |
| Source filenames | the captured-source filenames cited as evidence |
| Related entities | the entity(ies) selected in Step 3 |

The agent does NOT hand-write the page and does NOT re-implement the scribe's slug/collision/scope-overlap/frontmatter/section/citation/index checks — those are the scribe's sole authority.

### The one allowed interrupt — scope-overlap

`sb-fin-create-thesis` runs a semantic scope-overlap check against existing theses. If it detects overlap, its `extend` / `new` / `abort` prompt fires as the single allowed interrupt inside this handoff (`./investor-loop.md` § Present-and-confirm carve-out). Surface it to the user and act on the choice:

| Choice | Effect |
|--------|--------|
| `extend N` | The scribe appends to / revises existing thesis `N` instead of creating a new page; the agent acts on the emitted `extend` directive |
| `new` | A new thesis page is created; it cross-links the overlapping thesis as a sibling |
| `abort` | No writes |

Do not pre-empt this prompt and do not suppress it — it is the scribe's structural authority, not a second mode checkpoint.

---

## Boundaries (this mode)

- Read-only on portfolio/ledger data; position data ONLY through registered read tools (`./investor-loop.md` § Tools-only data access).
- Writes ONLY by invoking `sb-fin-create-thesis` — the agent NEVER hand-writes a thesis page (`./investor-loop.md` § Own-workspace-writes boundary).
- Never mutates ledgers, `portfolio.json`, or the dashboard. A request to do so, or to author the page by hand, is out-of-structure → Rule A in `./investor-loop.md`.
- Every user-facing turn ends at an Investor Checkpoint (`./investor-loop.md` § Per-Step Checkpoint). User-facing strings are in `communication.language` per `./investor.md` § Rules and `./investor-loop.md` § Language.
