---
name: sb-wiki-ingest
description: Distill a raw source into wiki pages — write source page, update existing entity/concept pages with append-only protection, create stubs, detect candidate-topic triggers, update indexes, append log, present Stage 1 + Stage 2 checkpoints.
---

# sb-wiki-ingest

End-to-end ingest of a single raw source into the Karpathy-style wiki layer. Implements the 11-step flow defined in the wiki schema. Stage 1 (step 10) is the commit gate; Stage 2 (step 11) is an optional post-commit reflection pass. Steps 1–9 run without mid-flow user input.

## Schema Source

Read `3-resources/tools/sb-os/wiki/docs/wiki-schema.md` — Operations § "/sb-wiki-ingest" — for canonical step definitions. This workflow body implements that spec verbatim. Schema deviations require updating the schema first.

## Retrieval Tiers

Schema § "Retrieval tiers — hybrid search" governs every semantic-tier touchpoint in this flow (Steps 3·5c, 3·7b, 3·7c, 3·7d). Probe the tier by invoking the helper once; degrade gracefully:

| Tier | Behavior |
|------|----------|
| Semantic / keyword (helper runs, exit 0) | `python {sb_os_path}/wiki/scripts/sb-wiki-search.py search "<query>" --k N [--type ...]` — the tier-gated augments below are ACTIVE |
| Unavailable (helper missing, errors, exit 2) | Every tier-gated augment is OFF — the flow runs the mechanical baseline exactly as pre-v7 |

The FIRST helper call of the run syncs the index (the step-2 source page enters it there); subsequent calls in the same run pass `--no-sync`. A helper failure NEVER aborts the ingest — drop the augment and continue. **The semantic tier NEVER decides a mechanical fire** — firm-tier topic detection, `Substance`-bullet stubs, and Step 6 trigger detection stay fully deterministic per the schema's mechanical-fire invariant. Runs in BOTH modes (default and silent) — silent's auto-reject postures for speculative updates and proposed answers are unchanged.

## Path Resolution

| Symbol | Resolution |
|--------|------------|
| `{wiki_root}` | Read from `sb-os.json` at vault root → `wiki_root` field. Resolve via `install/manifest.py` (`manifest.read(vault_root)`). Never hardcode. |
| `{user_context_root}` | Read from `sb-os.json` → `user_context_root`. Never hardcode. |
| `{sb_os_path}` | Read from `sb-os.json` → `sb_os_path` field. Never hardcode. |
| `{wiki_root}/wiki/` | Wiki page tree (concepts, entities, topics, sources). |
| `{wiki_root}/raw/` | Raw source tree — Markdown (`.md`) and PDF (`.pdf`) sources. **EXCLUDES `raw/_assets/`** (user-maintained binary attachments — per `../shared/folder-structure.md` "Asset Folder"). This workflow NEVER reads or writes `raw/_assets/` on its own initiative (see write-surface contract § "A10" for the user-directed exception). |
| `{wiki_root}/logs/` | Actionable queue folder — `logs/topics.md` (`candidate-topic`) + `logs/mentions.md` (`candidate-mention`). Ingest writes these two only; `logs/theses.md` (thesis candidates) is Phase-B, NOT written here. |
| `{wiki_root}/purpose.md` | OPTIONAL regulatory file — the focus-lens source loaded at Step 0.5. Root-level sibling of `raw/`, `wiki/`, `logs/`; NOT a wiki page, NOT raw. Absent → lens OFF (ingest identical to today). Per `../../docs/wiki-schema.md` § "Regulatory layer — purpose.md". |
| `{wiki_root}/questions.md` | OPTIONAL questions-layer registry — the user's open questions loaded at Step 0.6 for the answer-scan. Root-level sibling of `raw/`, `wiki/`, `logs/`, `purpose.md`; NOT a wiki page, NOT raw. Absent → questions layer OFF (ingest identical to today). Per `../../docs/wiki-schema.md` § "Questions layer — questions.md". |

## Shared Data Files

These files codify rules referenced across multiple `sb-wiki-*` workflows. Load only the files relevant to the active step.

| File | Used by step |
|------|--------------|
| `../shared/page-types.md` | 3 |
| `../shared/frontmatter-schemas.md` | 2, 5 |
| `../shared/section-menus.md` | 2, 4 |
| `../shared/stub-policy.md` | 3, 4, 5 |
| `../shared/citation-format.md` | 2, 4 |
| `../shared/log-entry-shapes.md` | 9 |
| `../shared/index-formats.md` | 7, 8 |
| `../shared/naming-convention.md` | 1.5, 2, 5 |
| `../shared/folder-structure.md` | 1.5, 2, 5 |
| `./data/candidate-topic-triggers.md` | 6 |

## Event-Scoped Extensions

Optional-feature machinery lives in `extensions/` and loads ONLY when its feature is active (JIT) — an interactive run with no questions layer and no purpose lens reads NONE of these files; the gate lines at each site are the only trace. Each gate states the load condition + path; load at the step named below.

| Extension | Load when | Loaded at | Applies at |
|-----------|-----------|-----------|------------|
| `extensions/silent-mode.md` | `silent` keyword present at invocation | Boot (before Step 1) | Silent Mode gate + Step 1, 1.5, 1.7, 10, 11 silent overrides |
| `extensions/questions-layer.md` | `{wiki_root}/questions.md` present and parseable | Step 0.6 gate | Step 0.6 (load questions) + Step 3·7c (answer-scan) |
| `extensions/purpose-lens.md` | `{wiki_root}/purpose.md` present and parseable (lens ON, decided at Step 0.5) | Step 0.5 (lens ON) | Step 2 (classify + depth dial), Step 3 clause 5b, Step 3·7b (ranking), Step 10 (Stage 1 presentation) |
| `extensions/light-path.md` | Interactive mode (`silent` keyword ABSENT) AND source meets all three qualifying criteria (Markdown, ≤ 300 words body, ≤ 1 H2 heading) | Step 0.7 gate (after Step 0.6, before Step 1) | Step 0.7 (proposal gate + owner approval), Step 10 (skip-list block), escalation triggers during Steps 3–6 |

Extension file missing on disk when its gate fires → HALT naming the missing path (never silently skip the feature). A gate that cannot determine feature state (e.g., `sb-os.json` unreadable) → resolve conservatively: load the extension.

## Invocation

| Form | Behavior |
|------|----------|
| `/sb-wiki-ingest <slug>` | Default (interactive). Runs the full 11-step flow with both checkpoints presented to the user. |
| `/sb-wiki-ingest silent <slug>` | Silent (non-interactive). Runs steps 0–9 UNCHANGED, auto-resolves step 10 to fixed defaults, SKIPS step 11, and RETURNS a structured summary instead of presenting checkpoints. See Silent Mode below. |

`<slug>` is a raw filename or unique substring.

## Silent Mode

**Gate (load at boot).** When the `silent` keyword is present at invocation, READ `extensions/silent-mode.md` NOW — before Step 1 — and apply its contract + every per-step override (Steps 1, 1.5, 1.7, 10, 11). Loading at boot guarantees each silent-override clause is in context BEFORE any halt-capable step is reached, so a silent-mode subagent never halts mid-batch. When the `silent` keyword is ABSENT, do NOT read that file: the run is interactive and NONE of the silent clauses apply — the workflow behaves EXACTLY as the default-mode body specifies.

## Write-Surface Contract

These rules bind ALL write operations in this workflow regardless of mode (default or silent).

### A7 — Thesis pages are scribe-only

`/sb-wiki-ingest` MUST NEVER create or edit ANY page under `wiki/theses/`. Thesis-relevant figures, conclusions, or data encountered during ingest MUST be reported in the Stage 1 RETURN table — NEVER written to a thesis page. Thesis authoring and editing is exclusively the domain of `sb-fin-create-thesis`.

### D24 — Two-tier T4 write rule

| Tier | Where it lives | Rule |
|------|----------------|------|
| Raw T4 framing — a specific below-bar claim extracted from a source | Source page ONLY | Write verbatim on its source page. NEVER on an entity page. |
| Synthesized below-bar verdict | Entity page (permitted) | MUST include attribution: `per {source}, T4 — see [[source-page]]`. NEVER absorb unattributed. |

