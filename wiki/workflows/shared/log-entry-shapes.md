# Wiki Log Entry Shapes

Format for all entry types appended to the split logs under `{wiki_root}/logs/`. Each log is append-only; entries are split across three files BY TYPE (each file holds only its own type(s) — the deterministic prune maps filename → entry-type):

| File | Entry type(s) |
|------|---------------|
| `logs/topics.md` | `candidate-topic` |
| `logs/mentions.md` | `candidate-mention` (concept + entity unified; `classification:` inline) |
| `logs/theses.md` | `proposed-new-thesis`, `speculative-thesis-update` |

## Header Format

Every entry is an H2 heading:

```
## [YYYY-MM-DD HH:MM] <type> | <brief>
```

Use the SAME timestamp for every sibling entry emitted in one ingest run so cross-references resolve cleanly.

## Active Types (4)

Each log is an ACTIONABLE QUEUE — it holds ONLY items awaiting a user action. Each entry is a STANDALONE H2 entry; entries do NOT reference a parent ingest.

| Type | File | Trigger | Awaiting action | Leaves the queue when |
|------|------|---------|-----------------|------------------------|
| `candidate-topic` | `logs/topics.md` | One of 3 triggers fires during ingest or lint | Promote via `sb-wiki-create-topic`, or dismiss | The topic page exists (create-topic removes it on promotion; lint prunes any candidate whose page exists) |
| `candidate-mention` | `logs/mentions.md` | Entity/concept name surfaced in ingest step 3 but the stub-creation rule did NOT fire (per `stub-policy.md`) | Review → promote to a stub, or dismiss | The matching page exists (lint prunes), or the user dismisses it. NEVER auto-aged |
| `proposed-new-thesis` | `logs/theses.md` | A new-thesis trigger fires on the investor path (per `finance/wiki-ext/candidate-thesis-triggers.md`) | Promote via `sb-fin-create-thesis`, or dismiss | The thesis page exists — create-thesis removes it on promotion; lint prunes by filename against `wiki/theses/` pages (resolves like `candidate-topic`) |
| `speculative-thesis-update` | `logs/theses.md` | A speculative change to an EXISTING thesis is proposed on the investor path | `sb-fin-create-thesis` extend applies it on user action, or the user dismisses | The user acts (create-thesis extend deletes the referenced entry) or dismisses. **Lint NEVER auto-prunes it** (see below) |

**Resolution = page exists** — for `candidate-topic`, `candidate-mention`, and `proposed-new-thesis`. A candidate is spent the moment its page exists; lint detects this by filename and removes the entry. There is no separate resolution entry.

**EXCEPTION — `speculative-thesis-update` resolves EXPLICIT-ONLY.** Its target thesis page already exists, so "page exists" carries NO resolution signal. It resolves only when the user acts (`sb-fin-create-thesis` extend deletes the referenced entry) or dismisses it; lint NEVER auto-prunes it — it ages + surfaces it as "awaiting investor decision." Thesis changes NEVER auto-apply (hard rule A7) — `logs/theses.md` is a surface-only proposal queue; every promotion/update flows through `sb-fin-create-thesis` with user approval.

## Entry Shapes

```markdown
## [2026-04-30 14:32] candidate-topic | mcp-debate
- trigger: contradiction (same-scope-opposing)
- between: [[2026-04-30-code-mode-mcp.md]] and [[2026-04-29-bye-bye-mcp.md]]
- claim A (verbatim): "MCP works in code-mode form when collapsed to..."
- claim B (verbatim): "MCP went sideways for our use case..."
- promote via: sb-wiki-create-topic skill (express intent: "create the mcp-debate topic")

## [2026-04-30 14:32] candidate-mention | sandboxing
- name: sandboxing
- classification: concept
- reason: stub rule did not fire (name not in source title, Notable Quote, or Substance bullet)

## [2026-06-09 10:15] proposed-new-thesis | ai-capex-overbuild
- thesis: <one-line statement of the proposed new thesis>
- trigger: recurring-claim | mispricing-signal | thesis-shaped-page-created
- sources: [[2026-06-08-some-source.md]]
- promote via: sb-fin-create-thesis (express intent: "create the ai-capex-overbuild thesis")

## [2026-06-09 10:15] speculative-thesis-update | ai-capex-overbuild
- target thesis: [[ai-capex-overbuild.md]]
- trigger: thesis-invalidation
- change: <one-line statement of the proposed change to the existing thesis>
- source: [[2026-06-08-some-source.md]]
- apply via: sb-fin-create-thesis extend (user decision REQUIRED — never auto-applies; lint never auto-prunes)
```

The `<brief>` of a `proposed-new-thesis` MUST be the thesis page slug — lint resolves it by filename against `wiki/theses/` pages (resolution = page exists), exactly as `candidate-topic` resolves against topic pages. A `speculative-thesis-update` carries no filename-prune contract (the page already exists); its `target thesis:` wikilink identifies the existing page the proposed change applies to.

## Candidate-mention Is Single-Subject

A `candidate-mention` names ONE subject: the heading `<brief>`, the `name:` field, and the resulting page filename on promotion are the SAME single name. This preserves the "Resolution = page exists" contract — lint prunes the entry the moment that one page exists.

NEVER use a synthetic collective slug (e.g., `seal-researchers`, `ai-ethics-institutes`) as the heading with multiple members in `name:`. An ad-hoc sibling set is logged as ONE entry PER member (per `stub-policy.md` § "Sibling clusters (test 3) — named collective vs. ad-hoc set"). A collective slug can never resolve — its page must never exist (`page-types.md` § "Aggregation Rule") — so it would orphan the entry in the queue.

## Retired Types (NO LONGER written)

`ingest`, `concept-created`, `entity-created`, `topic-created`, `topic-updated`, `topic-coverage-candidate`, `lint`, and `query` were logged pre-v1. They are no longer emitted — the source pages, raw indexes, and wiki pages are the record. Lint deletes any surviving instances on its next pass.

## Unknown Types

An entry whose type is neither active nor retired is NON-CANONICAL — a writer violated the queue contract. Lint KEEPS the entry (it may carry unrecovered content) and surfaces it in the LINT REPORT for manual routing to the correct vault home — NEVER auto-deletes it. Fix the misbehaving writer; NEVER register a personal capture type here — the log holds exclusively the two active types, and personal captures route to vault files.
