---
stepId: investor-capability-manifest
runtime: agent-loop
---

# Investor Capability Manifest

The intent → capability → access-mechanism routing map for `/sb-investor`. `sb-investor.md` reads this file after loading `sb-investor-loop.md` to pick the capability that matches the user's natural-language ask, then reads-and-follows that capability (or chains several). The agent infers the capability from intent; it NEVER asks the user "which mode?".

This file routes. It does NOT restate the invariants, boundaries, policy read-rules, present-and-confirm pattern, or checkpoint — those live in `./investor-loop.md` and bind every capability listed here. Read `./investor-loop.md` before acting on any routed capability.

---

## Access mechanisms

Every capability below is reached by one or more of these three mechanisms. They are NOT all "skills" — route by the mechanism column, not by assuming a skill exists.

| Mechanism | Reach it by | Used for |
|-----------|-------------|----------|
| **Invoke installed skill** | Call the `Skill` tool with the named skill; follow it exactly | User-facing scribes that also stand alone (`sb-fin-create-thesis`, `sb-fin-create-decision`) |
| **Read-and-follow sb-os workflow file** | Read the named `.md` and execute its protocol turn by turn | Agent-internal reasoning modes, not user-invocable (`./thesis.md`, `./research.md`, `./review.md`, `./portfolio.md`, `./decision.md`) |
| **Call registered tool** | Run the tool named in `../../scripts/tools-index.md` (the tools-only data-access invariant) | All position/ledger data access (`position_table`, `position_summary`, `fx_impact_report`, `validate_calculate`) |

The `investment_source_capture` tool and the web-search sub-agent are additional `research`-only access mechanisms named in that capability's row. The **adversarial refuter** (below) is a further shared CROSS-mode mechanism — distinct from the three above and reachable ONLY from inside a refuter-enabled mode's checkpoint, never as a standalone intent.

### `research` discovery-wave dispatch (width sweep + Disconfirm)

`research`'s discovery is a **native sub-agent dispatch** mechanism (NOT the `deep-research` skill): the parent fans out web-search sub-agents — each directed to invoke `rbtv-web-searching` and follow it exactly, keeping discovery plugin-agnostic. Two waves use it: the **Step 3 width sweep** (one wave per Decompose sub-question) and the **Step 7a Disconfirm wave** (adversarial — "what source would OVERTURN the anchor?"). Both run **Haiku · ≤ 5 fetches · single-pass**; both return **ranked candidates + metadata ONLY** (full source text stays in the sub-agent — anti-context-rot) and surface at the Step 4 Propose present-and-confirm checkpoint. Mechanics: `./research.md` Steps 2.5 / 3 / 7a — never restated here.

**Step 7a Disconfirm is the stable, dispatchable interface that `thesis` (B1) and `review` (B3) reach by DISPATCHING `research`** (the existing `review`→`research` sub-agent precedent) — they NEVER re-implement discovery (single evidence engine). Consumers dispatch against this contract (authoritative in `./research.md` Step 7a — keep stable):

| Side | Contract |
|------|----------|
| **Input** | anchor claim / assumption (a consumer hands in the specific assumption or near/untested invalidation criterion) **+** the entity(ies) **+** the `research-policy` scope/exclusions |
| **Output** | ranked disconfirming candidates **+** metadata **+** a **why-it-would-overturn** note per candidate (what about the source, if true, falsifies the anchor); full source text never returns |

### Adversarial refuter (shared, optional, cross-mode)

The optional **adversarial refuter** is a shared CROSS-mode access mechanism, distinct from the three per-mode mechanisms above: a calling mode reaches it by **reading-and-following `./adversarial-refuter.md`** ONLY after the user elects `[R]` at that mode's present-and-confirm checkpoint. It is NOT a capability with its own intent row — it has NO "Fires on" trigger and is NEVER routed from a user's natural-language ask; the agent never selects it from this map. It is reachable ONLY from the present-and-confirm checkpoint of a **refuter-enabled mode** (`thesis` / `review` / `decision`), and `research` / `portfolio` / `policy` never reach it.

