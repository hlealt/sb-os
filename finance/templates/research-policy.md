---
type: reference
tags: [finance, investor, policy]
---

# Research Policy

> [!note] User-Owned Content
> This file is user-owned and user-filled. The `sb-investor` agent reads it **before** suggesting or reviewing theses, mapping exposure, or proposing watchlist changes (per `finance/CLAUDE.md` § Policy Read-Rules). Pure structural wiki operations (ingest, lint, index updates) do **not** load it. This skeleton was bootstrapped by the sb-os installer — fill the `_Fill in_` slots; the installer never overwrites this file.

---

## Scope

### In Scope

- _Fill in — asset classes and markets the agent researches (e.g., domestic equities, international equities, fixed income, ETFs)._

### Out of Scope

- _Fill in — asset classes and strategies the agent never researches (e.g., day trading, illiquid small caps)._

---

## Priorities

Ordered — when multiple research fronts compete, investigate in this order:

1. _Fill in — e.g., new capital to deploy (entry opportunities)._
2. _Fill in — e.g., stale theses (longest since last review)._
3. _Fill in — e.g., positions at a loss / theses under pressure._

---

## Exclusions

- _Fill in — standing exclusions that never surface as research candidates._

---

## Watchlist-Approval Rule

The agent may set `watchlist: true` on a thesis page **only after explicit user approval**. A page carrying `watchlist: true` means approval has already been given. The agent never sets this flag unilaterally.

Additional qualification criteria — a thesis qualifies for a watchlist PROPOSAL only when:

- Its invalidation criteria are defined on the thesis page.
- _Fill in — evidence thresholds (e.g., minimum sources captured, minimum contrarian/evidence-against sources)._

---

## Horizon Preferences

_Fill in — global, per-class, or per-thesis horizon defaults. If no default is set, the agent never assumes a horizon: absent one on the thesis page, the agent asks._
