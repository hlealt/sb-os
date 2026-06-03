---
stepId: investor-research
runtime: agent-loop
---

# Research Mode (B2 — Evidence)

The `/sb-investor` reasoning mode that discovers, proposes, captures, and auto-files OPEN-web sources in service of a thesis or research question, so research stops dying in chat. **This mode NEVER hand-writes a raw source file or a wiki page** — it reasons and proposes; the `investment_source_capture` tool persists to `raw/`, and `sb-wiki-ingest` (run via sub-agents) files into the wiki (delegate-not-replace).

**Loaded by:** `./investor.md` reads-and-follows this file when `./capability-manifest.md` routes the `research` (B2) intent. The invariants, policy read-rules wiring, present-and-confirm pattern, issue-surfacing, Rule A, and the per-step Investor Checkpoint in `./investor-loop.md` are already in force when this file runs — this file does NOT restate them. Read `./investor-loop.md` before acting on any step below.

**Access mechanisms (this mode):** discovery = web-search sub-agent (plugin-agnostic) · capture = `investment_source_capture` registered tool (`../../scripts/tools-index.md`) · auto-ingest = `/sb-wiki-ingest silent <slug>` run via one sub-agent per source. All three are declared in `./capability-manifest.md` § `research`.

**Source lifecycle states (this mode drives them):** `rejected` → `approved_for_capture` → `captured_to_raw` → `ingested_to_wiki`; gated sources take the `gated_pending_access` branch; an unreachable/failed fetch is `blocked`. Each step below names the state it sets.

---

## Step 1 — Policy gate (MANDATORY, FIRST)

Before ANY web work, load the policy file(s) `../../CLAUDE.md` § Policy Read-Rules requires — per `./investor-loop.md` § Policy read-rules wiring. Researching sources for an investment is such an action: `research-policy.md` is required (scope / priorities / exclusions / horizon); load `source-policy.md` too (it weighs and trusts the sources this mode discovers). NEVER restate the read-rules table — read it.

If `research-policy.md` marks the research topic out-of-scope or excluded, say so and STOP, or offer to widen scope via the `policy` thin mode — do NOT reason past an exclusion (`./investor-loop.md` § Policy read-rules wiring; Rule A). This gate runs before Step 2 every time; no discovery dispatches before it clears.

## Step 2 — Anchor

Tie the research to its subject before discovering anything:

| Anchor | When | Effect |
|--------|------|--------|
| Existing thesis (preferred) | The ask names or implies a thesis already in the wiki | Discovery, ranking, and the "relation to the thesis" column are scoped to that thesis's claim and entities |
| Nascent thesis | The user is forming a belief not yet persisted | Anchor to the in-progress claim; the captured evidence later feeds `thesis` (B1) |
| Exploratory research question | A bare topic with no thesis ("dig into `<topic>`") | Register the question; exploratory findings MAY later fire a `candidate-thesis` trigger (Step 8) that feeds B1 |

Identify the entity(ies) the research touches — they scope discovery and become the `--thesis` / origin context passed to capture.

## Step 2.5 — Decompose (atomic sub-questions + coverage matrix)

Before discovering anything, split the anchor (the thesis claim or research question fixed in Step 2) into **atomic sub-questions** — the smallest standalone questions whose answers, taken together, settle the anchor. Decomposition is ANCHORED: every sub-question must trace to the anchor's claim and the entity(ies) from Step 2; do not drift into adjacent topics the anchor does not raise, and respect the `research-policy` scope/exclusions loaded in Step 1 (a sub-question that probes an excluded topic is dropped here, not searched).

Build a **coverage matrix** mapping each sub-question to the angle and source-type that will address it. The matrix is the contract the Step 3 width sweep fans out against (one discovery wave per sub-question) and the yardstick the Step 4 Propose step measures coverage gaps against:

```
| # | sub-question | angle / source-type that will address it |
```

Decompose reasons only; it writes nothing and fetches nothing. Keep it lightweight — atomic sub-questions and one matrix, not a research plan. This step adds no web access and no new write path.

## Step 3 — Discover (parallel width sweep — one sub-agent wave per sub-question)

Run a **parallel width sweep**: fan out web-search sub-agents — **one wave per Step 2.5 sub-question** — dispatched concurrently so breadth is covered in a single pass rather than one serial search. Each wave hunts OPEN sources for its own sub-question and the angle/source-type the coverage matrix assigned it. The fan-out MUST keep the mode plugin-agnostic — discovery is NOT wired to any single search plugin, preserving sb-os finance-module portability.