| Side | Contract |
|------|----------|
| **Reached by** | The calling mode reads-and-follows `./adversarial-refuter.md` after an `[R]` election (or an always-on `research-policy.md` key per `./investor-loop.md` § Present-and-confirm); never a standalone route |
| **Backend** | `auto` — Claude sub-agent default; Codex CLI opt-in via Bash; Codex absent/slow/error → sub-agent fallback (portable; a non-Codex installer is never broken) |
| **Input** | the drafted artifact **+** its cited sources (full text, read in the refuter's own context) **+** the calling mode's rubric **+** the `research-policy` scope |
| **Output** | a structured per-rubric-item verdict (`overturned` / `weakened` / `survives` + the disconfirming reason); persists NOTHING; the critique only feeds the calling mode's EXISTING checkpoint — the user still decides `[S]/[E]/[N]` |

Read-only / refute-only / no-generation / single-pass; it never fetches the web, calls a tool, persists, loops, or auto-acts. Mechanics, backends, and the invariant-preservation map are authoritative in `./adversarial-refuter.md` — never restated here.

---

## Capability map

One row group per mode. Route on the **Fires on** intent; reach the capability through its **Access mechanism**; load its **Inputs**; respect its **When NOT**.

### `thesis` (B1 — Capture)

| Field | Value |
|-------|-------|
| Fires on (intent) | "turn this into a thesis", "I think `<entity>` is mispriced because…", "write up my `<entity>` thesis", developing an informal investment idea into a structured claim |
| Access mechanism | Read-and-follow `./thesis.md` (the reasoning) **+** invoke `sb-fin-create-thesis` in its investor-orchestrated mode (the only writer of the thesis page) |
| Inputs | the informal idea / claim; the related entity(ies); `research-policy.md` (loaded per `./investor-loop.md` § Policy read-rules); any already-captured source filenames |
| When to use | The user is forming or articulating a NEW belief and wants it persisted as a falsifiable thesis (claim, causal mechanism, evidence for/against, invalidation criteria) |
| When NOT | Re-evaluating an EXISTING thesis against new information → `review`. Finding/capturing sources → `research`. Recording a buy/sell/hold → `decision`. The agent NEVER hand-writes the thesis page — persistence is always `sb-fin-create-thesis` |

### `research` (B2 — Evidence)

| Field | Value |
|-------|-------|
| Fires on (intent) | "research `<X>`", "find sources on `<Y>`", "what's the latest on my `<entity>` thesis", "dig into `<topic>`" |
| Access mechanism | Read-and-follow `./research.md` (the mode flow) **+** the `research` discovery-wave dispatch (above) — native web-search sub-agents for the Step 3 width sweep AND the Step 7a Disconfirm wave (plugin-agnostic) **+** `investment_source_capture` tool for capture **+** `sb-wiki-ingest` run via orchestrated sub-agents (one per source) for auto-ingest |
| Inputs | the anchoring thesis (existing or nascent) or a bare research question; the entity(ies); `research-policy.md` (scope/exclusions) and `source-policy.md` (trust classes), loaded per `./investor-loop.md` § Policy read-rules. When dispatched by `thesis`/`review`, the handed-in anchor is a specific assumption or near/untested invalidation criterion per the Step 7a Disconfirm input contract (above) |
| When to use | New OPEN-web sources must be discovered, proposed, captured to `raw/`, and filed into the wiki so research stops dying in chat. Internally the mode also: Decomposes the anchor into atomic sub-questions + a coverage matrix (Step 2.5) before discovery; runs a parallel width sweep (Step 3) and an adversarial Disconfirm wave (Step 7a); and flags coverage gaps + source tensions at Propose (Step 4) — mechanics in `./research.md`, never restated here. `thesis`/`review` reach Decompose/width-sweep/Disconfirm by DISPATCHING this mode, never by re-implementing them |
| When NOT | Weighing ALREADY-captured sources against a thesis verdict → `review`. Authoring the thesis itself → `thesis`. Gated/paywalled sources are NEVER fetched — they register `gated_pending_access` (per `./investor-loop.md` permanent source boundary) |

### `review` (B3 — Maintenance)

| Field | Value |
|-------|-------|
| Fires on (intent) | "review my `<entity>` thesis", "is `<thesis>` still valid?", "check `<thesis>` against the latest", a periodic-review prompt, a `Thesis Invalidation` candidate-trigger |
| Access mechanism | Read-and-follow `./review.md` (the reasoning) **+** the `research` Step 7a Disconfirm wave (above), DISPATCHED per near/untested invalidation criterion the Step 3a Assumption Audit flags as decayed — audit-driven, replacing the old thin-source auto-pull; its propose→approve checkpoint is retained **+** invoke `sb-fin-create-thesis` in extend mode (the only writer of thesis-page updates) |
| Inputs | the target thesis page (claim, evidence, invalidation criteria, `status`, `last_reviewed`); its related entities; sources newer than `last_reviewed`; `research-policy.md` + `source-policy.md`, loaded per `./investor-loop.md` § Policy read-rules |
| When to use | An EXISTING thesis must be tested against new evidence — staleness, new evidence-against, tripped/near invalidation criteria, a `status`/`conviction` change |
| When NOT | Creating a thesis that does not yet exist → `thesis`. Acquiring brand-new sources with no thesis to test → `research`. Acting on the buy/sell/hold a review implies → `decision`. Updates persist only via the scribe — never hand-written |

### `portfolio` (B4 — Coherence)

| Field | Value |
|-------|-------|
| Fires on (intent) | "does my portfolio still match my theses?", "which positions have no thesis?", "which theses have no exposure?", "check my `<entity>` position", "am I over-concentrated?" |
| Access mechanism | Read-and-follow `./portfolio.md` (the reasoning) **+** call the registered read tools `position_table`, `position_summary`, `fx_impact_report`, `validate_calculate` (per `../../scripts/tools-index.md`) **+** agent-performed join (read theses' `related_positions` frontmatter against the position list). No `portfolio-view` tool exists; the agent performs the coherence join itself |
| Inputs | position data via the read tools above (NEVER read `portfolio.json`/ledgers directly — tools-only invariant in `./investor-loop.md`); the thesis pages' `related_positions` frontmatter; `research-policy.md` (loaded per `./investor-loop.md` § Policy read-rules); single-company fundamentals read off the entity page's `## Financials` when reasoning |
| When to use | Belief must be mapped to REAL exposure — positions without theses, theses without exposure, concentration |
| When NOT | Reasoning about a belief with no portfolio link → `thesis`/`review`. Cross-entity fundamentals comparison (deferred; no tool in v1). Any ledger/`portfolio.json` mutation → out-of-structure, route to `sb-bookkeeper` per `./investor-loop.md` Rule A |

### `decision` (B5 — Decision record)

| Field | Value |
|-------|-------|
| Fires on (intent) | "I'm buying/selling/holding `<asset>` — record it", "log this decision", "note that I passed on `<X>` because…" |
| Access mechanism | Read-and-follow `./decision.md` (the reasoning) **+** invoke `sb-fin-create-decision` (the only writer of the decision page) |
| Inputs | the action (buy/sell/hold/pass) + its rationale; the related thesis / asset / company; relevant sources; `research-policy.md` if the decision reasons about a thesis (loaded per `./investor-loop.md` § Policy read-rules) |
| When to use | A buy/sell/hold/pass outcome and its reasoning must be persisted as an auditable dated record in `decisions/` |
| When NOT | Forming the underlying belief → `thesis`. Testing whether a thesis still holds → `review`. The agent NEVER hand-writes the decision page — persistence is always `sb-fin-create-decision` |

### `policy` (B6 — Governance)

| Field | Value |
|-------|-------|
| Fires on (intent) | "show my research policy", "update my exclusions", "what sources do I trust", "add `<X>` to my watchlist policy" |
| Access mechanism | **Inline in `./investor-loop.md` § B6 Policy thin mode** — NOT a separate capability file. Follow that section |
| Inputs | `.user/finance/investor/research-policy.md` and `.user/finance/investor/source-policy.md` (read-write, user content, inside the own-workspace boundary) |
| When to use | The user reads or changes the policy content itself (scope, priorities, exclusions, watchlist-approval, horizon, source trust) |
| When NOT | A mode merely LOADING policy before reasoning is the always-on read-rules wiring in `./investor-loop.md`, not this user-facing mode. Setting `watchlist: true` requires explicit user approval (watchlist invariant in `./investor-loop.md`) |

---

## Multi-mode chaining

A single ask MAY span several capabilities. Route to ALL matching modes in dependency order, not the single best match — a mis-fired single mode silently drops half the request.

| User ask (example) | Chain |
|--------------------|-------|
| "review my `<entity>` thesis vs today's earnings and check my position" | `review` → `portfolio` |
| "research `<topic>` then turn it into a thesis" | `research` → `thesis` |
| "review `<thesis>` and, if it's broken, record the sell" | `review` → `decision` |
| "find the latest on `<entity>` and tell me if my thesis still holds" | `research` → `review` |

Chaining rules:

1. **Order by dependency.** A mode that produces an input for another runs first (`research` before `review`/`thesis`; `review` before `decision`).
2. **Each chained mode keeps its own checkpoint.** Every capability's STOP is an Investor Checkpoint per `./investor-loop.md` § Per-Step Checkpoint — chaining never collapses two confirmations into one silent run.
3. **A blocking issue in an earlier mode halts the chain** at that mode's checkpoint (per `./investor-loop.md` § Issue-surfacing) — later modes do not run on untrustworthy output.
4. **Ambiguous single-vs-multi intent → surface it**, do not guess: present the candidate chain via `./investor-loop.md` § Present-and-confirm and let the user confirm the scope.
