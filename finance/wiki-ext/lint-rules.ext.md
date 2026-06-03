# Wiki Lint Rules — Finance Extension

Finance-module extension to the base wiki lint. Loaded only when `finance` is registered in `sb-os.json` → `wiki_extensions` (per the `sb-wiki-lint` Step 0 — Load extensions). Everything here is **MERGED onto** the base lint rule set defined in `../../wiki/workflows/sb-wiki-lint/sb-wiki-lint.md` — never a replacement. When this extension is absent, the base lint behaves identically.

Mirrors the base lint presentation: each rule is one scannable row (condition → what lint surfaces). `sb-wiki-lint` Step 0 adds these rows to the active rule set for the run.

## Scoping Guard

**These rules fire ONLY on investment scopes — NEVER on a general-wiki run.** A general-wiki run (no investment extension registered, or no matching folders/kinds present) applies the base lint rules ONLY. Investment scopes are:

| Scope | Definition |
|-------|------------|
| Folders | `theses/`, `decisions/` under `{wiki_root}/wiki/` |
| Entity kinds | `company`, `asset`, `country`, `sector` (the investment kinds from `./page-types.ext.md`) |
| Section | the `## Financials` body section on those entity kinds (schema in `./section-menus.ext.md`) |

A rule below NEVER evaluates a page outside its stated scope. The base structural lint still applies to every page; these rows ADD investment checks on top.

## Reuses Base Structural Lint

This file ADDS investment rules; it NEVER replaces the base structural checks. The base lint continues to apply unchanged: broken wikilinks, stub aging, orphans, raw-without-ingest, source-without-raw, slug convention, and frontmatter validity. Do NOT restate them here — run them per `../../wiki/workflows/sb-wiki-lint/sb-wiki-lint.md`.

## Investment-Semantic Rules

Scope: `theses/`, `decisions/`, and investment entity kinds. Field/section names below are controlled identifiers — they match the schemas in `./frontmatter-schemas.ext.md` and `./section-menus.ext.md` exactly.

| # | Condition | Lint surfaces |
|---|-----------|---------------|
| 1 | A thesis with `status: active` missing an `Evidence against` section | active thesis without `Evidence against` |
| 2 | A thesis with `status: active` missing an `Invalidation criteria` section | active thesis without `Invalidation criteria` |
| 3 | A thesis with `status: active` whose `last_reviewed` is older than N days (stale review) | active thesis with stale `last_reviewed` |
| 4 | A thesis with no entries in its `Sources` section / no source footnotes | thesis without sources |
| 5 | An `asset` entity missing `asset_type`, OR a country used as a sovereign asset (the macro `country` entity conflated with an `asset`) | asset without `asset_type` / country-as-asset |
| 6 | A page with `watchlist: true` lacking approval evidence in `log.md` or a `decisions/` decision | `watchlist: true` without approval evidence |
| 7 | A decision page with no related thesis or asset (`related_thesis`, `related_asset`, and `related_company` all empty) | decision without a related thesis or asset |
| 8 | A thesis with `status: archived` still wikilinked AS ACTIVE from another page | archived thesis referenced as active |

## Fundamentals Rules (`## Financials`)

Scope: the `## Financials` table on investment entity kinds (`company`, `asset`, `country`, `sector`). Column names (`metric`, `period_type`, `period_end`, `value`, `unit`, `source`, `method`) are the 7 fixed columns from `./section-menus.ext.md`. The `metric` and `unit` checks resolve allowed names from `./metric-vocab.md` — this file does NOT restate those lists.

| # | Condition | Lint surfaces |
|---|-----------|---------------|
| 1 | A `## Financials` row with an empty `source` cell | row missing `source` |
| 2 | A `## Financials` row with `method: llm` feeding a `status: active` thesis (cited as evidence) | route to the spot-check queue (verify the LLM-extracted figure) |
| 3 | No new `period_end` in > N quarters for an entity backing an active thesis | stale financials |
| 4 | A `metric` value NOT present in the controlled vocabulary in `./metric-vocab.md` (uncontrolled name or typo) | uncontrolled `metric` |
| 5 | A `unit` cell empty, OR a `unit` value outside the allowed set in `./metric-vocab.md` | `unit` missing / outside allowed set |
| 6 | Two or more rows giving conflicting `value`s for the same `metric` + `period_end` + entity from different sources | SURFACE the conflict — NEVER auto-resolve |
| 7 | A `## Financials` table grown unwieldy on a single page | PROPOSE splitting it to a companion page (mirrors the entity-folder subdivision pattern; split on evidence, never upfront) |

## Governance

- **Lint shows state; it never decides.** It surfaces findings only — the `sb-investor` proposes next actions from the lint output. Lint NEVER auto-resolves a conflict, NEVER edits a thesis or `## Financials` row, NEVER promotes or archives a page.
- **Implement incrementally — not all rules are required at MVP.** Add rules as the investment wiki grows; an unimplemented rule simply does not fire.