**The Step 7a Disconfirm wave fires in THIS same discovery pass** (it is numbered 7a for dispatch-identity only — see Step 7a § Where it runs; it is NOT a post-ingest step). Dispatch it concurrently with the width-sweep waves here; its disconfirming candidates merge into the same Step 4 Propose table. The remaining acquisition steps (Capture → Gated → Auto-ingest, Steps 5–7) act ONLY on the subset the user approves at Step 4.

**Cost cap (every discovery wave — width sweep AND the Step 7a Disconfirm wave).** This is the explicit cheap-model override the deepening mandates (it overrides the `sb-sub-agents` default of `sonnet`); name it in each wave's dispatch:

| Knob | Value |
|------|-------|
| Model | **Haiku** (high-volume discovery does not need deep reasoning) |
| Max fetches per wave | **≤ 5** |
| Wave shape | **single-pass** — each wave fires once, returns, and NEVER loops |
| Concurrency | parallel fan-out, bounded by the per-wave fetch cap |

Each discovery sub-agent's prompt MUST:

1. **Invoke the `rbtv-web-searching` skill before any web work and follow it exactly** (per the sub-agents rule — a sub-agent does not inherit this requirement; the parent states it explicitly and imperatively).
2. Carry its assigned sub-question, the anchor (thesis claim / research question), the entity(ies), and the `research-policy` scope and exclusions so the sub-agent does not surface excluded topics.
3. **Return ONLY ranked candidates + metadata** — `| title | url | source | trust class | why it matters | relation to the thesis |`. The **full source text MUST stay inside the sub-agent** and NEVER returns to this mode or `sb-investor.md` (anti-context-rot — the parent context stays clean; only ranked candidates + metadata cross back).

Merge the waves' returned candidates and rank them by relevance to the anchor AND by `source-policy` trust class (loaded in Step 1). A candidate that fails the `source-policy` trust bar is surfaced per `./investor-loop.md` § Issue-surfacing — never silently dropped or silently kept. Discovery writes NOTHING; it only returns ranked candidates with metadata. The merged candidate set (plus the Step 7a disconfirming candidates) is what Step 4 Propose presents.

## Step 4 — Propose (present-and-confirm; DEFAULT = propose before capture)

Run `./investor-loop.md` § Present-and-confirm. Default behavior is propose-before-capture: present the ranked candidates and STOP for the user's selection — NEVER capture before approval. Present each candidate as a row, including the Step 7a disconfirming candidates merged into the same table:

```
| # | title | url | source | trust class | why it matters | relation to the thesis |
```

Tag every Step 7a Disconfirm-wave candidate in its `relation to the thesis` cell as **disconfirming (evidence-against)** so the user sees, in one table, both the sources that support the anchor and the source(s) that would overturn it — never an undifferentiated list. (Step 7a defines the disconfirming wave; its candidates arrive here pre-tagged.)

**Coverage gaps (from Step 2.5).** Cross-check the merged candidates against the Step 2.5 coverage matrix and surface, beneath the table, any **sub-question with no candidate** — an explicit "coverage gaps" note so the user sees what the sweep did not cover before approving:

```
Lacunas de cobertura: sub-questions {#…} têm zero candidatos.
```

A coverage gap is informational, not blocking — the user MAY approve the subset anyway, widen scope, or re-run discovery for the uncovered sub-questions.

**Source tensions (lightweight flag).** From the candidates' titles and `why it matters` / `relation to the thesis` metadata ALREADY on the table — never by pulling full source text (anti-context-rot holds) — flag pairs or clusters of candidates that **contradict each other** (e.g. opposite conclusions on the same sub-question). Surface them as a short note beneath the table so the user weighs the disagreement instead of an undifferentiated list:

```
Tensões entre fontes: #{a} ↔ #{b} — {one-line description of the disagreement}.
```

This is a flag the user can act on, not a separate analysis pass: it reads only the metadata already returned. If no contradiction is evident from the metadata, write none — do not fetch text to manufacture one. The signal stays legible for `review` to consume downstream.

The user approves a SUBSET (supporting and/or disconfirming candidates alike). Approved OPEN candidates → state `approved_for_capture` (Step 5). Candidates the user rejects → state `rejected` (no capture, no record beyond the turn). Candidates the user (or discovery metadata) marks gated/paywalled → the gated branch (Step 6). The coverage-gap and source-tension notes do not change this subset-approval flow — they inform it. This is a mode checkpoint per `./investor-loop.md` § Per-Step Checkpoint.

