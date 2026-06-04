# Wiki Log Entry Shapes

Format for all entry types appended to `{wiki_root}/log.md`. The log is append-only and single-file.

## Header Format

Every entry is an H2 heading:

```
## [YYYY-MM-DD HH:MM] <type> | <brief>
```

Use the SAME timestamp for every sibling entry emitted in one ingest run so cross-references resolve cleanly.

## Active Types (2)

The log is an ACTIONABLE QUEUE — it holds ONLY items awaiting a user action. Each entry is a STANDALONE H2 entry; entries do NOT reference a parent ingest.

| Type | Trigger | Awaiting action | Leaves the queue when |
|------|---------|-----------------|------------------------|
| `candidate-topic` | One of 3 triggers fires during ingest or lint | Promote via `sb-wiki-create-topic`, or dismiss | The topic page exists (create-topic removes it on promotion; lint prunes any candidate whose page exists) |
| `candidate-mention` | Entity/concept name surfaced in ingest step 3 but the stub-creation rule did NOT fire (per `stub-policy.md`) | Review → promote to a stub, or dismiss | The matching page exists (lint prunes), or the user dismisses it. NEVER auto-aged |

**Resolution = page exists.** A candidate is spent the moment its page exists; lint detects this by filename and removes the entry. There is no separate resolution entry.

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
```

## Candidate-mention Is Single-Subject

A `candidate-mention` names ONE subject: the heading `<brief>`, the `name:` field, and the resulting page filename on promotion are the SAME single name. This preserves the "Resolution = page exists" contract — lint prunes the entry the moment that one page exists.

NEVER use a synthetic collective slug (e.g., `seal-researchers`, `ai-ethics-institutes`) as the heading with multiple members in `name:`. An ad-hoc sibling set is logged as ONE entry PER member (per `stub-policy.md` § "Sibling clusters (test 3) — named collective vs. ad-hoc set"). A collective slug can never resolve — its page must never exist (`page-types.md` § "Aggregation Rule") — so it would orphan the entry in the queue.

## Retired Types (NO LONGER written)

`ingest`, `concept-created`, `entity-created`, `topic-created`, `topic-updated`, `topic-coverage-candidate`, `lint`, and `query` were logged pre-v1. They are no longer emitted — the source pages, raw indexes, and wiki pages are the record. Lint deletes any surviving instances on its next pass.

## Unknown Types

An entry whose type is neither active nor retired is NON-CANONICAL — a writer violated the queue contract. Lint KEEPS the entry (it may carry unrecovered content) and surfaces it in the LINT REPORT for manual routing to the correct vault home — NEVER auto-deletes it. Fix the misbehaving writer; NEVER register a personal capture type here — the log holds exclusively the two active types, and personal captures route to vault files.
