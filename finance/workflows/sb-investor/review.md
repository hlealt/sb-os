---
stepId: investor-review
runtime: agent-loop
---

# Review Mode (B3 — Maintenance)

The `/sb-investor` reasoning mode that re-evaluates an EXISTING thesis against new information — surfacing staleness, new evidence-against, and tripped / near invalidation criteria — so the thesis base stays falsifiable over time. **This mode NEVER hand-writes a thesis page** — it reasons and proposes; `sb-fin-create-thesis` (its named `extend` entry point, targeting the existing thesis by slug) persists every update (delegate-not-replace).

**Loaded by:** `./sb-investor.md` reads-and-follows this file when `./capability-manifest.md` routes the `review` (B3) intent. Read `./sb-investor-loop.md` before acting on any step below.

**Division of labour (read once, then act):**

| Layer | Owns |
|-------|------|
| This mode (the reviewer) | reasoning: load the thesis, re-run the Assumption Audit on its standing assumptions, gather and weigh new evidence, test each invalidation criterion, reach a verdict, the present-and-confirm checkpoint, the buy/sell/hold and invalidation handoffs |
| `./research.md` (the evidence sourcer) | the Step 7a Disconfirm wave this mode dispatches PER near/untested invalidation criterion — discovery, propose→approve, capture, auto-ingest. This mode dispatches it; it NEVER re-specifies discovery, the cost cap, or ingest |
| `./thesis.md` Step 2a (the Assumption Audit lens) | the canonical first-principles method this mode REUSES to classify the thesis's standing assumptions and rewrite them as testable questions. This mode supplies the review-specific input (standing assumptions that may have decayed); it NEVER redefines the method |
| `sb-fin-create-thesis` (the scribe), its named `extend` entry point | persistence: append evidence-against, sharpen invalidation, update `status` / `conviction` / `last_reviewed`. The only writer of thesis-page updates; the agent NEVER re-implements these writes |

---

## Step 1 — Policy gate (MANDATORY, FIRST)

Before ANY reasoning, load the policy file(s) `../../CLAUDE.md` § Policy Read-Rules requires — per `./sb-investor-loop.md` § Policy read-rules wiring. Reviewing or invalidating a thesis is such an action: `research-policy.md` is required (scope / priorities / exclusions / horizon); load `source-policy.md` too — this mode weighs and trusts the sources it evaluates. NEVER restate the read-rules table — read it.

If `research-policy.md` marks the thesis's topic out-of-scope or excluded, say so and STOP, or offer to widen scope via the `policy` thin mode — do NOT reason past an exclusion (`./sb-investor-loop.md` § Policy read-rules wiring; Rule A).

## Step 2 — Load the target thesis

Read the target thesis page in full at `{wiki_root}/wiki/theses/{slug}.md` (resolve `{wiki_root}` from `sb-os.json`; never hardcode). The thesis is markdown the agent reads directly — it is NOT position data, so no read tool is involved here. Extract every field the evaluation depends on:

| Field | Used for |
|-------|----------|
| `Claim` + `Hypotheses` + `Causal mechanism` | what the review tests against new evidence |
| `Evidence for` / `Evidence against` | the prior evidence base the new evidence updates |
| `Invalidation criteria` | the per-criterion checklist evaluated in Step 4 |
| `status` / `conviction` / `time_horizon` | the current standing and the horizon cadence that defines staleness |
| `last_reviewed` | the cutoff date for "new" evidence in Step 3 |
| `related_companies` / `related_assets` / `related_sectors` / `related_countries` | the entities whose recent sources Step 3 gathers |

If the named thesis page does not exist, surface it per `./sb-investor-loop.md` § Issue-surfacing (this is blocking — there is nothing to review) and STOP.

## Step 3 — Gather recent evidence (Assumption Audit on standing assumptions → targeted Disconfirm)

**Discovery runs `./sb-investor-loop.md` § Wiki-page discovery FIRST** — search the wiki for pages relevant to the thesis (query = the thesis `Claim`, scoped by its `related_companies` / `related_assets` / `related_sectors` / `related_countries` entities; suggested `--type source,entity,concept`), treating the returned paths as discovery candidates including pages not named in the frontmatter. Then the existing pass runs as the retained backstop: find wiki sources touching the thesis's entities dated AFTER `last_reviewed` — read source/entity pages directly (markdown, not position data) — and grep the entities to catch exact strings and freshly-written pages. The evidence set is the **UNION** — search hits ∪ the direct-by-entity reads ∪ grep — so it always contains at least today's direct-by-entity candidate set (no recall regression; § Wiki-page discovery step 3). Weigh each candidate against `source-policy` (loaded in Step 1); a source that fails the trust bar is surfaced per `./sb-investor-loop.md` § Issue-surfacing, never silently kept or dropped.

