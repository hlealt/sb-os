# Question Entry Shapes

The runtime shape of a `{wiki_root}/questions.md` entry — the copy ingest, lint, and query agents read when they create, scan, or prune questions. Canonical spec: `wiki/docs/wiki-schema.md` § "Questions layer — questions.md". This file mirrors it; on any divergence the schema wins.

## Entry shape

Each entry is an H2 heading (same shape family as the wiki log entries under `logs/`):

```markdown
## [YYYY-MM-DD] <question text>
relates:
- "[[<page>.md]]"
seeded-by: "[[<source>.md]]"
answer:
- <claim that partially or fully answers the question> [^1]

[^1]: [[<source>.md]]
```

| Field | Rule |
|-------|------|
| H2 heading | `## [YYYY-MM-DD] <question>` — the capture date in brackets, then the question text. One entry per H2. |
| `relates:` | 0..n quoted wikilinks to the concept/entity/topic/source pages the question concerns. Omit the field or leave the list empty for a cross-cutting question tied to no existing page. |
| `seeded-by:` | OPTIONAL single quoted wikilink to the source that surfaced the question during ingest. Present when captured at ingest; absent when hand-added (chat, `/sb-wiki-query` miss, or direct Obsidian edit). |
| `answer:` | Accretes inline as a bulleted list — each scan that finds support appends a bullet. Every bullet carries an `[^N]` inline citation; footnote defs are `[^N]: [[<source>.md]]`. Reuse the wiki citation convention; do NOT reinvent. |

## State rule — NO `status` field

State is **inferred**, never stored:

| Inferred state | Condition |
|----------------|-----------|
| `open` | No `answer:` block, or an `answer:` block with zero bullets. |
| `answered` | An `answer:` block with at least one bullet exists. Transient — pre-graduation. |

A promoted entry (graduated to a page via `sb-wiki-create-topic`) or a retired entry is **REMOVED** from `questions.md` — there is no terminal state stored in the file (the page's existence, or the user's retirement, is the record). Write NO `status`, `kind`, or `origin` field — all three are deliberately absent.

## Worked examples

**Captured at ingest (`seeded-by:` present, answer accreted across two scans):**

```markdown
## [2026-05-28] Do tabular foundation models displace gradient-boosted trees?
relates:
- "[[tabular-foundation-models.md]]"
- "[[gradient-boosting.md]]"
seeded-by: "[[2026-05-28-tfm-paper.md]]"
answer:
- Leaning complementary, not a wholesale replacement, on small-to-mid tabular sets [^1]
- A later benchmark shows parity only above ~10k rows; below that, boosted trees still win [^2]

[^1]: [[2026-05-28-tfm-paper.md]]
[^2]: [[2026-06-01-tabular-benchmark.md]]
```

**Hand-added (no `seeded-by:`, still `open` — no `answer:` yet):**

```markdown
## [2026-06-02] What governs when a retrieval cache should be invalidated vs. refreshed?
relates:
- "[[retrieval-augmented-generation.md]]"
```
