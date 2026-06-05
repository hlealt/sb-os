# Wiki Section Menus — Finance Extension

Finance-module extension to the base wiki section menus. Loaded only when `finance` is registered in `sb-os.json` → `wiki_extensions` (per the wiki Step 0 — Load extensions). Everything here is **added to** the base set in `../../wiki/workflows/shared/section-menus.md` — never a replacement. When this extension is absent, the base 4-type wiki behaves identically.

Mirrors the base `section-menus.md` presentation (`## <Page type>` heading, `**Required:**` line, `**Optional menu:**` table). It defines the section menus for the two added page types — `thesis` and `decision` (from `./page-types.ext.md`) — plus the `## Financials` body-section schema carried by investment entity kinds. Read the base file for the 4 base types; this file does not restate them.

## Thesis Page

**Required:** `Claim`, `Hypotheses`, `Causal mechanism`, `Evidence for`, `Evidence against`, `Risks`, `Invalidation criteria`, `Sources`

**Optional menu:**

| Section | When to include |
|---------|----------------|
| `What the market may be mispricing` | The mispricing argument — the gap between price and the thesis' fair value |
| `What is consensus` | The prevailing view the thesis agrees with or argues against |
| `Related companies/assets/sectors/countries` | Wikilinks to the entity kinds this thesis touches — mirrors the `related_*` frontmatter |
| `Relation to portfolio` | How this thesis maps to owned positions; pairs with `related_positions` frontmatter |
| `Next questions` | Open research threads to resolve before conviction rises |

`Claim` is the single falsifiable statement the thesis defends. `Evidence against` and `Invalidation criteria` are MANDATORY — a thesis cites entity financials (the `## Financials` table below) as evidence via footnotes, and cannot reach `status: active` without them (per `./page-types.ext.md`).

## Decision Page

**Required:** `Context`, `Decision`, `Related thesis`, `Rationale`, `What I believed at the time`, `What would prove me wrong`, `Acknowledged risks`, `Data and sources used`, `Review trigger`

A decision page records ONE dated investment action and the reasoning at the time — never the transaction's price/qty, which live in the bookkeeper ledger (per `./frontmatter-schemas.ext.md`). `decisions/` is NOT an operational log: recurring scope/preference choices belong in `research-policy.md`, not in a decision page. Decision pages have no optional menu — all sections are required.

## `## Financials`

The `## Financials` body section carried by investment entity kinds (`company`, `asset`, `country`, `sector` — per `./page-types.ext.md`; `person`, `tool`, and `model` never carry one) is ONE uniform long-format table, **the same columns on every entity page**. Long/tidy format — one row per observation. This uniformity is the entire point of the layer: a tool unions every entity's `## Financials` table by trivial concat (same columns) for cross-entity / cross-time queries.

The table has exactly these 7 columns, in this order:

| Column | Meaning |
|--------|---------|
| `metric` | from the controlled vocabulary in `./metric-vocab.md` |
| `period_type` | `annual` \| `quarterly` \| `monthly` \| `ttm` \| `point` — how annual and quarterly coexist in one table |
| `period_end` | date the period closes — the anchor that sorts any mix of periodicities and handles non-December fiscal years |
| `value` | the number |
| `unit` | from the controlled unit set in `./metric-vocab.md`; mandatory (a sheet mixing BRL and % is meaningless without it) |
| `source` | `[[raw-file]]` wikilink — same citation discipline as the wiki |
| `method` | `xbrl` \| `structured` \| `llm` \| `manual` — how the figure was obtained (enables targeted verification) |

Rendered as a standard Markdown table (Obsidian-native, editable). The `metric` and `unit` column values are drawn from the controlled vocabulary in `./metric-vocab.md` (base identifiers + suffix families; `method` semantics defined there) — agents NEVER invent identifiers or units.

**Write path (BINDING).** The registered write tool `investment_financials_extract` is the SOLE agent-side writer of this section — investor-orchestrated (`research.md` Step 7b or the standalone extract route). Ingest and scan agents NEVER add, modify, or delete a `## Financials` row: an ingest agent that finds extractable fundamentals reports them as extraction candidates in its summary; a scan agent returns extraction TARGETS (anchors) for the tool to verify and write. The USER may hand-edit rows (`method: manual`); the lint Fundamentals rules backstop vocabulary conformance on hand edits.

**Row conventions (tool-enforced):**

| Convention | Rule |
|------------|------|
| Canonical sort | `metric` asc, then `period_end` asc, then `period_type` in enum order (`annual` < `quarterly` < `monthly` < `ttm` < `point`) |
| Upsert key | (`metric`, `period_type`, `period_end`, `source`) — identical row = no-op; same key + same value + stronger method = method upgrade in place (`xbrl` > `structured` > `llm` > `manual`); same key + different value = CONFLICT, surfaced and NOT written |
| Corroboration | Differing sources for the same (`metric`, `period_type`, `period_end`) COEXIST as rows — value conflicts across sources are surfaced by lint Fundamentals #6, never auto-resolved |
| Guidance | `_guidance` suffix rows are year-free; `period_end` = the guided period's close; re-guides across quarters are expected multi-rows, not conflicts |
| Section position | When absent, the tool creates `## Financials` after the last content section, before `## Related`/`## Sources` |

**Adding a metric = adding ROWS, never columns.** The column set is fixed at exactly these 7. Heterogeneous tables ("different tables with different data" per entity) and CSV sidecars are FORBIDDEN — they destroy the cross-entity / cross-time comparability that is the entire reason this layer is structured. One uniform table per entity.

Example (`entities/organizations/petrobras.md`, `## Financials`):

```markdown
| metric | period_type | period_end | value | unit | source | method |
|--------|-------------|------------|-------|------|--------|--------|
| revenue | annual | 2023-12-31 | 512000 | BRL_mn | [[2024-03-01-petrobras-4q23]] | xbrl |
| revenue | quarterly | 2024-09-30 | 138000 | BRL_mn | [[2024-11-08-petrobras-3q24]] | xbrl |
| net_margin | quarterly | 2024-09-30 | 18.2 | pct | [[2024-11-08-petrobras-3q24]] | xbrl |
| roic | annual | 2023-12-31 | 16.5 | pct | [[2024-03-01-petrobras-4q23]] | structured |
| ev_ebitda | point | 2025-05-20 | 3.1 | x | [[2025-05-20-screen]] | manual |
```

The investment lint rules (`./lint-rules.ext.md`) check `metric`, `unit`, `period_type`, and `method` values against the controlled vocabulary exactly.
