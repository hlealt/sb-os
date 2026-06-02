# Wiki Page Types

Definitions, tests, and discriminator rules for the 4 active wiki page types. Used by agents classifying entities/concepts during ingest and by agents authoring new wiki pages.

## Types

| Type | Definition |
|------|-----------|
| **Concept** | The idea itself. Definable in one sentence. Stable over time. |
| **Entity** | A specific named thing — tool, person, company, product, model. Concrete identity, not an abstraction. |
| **Topic** | The conversation around an idea or entity. Plural framing. Evolves over time. |
| **Source** | Per-source synthesis. 1:1 with a raw file. Entry point of the wiki. |

## Classification Tests

### Concept passes if:

| Test | Required answer |
|------|----------------|
| Can the user write a 1-sentence definition that would survive on Wikipedia? | Yes |
| Is the definition stable over time (modulo refinement)? | Yes |
| Is it a singular noun or noun phrase? | Yes |

### Topic passes if:

| Test | Required answer |
|------|----------------|
| Can the user write a 1-sentence definition? | No — it is a question, comparison, or survey |
| Is it stable? | No — "state of X" evolves |
| Is the framing plural / landscape / debate? | Yes |

### Entity: a specific named thing with concrete identity. No test table required — name-uniqueness is the signal.

### Source: always 1:1 with a raw file. No classification test — determined by the ingest operation.

## Discriminator Rule

**Concept = the idea or entity itself.** Topic = the conversation around it.

- `compound-engineering` → Concept (methodology)
- `anthropic` → Entity (company)
- `compound-engineering-adoption` → Topic (discussion of who is adopting it)
- `anthropic-vs-openai` → Topic (comparison)

## Aggregation Rule

An entity is ONE named thing referenced as a single actor. Aggregation of distinct entities is the role of **Topic** (the conversation around them — plural framing) and **Concept** (the category they instantiate) — NEVER an entity.

| Case | Entity? | Page outcome |
|------|---------|--------------|
| A named collective with its own identity — an organization, lab, fund, committee, named consortium | YES | ONE entity page; it MAY link members. Having members ≠ being an aggregate. |
| A school of thought, movement, or named class of things | NO | ONE Concept or Topic page; instances link in. |
| A bare set of entities co-mentioned with NO collective identity — people quoted together, institutions named only as affiliations, items used as a test-bed | NO | NOT one page. Create the individual entities, or a Topic/Concept that links them. |

The discriminator is "named and referenced as one actor," NEVER the grammatical plurality of the label. NEVER create an entity whose only content is a list of other entities (a synthetic aggregator).

## Tie-Breaker

When in doubt, start as Concept or Entity. Promote to Topic only when finding "there are N variants of this, evolving over time."

## Extensibility

The type list is extensible. New page types may be added when a real ingest pattern hits a gap not covered by the current 4. Agents MUST propose new types via the user — never auto-create a new type.
