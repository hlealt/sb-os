# Wiki Frontmatter Schemas — Finance Extension

Finance-module extension to the base wiki frontmatter schemas. Loaded only when `finance` is registered in `sb-os.json` → `wiki_extensions` (per the wiki Step 0 — Load extensions). The schemas here are **added to** the base set in `../../wiki/workflows/shared/frontmatter-schemas.md` — never a replacement. When this extension is absent, the base schemas behave identically.

Mirrors the base `frontmatter-schemas.md` presentation. Every page of these types MUST include the base common block (`type`, `created`, `last-touched`, `related`, `tags`) plus the type-specific additions below. These two types back the `thesis` and `decision` page types defined in `./page-types.ext.md`.

## Thesis

```yaml
type: thesis
status: seed | developing | active | rejected | archived
conviction: low | medium | high
time_horizon: short | medium | long
last_reviewed: YYYY-MM-DD
related_companies: []
related_assets: []
related_sectors: []
related_countries: []
related_positions: []   # links to portfolio positions this thesis maps to (by ledger id/ticker)
watchlist: false
```

The `related_*` lists are wikilinks to the matching entity kinds. `related_positions` links owned positions by ledger id/ticker. A thesis cites entity financials as evidence via footnotes.

## Decision

```yaml
type: decision
date: YYYY-MM-DD
decision_type: buy | sell | trim | add | hold | pass | reject | pause | review | rebalance
related_thesis:
related_asset:
related_company:
```

Filename convention: `YYYY-MM-DD-<action>-<asset-or-thesis>.md`, where `<action>` is one of the action enum: `buy | sell | trim | add | hold | pass | reject | pause | review | rebalance` (the same values as `decision_type`). The wiki holds the reasoning; the bookkeeper ledger holds the transaction (price/qty) — do NOT duplicate transaction data here.

## Source queue (`type: source-queue`)

`{wiki_root}/source-queue.md` — a root-level sibling of the `logs/` queues (NOT a wiki page, NOT raw). Holds the open investment source-lifecycle entries (`gated_pending_access`, `blocked`) written by the `sb-wiki-capture-source` tool and surfaced/pruned by lint per `./lint-rules.ext.md` § Source-Lifecycle Rules.

```yaml
type: source-queue
```

`source-queue` is a non-page type value: the file is excluded from page-type checks, leaf indexes, stub/orphan detection, and every wiki/raw validation walk (it lives outside `wiki/` and `raw/`, mirroring the base `questions.md` pattern). The tool creates the file with this frontmatter when absent; no other agent or workflow creates it.

## Entity `## Financials` note

Investment entity kinds (`company`, `asset`, `country`, `sector`) carry a `## Financials` section of structured fundamentals on the entity's own page. Its structure is defined in `./section-menus.ext.md`. The `person`, `tool`, and `model` kinds never carry one. This is a body section, not frontmatter — no `financials:` frontmatter field is added.

## Entity `cik:` field (company kind, optional)

A `company` entity MAY carry a `cik:` frontmatter field — the SEC EDGAR Central Index Key, used by `investment_financials_extract` to cross-check captured XBRL companyfacts artifacts (the `--cik` flag overrides it).

```yaml
cik: 1650372
```

The agent PROPOSES adding `cik:` on a company's first SEC extraction — a user-approved edit, never silent. Non-SEC-registrant companies simply omit the field.