### Step 3a — Re-run the Assumption Audit on the thesis's STANDING assumptions

A thesis decays when an assumption that held at authoring no longer holds. Re-run the Assumption Audit — **REUSE the lens defined in `./thesis.md` § Step 2a (the canonical method: the same `true` / `partial` / `unproven` / `outdated` / `convenience` classification + the rewrite-as-testable-questions step)**; this mode does NOT redefine that method. The review-specific INPUT is what differs: not a fresh claim's hidden assumptions, but the thesis's ALREADY-STATED standing assumptions — the ones its `Claim`, `Hypotheses`, and `Causal mechanism` (read in Step 2) rest on — re-classified against the evidence dated after `last_reviewed`.

The review question the audit answers: **which standing assumptions turned `unproven` or `outdated` since `last_reviewed`?** An assumption that was `true`/`partial` at authoring but is contradicted, eroded, or overtaken by the new evidence is now decayed. Run the lens as a SINGLE inline pass (it fetches nothing, writes nothing, dispatches no sub-agent — per `./thesis.md` § Step 2a). Its output — the testable questions on the now-decayed assumptions — identifies WHICH of the Step 2 invalidation criteria the new evidence has pushed to `near` or left untested, and therefore which criteria Step 3b must hunt against. Surface any decayed assumption the audit cannot resolve from reasoning alone per `./sb-investor-loop.md` § Issue-surfacing.

### Step 3b — Dispatch a Disconfirm wave PER near/untested invalidation criterion

For EACH invalidation criterion the Step 3a audit flags as `near` or untested by the post-`last_reviewed` evidence, dispatch a TARGETED Disconfirm wave — hunt for the source that would push that specific criterion to `tripped`. This REPLACES the generic "auto-pull research when thin": the audit, not a thin-source heuristic, decides what to hunt, and the hunt is scoped per criterion rather than a blanket research pull. The discovery lives in `disconfirm-wave`; this mode DISPATCHES it by **dispatching `./disconfirm-wave.md` directly** (it does NOT re-implement discovery, re-specify the search mechanics, or restate the cost cap — `./disconfirm-wave.md` owns all of that). This rides the existing `review`→`research` sub-agent dispatch precedent.

For each such criterion, dispatch one sub-agent whose prompt MUST direct it to:

1. **Read-and-follow `./disconfirm-wave.md` and execute the Disconfirm wave exactly**, passing — per the documented input contract — the anchor assumption (the decayed standing assumption / near criterion as the testable question from Step 3a), the entity(ies) the thesis touches, and the `research-policy` scope/exclusions loaded in Step 1. `./disconfirm-wave.md` owns the wave's discovery mechanics, its plugin-agnostic web-search skill directive, and its cost cap — this mode names none of them.
2. **Retain `./research.md`'s propose→approve checkpoint** — the user still approves which disconfirming sources enter the wiki. ONLY the hunt is automatic; there are NO silent web writes and NO bypassed approval.
3. **Return only the structured result `./research.md` produces** — the ranked disconfirming candidates + metadata + each candidate's why-it-would-overturn note (Step 7a's documented output), including any source-tension flag the Propose step surfaced. Full source text MUST NOT return to this mode (anti-context-rot — the parent context stays clean).

`./disconfirm-wave.md` owns the wave mechanics (including the skill directives its sub-agent requires); `./research.md` owns capture, ingest, and the propose→approve checkpoint this mode's sub-agent returns through. On return, fold the newly-surfaced disconfirming sources into the evidence set for Step 4 and tie each to the criterion it targets. A `failed` / `partial` ingest in the summary is surfaced per `./sb-investor-loop.md` § Issue-surfacing. If a criterion's Disconfirm wave returns no candidate that clears the `source-policy` trust bar, that criterion is evaluated in Step 4 on the existing evidence alone, and the empty hunt is surfaced per `./sb-investor-loop.md` § Issue-surfacing.