## Step 5 — Capture approved OPEN sources

For EACH `approved_for_capture` OPEN source, call the registered `investment_source_capture` tool (`../../scripts/tools-index.md`) — the SOLE writer of `raw/` files; the agent NEVER hand-writes a raw source file (`./investor-loop.md` § Own-workspace-writes boundary). Pass the url, the origin folder, the fetch mode, and the anchoring thesis slug per the tool's `expected_inputs`.

The tool saves to `{wiki_root}/raw/{origin}/` and returns a **metadata summary only** (state, saved path, title, origin, related thesis, byte count) — full source text NEVER enters this mode's context. On success → state `captured_to_raw`; capture the returned raw filename for Step 7. A tool result of `state=blocked` (unreachable / fetch failed) → surface it per `./investor-loop.md` § Issue-surfacing; that source stops at `blocked` and is NOT ingested.

## Step 6 — Gated sources register (NOT fetched)

A gated source (paywall / login / IR / broker portal) is NEVER fetched — the permanent source boundary in `./investor-loop.md` (no paywall bypass, no bank/brokerage credentials). Register it as `gated_pending_access` by calling the `investment_source_capture` tool with its `--gated` path — the SOLE writer of the gated record (it appends to `raw/{origin}/log.md` without fetching, co-located with where the user later drops the manual fetch; the agent NEVER hand-writes that record, per `./investor-loop.md` § Own-workspace-writes boundary). Pass title, url, origin, the related thesis slug, and why it matters per the tool's `expected_inputs`; the tool records the required user action. So the gated source surfaces at end-of-interaction instead of dying in chat, ALSO record it as a deferrable issue per `./investor-loop.md` § Issue-surfacing. State → `gated_pending_access`. Never advance a gated source to capture or ingest.

## Step 7 — Auto-ingest (one sub-agent per captured source)

