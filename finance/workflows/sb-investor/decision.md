---
stepId: investor-decision
runtime: agent-loop
---

# Decision Mode (B5 — Decision record)

The `/sb-investor` reasoning mode that reasons about ONE investment decision and the rationale held at the time, then delegates persistence to `sb-fin-create-decision`. **This mode NEVER writes a decision page** — it reasons; the scribe persists (delegate-not-replace).

**Loaded by:** `./investor.md` reads-and-follows this file when `./capability-manifest.md` routes the `decision` (B5) intent. The invariants, policy read-rules wiring, present-and-confirm pattern, issue-surfacing, Rule A, and the per-step Investor Checkpoint in `./investor-loop.md` are already in force when this file runs — this file does NOT restate them. Read `./investor-loop.md` before acting on any step below.

**Division of labour (read once, then act):**

| Layer | Owns |
|-------|------|
| This mode (the thinker) | reasoning: the action taken, rationale, what was believed at the time, what would prove it wrong, acknowledged risks, review trigger, the related thesis; the present-and-confirm checkpoint |
| `sb-fin-create-decision` (the scribe) | persistence: filename (`YYYY-MM-DD-<action>-<asset-or-thesis>.md`) + collision check, frontmatter, the nine required sections, citation discipline, entity/thesis cross-linking, decisions index update. The agent NEVER re-implements these checks |

**Never transaction data.** This mode records reasoning ONLY. Transaction price, quantity, fees, and position size live in the `sb-bookkeeper` ledger and are NEVER reasoned into a decision page (`./investor-loop.md` § Read-only invariant). A request to record them is out-of-structure → Rule A.

---

## Step 1 — Policy gate (MANDATORY)

Before ANY reasoning, load the policy file(s) `../../CLAUDE.md` § Policy Read-Rules requires for an action that REASONS about an investment — per `./investor-loop.md` § Policy read-rules wiring. Recording a buy/sell/hold/pass decision is such an action: `research-policy.md` is required; load `source-policy.md` too when the decision cites or weighs sources. NEVER restate the read-rules table — read it.

If `research-policy.md` marks the decision's subject out-of-scope or excluded, say so and STOP, or offer to widen scope via the `policy` thin mode — do not reason past an exclusion (`./investor-loop.md` § Policy read-rules wiring; Rule A).

## Step 2 — Reason the decision

Develop the decision's reasoning. The decision is a dated record of ONE action and the belief state behind it; reason every element below. These elements map onto the scribe's nine required sections — reason them here, do NOT format the page (the scribe owns structure).

| Element | What to reason | Scribe section |
|---------|----------------|----------------|
| Context | The situation that prompted the action | `Context` |
| Action | The single action taken, in one falsifiable sentence — one value from the `decision_type` enum (`buy \| sell \| trim \| add \| hold \| pass \| reject \| pause \| review \| rebalance`) | `Decision` |
| Related thesis | The thesis this decision acts on and how the action follows from or departs from it; `None` if not thesis-anchored | `Related thesis` |
| Rationale | The reasoning for the action | `Rationale` |
| What I believed at the time | The belief state, recorded so a future review can audit it against outcomes | `What I believed at the time` |
| What would prove me wrong | The observable falsifier | `What would prove me wrong` |
| Acknowledged risks | The risks accepted in taking the action | `Acknowledged risks` |
| Review trigger | The event or date that should reopen this decision (next earnings, a price level, a thesis-invalidation criterion tripping) | `Review trigger` |

Cite the source pages and entity `## Financials` rows the reasoning rests on — these become the scribe's `Data and sources used` section. Read a single company's `## Financials` table off its wiki entity page directly when fundamentals inform the reasoning (no fundamentals tool in v1); inspect position data ONLY through a registered `class: read` tool in `../../scripts/tools-index.md` (tools-only invariant), NEVER `portfolio.json`/ledgers directly.

Record reasoning ONLY — NEVER reason price, quantity, fees, or position size into the decision (the `sb-bookkeeper` ledger owns those). Surface a problem with the reasoning or its inputs (a source failing the `source-policy` trust bar, a contradicted premise) per `./investor-loop.md` § Issue-surfacing — never pass it silently.

## Step 3 — Select related thesis + entities

1. Identify the thesis the decision acts on (if any) — the scribe's `related_thesis`. A buy/sell/hold that follows from a thesis links it; a decision made without a thesis records `None`.
2. Identify the investment entity(ies) the decision concerns — the company (`related_company`) or asset (`related_asset`) it acts on.
3. These become the scribe's cross-links; leave any that do not apply blank.

## Step 4 — Present-and-confirm checkpoint

Run `./investor-loop.md` § Present-and-confirm before the handoff. State the proposed decision (the action + decision date + the eight reasoned sections + the related thesis/entities to cross-link + the sources to cite) and STOP for the user's choice. State that price/qty are NOT recorded — they live in the `sb-bookkeeper` ledger.

This is the mode's single user-facing checkpoint. Per the scribe's investor-orchestrated mode there is NO second checkpoint at the scribe — the agent's confirm here covers the invocation.

| User choice | Action |
|-------------|--------|
| `[R]` Refutar | Run a second-model refutation of this decision reasoning before deciding (§ Adversarial refuter below); re-present THIS checkpoint with the critique added — `[R]` never persists, never auto-acts, never replaces `[S]/[E]/[N]` |
| `[S]` Aprovar | Proceed to Step 5 — invoke the scribe |
| `[E]` Editar | Apply the user's edits to the reasoning; re-present; loop until `[S]` or `[N]` |
| `[N]` Rejeitar | Persist nothing; take the user's alternative path or halt |

