# Wiki Log Entry Shapes

Format for all entry types appended to `{wiki_root}/log.md`. The log is append-only and single-file.

## Header Format

Every entry is an H2 heading:

```
## [YYYY-MM-DD HH:MM] <type> | <brief>
```

Use the SAME timestamp for every sibling entry emitted in one ingest run so cross-references resolve cleanly.

## Active Types (7)

| Type | Trigger | Sibling of |
|------|---------|------------|
| `ingest` | `/sb-wiki-ingest <slug>` — always emitted | — (anchor entry) |
| `candidate-topic` | One of 3 triggers fires during ingest or lint | Sibling of parent `ingest`; referenced from it by timestamp |
| `concept-created` | Stub Concept created during ingest step 5 | Sibling of parent `ingest`; referenced from it by timestamp |
| `entity-created` | Stub Entity created during ingest step 5 | Sibling of parent `ingest`; referenced from it by timestamp |
| `topic-created` | `sb-wiki-create-topic` skill — mid-ingest or user-intent-driven | Sibling of parent `ingest` (or standalone if user-intent-driven) |
| `lint` | `/sb-wiki-lint` | — (standalone) |
| `query` | `/sb-wiki-query` — only if the user files the answer back | — (standalone) |

**Sibling rule:** `candidate-topic`, `concept-created`, `entity-created`, and `topic-created` entries are NEVER nested under the parent `ingest` entry. They are sibling H2 entries in `log.md`, referenced from the parent `ingest` entry by timestamp.

## Entry Shapes

```markdown
## [2026-04-30 14:32] ingest | Code Mode (Cloudflare)
- source: [[2026-04-30-code-mode-mcp.md]] (new)
- updated: [[model-context-protocol.md]] (+ Code Mode perspective)
- candidate-topic: see entry at 14:32
- concept-created: see entry at 14:32
- entity-created: see entry at 14:32

## [2026-04-30 14:32] candidate-topic | mcp-debate
- trigger: contradiction (same-scope-opposing)
- between: [[2026-04-30-code-mode-mcp.md]] and [[2026-04-29-bye-bye-mcp.md]]
- claim A (verbatim): "MCP works in code-mode form when collapsed to..."
- claim B (verbatim): "MCP went sideways for our use case..."
- promote via: sb-wiki-create-topic skill (express intent: "create the mcp-debate topic")

## [2026-04-30 14:32] concept-created | code-execution-pattern
- page: [[code-execution-pattern.md]]
- kind: pattern
- from-ingest: 2026-04-30 14:32

## [2026-04-30 14:32] entity-created | cloudflare
- page: [[cloudflare.md]]
- kind: company
- from-ingest: 2026-04-30 14:32

## [2026-04-30 16:10] topic-created | mcp-debate
- resolves: candidate from 2026-04-30 14:32
- page: [[mcp-debate.md]]
- framing: "When MCP earns its complexity vs. when it doesn't"

## [2026-05-07 09:00] lint | weekly health-check
- stubs aged >30d (3): [[X.md]], [[Y.md]], [[Z.md]]
- orphans (no inbound) (2): [[A.md]], [[B.md]]
- candidates aging (1): "mcp-debate" (logged 2026-04-12)
- broken wikilinks (0)
- index sync (wiki sources My take): 4 pages
- index sync (raw): 1 created, 3 rows added

## [2026-05-07 10:15] query | filed answer on MCP contradiction
- question: "What's the contradiction between code-mode and bye-bye-mcp on MCP?"
- filed as: [[mcp-debate.md]] (topic)
```
