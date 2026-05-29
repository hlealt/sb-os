---
stepId: investor-review
runtime: agent-loop
---

# Review Mode (B3 — Maintenance)

The `/investor` reasoning mode that re-evaluates an EXISTING thesis against new information — surfacing staleness, new evidence-against, and tripped / near invalidation criteria — so the thesis base stays falsifiable over time. **This mode NEVER hand-writes a thesis page** — it reasons and proposes; `sb-fin-create-thesis` (resolving to its `extend` path against the existing thesis) persists every update (delegate-not-replace).

**Loaded by:** `./investor.md` reads-and-follows this file when `./capability-manifest.md` routes the `review` (B3) intent. The invariants, policy read-rules wiring, present-and-confirm pattern, issue-surfacing, Rule A, and the per-step Investor Checkpoint in `./investor-loop.md` are already in force when this file runs — this file does NOT restate them. Read `./investor-loop.md` before acting on any step below.

**Division of labour (read once, then act):**

| Layer | Owns |
|-------|------|
| This mode (the reviewer) | reasoning: load the thesis, gather and weigh new evidence, test each invalidation criterion, reach a verdict, the present-and-confirm checkpoint, the buy/sell/hold and invalidation handoffs |
| `./research.md` (the evidence sourcer) | auto-pull of fresh OPEN sources when wiki evidence is thin — discovery, propose→approve, capture, auto-ingest. This mode dispatches it; it NEVER re-specifies discovery or ingest |
| `sb-fin-create-thesis` (the scribe), resolving to its `extend` path | persistence: append evidence-against, sharpen invalidation, update `status` / `conviction` / `last_reviewed`. The only writer of thesis-page updates; the agent NEVER re-implements these writes |

---

## Step 1 — Policy gate (MANDATORY, FIRST)

Before ANY reasoning, load the policy file(s) `../../CLAUDE.md` § Policy Read-Rules requires — per `./investor-loop.md` § Policy read-rules wiring. Reviewing or invalidating a thesis is such an action: `research-policy.md` is required (scope / priorities / exclusions / horizon); load `source-policy.md` too — this mode weighs and trusts the sources it evaluates. NEVER restate the read-rules table — read it.

If `research-policy.md` marks the thesis's topic out-of-scope or excluded, say so and STOP, or offer to widen scope via the `policy` thin mode — do NOT reason past an exclusion (`./investor-loop.md` § Policy read-rules wiring; Rule A). This gate runs before Step 2 every time; no review reasoning begins before it clears.

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

If the named thesis page does not exist, surface it per `./investor-loop.md` § Issue-surfacing (this is blocking — there is nothing to review) and STOP.

## Step 3 — Gather recent evidence (auto-pull research when thin)

Find wiki sources touching the thesis's entities dated AFTER `last_reviewed` — read source/entity pages directly (markdown, not position data). Weigh each candidate against `source-policy` (loaded in Step 1); a source that fails the trust bar is surfaced per `./investor-loop.md` § Issue-surfacing, never silently kept or dropped.

When the recent wiki evidence is **thin** (too few sources after `last_reviewed` to test the criteria), auto-pull fresh OPEN sources by dispatching the `research` mode — do NOT discover, capture, or ingest in this file. Dispatch one sub-agent whose prompt MUST direct it to:

1. **Read-and-follow `./research.md` and execute its protocol exactly**, anchored to THIS thesis (pass the claim, the entity(ies), and the `research-policy` scope/exclusions loaded in Step 1).
2. **Retain `./research.md`'s propose→approve checkpoint** — the user still approves which sources enter the wiki. ONLY the search kickoff is automatic; there are NO silent web writes and NO bypassed approval.
3. **Return only the structured post-ingest summary** `./research.md` produces (pages created/updated, scope-overlaps, lint flags) — full source text MUST NOT return to this mode.

`./research.md` owns every web-search, capture, and ingest mechanic (including the skill directives its own sub-agents require); this mode references it and consumes its summary. On return, fold the newly-ingested sources into the evidence set for Step 4. A `failed` / `partial` ingest in the summary is surfaced per `./investor-loop.md` § Issue-surfacing.

## Step 4 — Evaluate

Test the thesis against the assembled evidence (prior + new). Three sub-evaluations, all required:

| Sub-evaluation | Method | Output |
|----------------|--------|--------|
| Invalidation criteria | Test EACH criterion from Step 2 against the new evidence | per-criterion status: **tripped** (the disconfirming condition occurred) / **near** (evidence is approaching the threshold) / **clear** (no movement toward invalidation) |
| Evidence balance | Weigh new evidence-FOR against new evidence-AGAINST (each passed the `source-policy` bar) | the net direction the new evidence pushes conviction |
| Staleness | The thesis is stale if it is contradicted by new evidence, OR unreviewed past its `time_horizon` cadence (the horizon defines the expected review interval) | stale / current |