After capture, file each `captured_to_raw` source into the wiki by dispatching **one sub-agent per source** (fanned out — full text stays in each sub-agent's context, so this mode and `sb-investor.md` stay clean). The agent invokes the real ingest command via the sub-agent; it NEVER reimplements ingest.

Each sub-agent prompt MUST direct it to:

1. **Run `/sb-wiki-ingest silent <slug>`** — the non-interactive form (`<slug>` = the raw filename returned by Step 5). The `silent` keyword makes the run emit no checkpoints and return a structured per-file summary, per `sb-wiki-ingest`'s Silent Mode.
2. **Invoke the `sb-wiki-ingest` skill and follow it exactly**, and **invoke the `sb-vault-ops` skill before the file operations it performs and follow it exactly** (per the sub-agents rule — stated explicitly and imperatively because a sub-agent does not inherit these requirements).
3. **Return only the structured summary** (per-file status `committed` / `partial (<reason>)` / `failed (<reason>)`, plus pages created/updated and any candidate-topic or lint flags). The full source text MUST NOT be returned to the parent.

On a returned summary → state `ingested_to_wiki` for that source. A `failed` / `partial` status is surfaced per `./investor-loop.md` § Issue-surfacing — never silently treated as ingested.

### Post-ingest report (MANDATORY — replaces a pre-ingest confirm)

After all sub-agents return, present a consolidated report so a misfire is catchable:

```
| source (slug) | ingest status | pages created/updated | scope-overlaps / lint flags |
```

Summarize, in `communication.language`, the pages created/updated and any scope-overlaps or lint flags the sub-agents surfaced. A flag is an issue → route it per `./investor-loop.md` § Issue-surfacing (blocking vs deferrable). The report is informational-by-default; it does NOT re-prompt for the already-committed ingests (the Step 4 approval authorized capture-and-file).

## Step 7a — Disconfirm (adversarial discovery wave)

The highest-value discovery primitive: instead of asking "what supports the anchor?", it asks **"what source would OVERTURN the anchor?"** and hunts for it — making the rigor spine (evidence → counter-evidence → invalidation) an ACTIVE search, not a reasoned-from-context afterthought. Step 7a is the **stable, dispatchable home** of this wave: `thesis` (B1) and `review` (B3) reach it by DISPATCHING `research` (the existing `review`→`research` sub-agent precedent), never by re-implementing discovery. Keep its interface below stable — consumers depend on it.

**Where it runs (sequencing).** Although numbered 7a, the Disconfirm wave is a DISCOVERY operation: it fires in the discovery pass **alongside the Step 3 width sweep**, and its candidates merge into the **Step 4 Propose** table tagged `disconfirming (evidence-against)` — they are NOT a post-ingest step. Capture/ingest (Steps 5–7) act only on the subset the user approves at Step 4; a disconfirming candidate the user approves flows through capture-and-ingest exactly like any other approved source. The 7a label marks the wave's identity and dispatch interface, not a runtime position after ingest.

**Interface (DOCUMENTED — keep stable; `thesis`/`review` dispatch against this):**

| Side | Contract |
|------|----------|
| **Input** | The anchor claim / assumption (the Step 2 thesis claim, or — when dispatched by a consumer — the specific assumption or near/untested invalidation criterion the consumer hands in) + the entity(ies) + the `research-policy` scope/exclusions |
| **Output** | **Ranked disconfirming candidates + metadata ONLY**, each carrying a **why-it-would-overturn** note (what about the source, if true, falsifies the anchor) in addition to the standard `| title | url | source | trust class | why it matters | relation to the thesis |` fields. Full source text NEVER returns to the parent. |

**Dispatch.** Prompt ONE sub-agent (native dispatch — NOT the `deep-research` skill) to find the strongest source that would FALSIFY the anchor. The prompt MUST:

1. **Invoke the `rbtv-web-searching` skill before any web work and follow it exactly** (the sub-agent does not inherit this requirement; state it explicitly and imperatively), keeping the wave plugin-agnostic (no hard-wired search plugin).
2. Frame the hunt adversarially: search for the data, analysis, or primary source that, if it exists and holds, breaks the anchor — not for confirmation of it.
3. Obey the **same cost cap as the width sweep** (Step 3 table): **Haiku model · ≤ 5 fetches · single-pass, never loops**.
4. **Return ONLY ranked disconfirming candidates + metadata + the why-it-would-overturn note.** The **full source text MUST stay inside the sub-agent** (anti-context-rot — the parent context stays clean).

Rank the returned disconfirming candidates by `source-policy` trust class (loaded in Step 1) exactly as Step 3 does; a candidate that fails the trust bar is surfaced per `./investor-loop.md` § Issue-surfacing — never silently dropped or kept. The wave writes NOTHING and fetches nothing into this mode; it adds no new data-access path. Its candidates feed the Step 4 Propose checkpoint, where the user approves or rejects them through the unchanged present-and-confirm subset flow — nothing disconfirming is captured before approval.

## Step 8 — Feed forward

Ingested sources are now evidence available to other modes:

- They feed `thesis` (B1) authoring as sourced evidence-for / evidence-against.
- They feed `review` (B3) when an existing thesis is re-evaluated against fresh sources.
- A `candidate-thesis` trigger (Recurring Claim / Mispricing Signal / Thesis Invalidation, per the finance module's `candidate-thesis-triggers.md`) MAY fire from the new evidence — surface it; a `Thesis Invalidation` fire suggests `review` (B3), a Recurring Claim / Mispricing Signal suggests `thesis` (B1). Surfacing a candidate-thesis is a proposal, never an auto-author — the agent NEVER writes a thesis page from this mode.

State the chain options to the user; do NOT auto-chain without the routing the user confirms (`./capability-manifest.md` § Multi-mode chaining).

---

## Boundaries (this mode)

- Read-only on portfolio/ledger data; position data ONLY through registered read tools (`./investor-loop.md` § Tools-only data access). This mode reads no position data directly.
- Writes ONLY to `raw/` via the `investment_source_capture` tool (including the gated `raw/{origin}/log.md` record), to `.user/finance/investor/log.md` (deferred-issue records per § Issue-surfacing), and to the wiki via `sb-wiki-ingest` run through sub-agents — the agent NEVER hand-writes a raw source file or a wiki page (`./investor-loop.md` § Own-workspace-writes boundary).
- NEVER bypasses a paywall and NEVER uses bank/brokerage credentials — gated sources register `gated_pending_access` only (permanent source boundary in `./investor-loop.md`).
- Never mutates ledgers, `portfolio.json`, or the dashboard. A request to do so, to bypass a paywall, or to hand-write a raw/wiki file is out-of-structure → Rule A in `./investor-loop.md`.
- Every user-facing turn ends at an Investor Checkpoint (`./investor-loop.md` § Per-Step Checkpoint). User-facing strings are in `communication.language` per `./investor.md` § Rules and `./investor-loop.md` § Language.
