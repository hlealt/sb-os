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
| Hypotheses | The sub-claims that, if true, make the claim hold |
| Causal mechanism | WHY the claim would play out — the chain from cause to outcome |
| Evidence for | Concrete, sourced support; tie each item to a captured source filename where one exists |
| Evidence against | MANDATORY and substantive — the strongest disconfirming evidence and counter-arguments; never an empty placeholder |
| Risks | What could break the thesis or the position independent of the core claim |
| Invalidation criteria | MANDATORY and substantive — the specific, observable conditions under which the thesis is wrong and must be retired |

Surface a problem with the reasoning or its inputs (a source failing the `source-policy` trust bar, a contradicted premise) per `./investor-loop.md` § Issue-surfacing — never pass it silently.

## Step 3 — Select related entities + position mapping

1. Identify the investment entity(ies) the thesis touches (companies, assets, sectors, countries). These become the scribe's `related_companies` / `related_assets` / `related_sectors` / `related_countries` cross-links.
2. Read a single company's `## Financials` table off its wiki entity page directly when fundamentals inform the reasoning (no fundamentals tool in v1).
3. Map owned positions ONLY if the user maps a belief to real exposure — these become `related_positions`. Inspect position data ONLY through a registered `class: read` tool in `../../scripts/tools-index.md` (tools-only invariant); NEVER read `portfolio.json`/ledgers directly. Leave `related_positions` empty when the user does not map exposure.

## Step 4 — Present-and-confirm checkpoint

Run `./investor-loop.md` § Present-and-confirm before the handoff. State the proposed thesis (claim + the sections developed + entities to cross-link + sources to cite + proposed `status`/`conviction`/`time_horizon`) and STOP for the user's choice.

This is the mode's single user-facing checkpoint. Per the handoff contract there is NO second checkpoint at the scribe — the agent's confirm here covers the invocation. The one carve-out is the scribe's own scope-overlap interrupt (Step 5).

| User choice | Action |
|-------------|--------|
| `[S]` Aprovar | Proceed to Step 5 — invoke the scribe |
| `[E]` Editar | Apply the user's edits to the reasoning; re-present; loop until `[S]` or `[N]` |
| `[N]` Rejeitar | Persist nothing; take the user's alternative path or halt |

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