**When the audit flags nothing, no wave fires (by design).** The trigger is audit-driven, not source-count-driven: if the Step 3a audit finds NO standing assumption decayed and pushes NO invalidation criterion to `near`/untested, then ZERO Disconfirm waves dispatch and the review proceeds on the existing evidence alone. This is the deliberate precision upgrade over the old thin-source auto-pull (which fired a blanket pull on a source-count heuristic regardless of whether any assumption had actually decayed) — a review that finds the thesis still holding spends no discovery budget.

## Step 4 — Evaluate

Test the thesis against the assembled evidence (prior + new, including the Step 3b targeted Disconfirm candidates). Three sub-evaluations, all required:

| Sub-evaluation | Method | Output |
|----------------|--------|--------|
| Invalidation criteria | Test EACH criterion from Step 2 against the new evidence, informed by the Step 3a audit (which standing assumptions decayed) and the Step 3b Disconfirm result for each near/untested criterion | per-criterion status: **tripped** (the disconfirming condition occurred) / **near** (evidence is approaching the threshold) / **clear** (no movement toward invalidation) |
| Evidence balance | Weigh new evidence-FOR against new evidence-AGAINST (each passed the `source-policy` bar) AND surface explicit source tensions — which sources contradict each other, on what | the net direction the new evidence pushes conviction, PLUS the source tensions feeding that direction (see below) |
| Staleness | The thesis is stale if it is contradicted by new evidence, an assumption decayed (Step 3a), OR it is unreviewed past its `time_horizon` cadence (the horizon defines the expected review interval) | stale / current |

**Source tensions in the evidence balance.** Do not report only a net direction — surface which sources DISAGREE and on what, so the verdict rests on the visible disagreement rather than a collapsed average. CONSUME the source-tension signal `./research.md` § Step 4 Propose produces: any Step 3b Disconfirm wave that returned a tension flag already carries it in the `relation to the thesis` / why-it-would-overturn metadata. Read those flags AND cross-read the assembled evidence (prior + new) for the same contradictions — from the metadata and the sources' stated conclusions already in hand, NEVER by pulling full source text (anti-context-rot holds). Surface each as a short note, in the same format `./research.md` emits:

```
Source tensions: #{a} ↔ #{b} — {one-line description of the disagreement}.
```

A source tension is a flag the user weighs, not a separate analysis pass: it reads only metadata and stated conclusions already assembled. If the evidence shows no contradiction, write none — do not fetch text to manufacture one. The verdict (Step 5) MUST reflect these tensions: a criterion whose evidence is internally contradicted is `near`, not `clear`, until the contradiction resolves. A numeric market figure the sources state differently is presented as the source-attributed range per `./thesis.md` Step 2 § Market-figure range rule — unless a registered read tool resolves it.

Read a related company's `## Financials` table off its wiki entity page directly when fundamentals inform the evaluation (no fundamentals tool in v1). Surface any reasoning problem — a contradicted premise, an unresolved source, a thesis already resting on tripped criteria — per `./sb-investor-loop.md` § Issue-surfacing; a blocking issue halts the step until resolved.

## Step 5 — Present findings (present-and-confirm)

Run `./sb-investor-loop.md` § Present-and-confirm. State the review outcome and STOP for the user's choice. The findings MUST carry:

