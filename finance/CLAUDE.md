# finance/

Finance module source — the investment-research layer that extends the open-source `sb-os` wiki without putting investment content into the base wiki. This file documents how that layer plugs in: the wiki extension, lint scoping, the policy read-rules, and the watchlist invariant. It is the canonical statement of the read-rules; their runtime wiring belongs to the `investor` agent build (deferred — see Deferred Wiring below).

Investment terminology (`thesis`, `decision`, `asset`, `country`, `sector`, fundamentals/metrics) is native to this module and appears throughout this file by design. The domain-clean guard keeps that terminology OUT of the base wiki only — never out of this module's own docs.

---

## Wiki Extension

The finance module ships investment definitions as **extension data files** under `wiki-ext/`. The wiki workflows load them only when the finance module is registered, keeping the base wiki domain-clean for general users while giving this vault the full investment layer.

| File | Adds |
|------|------|
| `./wiki-ext/page-types.ext.md` | `thesis` and `decision` page types; extends the entity-kind enum with `asset`, `country`, `sector`; discriminators |
| `./wiki-ext/frontmatter-schemas.ext.md` | `thesis` and `decision` frontmatter; the entity `## Financials` note |
| `./wiki-ext/section-menus.ext.md` | thesis sections, decision sections, the `## Financials` long-format table schema |
| `./wiki-ext/metric-vocab.md` | controlled metric / unit / period / method vocabulary per entity kind |
| `./wiki-ext/lint-rules.ext.md` | investment-semantic and fundamentals lint rules (scoped — see Lint Scoping) |
| `./wiki-ext/candidate-thesis-triggers.md` | ingest trigger that flags candidate theses |

For each file's definitions, read that file directly. This module doc never restates them.

### Registration

`sb-os.json` carries `"wiki_extensions": ["finance"]`. When the field is absent or empty, the wiki behaves exactly as the base 4-type wiki — no investment types, kinds, sections, or lint rules load.

### Load mechanism (Step 0)

`sb-wiki-ingest` and `sb-wiki-lint` each run a **Step 0 — Load extensions** before their native logic. Step 0 reads `sb-os.json` → `wiki_extensions`, locates each listed module's `wiki-ext/` folder, and MERGES its `page-types.ext.md`, `frontmatter-schemas.ext.md`, `section-menus.ext.md`, and `lint-rules.ext.md` into the active rule set for that run. Extension page types, entity kinds, sections, and lint rules are ADDED to the base set — never replace it. Step 0 mechanism is defined in `../wiki/claude-mds/wiki.md`; the merge is additive-only.

### Financial extraction boundary

`sb-wiki-ingest` produces source pages, entities, concepts, and candidate-topics — and, with the extension loaded, recognizes the investment entity kinds. It does NOT write the `## Financials` table. The `## Financials` write path is run by the `investor` agent's ingest/research path (deferred), keeping numeric extraction out of general ingest. Until the extraction parser exists, `## Financials` rows are entered manually (`method: manual`).

---

## Lint Scoping

The investment lint rules in `./wiki-ext/lint-rules.ext.md` are loaded by `sb-wiki-lint` Step 0 and MUST fire ONLY on investment folders and investment entity kinds (`thesis`, `decision`, `asset`, `country`, `sector`). They MUST NEVER fire on a general-wiki run — this is the guard against investment rules flagging general pages.

The base structural lint (broken wikilinks, stub aging, orphans, raw-without-ingest, source-without-raw, slug convention, frontmatter validity) applies to all pages and is reused, not redefined, by the extension.

Lint shows state; it never decides. The `investor` agent proposes next actions from lint output.

---

## Policy Read-Rules

Two user-owned policy files live under `.user/finance/investor/`. Their CONTENT is the user's; the read-rules below — WHEN each agent or command must load them — are authored here and ship with this module.

| Policy file | Holds |
|-------------|-------|
| `.user/finance/investor/research-policy.md` | user-approved scope, priorities, exclusions, watchlist-approval rule, horizon preferences |
| `.user/finance/investor/source-policy.md` | source trust classification and allowed-use rules |

**Read-rules:**

| When | Load `research-policy.md` | Load `source-policy.md` |
|------|---------------------------|-------------------------|
| Before suggesting, reviewing, or invalidating a thesis | MUST | MUST when the action cites or weighs sources |
| Before mapping exposure or proposing a watchlist change | MUST | — |
| Before ingesting or trusting a source for an investment claim | — | MUST |
| Pure structural wiki ops (ingest of a general source, lint, index maintenance, slug/link fixes) | NEVER | NEVER |

The rule is: any action that REASONS about investments loads the relevant policy first; any action that only MOVES STRUCTURE around does not. A general `sb-wiki-ingest` or `sb-wiki-lint` run is a pure structural op and loads neither policy.

---

## Watchlist Invariant

Any page MAY carry `watchlist: true` in frontmatter, but an agent MAY set it ONLY after explicit user approval. Therefore `watchlist: true` ⇒ approval already happened. Lint surfaces a `watchlist: true` page that lacks approval evidence in `log.md` or a related decision (per `./wiki-ext/lint-rules.ext.md`); the agent never auto-approves to clear the flag.

---

## Deferred Wiring

The `investor` agent (the runtime consumer of the read-rules above) is DEFERRED and built last. `./commands/investor.md` is a reserved stub until then. This file is the canonical statement of the read-rules NOW; the `investor` build wires them into runtime behavior LATER. No agent currently enforces them — they bind when the `investor` agent ships.

> Codex mirror note: do not read the sibling `AGENTS.md`. It is an auto-generated mirror for Codex agents. This `CLAUDE.md` file is the source of truth.