Read a related company's `## Financials` table off its wiki entity page directly when fundamentals inform the evaluation (no fundamentals tool in v1). Surface any reasoning problem — a contradicted premise, an unresolved source, a thesis already resting on tripped criteria — per `./investor-loop.md` § Issue-surfacing; a blocking issue halts the step until resolved.

## Step 5 — Present findings (present-and-confirm)

Run `./investor-loop.md` § Present-and-confirm. State the review outcome and STOP for the user's choice. The findings MUST carry:

| Element | Content |
|---------|---------|
| Verdict | **holding** (evidence supports the claim; no criterion tripped) / **weakening** (evidence-against accumulating or a criterion near) / **invalidated** (a criterion tripped or the claim contradicted) |
| New evidence-against | the disconfirming sources/arguments found in Steps 3–4, each tied to its source |
| Per-criterion status | each invalidation criterion marked tripped / near / clear |
| Recommended change | the proposed `status` and `conviction` change (and `last_reviewed` advance), with one-line rationale |

A `status` downgrade (e.g. `active` → `developing`, or → `rejected` / `archived`) is ALWAYS surfaced here for explicit approval — NEVER applied silently. This is the mode's single user-facing checkpoint before persistence.

| User choice | Action |
|-------------|--------|
| `[S]` Aprovar | Proceed to Step 6 — delegate the update to the scribe |
| `[E]` Editar | Apply the user's edits to the verdict / recommended change; re-present; loop until `[S]` or `[N]` |
| `[N]` Rejeitar | Persist nothing; take the user's alternative path or halt |

## Step 6 — Persist via the scribe (`extend` path)

On `[S]`, invoke `sb-fin-create-thesis` in its **investor-orchestrated mode** (Skill tool) to update the EXISTING thesis page reviewed in Step 2 — append evidence-against, sharpen the invalidation criteria, and update `status` / `conviction` / `last_reviewed` per the confirmed findings. Pass the existing thesis slug as the subject: the scribe's scope-overlap check (its Step 1) resolves a same-subject existing thesis to its **`extend`** path and appends to that page in place rather than creating a new one. Pass these inputs; the scribe runs without re-prompting (the Step 5 confirm covers the invocation), except the one allowed interrupt below:

| Input | Source |
|-------|--------|
| Target thesis slug | the page reviewed in Step 2 — the subject the scribe matches its scope-overlap check against, resolving to `extend` of that page |
| New evidence-against | the disconfirming items confirmed in Step 5, with their source filenames for citation |
| Sharpened invalidation | the criteria revisions confirmed in Step 5 |
| `status` / `conviction` / `last_reviewed` | the confirmed values from Step 5 |

The agent does NOT hand-write the page and does NOT re-implement the scribe's frontmatter / section / citation / index checks — those are the scribe's sole authority (`./investor-loop.md` § Own-workspace-writes boundary). The scribe's scope-overlap prompt is the one allowed interrupt during an otherwise no-second-checkpoint invocation: if the scribe surfaces it (or any structural prompt) during the extend, act on it; do not pre-empt or suppress it.

## Step 7 — Handoff

After persistence, route any implied next step — surface it, never auto-chain without the routing the user confirms (`./capability-manifest.md` § Multi-mode chaining):

| Review implies | Handoff |
|----------------|---------|
| A buy / sell / hold the verdict points to | Suggest `decision` (B5, read-and-follow `./decision.md`) to record the action + rationale |
| An invalidated thesis | Propose `status: rejected` / `archived` via `./investor-loop.md` § Present-and-confirm — applied ONLY on the user's explicit approval, persisted ONLY through the scribe's `extend` path (never hand-written) |

---

## Boundaries (this mode)

- Read-only on portfolio/ledger data; position data ONLY through registered read tools (`./investor-loop.md` § Tools-only data access). Thesis / source / entity pages are markdown the agent reads directly — they are not position data.
- Writes ONLY by invoking `sb-fin-create-thesis` in its investor-orchestrated mode resolving to the `extend` path (thesis-page updates) and by dispatching `./research.md` (which persists `raw/` + wiki only through its own tool and ingest sub-agents). The agent NEVER hand-writes a thesis page or a raw/wiki file (`./investor-loop.md` § Own-workspace-writes boundary).
- `status` downgrades are ALWAYS surfaced for approval, NEVER applied silently.
- Never mutates ledgers, `portfolio.json`, or the dashboard. A request to do so, or to hand-write the thesis page instead of delegating to the scribe, is out-of-structure → Rule A in `./investor-loop.md`.
- Every user-facing turn ends at an Investor Checkpoint (`./investor-loop.md` § Per-Step Checkpoint). User-facing strings are in `communication.language` per `./investor.md` § Rules and `./investor-loop.md` § Language.
