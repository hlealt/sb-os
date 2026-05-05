# Wiki Section Menus

Required and optional sections per wiki page type. Agents select optional sections based on source signal and page kind.

## Concept Page

**Required:** `Definition`, `Sources`

**Optional menu:**

| Section | When to include |
|---------|----------------|
| `How it works` | Mechanics or process — skip for purely abstract concepts |
| `Why it matters` | Significance in current AI/PM/finance landscape — usually included |
| `Open variants / debates` | Only when contradictions or evolution detected; cites both sources |
| `Related` | Wikilinks to entities + topics — usually included |

`Definition` is a 1–2 sentence factual definition (Wikipedia-style). All other sections are agent-written, neutral.

## Entity Page

**Required:** `What it is`, `Sources`

**Optional menu** (agent picks per `kind:`):

| Section | When to include |
|---------|----------------|
| `Notable facts` | Bulleted facts from sources — usually included |
| `How it works` | Mechanics — for tools, products, models, protocols |
| `History` | For long-lived entities (people, companies); pivotal moments |
| `Architecture` | For tools, models, products — technical structure |
| `Variants` | For products/models with multiple versions |
| `How I use it / Why it matters to me` | For tools the user actively uses |
| `Related` | Wikilinks — usually included |

## Topic Page

**Required:** `Scope`, `Sources`

**Optional menu** (agent picks per topic shape: debate / comparison / landscape / decision-frame / evolution):

| Section | When to include |
|---------|----------------|
| `Key positions / Angles` | Debate or comparison topics |
| `Key concepts` | Wikilinks to concepts — usually included |
| `Key entities` | Wikilinks to entities — usually included |
| `Open questions` | What is unresolved — usually included |
| `Consequences` | Downstream effects of the positions |
| `Timeline` | Evolution-shaped topics — chronological pivots |
| `Stakeholders` | Decision-frame topics — who is affected |
| `Decision criteria` | Decision-frame topics — how positions are evaluated |

## Source Page

**Required:** `Sources`

**Agent half — optional menu** (agent picks per source kind: article / paper / podcast / study / repo):

| Section | When to include |
|---------|----------------|
| `Substance` | Paraphrased prose synthesis of the source — usually included |
| `Notable quotes` | Verbatim quotations only — kept distinct from `Substance` (paraphrase vs. verbatim) |
| `Connections` | Wiki pages this source updates or contradicts; each connection states why (one clause) — usually included |
| `Methodology` | For studies, papers — method, dataset, sample, limitations |
| `Counterpoints` | Where the source disagrees with itself or with prior wiki claims |

**User half** (separated by `---`):

| Section | Owner |
|---------|-------|
| `My take` | User — why it mattered, what surprised, agreements/disagreements |
| `Open questions` | User — what is unclear, what to dive into |
| `Dive deeper` | User — checklist of follow-ups |

The `---` separator marks agent-half / user-half / sources boundaries.

**Empty-shell rule:** User-half sections on Source pages MUST be created as empty shells (heading only, no content) by ingest step 2. Empty user-half sections do NOT count toward stub-state — this is the page's natural post-ingest state. The user fills them at Stage 2 or later in Obsidian.

## Contradiction — Disputed Callout

When Contradiction fires `same-scope-opposing`, prepend a `> [!warning] Disputed` callout to the affected concept/entity page's `Open variants / debates` section:

```markdown
> [!warning] Disputed
> Conflicting claims on [scope]: [[source-a.md]] vs [[source-b.md]]. See candidate-topic log entry [YYYY-MM-DD HH:MM].
```
