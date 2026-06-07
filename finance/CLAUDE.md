# finance/

Finance module source — the investment-research layer that extends the open-source `sb-os` wiki without putting investment content into the base wiki. This file documents how that layer plugs in: the wiki extension, lint scoping, the policy read-rules, and the watchlist invariant. It is the canonical statement of the read-rules; their runtime wiring is carried by the live `sb-investor` agent (see Read-Rules Runtime Wiring below).

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
| `./wiki-ext/lint-rules.ext.md` | investment-semantic, fundamentals, and source-lifecycle lint rules (scoped — see Lint Scoping) |
| `./wiki-ext/candidate-thesis-triggers.md` | ingest trigger that flags candidate theses |

For each file's definitions, read that file directly. This module doc never restates them.

### Registration

`sb-os.json` carries `"wiki_extensions": ["finance"]`. When the field is absent or empty, the wiki behaves exactly as the base 4-type wiki — no investment types, kinds, sections, or lint rules load.

### Load mechanism (Step 0)

`sb-wiki-ingest` and `sb-wiki-lint` each run a **Step 0 — Load extensions** before their native logic. Step 0 reads `sb-os.json` → `wiki_extensions`, locates each listed module's `wiki-ext/` folder, and MERGES its `page-types.ext.md`, `frontmatter-schemas.ext.md`, `section-menus.ext.md`, and `lint-rules.ext.md` into the active rule set for that run. Extension page types, entity kinds, sections, and lint rules are ADDED to the base set — never replace it. Step 0 mechanism is defined in `../wiki/claude-mds/wiki.md`; the merge is additive-only.

### Financial extraction boundary

`sb-wiki-ingest` produces source pages, entities, concepts, and candidate-topics — and, with the extension loaded, recognizes the investment entity kinds. It does NOT write the `## Financials` table — that invariant is permanent. The write path is the registered `investment_financials_extract` tool (`scripts/tools-index.md`), the SOLE agent-side writer of that section, orchestrated by `sb-investor` (`workflows/sb-investor/research.md` Step 7b, or the standalone `extract` route in the capability manifest) — keeping numeric extraction out of general ingest. The prohibition and row conventions are stated inside `./wiki-ext/section-menus.ext.md` § `## Financials` (the file writing agents load). The user may hand-enter rows (`method: manual`); the lint Fundamentals rules are the backstop.

---

## Lint Scoping

