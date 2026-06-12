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
| Source queue | `{wiki_root}/source-queue.md` — exists ONLY via the finance capture tool, so the file itself is the scope guard |
| Data artifacts | raw files matching `*-xbrl-companyfacts.json` under `{wiki_root}/raw/{origin}/` — captured only by the finance capture tool, so the filename class is the scope guard |

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
| 6 | A page with `watchlist: true` lacking approval evidence in a `decisions/` decision | `watchlist: true` without approval evidence |
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

Rules #1–#6 are IMPLEMENTED — every finance-extension lint run MUST evaluate them against the merged rule set and report findings (a silent run over violating rows is a lint defect). Rule #7 is propose-only. The `metric` check (#4) resolves a valid name as a base identifier OR base + one suffix family per `./metric-vocab.md` § Suffix Families.

**Rule #2 spot-check queue.** The queue is THIS report block — re-derived from state on every run (an `llm` row cited by an active thesis keeps surfacing until verified or upgraded), mirroring the stubs/orphans pattern; no queue file exists. The prescribed verification is a lane-2 re-derivation through the `investment_financials_extract` standalone route (anchor-verify against the row's own cited source → `method` upgrades on match). Append to the LINT REPORT after the base findings; omit the block when zero findings:

```
FUNDAMENTALS — ## Financials findings:
Spot-check queue — llm rows feeding an active thesis (N): [[entity.md]] metric @ period_end → thesis [[slug.md]]
Uncontrolled metric (N): [[entity.md]] `identifier` (not in metric-vocab)
Unit missing/invalid (N) · Source missing (N) · Stale financials (N) · Value conflicts (N): <one row each>
```

## Data-Artifact Raw Class (`*-xbrl-companyfacts.json`)

Captured XBRL companyfacts JSONs (`YYYY-MM-DD-{entity}-xbrl-companyfacts.json`, fetched by the capture tool's `--ext json` path) are **extraction inputs, never ingested** — lane-1 feedstock for `investment_financials_extract`. They are raw files (immutable, indexed) with one class-wide deviation:

| Rule | Behavior |
|------|----------|
| Raw index `Wiki` cell | Carries `N/A (data artifact)` — never `Yes`/`Partial`/`No`. A helper-created `No` cell on a data-artifact row is corrected to `N/A (data artifact)` during the lint run (an index-sync write, auto-applied) |
| Base raw-without-ingest | EXEMPT — the class never fires it, and the file is never surfaced as an ingest candidate |
| Source page | None exists, by design — `source-without-raw`/orphan logic never expects one |

## Source-Lifecycle Rules (`source-queue.md`)

Scope: `{wiki_root}/source-queue.md` — the investment source queue, a root-level sibling of the `logs/` queues (frontmatter `type: source-queue` per `./frontmatter-schemas.ext.md`). It holds the open lifecycle states of investment sources that could not complete the capture→ingest path: `gated_pending_access` (paywalled/login — awaits user action) and `blocked` (fetch failed after both tool methods — retry candidate). The `sb-wiki-capture-source` tool is the SOLE writer of entries; lint's only write is the rule-3 prune, applied SOLELY under the owner-gated `--prune-source-queue` flag (never on a plain check/apply run); the user retires a source by deleting its entry.

File absent → no sources are queued; skip these rules silently. Present but malformed (unreadable, or no parseable H2 entries) → WARN, skip these rules, NEVER abort the lint. Mirrors the `questions.md` skip-if-absent contract.

Entry shape (tool-written): `## {state} — YYYY-MM-DD` H2 + `- title:`, `- url:`, `- source:` (origin), `- related_thesis:`, `- why_it_matters:` (gated), `- failure:` (blocked), `- required_user_action:` bullets.

`sb-wiki-lint-deterministic.py` (`scan_source_queue`) computes rule 3 (resolution) FIRST on every run; rules 1, 2, and 4 then surface the remaining open entries from the helper's `source_queue_open` list — a resolved entry never appears under rules 1/2/4. The delete is owner-gated: every run surfaces resolved entries as prune candidates (helper `source_queue_resolved`); the `--prune-source-queue` invocation applies the delete.

| # | Condition | Lint surfaces |
|---|-----------|---------------|
| 1 | An open `gated_pending_access` entry | EVERY open gated entry with its `required_user_action`; append `[AGED]` when the entry date is >30 days old |
| 2 | An open `blocked` entry | EVERY open blocked entry as a retry candidate (re-run the capture tool); append `[AGED]` when the entry date is >30 days old |
| 3 | An entry whose wiki source page now EXISTS under `wiki/sources/{origin}/` — resolution is DETERMINISTIC, computed by `sb-wiki-lint-deterministic.py` (`scan_source_queue`): the entry's `url:` matched (normalized, prefix-tolerant) against a source-page `url:` frontmatter in the same origin (authoritative), with a shared DOI or an exact normalized-title match (vs page H1 / filename stem) as confirmation for PDF-sourced entries. NEVER title-token fuzz. | SURFACE the entry as a prune candidate (helper `source_queue_resolved`); DELETE it ONLY under the owner-gated `--prune-source-queue` invocation — count pruned for the report |
| 4 | An entry whose raw file exists but whose wiki source page does NOT (a manually-recovered source awaiting ingest) | KEEP the entry open; append `[captured, awaiting ingest]` to its report row |

Report block — append to the LINT REPORT after the base findings. Omit the whole block when the file is absent or holds zero entries; omit the `prune candidates` / `pruned` lines when 0:

```
SOURCE QUEUE — open lifecycle states:
Gated pending access (N, M aged >30d):
  "<title>" (<origin>) — registered YYYY-MM-DD — action: <required_user_action> [AGED]
Blocked, retry candidates (N, M aged >30d):
  "<title>" (<origin>) — blocked YYYY-MM-DD [AGED] [captured, awaiting ingest]
Source queue prune candidates (N) — page now exists, awaiting owner-gated --prune-source-queue:
  "<title>" (<origin>) → [[<matched_page>]] via <url|doi|title>
Source queue pruned: <N> deleted (only on a --prune-source-queue run)
```

One row per open entry under its state line; `[AGED]` and `[captured, awaiting ingest]` appear only when rule 1/2/4 marks them.

## Governance

- **Lint shows state; it never decides.** It surfaces findings only — the `sb-investor` proposes next actions from the lint output. Lint NEVER auto-resolves a conflict, NEVER edits a thesis or `## Financials` row, NEVER promotes or archives a page.
- **Lint NEVER writes a source-queue entry.** The capture tool is the sole entry writer; lint's only queue write is the rule-3 prune of resolved entries, and that delete fires ONLY under the owner-gated `--prune-source-queue` invocation — a plain check/apply lint run surfaces prune candidates but never deletes.
- **Implement incrementally — not all rules are required at MVP.** Add rules as the investment wiki grows; an unimplemented rule simply does not fire.