| Element | Content |
|---------|---------|
| Verdict | **holding** (evidence supports the claim; no criterion tripped) / **weakening** (evidence-against accumulating or a criterion near) / **invalidated** (a criterion tripped or the claim contradicted) — the verdict MUST reflect the source tensions and decayed assumptions below, not a collapsed net average |
| Decayed assumptions | the standing assumptions the Step 3a audit re-classified `unproven` / `outdated`, each as the testable question that exposed the decay |
| New evidence-against | the disconfirming sources/arguments found in Steps 3–4 (including each criterion's targeted Step 3b Disconfirm result), each tied to its source |
| Source tensions | the `Source tensions: #{a} ↔ #{b} — …` flags from Step 4 — which sources contradict each other and on what; empty only if the evidence shows no contradiction |
| Per-criterion status | each invalidation criterion marked tripped / near / clear |
| Recommended change | the proposed `status` and `conviction` change (and `last_reviewed` advance), with one-line rationale |

A `status` downgrade (e.g. `active` → `developing`, or → `rejected` / `archived`) is ALWAYS surfaced here for explicit approval — NEVER applied silently. This is the mode's single user-facing checkpoint before persistence.

| User choice | Action |
|-------------|--------|
| `[R]` Refute | Run a second-model refutation of this verdict before deciding (§ Adversarial refuter below); re-present THIS checkpoint with the critique added — `[R]` never persists, never auto-acts, never replaces `[S]/[E]/[N]` |
| `[S]` Approve | Proceed to Step 6 — delegate the update to the scribe |
| `[E]` Edit | Apply the user's edits to the verdict / recommended change; re-present; loop until `[S]` or `[N]` |
| `[N]` Reject | Persist nothing; take the user's alternative path or halt |

### Adversarial refuter (`[R]`) — dispatch with the review rubric

On `[R]`, read-and-follow `./adversarial-refuter.md` and dispatch it with the closed input set its § Step 1 requires: **Drafted artifact** = the Step 5 verdict block (verdict, decayed assumptions, new evidence-against, source tensions, per-criterion status, and recommended change); **Cited sources** = every source the verdict cites (the Step 3–4 evidence), inline for small payloads or as the closed read-set of cited file paths for large ones (full text never re-enters this mode — anti-context-rot); **rubric** = the ordered attack questions below; **policy scope** = the scope/exclusions loaded at Step 1. Display the returned critique per `./adversarial-refuter.md` § Step 4; re-present this SAME checkpoint with the critique added.

**Review rubric (the attack questions the refuter tests this verdict against):**

1. Is EACH invalidation criterion tested against the BEST available disconfirming evidence — including the criterion's targeted Step 3b Disconfirm result — or does a stronger disconfirmer in the cited sources go unaddressed?
2. Is the verdict (**holding** / **weakening** / **invalidated**) consistent with the per-criterion statuses — does any tripped/near criterion contradict the stated verdict?
3. Does any criterion marked **clear** sit on sources that actually show it as **near** or **tripped** (incl. internally-contradicted evidence the Step 4 tension flags expose)?

## Step 6 — Persist via the scribe (`extend` path)

On `[S]`, invoke `sb-fin-create-thesis` in its **investor-orchestrated `extend` entry point** (Skill tool) to update the EXISTING thesis page reviewed in Step 2 — append evidence-against, sharpen the invalidation criteria, and update `status` / `conviction` / `last_reviewed` per the confirmed findings. Pass the existing thesis slug as the named target: this entry point appends to that page in place and SKIPS the scribe's scope-overlap discovery prompt (the page is already identified — no disambiguation runs). Pass these inputs; the scribe runs without re-prompting (the Step 5 confirm covers the invocation):

| Input | Source |
|-------|--------|
| Target thesis slug | the page reviewed in Step 2 — the named target the `extend` entry point updates in place |
| New evidence-against | the disconfirming items confirmed in Step 5, with their source filenames for citation |
| Sharpened invalidation | the criteria revisions confirmed in Step 5 |
| `status` / `conviction` / `last_reviewed` | the confirmed values from Step 5 |

The agent does NOT hand-write the page and does NOT re-implement the scribe's frontmatter / section / citation / index checks — those are the scribe's sole authority (`./sb-investor-loop.md` § Own-workspace-writes boundary). The `extend` entry point skips the scope-overlap discovery prompt, so it does not interrupt; if the scribe surfaces any other structural prompt during the extend, act on it — do not pre-empt or suppress it.

## Step 7 — Handoff

After persistence, route any implied next step — surface it, never auto-chain without the routing the user confirms (`./capability-manifest.md` § Multi-mode chaining):

| Review implies | Handoff |
|----------------|---------|
| A buy / sell / hold the verdict points to | Suggest `decision` (B5, read-and-follow `./decision.md`) to record the action + rationale |
| An invalidated thesis | Propose `status: rejected` / `archived` via `./sb-investor-loop.md` § Present-and-confirm — applied ONLY on the user's explicit approval, persisted ONLY through the scribe's `extend` path (never hand-written) |

---

## Boundaries (this mode)

The loop invariants (`./sb-investor-loop.md` § Read-only invariant, § Tools-only data access, § Own-workspace-writes boundary, § Per-Step Checkpoint) are in force. Thesis / source / entity pages are markdown the agent reads directly — they are not position data.

- Writes ONLY by invoking `sb-fin-create-thesis` in its named investor-orchestrated `extend` entry point (thesis-page updates) and by dispatching `./research.md` (which persists `raw/` + wiki only through its own tool and ingest sub-agents). The agent NEVER hand-writes a thesis page or a raw/wiki file (`./sb-investor-loop.md` § Own-workspace-writes boundary).
- `status` downgrades are ALWAYS surfaced for approval, NEVER applied silently.