### A11 — ASCII-only filenames at creation time

Every raw file placed into `{wiki_root}/raw/` and every wiki page written by this workflow MUST have a pure ASCII filename (stem + extension). Non-ASCII characters (accented letters, curly quotes, em-dashes, emoji, etc.) MUST be folded to ASCII before any write.

The ASCII-fold authority is the `normalize-filenames` subcommand of `sb-wiki-lint-deterministic.py` (`_slug_fold`), documented in `../../docs/wiki-schema.md` § "ASCII filename requirement". For PDFs, the title-slug algorithm at Step 1.5 already enforces ASCII; for `.md` raws delivered by a clipper or browser extension, the agent MUST verify the filename is ASCII-only at Step 1 and, if any character is above `0x7F`, rename it via the subcommand (`sb-wiki-lint-deterministic.py normalize-filenames --vault-root <vault> --execute` — it folds the non-ASCII stem, heals every reference class, and re-keys lint state) before proceeding with the ingest. Do NOT create any wiki page whose stem contains a non-ASCII character.

**Clipper seam.** Browser extensions and clippers frequently produce filenames with accents (e.g., `2026-06-01-são-paulo.md`) or curly quotes. These arrive already written to `raw/`. On Step 1, check the resolved raw filename — if it contains any byte above `0x7F`, treat the situation identically to the Step 1.5 PDF rename: fold the stem to ASCII via the algorithm, verify no collision, rename the raw file, and use the ASCII stem for all downstream references (source page, raw index, wiki sources index).

### A10 — File and image routing

**Rule A — Relocate referenced files via the designated capture tool.**
When the user directs ingest to handle a file NOT yet in `raw/{origin}/` (parked in Downloads or in `raw/_unrouted/`), route it into `raw/{origin}/{title-slug}.{ext}` via the workspace's DESIGNATED sole raw-capture tool — the SOLE raw writer, NEVER an ad-hoc file move. Guard: fire ONLY on explicit ingest/capture intent. Infer `origin` from URL/content and CONFIRM when ambiguous. For files already in `raw/_unrouted/`, this IS the staging→`raw/{origin}/` move.

**Rule B — Screenshot images → `raw/_assets/` + embedded in place.**
When the user explicitly mentions a file has images and provides their paths (e.g. from the OS screenshot folder), the agent MUST:
1. Move each image into `{wiki_root}/raw/_assets/` renamed to a descriptive slug (NEVER preserve a name like "Captura de tela …").
2. Embed `![[slug.png]]` in the raw Markdown at the position each image appears, using image-read + surrounding context.
3. FLAG any placement it is unsure of in the Stage 1 table — NEVER silently guess placement.

The user's explicit mention of the file/images IS the required direction to write under `raw/_assets/`.

## Flow

No mid-flow user input during steps 1–9. Stage 1 commits approved changes before Stage 2 begins. Stage 2 is optional and can be ignored without blocking the committed ingest.

### Step 0 — Load extensions

Read `sb-os.json` at vault root → `wiki_extensions` field (a list of registered module names; resolve via `install/manifest.py`, never hardcode). For each listed module, locate its `wiki-ext/` folder and MERGE its `page-types.ext.md`, `frontmatter-schemas.ext.md`, `section-menus.ext.md`, and `lint-rules.ext.md` into the active rule set for this run. Extension page types, entity kinds, sections, and lint rules are ADDED to — never replace — the base set referenced by the shared data files. If `wiki_extensions` is absent or empty, run with the base behavior unchanged. Process every later step against the merged rule set.

### Step 0.5 — Load purpose (focus lens)

Read + parse the OPTIONAL regulatory file `{wiki_root}/purpose.md`. This loads the focus lens that modulates the discretionary surfaces at Steps 2, 5, 3·7b, and 10. The canonical spec is `../../docs/wiki-schema.md` § "Regulatory layer — purpose.md" — follow it; the parsing contract and per-step modulation table there are authoritative.