The investment lint rules in `./wiki-ext/lint-rules.ext.md` are loaded by `sb-wiki-lint` Step 0 and MUST fire ONLY on investment scopes: investment folders, investment entity kinds (`thesis`, `decision`, `asset`, `country`, `sector`), and `{wiki_root}/source-queue.md` (the investment source queue — written only by the finance capture tool, so the file's existence is itself the scope guard). They MUST NEVER fire on a general-wiki run — this is the guard against investment rules flagging general pages.

The base structural lint (broken wikilinks, stub aging, orphans, raw-without-ingest, source-without-raw, slug convention, frontmatter validity) applies to all pages and is reused, not redefined, by the extension.

Lint shows state; it never decides. The `sb-investor` agent proposes next actions from lint output.

---

## Policy Read-Rules

Two user-owned policy files live under `.user/finance/investor/`. Their CONTENT is the user's; the read-rules below — WHEN each agent or command must load them — are authored here and ship with this module.

| Policy file | Holds |
|-------------|-------|
| `.user/finance/investor/research-policy.md` | user-approved scope, priorities, exclusions, watchlist-approval rule, horizon preferences |
| `.user/finance/investor/source-policy.md` | source trust classification and allowed-use rules |

Both files are bootstrapped by the installer from the user-agnostic skeletons in `./templates/` (manifest-template mechanism, install-if-missing — fresh installs get the designed structure with `_Fill in_` slots; an existing file is never overwritten). Structure ships with this module; content is the user's. While a policy remains unfilled, `research.md` Step 3 item 4's seed rubric is the degradation path.

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

## Read-Rules Runtime Wiring

The `sb-investor` agent — the runtime consumer of the read-rules above — is BUILT and live. `./commands/sb-investor.md` is a live loader (no longer a reserved stub): it loads the orchestrator `./workflows/sb-investor/sb-investor.md`, which loads `./workflows/sb-investor/sb-investor-loop.md`. The loop enforces the read-rules table above by loading each policy file at the moment its row requires. This file remains the canonical statement of the read-rules; the live loop references that table and NEVER duplicates it. The read-rules now bind at runtime — every `sb-investor` mode that reasons about investments loads the relevant policy first, per the table above.

---

## Data Access (always-on rule)

The module ships `./rules/sb-finance-data-access.md`, installed to `.claude/rules/sb-finance-data-access.md` on every install run. It binds EVERY agent session in the vault — not only bookkeeper runs — to the tools-only data-access protocol for `.user/finance/bookkeeper/` data: reads and writes route through registered tools in `./scripts/tools-index.md`, mutations are dry-run-first with user confirmation, corrections are append-only, and a missing capability is a deviation routed to the companions. The canonical runtime statement of the protocol remains `./workflows/sb-bookkeeper/gatekeeper-loop.md` § Tools-only data access; the rule carries its binding statements into sessions that never load that workflow (incident 2026-06-06: four ad-hoc mutation scripts written in a review-mode session).

The companions have user-invocable front doors: the `sb-tool-builder` and `sb-doc-maintainer` skills (`./skills/`) load the companion workflows directly and the invoking agent becomes the caller-broker — an entry-point addition, not a runtime-model change (each workflow's "Skill front door (binding)" clause; p2-17 addendum 2026-06-06). Sibling agents keep dispatching the companions via the Agent tool (gatekeeper-loop Seams 1/2).

---

## Documentation Currency

The finance module's living docs describe what its code and config actually do. When code or config changes and the matching doc does not, the doc becomes a lie — and because verification of this module happens THROUGH its docs, a stale doc is a correctness defect, not a cosmetic one. This section is the **canonical declaration of the doc↔code/config coupling**: which living doc is bound to which code/config surface. The three enforcement layers below (and the `doc-maintainer` companion) act on THIS declaration — it is the single statement they all read the coupling from. Mechanism rationale and the failure modes it closes: `1-projects/finance-system/finance-system-v2-foundation/phase-2/decision-prep/p2-19-documentation-currency.md` (Option D Hybrid).

### Coupling map (the binding declaration)

Each row binds a **living doc surface** to the **code/config surfaces** whose change makes that doc stale. A change to a surface in the right column REQUIRES a matching update to the doc in the left column, in the SAME commit. Paths are repo-relative to `sb-os/finance/` unless rooted at `.user/`.

| Living doc surface | Coupled code/config surfaces (change here ⇒ doc may be stale) |
|--------------------|---------------------------------------------------------------|
| `docs/architecture.md` — pipeline shape, roles-by-directory, what-lives-where (**judgment coupling — `signal-only`**, see note below) | `scripts/shared/normalize.py`, `scripts/shared/categorize.py`, `scripts/investimentos/calculate.py`, `scripts/investimentos/update_ledgers.py` (a change to the producer→store→consumer chain or a directory's role) |
| `docs/expenses-data.md` — gastos schemas, column contracts, classifier layers | `scripts/shared/categorize.py` (`CATEGORIZED_COLUMNS`, classifier layers), `scripts/shared/normalize.py` (`NORMALIZED_COLUMNS`), `scripts/shared/utils.py` (shared column constants), `.user/finance/bookkeeper/config/{categories,suppliers,tags}.json` (classifier config contracts) |
| `docs/investimentos.md` — investment ledger schemas, portfolio.json shape, calculate chain | `scripts/investimentos/calculate.py`, `scripts/investimentos/import_balance_snapshots.py`, `scripts/investimentos/fx_engine.py`, the per-asset ledger schemas (`assets.csv`, `balcao.csv`, `portfolio.json` fields) |
| `docs/financial-dashboard.md` — dashboard views + which store feeds which view | `dashboard/*.js` (any view's data source or rendered field), `scripts/investimentos/calculate.py` (`portfolio.json` fields the dashboard reads), `scripts/shared/categorize.py` (`transactions.csv` fields `expenses.js` reads) |
| `docs/sources-manifest.md` — active/historical sources + parser entry points | any parser under `scripts/` (added / renamed / retired), `.user/finance/bookkeeper/config/sources.yaml` (when it ships at `p5-6`) |
| `scripts/tools-index.md` — tool registry narrative + per-tool entries | any registered tool's `owner_script` under `scripts/` (a tool added / behavior-changed / retired ⇒ its entry's `outputs`/`expected_inputs`/`last_validated` may be stale) |
| `.user/finance/bookkeeper/config/standing-rules.yaml` accompanying prose (per-section rule docs) | `scripts/shared/lib/standing_rules.py` (a section's loader/consumer changed), the `standing-rules.yaml` section values |
| the field-class registry doc (`_field_ownership.yaml` documentation) | `scripts/investimentos/calculate.py` and any parser that adds/changes an owned field |

The authoritative end-to-end pipeline map is the foundation artifact `1-projects/finance-system/finance-system-v2-foundation/phase-2/data-flow-map-target.md`; `doc-maintainer` keeps that target map current as part of the same coupling (it is a doc surface, not an sb-os-shipped file, so it is reconciled by the companion rather than gated by the commit-time hook in this repo).

**Hard-block vs signal-only couplings.** Most couplings are **hard-block**: a change to the code/config surface with no matching doc in the same commit is refused at commit time (layer 3). The `pipeline_shape` row (`docs/architecture.md`) is **`signal-only`**: whether a given edit to a pipeline script actually changed the pipeline SHAPE (the producer→store→consumer structure `architecture.md` describes) versus an internal/additive change (a new CLI flag, a refactor) is a JUDGMENT, not a path match — so it is NOT commit-gated. It still emits the layer-2 signal and is reconciled by `doc-maintainer` (layer 4). This follows p2-19's design: the commit hook is a coarse, deterministic gate; the companion makes the judgment calls. A change to a store SCHEMA or a dashboard field IS path-expressible and stays hard-block via the `*_schema` and `dashboard_views` rows.

### The shared manifest

The coupling above is also encoded, machine-readable, in `docs/doc-currency-manifest.yaml` — a static lookup mapping each code/config path (or glob) to the doc file(s) and section(s) that describe it, plus a per-coupling `enforcement` field (`hard-block` default, or `signal-only`). The manifest is the SINGLE artifact the signal emitter (layer 2) and the pre-commit hard block (layer 3) both read, so the coupling is declared once and enforced consistently. When this prose declaration and the manifest disagree, the manifest is the machine-read source of truth and MUST be reconciled to match this declaration. The commit-time hook blocks ONLY on `hard-block` couplings that have at least one in-repo doc (a doc the commit could stage); a coupling whose docs all live outside this repo is reconciled by the companion, never commit-gated. Maintaining the manifest is `doc-maintainer`'s job: when a new store/transformation is added, the manifest gains a row in the same reconcile that updates the docs.

### The four enforcement layers

| Layer | What it is | Where |
|-------|-----------|-------|
| **1 — Narrative (this section)** | Declares the coupling and the rule "never change a coupled surface without updating its doc in the same commit." The other layers enforce THIS. | `finance/CLAUDE.md` (here) |
| **2 — Signal (`docs_potentially_stale`)** | An audit event emitted when a structural change (data-store / config / dashboard-script edit) lands without a matching doc update, so the staleness is visible and persistent. Fail-soft (never raises into the caller). | `scripts/shared/lib/audit.py` (`emit_docs_potentially_stale`) |
| **3 — Hard block (pre-commit)** | A pre-commit hook that HARD-BLOCKS (not advisory) any commit changing a coupled code/config surface without staging the matching doc. The block message names the stale doc + the fix. The only pass-path is reconciling the doc — there is no bypass flag. | `scripts/shared/doc_currency_check.py` + `hooks/pre-commit-doc-currency` (activation in `docs/hooks.md`) |
| **4 — Reconciliation (`doc-maintainer`)** | The companion sub-agent that brings the docs current after an approved change and thereby CLEARS the layer-2 signal and lets the layer-3 block pass. It is the legitimate way through the hard block. | `workflows/doc-maintainer/doc-maintainer.md` |

Layers 2 and 3 both read the manifest; layer 4 clears what layers 2 and 3 detect. A commit blocked by layer 3 is resolved by running `doc-maintainer` (layer 4) to reconcile the doc, then re-committing — NOT by bypassing the hook.
