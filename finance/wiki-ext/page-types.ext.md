# Wiki Page Types — Finance Extension

Finance-module extension to the base wiki page-type model. Loaded only when `finance` is registered in `sb-os.json` → `wiki_extensions` (per the wiki Step 0 — Load extensions). Everything here is **added to** the base set in `../../wiki/workflows/shared/page-types.md` — never a replacement. When this extension is absent, the base 4-type wiki behaves identically.

Mirrors the base `page-types.md` classification-test + discriminator style. Read the base file for the 4 base types (`concept`, `entity`, `topic`, `source`) and their tests; this file does not restate them.

## Added Types

| Type | Definition |
|------|-----------|
| **Thesis** | An investment argument: a falsifiable claim about an asset/company/sector/country, with evidence and explicit invalidation criteria. Authored deliberately by the `sb-investor` agent — never auto-created by ingest. |
| **Decision** | A dated record of one investment decision and its reasoning (buy/sell/hold/pass/…). The reasoning lives here; the transaction (price/qty) lives in the bookkeeper ledger — never duplicated here. |

## Classification Tests

### Thesis passes if:

| Test | Required answer |
|------|----------------|
| Is it a falsifiable claim about a specific asset/company/sector/country (not a definition, not a survey)? | Yes |
| Does it carry — or commit to carry — evidence-for, evidence-against, and invalidation criteria? | Yes |
| Was it authored deliberately as an argument (not produced 1:1 from a raw source)? | Yes |

### Decision passes if:

| Test | Required answer |
|------|----------------|
| Does it record one dated investment action (buy/sell/trim/add/hold/pass/reject/pause/review/rebalance)? | Yes |
| Does it capture the reasoning at the time, not the transaction's price/qty? | Yes |
| Is it tied to a date and (usually) a thesis, asset, or company? | Yes |

## Discriminator Rules

These extend the base discriminator rule (**concept/entity = the thing itself; topic = the conversation around it**).

- **Thesis vs Topic.** A thesis is a falsifiable, owned argument with invalidation criteria. A topic is a plural, evolving conversation with no single claim to disprove. "Is Petrobras undervalued? — yes, because X, invalidated if Y" → Thesis. "The landscape of state-oil-company governance debates" → Topic.
- **Thesis vs Decision.** A thesis is the standing argument; a decision is a dated act taken in light of it. One thesis spawns many decisions over time. The thesis answers "what do I believe and why"; the decision answers "what did I do on this date and why".
- **News is evidence, not a thesis** (spec §9). A news item, filing, or earnings call is cited inside a thesis as evidence (via footnote) or becomes a `source` page — it is never itself a thesis. A thesis MUST have evidence-against + invalidation criteria before it can be `active`.

## Extended Entity Kinds

The entity-kind enum's single source of truth remains the base `../../wiki/workflows/shared/frontmatter-schemas.md`. This extension MERGES three investment kinds into that enum (added to, never replacing, the base values):

| Kind | For | Subfolder (lazy, created at threshold) |
|------|-----|----------------------------------------|
| `asset` | Instruments that aren't companies: bonds, sovereign bonds, ETFs, funds, FIIs, crypto, treasuries, debentures | `assets/` |
| `country` | Macro / sovereign-risk / currency entities | `countries/` |
| `sector` | Industry sectors | `sectors/` |

Rules:

- A **country** (the macro entity) is distinct from a **sovereign bond** (an `asset`). The country → `entities/`, kind `country`; the bond → `entities/`, kind `asset`.
- `sector` is an **entity kind**, never a topic.
- Subfolders are lazy — created only when entities of that kind accumulate to threshold, matching the base wiki's lazy-subfolder behavior.

## `## Financials` Section Eligibility

Only the investment entity kinds `company`, `asset`, `country`, and `sector` carry a `## Financials` section (structured fundamentals; schema defined in `./section-menus.ext.md`). The kinds `person`, `tool`, and `model` NEVER carry one.

## Extensibility

New investment page types or entity kinds follow the base `page-types.md` extensibility rule: propose via the user, never auto-create. New additions land in this extension file, never in the base shared files.