1. Resolve `{wiki_root}/purpose.md`.
2. **Absent** → **lens OFF**: skip classification and all lens modulation for this run; every later step behaves EXACTLY as it does today (optionality guarantee #1). Proceed to Step 1.
3. **Malformed** (unreadable, invalid frontmatter, or no parseable `## Focus areas`) → WARN and proceed **lens-OFF** (guarantee #5). NEVER abort the ingest. Proceed to Step 1.
4. **Present and parseable** → **lens ON**: parse the four sections per the schema's parsing contract and hold them for the run:

| Section | Lens use |
|---------|----------|
| `## Focus areas` | The match set for band classification (in-focus detection) at Step 2 open. |
| `## Down-weight signals` | Hints that push a source toward the **peripheral** band. |
| `## Quality bar` | Synthesis preferences applied while writing the source page (Step 2). Does NOT influence the wiki sources index `What it says` phrasing (index neutrality guard). |
| `## Out of purpose` | Optional explicit off-purpose list; if absent, off-purpose = "matches no Focus area". |

Lens ON modulates ONLY discretionary surfaces (Steps 2, 5 Title-only/Notable-Quote branches, 3·7b, 10). It NEVER alters a mechanical branch's logic, NEVER drops content, and NEVER suppresses a detected trigger (guarantees #2/#3). Peripheral treatment is floored at today's baseline including cluster granularity (guarantee #4).

**Gate (purpose lens).** Lens ON → READ `extensions/purpose-lens.md` NOW and apply its per-step modulation blocks at their named sites (Step 2 classify + depth dial, Step 3 clause 5b, Step 3·7b ranking, Step 10 Stage 1 presentation; the silent-summary band is in `extensions/silent-mode.md`). Lens OFF (absent or malformed) → do NOT read it; no classification, no band, no modulation.

### Step 0.6 — Load questions (answer-scan)

**Gate (questions layer).** Resolve `{wiki_root}/questions.md`. **Absent OR malformed** (unreadable, invalid frontmatter, or no parseable H2 entries) → **questions layer OFF**: hold an EMPTY question set, omit the Step 10 `PROPOSED ANSWERS` block, do NOT read the extension, and behave EXACTLY as today (optionality guarantee #1; never abort — guarantee #5). **Present and parseable** → **questions layer ON**: READ `extensions/questions-layer.md` and execute its Step 0.6 (parse + hold open questions) HERE, then its Step 3·7c (answer-scan) at the Step 3·7c gate.

### Step 0.7 — Light-path gate (interactive mode only)

**Gate (light path).** This gate runs ONLY in interactive mode. When the `silent` keyword is present, SKIP this gate entirely — do NOT read `extensions/light-path.md`; the full flow runs.

When the `silent` keyword is ABSENT:

1. Resolve the raw file path for `<slug>` (read the raw file now to measure — Step 1 will reuse this read without duplication).
2. Measure the three qualifying criteria against the raw file:
   - **Kind**: extension is `.md` (not `.pdf`)
   - **Word count**: strip the opening YAML frontmatter block (leading `---` through its closing `---` at file start only — NOT inline `---` horizontal rules) and all fenced code blocks (triple-backtick delimited); count whitespace-delimited tokens in the remaining body — passes if ≤ 300 words
   - **Structural simplicity**: count lines beginning with `## ` in the body (after frontmatter strip) — passes if ≤ 1 such heading
3. **Any criterion fails** → do NOT read the extension; run the FULL flow unchanged from Step 1.
4. **All criteria pass** → READ `extensions/light-path.md` NOW and execute its Step 0.7 (proposal gate + owner approval). If the owner approves, set the `light_path_active` flag and proceed to Step 1 under the reduced-flow contract in that extension. If the owner declines (or no response), clear the flag and run the FULL flow from Step 1.

Extension file missing on disk when the gate fires → HALT naming the missing path (never silently skip the feature).

### Step 1 — Read raw file

1. Resolve `<slug>` against `{wiki_root}/raw/`:
   - Exact filename match wins (never ambiguous).
   - Otherwise match unique substring across `{wiki_root}/raw/{origin}/*.md`, `{wiki_root}/raw/{origin}/*.pdf`, and `{wiki_root}/raw/studies/*.md`.
   - Multiple matches → halt and ask the user to disambiguate before any other action.
   - **Silent mode** (keyword present) → apply the Step 1 silent override from `extensions/silent-mode.md` (loaded at boot): do NOT prompt — multi-match RETURNS `failed (slug ambiguous: N matches)`, zero-match RETURNS `failed (slug not found)`.
2. Read the raw file in full. For a PDF source, read it natively (the Read tool renders PDF pages); read every page — issue successive page-range requests when the file exceeds the per-request page limit. Capture origin (`{origin}` = parent folder name; `studies` is a valid origin).
3. Note the source kind from origin and content shape: `article` | `paper` | `podcast` | `study` | `repo` (a PDF source is typically `paper` or `article`).

### Step 1.5 — PDF title-conformance rename + text-twin extraction (PDF sources only)

Markdown raw sources SKIP this step. For a PDF raw source:

1. Determine the paper's title from the document (page 1 / metadata, already read in step 1).
2. Compute `{title-slug}` per `../shared/naming-convention.md` § "Raw PDF Title-Conformance" → "Title-slug algorithm".
3. Stem already equals `{title-slug}` → do nothing; proceed to sub-step 4 (text-twin check).
4. Stem differs AND `raw/{origin}/{title-slug}.pdf` does NOT exist → rename `raw/{origin}/{stem}.pdf` → `raw/{origin}/{title-slug}.pdf` NOW, before the source page is created. The source page (step 2), its `raw:` frontmatter, and every downstream footnote are then born title-named — NO referrer propagation is needed because no page cites this source yet. Use `{title-slug}` as the slug for the rest of the flow.
5. Collision — `raw/{origin}/{title-slug}.pdf` already exists → this raw duplicates an already-ingested paper. ERROR-halt and ask the user: abort (skip the duplicate) or proceed without renaming. **Silent mode** (keyword present) → apply the Step 1.5 silent override from `extensions/silent-mode.md` (loaded at boot): do NOT halt — RETURN `failed (duplicate raw: {title-slug}.pdf exists)` and ingest nothing.
6. **Text-twin extraction (non-optional).** After the rename (or no-rename) above, check whether a Markdown twin `raw/{origin}/{title-slug}.md` already exists.
   - **Twin exists** → skip extraction; proceed to step 2 using the existing twin as the source text.
   - **Twin absent** → MUST extract a durable text twin using `pypdf`-extraction: write the extracted text to `raw/{origin}/{title-slug}.md`. NEVER delete or replace the PDF — BOTH files MUST be preserved. The source page (step 2) MUST link both:
     - `raw:` frontmatter: `"[[{title-slug}.md]]"` (the Markdown twin)
     - body line `Original PDF: [[{title-slug}.pdf]]` immediately after the frontmatter block (the preserved PDF) — NOT a frontmatter key

The rename changes the FILENAME only — raw content is never edited (immutability governs content, per `../shared/folder-structure.md`). The text-twin extraction writes a NEW file; the PDF is preserved.

### Step 1.7 — Content-duplicate check (all sources)

Runs for EVERY source — markdown AND PDF — after step 1 (and after step 1.5 for PDFs). Detects that this raw duplicates an ALREADY-INGESTED source BEFORE any wiki write. Step 1.5 catches only PDF filename collisions; this step catches re-clips, dated twins, and cross-origin duplicates regardless of filename.

Two deterministic signals — EITHER fires:

| Signal | Detection |
|--------|-----------|
| URL match | Normalize this raw's frontmatter `url`/`source` value: lowercase the host, strip scheme, leading `www.`, query string, fragment, and trailing slash. Run ONE `ripgrep`/`grep` pass over `url:` lines in `{wiki_root}/wiki/sources/**` and compare normalized values. Equal → fire. Raw has no URL → signal skipped. |
| Title match | Normalize this raw's title (frontmatter `title`, else first H1): lowercase, collapse every non-alphanumeric run to a single space, trim. Compare against the same-normalized titles of already-ingested raws (raws whose source page exists) in ANY origin — use the raw indexes' `Title` column across ALL rows regardless of `Wiki` cell value; the comparison set is every raw whose 1:1 source page exists under `{wiki_root}/wiki/sources/**` (a stale `Wiki = No` cell never excludes a raw whose source page exists); confirm a hit against the matched raw's frontmatter before firing. Equal → fire. |

On fire:

- **Interactive:** ERROR-halt and ask the user — `abort` (skip the duplicate; raw index `Wiki` stays `No`) or `proceed` (ingest anyway — e.g. the new clip genuinely supersedes the old one). Name the existing raw and its source page in the prompt.
- **Silent mode** (keyword present) → apply the Step 1.7 silent override from `extensions/silent-mode.md` (loaded at boot): do NOT halt — RETURN `failed (content-duplicate: duplicate of <existing-raw>)`.

No fire → proceed to step 2. A fire NEVER deletes the duplicate raw file — disposition (delete vs. re-point) is the user's call.

### Step 2 — Write source page

**Gate (purpose lens).** Lens ON (Step 0.5: `purpose.md` present and parseable) → apply the Step 2 "classify the source" and "`Substance` depth dial" blocks from `extensions/purpose-lens.md` HERE: classify into one band, hold it for Steps 3·7b/5/10, and dial discretionary `Substance` depth by band. Lens OFF → no classification, no band; write `Substance` and select optional sections exactly as today.

Write `{wiki_root}/wiki/sources/{origin}/{date}-{slug}.md`. Filename mirrors the raw counterpart's stem EXACTLY with a `.md` extension — preserve the date format the origin uses (`YYYY-MM-DD-slug.md`, `YYYY_MM_DD-slug.md`, etc.). Do NOT normalize date formats. A PDF raw source keeps the same stem with `.md` (e.g., `Starting-Up-AI.pdf` → `Starting-Up-AI.md`); the `raw:` frontmatter wikilinks the actual raw filename including its real extension (`[[Starting-Up-AI.pdf]]`).

**Substance-bullet granularity discipline.** Bullets MUST name entities/concepts at page-cluster granularity per `../shared/stub-policy.md` § "Page Granularity". Sub-cluster names (variants of a family, properties of a whole, sibling members of a group) appear in prose only — without wikilinks. The bullet writer is responsible for the implicit page-set the bullets define: every wikilinked name in a Substance bullet will trigger the mechanical stub-creation rule downstream in step 5. Cluster first, then write bullets at the chosen granularity.

Frontmatter per `../shared/frontmatter-schemas.md` Source schema:

```yaml
---
type: source
created: <today YYYY-MM-DD>
last-touched: <today YYYY-MM-DD>
raw: "[[<raw-filename>]]"
url: <source URL if present in raw>
author: <author if present in raw>
related: []
tags: [source]
---
```

Section structure per `../shared/section-menus.md` Source page entry:

| Half | Sections to write |
|------|-------------------|
| Agent half | `Substance` (always); `Connections` (always); `Notable quotes` / `Methodology` / `Counterpoints` per source kind selection rules |
| Separator | `---` |
| User half | `My take` ONLY — empty shell (heading only, no body) (v5 — questions-layer; `Open questions` / `Dive deeper` are NOT source-page sections, per `../shared/section-menus.md`. Stage-2 question/dive-deeper content routes to `{wiki_root}/questions.md` instead) |
| Separator | `---` |
| Sources | `Sources` section — required |

Citations: emit inline `[^N]` markers at every claim derived from the raw, then append `[^N]: [[<raw-filename>]]` definitions in the `Sources` section per `../shared/citation-format.md`.

### Step 3 — Identify entities and concepts

1. Extract candidate entity and concept mentions from the raw source AND from the agent-written `Substance` and `Notable quotes` sections of the source page produced in step 2.
2. **Cluster candidates by page-granularity** per `../shared/stub-policy.md` § "Page Granularity". Apply the four decision tests (variants, whole+part, siblings, producer+work) to every pair of related candidates. Replace each TRUE cluster with a SINGLE representative name; sub-cluster names dropped from the working set are NOT logged as `candidate-mention` — they are part of the cluster representative's page. EXCEPTION — a test-3 ad-hoc co-mention set has NO representative: each member stays an independent candidate and NEVER collapses into a synthetic group slug, per `../shared/stub-policy.md` § "Sibling clusters (test 3) — named collective vs. ad-hoc set".
3. For each cluster representative, classify as `entity` or `concept` per `../shared/page-types.md` discriminator rule.
4. For each cluster representative, check existence under `{wiki_root}/wiki/concepts/{slug}.md` and `{wiki_root}/wiki/entities/{slug}.md`.
5. Apply the stub-creation rule per `../shared/stub-policy.md`:
   - The `Substance`-bullet branch is MECHANICAL — fire on match against the cluster representative.
   - The Source-title branch is MECHANICAL ONLY when the title name also appears in a Substance bullet. Title-only names fall under DISCRETION per `../shared/stub-policy.md` § "Title-Branch Rule" — apply the relevance heuristic before firing.
   - The Notable-Quote branch is AGENT DISCRETION per `../shared/stub-policy.md` § "Notable Quote Stub Creation" — apply the relevance heuristic before firing.
5b. **Gate (purpose lens — discretionary stub branches).** Lens ON (Step 0.5) → apply the "Step 3 clause 5b — discretionary stub branches" block from `extensions/purpose-lens.md` HERE: bias ONLY the Title-only / Notable-Quote relevance heuristic by the source's band; the MECHANICAL `Substance`-bullet branch is UNTOUCHED. Lens OFF → apply the heuristic exactly as clause 5 specifies, no bias.
5c. **Near-duplicate probe (NON-SKIPPABLE gates — run for EVERY candidate regardless of tier availability).** Before creating any stub, EVERY candidate MUST pass ALL of the following gates:

   1. **Cross-kind + theses-namespace check (always runs).** The planned slug MUST NOT already exist in ANY kind folder under `wiki/` — `concepts/`, `entities/`, `topics/` — OR as a filename in `wiki/theses/` (vault-wide filename uniqueness). A `concepts/` vs `entities/` collision is allowed per the naming convention; `concepts/` vs `topics/` and any `wiki/theses/` collision are FORBIDDEN. A collision routes the candidate to the `existing-pages` set (step-4 update path) or halts to ask.
   2. **Stub routing validation (always runs).** The planned path MUST match the kind-routing table (schema § "Folder subdivision" naming policy). A `kind: tool` MUST NOT land in `organizations/`; a financial benchmark MUST land in `ai-benchmarks/`; etc. Misrouting is caught HERE, not at lint time.
   3. **Semantic same-referent check (tier-gated; SKIP only when the tier is unavailable).** For EACH candidate that cleared gates 1–2, run ONE helper call: `search "<candidate name> — <planned preamble>" --type concept,entity,topic --k 8` (first call of the run syncs; later calls `--no-sync`). Apply the same-referent test per the schema (Stub policy § "Near-duplicate probe") to concept/entity hits: a hit denoting the SAME referent under a different slug (synonym, alias, spelling/formatting variant — NOT merely related) reroutes the candidate to `existing-pages` instead of stub creation; merely-related or UNCERTAIN → keep the stub (when in doubt, create). HOLD each call's topic-page hits for clause 7b's semantic fires — do NOT re-call the helper there. Tier unavailable → skip gate 3 only; gates 1–2 ALWAYS run.
6. Build six working sets for downstream steps:
   - `existing-pages` — concept/entity pages that already exist (handled in step 4)
   - `stub-candidates` — new concept/entity pages whose stub-creation rule fires (handled in step 5)
   - `mention-only` — names that did NOT clear the stub rule, including Title-only and Notable-Quote-only mentions that the discretion heuristic demoted (logged as `candidate-mention` in step 9)
   - `candidate-topic-updates` — FIRM tier: existing topic pages whose relevance to this source matches per the mechanical rule below (proposed at Stage 1; applied in step 4.5 only on user accept)
   - `candidate-topic-updates-speculative` — SPECULATIVE tier: NEW stubs from this ingest paired with existing topic pages by token overlap or tier-gated semantic fire (proposed at Stage 1 in a separate block; applied in step 4.5 only on user accept; capped at 2)
   - `candidate-topic-updates-semantic` — SEMANTIC tier (source-level): existing topic pages a tier-gated source-level probe surfaces and the confirmation bar confirms (clause 7d; proposed at Stage 1 in a separate block; applied in step 4.5 only on user accept; capped at 2; arm OFF when the semantic tier is unavailable)
7. **Firm tier.** Detection semantics per the schema (§ "Existing topic updates") — the read-path is a deterministic shortlist; NEVER read every topic page, and NEVER use the semantic tier to shortlist this tier (mechanical-fire invariant):

   1. List topic page filenames under `{wiki_root}/wiki/topics/` (directory listing; exclude `topics.md`) — evaluate the slug-match condition against names alone.
   2. Run ONE `ripgrep`/`grep` alternation pass over `{wiki_root}/wiki/topics/` for the source's substance-wikilinked page filenames (files-with-matches) — both wikilink-overlap conditions surface here, since section wikilinks AND `related:` frontmatter both contain the filename text.
   3. READ ONLY the union (slug-matched ∪ grep-hit pages) in full and confirm which mechanical condition holds, dropping grep false-positives (wikilink hits outside the qualifying locations). Fire a candidate-topic-update for each confirmed page where AT LEAST ONE match holds:

| Match | Detection |
|-------|-----------|
| Key-concept/entity overlap | Topic's `Key concepts` or `Key entities` section wikilinks ≥1 page that ALSO appears as a wikilink in this source's `Substance` bullets |
| Related-frontmatter overlap | Topic's `related:` frontmatter wikilinks overlap (≥1) with the source's substance entities/concepts |
| Topic slug match | Topic slug appears in the source title OR in a `Substance` bullet (exact substring, kebab-case match) |

   For each fire, capture: topic page path, the matching match-type (key-concept overlap / related overlap / slug match), and the matched name(s). Semantic-only "feels relevant" matches do NOT fire. NEVER apply the update at this step — populate `candidate-topic-updates` only.

7b. **Speculative tier (new-stub conceptual fit).** For EACH entry in `stub-candidates`, fire speculative candidates against existing topics. **Semantic-primary (D11):** when the semantic tier is available the membership signal is the SOLE decider; `token_overlap` is the degrade path used ONLY when the tier is down (schema § "Existing topic updates" speculative tier):

| Condition | Detection |
|-----------|-----------|
| Semantic membership (PRIMARY — the decider when the tier is available) | When the semantic tier is available: the topic page appears among the stub's HELD probe-call results from clause 5c (`--type concept,entity,topic --k 8` — no new helper call here). While the tier is up this is the SOLE firing signal — token overlap is suppressed entirely. |
| Token overlap (DEGRADE path — fires ONLY when the semantic tier is down) | When the semantic tier is unavailable: the stub's preamble (the 1–2-sentence factual sentence the agent will write at step 5) shares ≥2 substantive tokens with the topic's `Scope` text, sourced from the topics leaf index `Scope` cells (`{wiki_root}/wiki/topics/topics.md` — ONE read covers every topic; a topic missing its index row is read directly for its `Scope` section). **Tokenize via `token_overlap(preamble, scope_text)` in `sb-wiki-lint-deterministic.py`** — the function's docstring carries the full 3·7b tokenization spec verbatim. Threshold: ≥2 distinct substantive tokens shared. When the tier is UP this never fires on its own. |
| Dedupe with firm | The (topic, source) pair must NOT already appear in firm `candidate-topic-updates` — firm wins; suppress speculative for the same topic. Applies to whichever signal fired. |

   Rank by the active signal — semantic fires by helper score (descending) while the tier is up; token fires by overlap count (descending) on the degrade path. Cap to TOP 2. The remaining candidates are dropped silently (NOT logged — they re-detect on future ingests of related sources). For each kept entry, capture: topic page path, the stub's slug, the firing signal (helper score, or matched tokens on the degrade path), and the topic-shape-appropriate proposed body bullet (per the same routing as firm-tier in step 4.5).

   **Gate (purpose lens — speculative ranking).** Lens ON (Step 0.5) → apply the "Step 3·7b — speculative ranking" block from `extensions/purpose-lens.md`: re-rank the qualifying candidates by focus overlap WITHIN the existing TOP-2 cap (reorder only — firing rules, cap, and silent-drop UNCHANGED). Lens OFF → rank exactly as above (semantic fires by score while the tier is up; token fires by count on the degrade path).

7d. **Semantic tier (source-level topic updates).** Detection semantics per the schema (§ "Existing topic updates" → "Semantic tier (source-level)"). This is an ADDITIVE arm catching a source whose substance extends an EXISTING topic with NO firm trigger and no new stub to pair against. It populates `candidate-topic-updates-semantic` only — NEVER applies here. (Clause 7c below is the separate answer-scan step against open questions — a different subject; do NOT conflate.)

   - **Tier-gated — arm OFF when unavailable.** Semantic tier available (§ "Retrieval tiers" — helper runs, exit 0) → arm ON. Unavailable → this arm is OFF entirely; hold an EMPTY `candidate-topic-updates-semantic` set and the run is today's mechanical baseline. There is NO degrade signal — the arm simply does not fire when the tier is down.
   - **One probe per ingest.** After the run's first syncing helper call, run ONE call: `search "<source title> — <substance digest (≤2 sentences)>" --type topic --k 5 --no-sync`. No per-topic loop, no full topic walk.
   - **Confirmation bar (fire condition).** For each returned topic page, READ its `Scope` + section headings (≤5 bounded partial reads) and fire ONLY when the source's `Substance` carries a **citable factual claim that extends that topic's scope**. Thematic resemblance with NO citable claim → NO fire (nothing to propose). A semantic hit is NEVER promoted to firm.
   - **Dedupe (apply in order):** (1) firm wins — suppress any topic already in this run's `candidate-topic-updates`; (2) no double-presentation — suppress any topic already in this run's `candidate-topic-updates-speculative`; (3) citation-dedupe — suppress when the topic's `Sources` already cites this source (raw or source-page wikilink): the mechanical "already contains the information" proxy; (4) artifact/ledger-dedupe — suppress (source, topic) pairs already pending in, or rejected-ledgered by, `{wiki_root}/pending-topic-updates.md` (read it if present; absent → no suppression).
   - **Cap 2 per ingest**, ranked by helper score (descending). Overflow drops silently — re-detected by future ingests or the backfill.
   - For each kept entry, capture: topic page path, the firing signal (`semantic: <score>`), and the topic-shape-appropriate proposed body bullet (same routing as firm-tier in step 4.5).

### Step 3·7c — Answer-scan (match new source against open questions, BOTH homes)

**Gate (questions layer).** Questions layer OFF (Step 0.6: `questions.md` absent or malformed) → SKIP this step entirely; hold an EMPTY `candidate-answers` set; the Step 10 `PROPOSED ANSWERS` block is omitted and the run is identical to today. Questions layer ON → execute the Step 3·7c answer-scan from `extensions/questions-layer.md` HERE (loaded at the Step 0.6 gate). It prepares but does NOT write — apply happens at Step 10 commit, only for accepted rows.

### Step 4 — Update existing entity/concept pages

For each page in `existing-pages`:

1. Read the target page in full.
2. Apply append-only protection per `../shared/stub-policy.md` "Append-Only Protection" section.
3. If Contradiction-`same-scope-opposing` fires (detected in step 6 against this page's existing claims), populate the `Open variants / debates` section AND prepend a `> [!warning] Disputed` callout per `../shared/section-menus.md` "Contradiction — Disputed Callout" section.
4. Update `last-touched: <today>` in frontmatter.
5. Append inline `[^N]` markers in any newly-written prose tied to this source, with matching `[^N]: [[<raw-filename>]]` definition in `Sources`. Number footnotes locally per page; lint renumbers across pages later. Format per `../shared/citation-format.md`.

### Step 4.5 — Stage existing topic-update proposals

Process ALL THREE tiers built at step 3: `candidate-topic-updates` (firm), `candidate-topic-updates-speculative` (speculative), and `candidate-topic-updates-semantic` (semantic source-level, clause 7d). The staging logic is identical for all three — each produces staged proposals applied through the SAME apply-semantics (sub-step 3 below — the sole authority; never fork a second apply path). The tiers are surfaced in SEPARATE blocks at Stage 1 (`TOPIC UPDATES (firm — applied on commit; reject N to skip)` for firm, `SEMANTIC TOPIC UPDATES (source-level, default reject)` for semantic, `SPECULATIVE TOPIC UPDATES` for speculative).

For each entry in ANY tier:

1. Read the topic page in full.
2. Determine the topic shape from its sections (debate / comparison / landscape / decision-frame / evolution / cross-application). Use existing section presence as the signal: `Key positions / Angles` → debate; `Timeline` → evolution; `Key concepts` / `Key entities` only → landscape; etc.
3. Determine the proposed change (staged ONLY — NEVER apply yet):
   - Footnote: a new `[^N]: [[<raw-filename>]]` entry to be appended to the topic's `Sources` section. Number locally; lint normalizes globally.
   - Body bullet: ONE bullet under the topic-shape-appropriate section per the schema § "Existing topic updates" Update behavior table:
     - debate-shaped → `Key positions / Angles`
     - evolution-shaped → `Timeline`
     - cross-application-shaped → `Key concepts` or `Key entities` (whichever holds the source's substance overlap)
     - other shapes → `Key concepts` / `Key entities` if the source introduces a new wikilinkable page; otherwise no body bullet (citation-only update)
   - Frontmatter: `last-touched: <today>`.
   - **Apply-semantics (sole authority — Step 10 accept rows point here).** On user accept, apply the three staged changes above as APPEND-ONLY edits: append the footnote `[^N]: [[<raw-filename>]]` to `Sources`; append the staged body bullet under its section with an inline `[^N]` marker; bump `last-touched: <today>`. Append-only protection per `../shared/stub-policy.md` "Append-Only Protection" applies — NEVER overwrite existing prose. No log entry — the topic page records its own updated content.
4. Surface the staged proposal at Stage 1 (step 10) in the block matching its tier, each with its posture:
   - **Firm** (`candidate-topic-updates`) → `TOPIC UPDATES (firm — applied on commit; reject N to skip)` — GENUINE firm rows apply on the Stage-1 commit; the user vetoes a row with explicit `reject N`.
   - **Semantic** (`candidate-topic-updates-semantic`) → `SEMANTIC TOPIC UPDATES (source-level, default reject)` — default reject; the user must explicitly `accept N` to apply.
   - **Speculative** (`candidate-topic-updates-speculative`) → `SPECULATIVE TOPIC UPDATES` — default reject; explicit `accept N` to apply.
   **EXCEPTION — answer-origin firm entries:** a firm `candidate-topic-updates` entry staged by Step 3·7c (an answer to a topic's `Open questions` line) is surfaced in the `PROPOSED ANSWERS` block at Step 10 instead — SUPPRESS it from the firm `TOPIC UPDATES` block so the same resolution is never presented twice, and it keeps the PROPOSED ANSWERS default-reject posture (NEVER applies on commit). Its staged change additionally includes the strike of the matched `Open questions` line, and accepting its `PROPOSED ANSWERS` row applies this same staged update.

This step prepares but does NOT write. Apply happens at step 10 commit, only for accepted rows.

### Step 5 — Create stubs

For each entry in `stub-candidates`:

1. Resolve target path. Default: `{wiki_root}/wiki/concepts/{slug}.md` (concept) or `{wiki_root}/wiki/entities/{slug}.md` (entity). **If the parent type folder has been subdivided** per schema § "Folder subdivision" (per-kind subfolders proposed and executed by `/sb-wiki-lint`), check the parent `{wiki_root}/wiki/{type}/CLAUDE.md` marker-block routing table for the kind's subfolder and write to `{wiki_root}/wiki/{type}/{subfolder}/{slug}.md` instead. Kinds without a subfolder write to the type-folder root. Subdivision read is best-effort — if the parent CLAUDE.md is absent or the marker block is missing, default to type-folder root.
2. Slug per `../shared/naming-convention.md` — `lowercase-kebab.md`. Forbidden: same slug already present in a sibling type folder (concepts vs topics is forbidden per schema; concepts vs entities is allowed).
3. Write frontmatter per `../shared/frontmatter-schemas.md` (Concept adds `kind:` free-form string; Entity adds `kind:` from the enum defined in `../shared/frontmatter-schemas.md` — single source of truth, never restated here).
4. Write a 1–2 sentence preamble derived from the raw source.
5. Write the required sections empty:
   - Concept: `Definition` (1 factual sentence ending with the inline `[^1]` marker) + `Sources` (with the matching `[^1]: [[<raw-filename>]]` definition)
   - Entity: `What it is` (1 factual sentence ending with the inline `[^1]` marker) + `Sources` (with the matching `[^1]: [[<raw-filename>]]` definition)
6. Do NOT populate optional sections — stub-state per `../shared/stub-policy.md` requires main content sections empty or absent.

### Step 6 — Detect candidate-topic triggers

Run all three triggers per `./data/candidate-topic-triggers.md`. For each fire, record the data needed for the step 9 log entry and the step 10 PROPOSED TOPICS block.

| Trigger | Action on fire |
|---------|----------------|
| Contradiction (`same-scope-opposing` only — other scopes log informationally, no candidate) | Stage `> [!warning] Disputed` callout for the affected concept/entity page (applied at step 4 if the page exists, OR queued onto the new stub if step 5 created it). Capture verbatim quotes from both sides + scope classification. |
| Evolution | Capture both source dates and the divergent claims. Single-source temporal phrases do NOT fire — both required: ≥2 dated sources AND divergent claims. |
| Cross-application | Capture the X-for-Y phrase + both wiki page slugs (exact wikilink match required) + the ≥2 sources referencing the pairing. |

If no triggers fire, leave the candidate set empty — Stage 1 omits the PROPOSED TOPICS block.

### Steps 7–8 — Record index transaction

Invoke the transaction helper once after the source page and staged wiki writes are ready:

```bash
python {sb_os_path}/wiki/scripts/sb-wiki-index-transaction.py --vault-root <vault-root> --origin <origin> --raw-file <raw-filename> --source-file <source-page-filename> --what-it-says "<1-sentence factual summary>" --raw-title "<raw title>" --raw-date "<capture date>"
```

The helper resolves `{wiki_root}` from `sb-os.json`, sets the raw index `Wiki` cell to `Yes`, and adds the wiki sources index row atomically: both index writes land or neither does. It reads table headers to locate columns and follows `../shared/index-formats.md` exactly.

Arguments:

- `--origin`: raw/source origin folder.
- `--raw-file`: current raw filename, including extension.
- `--source-file`: source page filename matching Step 2 exactly.
- `--what-it-says`: 1-sentence factual summary (≤280 chars) derived from the source page's `Substance` section.
- `--my-take`: omit at initial ingest; default is `pending`. Stage 2 (step 11) may overwrite this cell with a 1-sentence reflected preview, with `—` (em-dash) if the user finalizes empty, or leave it as `pending` if the user declines reflection.
- `--raw-title` and `--raw-date`: required only if the raw-index row is missing; use deterministic values already established for the raw index format.

Idempotency: if the wiki sources row already exists, the helper writes no duplicate and still ensures the raw index `Wiki` cell is `Yes`.

Manual fallback for environments without Python: perform the same two edits manually as one staged unit, then verify both landed before continuing. Resolve raw index `{wiki_root}/raw/{origin}/{origin}.md` (or `{wiki_root}/raw/studies/studies.md`), locate/create the row whose `File` column wikilinks the current raw filename, and set `Wiki = Yes`. Resolve wiki sources index `{wiki_root}/wiki/sources/{origin}/{origin}.md`, add or update the row `| [[<source-page-filename>]] | <What it says> | pending |`, and keep the cell rules in `../shared/index-formats.md` "`My take` Cell — Three States" authoritative. Raw-index FILE missing → LOG A WARNING; do not create it. Wiki sources index FILE missing → create it with `| File | What it says | My take |` plus the separator row before adding the source row.

### Step 9 — Append log entries

Append entries to the split logs under `{wiki_root}/logs/` per `../shared/log-entry-shapes.md` — each log is an ACTIONABLE QUEUE. Emit ONLY the two types below, each a STANDALONE H2 entry (`## [YYYY-MM-DD HH:MM] <type> | <brief>`) appended to its own file. Do NOT cross-reference a parent ingest.

| Entry | File | When emitted |
|-------|------|--------------|
| `candidate-topic` | `{wiki_root}/logs/topics.md` | Once per trigger fire from step 6 |
| `candidate-mention` | `{wiki_root}/logs/mentions.md` | Once per name in the `mention-only` set from step 3 |

Emit NOTHING for the ingest itself, for stubs created in step 5, or for topic updates from step 10. Those are recorded by the pages themselves (the source page's `raw:` field, the raw index `Wiki = Yes` row, the stub/topic pages). Overflow speculative matches dropped at step 3.7b are NOT logged — they re-detect on future ingests. Resolution = page exists: a candidate leaves the queue when its page is created (lint prunes it). See `../shared/log-entry-shapes.md` § "Retired Types".

### Step 10 — Stage 1 checkpoint

Present the user with a structured preview of all proposed file changes AND the PROPOSED TOPICS block. No file writes commit until the user responds.

**Gate (purpose lens — Stage 1 presentation).** Lens ON (Step 0.5) → apply the "Step 10 — Stage 1 presentation" block from `extensions/purpose-lens.md`: add the classification line to the preview header, the off-purpose advisory banner, and the `focus` trigger-priority tags (controls, file-changes table, and Step 6 detection all UNCHANGED). Lens OFF → NO classification line, NO banner, NO `focus` tags — the preview is IDENTICAL to today.

Format VERBATIM (lens ON appends ` [purpose: …]` to the header line; lens OFF omits it):

```
INGEST PREVIEW — <source slug>   [purpose: in-focus | peripheral | ⚠ off-purpose]

⚠ Off-purpose — this source matches no focus area in purpose.md.   (only when band = off-purpose)
   Ingest anyway?  (accept-all proceeds · abort discards)

| # | file | action | preview |
|---|------|--------|---------|
| 1 | wiki/sources/<origin>/<date>-<slug>.md | new | <first sentence of Substance, ≤80 chars, truncate with …> |
| 2 | wiki/concepts/<slug>.md | updated | + section "<new section name>" |
| 3 | wiki/concepts/<slug>.md | new (stub) | <preamble first sentence, ≤80 chars, truncate with …> |
| 4 | wiki/entities/<slug>.md | new (stub) | <preamble first sentence, ≤80 chars, truncate with …> |
| 5 | logs/topics.md, logs/mentions.md | appended | candidate-topic + candidate-mention entries (only if triggered) |
| 6 | raw/<origin>/<origin>.md | row updated | Wiki = Yes |
| 7 | wiki/sources/<origin>/<origin>.md | row added | new entry |

PROPOSED TOPICS:
| # | name | trigger | sources |
|---|------|---------|---------|
| 1 | <topic-slug> | <contradiction (same-scope-opposing) | evolution | cross-application> | [[<src1>]], [[<src2>]] |

TOPIC UPDATES (firm — applied on commit; reject N to skip):
| # | topic | match | proposed change |
|---|-------|-------|-----------------|
| 1 | [[<topic-slug>.md]] | <key-concept overlap | related overlap | slug match> ([[<matched-page>]]) | + bullet under "<section-name>" + citation |

SEMANTIC TOPIC UPDATES (source-level, default reject):
| # | topic | signal | proposed change |
|---|-------|--------|-----------------|
| 1 | [[<topic-slug>.md]] | semantic: <score> | + bullet under "<section-name>" + citation |

SPECULATIVE TOPIC UPDATES (low-confidence, default reject):
| # | topic | overlap | proposed change |
|---|-------|---------|-----------------|
| 1 | [[<topic-slug>.md]] | tokens: <token1>, <token2> ([[<new-stub-slug>.md]]) | + bullet under "<section-name>" + citation |
| 2 | [[<topic-slug>.md]] | semantic: <score> ([[<new-stub-slug>.md]]) | + bullet under "<section-name>" + citation |

PROPOSED ANSWERS (default reject):
| # | question | home | overlap | proposed resolution |
|---|----------|------|---------|---------------------|
| 1 | <question text> | [[<topic-slug>.md]] | tokens: <token1>, <token2> — or: semantic (top-5) | strike "Open questions" line + fold answer into "<section-name>" + citation |
| 2 | <question text> | questions.md | tokens: <token1>, <token2> — or: semantic (top-5) | + answer: bullet on the entry + citation |

File changes: accept-all | reject N (e.g. "reject 3,4") | abort
Topic decisions: accept N (creates now) | defer N (logs as candidate) | (default: defer all)
Firm topic updates: applied on commit | reject N (skip — ledgers the pair) | (default: apply all)
Semantic topic updates: accept N (applies append-only update) | reject N (skip — ledgers the pair) | (default: reject all)
Speculative updates: accept N (applies append-only update) | reject N (skip) | (default: reject all)
Proposed answers: accept N (applies answer) | reject N (skip) | (default: reject all)
```

Omit the PROPOSED TOPICS block entirely if no triggers fired in step 6. Omit the firm `TOPIC UPDATES` block entirely if `candidate-topic-updates` has no non-answer-origin entries after step 3 (answer-origin entries surface in PROPOSED ANSWERS, not here). Omit the SEMANTIC TOPIC UPDATES block entirely if `candidate-topic-updates-semantic` is empty after step 3 (arm OFF, or no fire confirmed). Omit the SPECULATIVE TOPIC UPDATES block entirely if `candidate-topic-updates-speculative` is empty after step 3. Omit the PROPOSED ANSWERS block entirely if `candidate-answers` is empty after step 3·7c (questions layer OFF, or no question matched).

User response handling:

| Response | Behavior |
|----------|----------|
| `accept-all` | Commit all file changes immediately. Then present step 11 as an optional post-commit prompt. |
| `reject N` (or comma list, e.g. `reject 3,4`) | Roll back ONLY the listed numbered items: delete new files for those rows, revert edits, remove log entries scoped to those changes. Other changes commit immediately. If a downstream page (e.g., row 3) is rejected but the source page (row 1) is not, downgrade the raw index update from `Wiki = Yes` to `Wiki = Partial` in row 6. If the source page remains committed, present step 11 as an optional post-commit prompt. |
| `abort` | Roll back EVERYTHING. Raw index `Wiki` stays `No`. Source page is not created. Log entries removed. Skip step 11. |
| Topic `accept N` (per topic row) | Invoke the `sb-wiki-create-topic` skill mid-run with the proposed topic name. The skill writes the topic page, updates `wiki/topics/topics.md`, cross-links from triggering concept/entity pages, and REMOVES the promoted `candidate-topic` log entry (the topic page is now the record — no `topic-created` entry). |
| Topic `defer N` (per topic row, default if user omits a topic decision) | The `candidate-topic` log entry persists. The user may promote later by expressing intent — Claude Code auto-fires the `sb-wiki-create-topic` skill. |
| Firm topic update — APPLIED ON COMMIT (genuine firm rows in the `TOPIC UPDATES (firm …)` block) | Any committing response (`accept-all`, or `reject N` of other rows) APPLIES every genuine firm topic-update row via the staged Step 4.5 update (Step 4.5 owns the apply-semantics — sole authority), minus rows the user explicitly `reject N`s. `abort` rolls back everything (no firm update applies). No log entry — the topic page records its own updated content. (Answer-origin firm entries are excluded — they live in PROPOSED ANSWERS, default-reject.) |
| Firm topic update `reject N` (per firm topic-update row) | No change to the topic page. APPEND the (source, topic) pair to the rejected ledger in `{wiki_root}/pending-topic-updates.md` (no-renag — the backfill never re-proposes it; create the file with a minimal header if absent). No log entry. |
| Semantic update `accept N` (per semantic topic-update row) | Apply the staged Step 4.5 update (same apply-semantics — sole authority; no log entry). |
| Semantic update `reject N` (per semantic topic-update row, default if user omits) | No change to the topic page. APPEND the (source, topic) pair to the rejected ledger in `{wiki_root}/pending-topic-updates.md` (no-renag; create the file with a minimal header if absent). No log entry. An OMISSION-default reject (user never reviewed the row) does NOT ledger — only an EXPLICIT `reject N` ledgers. |
| Speculative update `accept N` (per speculative topic-update row) | Apply the staged Step 4.5 update (same apply-semantics as firm; no log entry). ALSO append the new stub's wikilink to the topic's `related:` frontmatter (so future firm-tier detection picks up the connection mechanically). |
| Speculative update `reject N` (per speculative topic-update row, default if user omits) | No change to the topic page. No log entry. The detection is not preserved — re-detected on future ingests of related sources if token overlap recurs. |
| Proposed answer `accept N` — **topic-home** row (home = `[[<topic>.md]]`) | Apply the staged Step 4.5 update from Step 3·7c (Step 4.5 owns the apply-semantics — sole authority), PLUS strike the matched `Open questions` line in place (`~~…~~`) — never delete it. NEVER auto-authors a page. No log entry — the topic page records its own content. |
| Proposed answer `accept N` — **questions.md** row (home = `questions.md`) | Accrete the 1-sentence claim onto that `questions.md` entry's `answer:` field per the answer-write procedure in `../shared/question-entry-shapes.md` (`answer:` field rule + State rule), citing `[[<raw-filename>]]`. |
| Proposed answer `reject N` (per row, default if user omits) | No change to the topic page or `questions.md` entry; for a topic-home row, discard the staged step-4.5 topic-update too. No log entry. The detection is not preserved — re-detected on future ingests (or by the lint sweep) if overlap recurs. |

Default behavior when the user omits per-topic decisions: defer all topics, **apply firm updates** (genuine firm rows apply on commit; an explicit `reject N` ledgers that pair, omission does not), reject semantic, reject speculative, reject all proposed answers. Answer-origin firm entries (in PROPOSED ANSWERS) reject by omission like the other answer rows.

**Post-commit citation-integrity gate (MANDATORY — runs after ANY committing response, including silent mode; skipped only on `abort`).** Immediately after the commit lands, run the gate over EVERY page the commit wrote or edited (source page, step-4 updated pages, step-5 stubs, accepted topic pages):

```bash
python {sb_os_path}/wiki/scripts/sb-wiki-lint-deterministic.py check-pages --vault-root <vault-root> <page> [<page> ...]
```

Exit 0 → proceed. Exit 1 → repair each listed failure NOW (place the missing inline `[^N]` marker on the sentence the source backs, or add the missing `[^N]:` definition) and re-run until exit 0. The ingest is NOT complete while the gate fails. NEVER repair by deleting a `[^N]:` definition — stale-removal is report-only per `../shared/citation-format.md`.

**Silent mode override (step 10) — gate.** Silent mode (keyword present) → apply the "Step 10 silent override" block from `extensions/silent-mode.md` (loaded at boot): do NOT present the preview, do NOT prompt, do NOT HALT; bucket every firm-set entry by origin (genuine firm updates auto-APPLY; answer-origin entries auto-REJECT); auto-resolve every decision point to its fixed default; write the per-record audit `Flags` lines; RETURN the structured summary. The silent-summary purpose-band field (lens ON only) is in that same extension block.

### Step 11 — Stage 2 checkpoint

**Silent mode override (step 11) — gate.** Silent mode (keyword present) → apply the "Step 11 silent override" block from `extensions/silent-mode.md` (loaded at boot): SKIP this step entirely — never present the prompt, never await a response. The source page user-half stays empty shells; the wiki sources index `My take` cell stays `pending` (set at step 8). The structured summary was already returned at step 10.

Optional post-commit reflection pass. Skip entirely if Stage 1 was aborted OR the source page was rejected at Stage 1. The ingest is already complete when this prompt appears. If the user ignores the prompt and sends an unrelated next command, do not treat that next command as a reflection response.

The prompt is a SINGLE combined ask (v5). `My take` stays its own routed answer destined for the source page; questions and dive-deepers are BOTH captured as `{wiki_root}/questions.md` entries. Format VERBATIM:

```
Committed approved ingest changes.

Reflect on this source? (y/n, or write any reflection now)
My take? Any questions or anything to dive deeper?
```

Handling:

| User response | Behavior |
|---------------|----------|
| No response / unrelated next command | Do nothing. Source page `My take` stays empty. No `questions.md` entry written. Wiki sources index `My take` cell stays `pending` (set at step 8). |
| `n`, `no`, `skip`, or equivalent no-reflection response | Skip reflection. Source page `My take` stays empty. No `questions.md` entry written. Wiki sources index `My take` cell stays `pending` (set at step 8). |
| Freeform reflection text | Route the text into `My take` (source page) and/or `questions.md` entries by intent, regardless of order. |

Reflection routing — two destinations:

| Destination | Receives | Where it is written |
|-------------|----------|---------------------|
| `My take` | "why it mattered" reflection content | The source page `## My take` section (UNCHANGED — still feeds the 3-state index cell below) |
| `questions.md` | every question AND every dive-deeper / follow-up | One `{wiki_root}/questions.md` entry per question/dive-deeper, `seeded-by:` THIS source, per `../shared/question-entry-shapes.md` |

1. Treat the first substantive response to the Stage 2 prompt as a routing bundle. The user does NOT need to answer in order.
2. Split spans by intent markers:
   - `My take` (→ source page): "my take", "take", "why it mattered", "o que eu achei", "minha visão", "minha leitura".
   - `questions.md` (→ entry): "open questions", "question", "dúvida", "pergunta", "unclear", "não entendi", "dive deeper", "deep dive", "deep diver", "dive deepr", "follow up", "aprofundar", "quero dive deeper em", "quero me aprofundar em".
3. Route semantically clear unlabeled clauses to the matching destination even if they arrive while another part is displayed. Example: "quero dive deeper em graph databases" becomes a `questions.md` entry, never `My take`.
4. For each question/dive-deeper span, write ONE `questions.md` entry per the inlined shape below. For `My take` span(s), write the text under the source page `## My take` heading.
5. If a response contains substantive text with no routing signal, write it under `My take` (source page).
6. If a span could reasonably belong to either destination and misrouting would change meaning, ask one targeted clarification instead of writing it.
7. Do not prompt for the unfilled destination after routing a freeform bundle. The user can add to `My take` or `questions.md` later in Obsidian.

`questions.md` entry write — append per `../shared/question-entry-shapes.md`: one H2 entry per question/dive-deeper, `seeded-by: "[[<this-source>.md]]"`, `relates:` to any wiki page the question concerns (omit if cross-cutting), and NO `answer:` block (the entry is born `open`). Write NO `status` field.

**Absent `questions.md` at capture time → CREATE-ON-FIRST-CAPTURE.** When the user routes a question/dive-deeper but `{wiki_root}/questions.md` does not yet exist, create the file (frontmatter `type: questions`, per `../../docs/wiki-schema.md` § "Questions layer — questions.md"), then append the entry. This is consistent with the Step 0.6 load contract: absence at LOAD time means the answer-scan held an empty set for THIS run (layer was OFF for scanning), but a user reflection is an explicit write intent — honor it by materializing the registry. Never silently drop a user-volunteered question. (Load-time absence = no-op for reading; capture-time routing = create-then-write.)

After handling the Stage 2 response, re-sync the wiki sources index `My take` cell per `../shared/index-formats.md` § "`My take` Cell — Three States (NEVER blank)" — its **Write rules** table defines the Stage 2 (step 11) outcome→cell-value mapping (routed reflection filled `My take` → reflected preview; `My take` empty while `Open questions`/`Dive deeper` filled → `—`; declined/ignored/no routed content → `pending`). Source page is canonical; index is derived. **NEVER leave the cell blank.**

End of flow.

## Failure Modes

| Failure | Behavior |
|---------|----------|
| `<slug>` resolves to multiple raw files | Halt at step 1; ask user to disambiguate. No writes. |
| PDF `{title-slug}.pdf` already exists at step 1.5 (duplicate raw) | Error-halt; ask abort / proceed-without-rename. Silent: RETURN `failed (duplicate raw: {title-slug}.pdf exists)`. No writes. |
| Content-duplicate fires at step 1.7 (URL or title matches an already-ingested source) | Error-halt; ask abort / proceed. Silent: RETURN `failed (content-duplicate: duplicate of <existing-raw>)` — sole permitted write: raw index row → `Wiki = Duplicate (of [[<existing-raw>]])`. Never delete the raw. |
| `pypdf` extraction fails at step 1.5 (text-twin write error) | LOG A WARNING; proceed with native PDF read from step 1 as source text; write the `Original PDF: [[{title-slug}.pdf]]` body line but omit the `raw:` twin link in the source page (no twin was produced). Do NOT abort the ingest. |
| `<slug>` resolves to multiple raw files (silent mode) | No halt. RETURN summary `failed (slug ambiguous: N matches)`. No writes. |
| `<slug>` resolves to zero raw files (silent mode) | RETURN summary `failed (slug not found)`. No writes. |
| `{wiki_root}` cannot be resolved from `sb-os.json` | Halt before step 1; surface error. No writes. |
| Stage 1 not yet reached when the user interrupts | Roll back any partial writes from steps 2–8. |
| `sb-wiki-create-topic` skill fails mid-Stage-1 acceptance | Mark the topic row as failed; keep the `candidate-topic` log entry; proceed with the rest of the acceptance. |
| Raw-index ROW missing at step 7 | CREATE the row (deterministic — no warning). |
| Raw-index FILE missing at step 7 | LOG A WARNING; do not create the file (lint owns raw-index files); do not block the ingest. |
| Wiki sources index file missing at step 8 | Create it with header row; proceed. |
| `sb-wiki-search.py` unavailable (missing, non-zero exit, runtime error) at any tier-gated touchpoint (3·5c, 3·7b semantic fires, 3·7c semantic membership) | Drop ALL tier-gated augments silently — the run is the mechanical baseline (exact-slug existence, token-overlap fires only). NEVER abort the ingest. |
| `sb-wiki-search.py` unavailable at the Step 3·7d source-level semantic probe | The semantic source-level arm is OFF for this run — hold an EMPTY `candidate-topic-updates-semantic` set, omit the SEMANTIC TOPIC UPDATES block. NO token fallback (the arm has no degrade signal — it simply does not fire). NEVER abort the ingest. |
| `{wiki_root}/wiki/topics/topics.md` missing or a topic lacks its index row at step 3·7b | Read the affected topic page(s) directly for `Scope` text; proceed. Never skip a topic for a missing index row. |
| `{wiki_root}/purpose.md` malformed at step 0.5 (unreadable, invalid frontmatter, or no parseable `## Focus areas`) | WARN and proceed **lens-OFF** — every later step behaves as it does today. NEVER abort the ingest (guarantee #5). (Absent `purpose.md` is NOT a failure — it is the clean no-op lens-OFF path handled at Step 0.5.) |
| `{wiki_root}/questions.md` malformed at step 0.6 (unreadable, invalid frontmatter, or no parseable H2 entries) | WARN and proceed with an EMPTY question set (questions layer OFF) — the Step 10 `PROPOSED ANSWERS` block is omitted; every other step behaves as it does today. NEVER abort the ingest (guarantee #5). (Absent `questions.md` is NOT a failure — it is the clean no-op layer-OFF path handled at Step 0.6.) |