### Adversarial refuter (`[R]`) — dispatch with the decision rubric

On `[R]`, read-and-follow `./adversarial-refuter.md` (the shared refuter-dispatch workflow; registered as a cross-mode mechanism). This mode DISPATCHES it — it adds NO discovery engine and NEVER re-implements the refutation logic; `./adversarial-refuter.md` owns the backend, single-pass, read-only, and no-generation mechanics. The refuter attacks ARGUMENT STRUCTURE only (the falsifier, the risks, rationale drift, source contradiction) — it NEVER reasons or critiques price / quantity / fees / position size (the `sb-bookkeeper` ledger owns those; this mode records reasoning only). Hand it the CLOSED input set its § Step 1 requires:

| Input | What this mode passes |
|-------|------------------------|
| Drafted artifact | the Step 4 decision record above — the Context, Action, Related thesis, Rationale, What I believed at the time, What would prove me wrong, Acknowledged risks, and Review trigger exactly as drafted (reasoning only — no price/qty/fees) |
| Cited sources | the full text of every source the decision cites (the source pages and entity `## Financials` rows reasoned in Step 2) — passed inline so the refuter reads it in its OWN context; full text never re-enters this mode (anti-context-rot) |
| The decision rubric | the ordered attack questions below — this mode OWNS its rubric; `./adversarial-refuter.md` never hard-codes it |
| `research-policy` scope | the scope / exclusions loaded at Step 1 |

**Decision rubric (the attack questions the refuter tests this decision reasoning against):**

1. Is "What would prove me wrong" a genuinely observable falsifier — a specific, checkable condition — rather than a hedged or unfalsifiable restatement of the Rationale?
2. Are the `Acknowledged risks` complete, or does a material risk in the cited sources go unlisted?
3. Does the Rationale still follow from the `Related thesis`, or has it drifted from what that thesis actually claims?
4. Is the decision contradicted by its own cited sources — does any source the Rationale rests on actually point the other way?

The refuter returns its § Output schema verbatim — one `overturned | weakened | survives` verdict per rubric item. Render that returned block RAW + flagged as a distinct **"Adversarial critique"** block beside the decision record, then RE-PRESENT this SAME checkpoint with the critique added:

- The critique is shown intact; this mode may add a one-line agree/disagree per item but NEVER edits or suppresses it.
- It is single-pass — the refuter runs ONCE and never loops. Points the user accepts fold into the decision via the existing `[E]` path, NOT by re-running the refuter.
- The `[S]/[E]/[N]` choice then follows unchanged — the critique informs the decision; the user still decides. A failed or unavailable refuter NEVER blocks this checkpoint: present the decision record unchanged and proceed (`./adversarial-refuter.md` § Step 2).

## Step 5 — Delegate persistence to `sb-fin-create-decision`

On `[S]`, invoke `sb-fin-create-decision` in its **investor-orchestrated mode** (its named entry point — Invocation Inputs, mode = investor-orchestrated). Invoke it by **read-and-follow of its workflow file by path** — read `../sb-fin-create-decision/sb-fin-create-decision.md` and follow its steps 1–5. After the scribe is installed as a skill (build task p5-3), this MAY instead invoke the installed `sb-fin-create-decision` skill (Skill tool); until then, default to the path invocation. Either way the agent NEVER hand-writes the page and NEVER re-implements the scribe's filename/collision/frontmatter/section/citation/cross-link/index checks — those are the scribe's sole authority.

Pass these inputs; the scribe runs its steps without re-prompting:

| Input | Source |
|-------|--------|
| The action | the `decision_type` enum value reasoned in Step 2 |
| The decision date | today, unless the user states the date the decision was made |
| The asset-or-thesis subject | the subject the decision concerns (drives the filename slug) |
| Resolved reasoning per required section | the eight sections reasoned in Step 2 (`Context`, `Decision`, `Related thesis`, `Rationale`, `What I believed at the time`, `What would prove me wrong`, `Acknowledged risks`, `Review trigger`) |
| Related thesis/asset/company wikilinks | the `related_thesis` / `related_asset` / `related_company` selected in Step 3 |
| Source filenames | the captured-source filenames the reasoning cited (the scribe's `Data and sources used`) |

The scribe halts if the decision filename already exists for that date+action+subject (a same-day same-action decision is already recorded) — surface the conflict to the user; do NOT overwrite.

## Step 6 — Handoff

A decision that revises the conviction or status of its related thesis → suggest `/sb-investor review` (B3) to update the thesis page via its scribe; this mode NEVER edits the thesis. A suspected data problem encountered while reasoning → record it and route the user to `sb-bookkeeper` (`./investor-loop.md` § Read-only invariant) — never fix data in place.

---

## Boundaries (this mode)

- Read-only on portfolio/ledger data; position data ONLY through registered read tools (`./investor-loop.md` § Tools-only data access).
- Writes ONLY by invoking `sb-fin-create-decision` — the agent NEVER hand-writes a decision page (`./investor-loop.md` § Own-workspace-writes boundary).
- Never reasons or records transaction price / quantity / fees / position size — the `sb-bookkeeper` ledger owns those. A request to do so is out-of-structure → Rule A in `./investor-loop.md`.
- Never mutates ledgers, `portfolio.json`, or the dashboard. A request to do so, or to author the page by hand, is out-of-structure → Rule A.
- Every user-facing turn ends at an Investor Checkpoint (`./investor-loop.md` § Per-Step Checkpoint).
