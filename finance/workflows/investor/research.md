---
stepId: investor-research
runtime: agent-loop
---

# Research Mode (B2 — Evidence)

The `/investor` reasoning mode that discovers, proposes, captures, and auto-files OPEN-web sources in service of a thesis or research question, so research stops dying in chat. **This mode NEVER hand-writes a raw source file or a wiki page** — it reasons and proposes; the `investment_source_capture` tool persists to `raw/`, and `sb-wiki-ingest` (run via sub-agents) files into the wiki (delegate-not-replace).

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

## Step 3 — Discover (web-search sub-agent)

Dispatch a web-search sub-agent to find OPEN sources. The dispatch MUST keep the mode plugin-agnostic — it is NOT wired to any single search plugin, preserving sb-os finance-module portability.

The sub-agent prompt MUST direct it to **invoke the `rbtv-web-searching` skill before any web work and follow it exactly** (per the sub-agents rule — a sub-agent does not inherit this requirement; the parent states it explicitly and imperatively). The prompt passes the anchor (thesis claim / research question), the entity(ies), and the `research-policy` scope and exclusions so the sub-agent does not surface excluded topics.

Rank returned candidates by relevance to the anchor AND by `source-policy` trust class (load it in Step 1). A candidate that fails the `source-policy` trust bar is surfaced per `./investor-loop.md` § Issue-surfacing — never silently dropped or silently kept. Discovery writes NOTHING; it only returns ranked candidates with metadata (title, url, source, trust class).

## Step 4 — Propose (present-and-confirm; DEFAULT = propose before capture)

Run `./investor-loop.md` § Present-and-confirm. Default behavior is propose-before-capture: present the ranked candidates and STOP for the user's selection — NEVER capture before approval. Present each candidate as a row:

```
| # | title | url | source | trust class | why it matters | relation to the thesis |
```

The user approves a SUBSET. Approved OPEN candidates → state `approved_for_capture` (Step 5). Candidates the user rejects → state `rejected` (no capture, no record beyond the turn). Candidates the user (or discovery metadata) marks gated/paywalled → the gated branch (Step 6). This is a mode checkpoint per `./investor-loop.md` § Per-Step Checkpoint.

## Step 5 — Capture approved OPEN sources

For EACH `approved_for_capture` OPEN source, call the registered `investment_source_capture` tool (`../../scripts/tools-index.md`) — the SOLE writer of `raw/` files; the agent NEVER hand-writes a raw source file (`./investor-loop.md` § Own-workspace-writes boundary). Pass the url, the origin folder, the fetch mode, and the anchoring thesis slug per the tool's `expected_inputs`.

The tool saves to `{wiki_root}/raw/{origin}/` and returns a **metadata summary only** (state, saved path, title, origin, related thesis, byte count) — full source text NEVER enters this mode's context. On success → state `captured_to_raw`; capture the returned raw filename for Step 7. A tool result of `state=blocked` (unreachable / fetch failed) → surface it per `./investor-loop.md` § Issue-surfacing; that source stops at `blocked` and is NOT ingested.

## Step 6 — Gated sources register (NOT fetched)

A gated source (paywall / login / IR / broker portal) is NEVER fetched — the permanent source boundary in `./investor-loop.md` (no paywall bypass, no bank/brokerage credentials). Register it as `gated_pending_access` by calling the `investment_source_capture` tool with its `--gated` path — the SOLE writer of the gated record (it appends to `raw/{origin}/log.md` without fetching, co-located with where the user later drops the manual fetch; the agent NEVER hand-writes that record, per `./investor-loop.md` § Own-workspace-writes boundary). Pass title, url, origin, the related thesis slug, and why it matters per the tool's `expected_inputs`; the tool records the required user action. So the gated source surfaces at end-of-interaction instead of dying in chat, ALSO record it as a deferrable issue per `./investor-loop.md` § Issue-surfacing. State → `gated_pending_access`. Never advance a gated source to capture or ingest.

## Step 7 — Auto-ingest (one sub-agent per captured source)

After capture, file each `captured_to_raw` source into the wiki by dispatching **one sub-agent per source** (fanned out — full text stays in each sub-agent's context, so this mode and `investor.md` stay clean). The agent invokes the real ingest command via the sub-agent; it NEVER reimplements ingest.

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
