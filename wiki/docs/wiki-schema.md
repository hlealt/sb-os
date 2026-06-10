# Wiki Schema (v7 — retrieval-first)

> **Status:** Locked design. Operational spec for the Karpathy-style wiki layer shipped by **sb-os v2** (per `sb-os-build/second-brain-os-architecture.md` §12 and Decisions Log #12). sb-os v1 ships only the `wiki_root` config slot in `sb-os.json` (default `3-resources/knowledge-base/`), the empty default folder, and a placeholder managed `CLAUDE.md` at `{wiki_root}/CLAUDE.md`. The schema, the four `sb-wiki-*` components, and any populated wiki content described below are out of v1 scope — they ship in **sb-os v2**. Agents and CLAUDE.md files reference this document only after v2 lands.

## Purpose & context

Defines schema and operational rules for the wiki layer shipped by sb-os v2. Pattern source: [Karpathy's LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f). Wiki content lives at `{wiki_root}/` (vault-side, user data), where `{wiki_root}` is the configurable path persisted in `sb-os.json` at install time (default `3-resources/knowledge-base/`). All paths in this document that begin with `3. Resources/knowledge-base/` are pre-cutover examples — read them as `{wiki_root}/` once sb-os is installed.

Goal: turn high-volume reading (articles, podcasts, papers, repos, study sessions) into compounding knowledge — cross-referenced, contradiction-flagged, queryable.

User mode preference: **query-driven** (asks the agent rather than browses), with **mandatory cross-linking on ingest** so wikilinks-graph stays viable as fallback. **No browse-mode affordance in lint v1.**

Audience: future agents executing wiki ingest / create-topic / lint / query operations, and the user reviewing those operations.

## Installer scope guarantee

The sb-os installer (`install.py`) NEVER reads or writes any file under `{wiki_root}/wiki/` or `{wiki_root}/raw/`. The installer's write surface is limited to: managed CLAUDE.mds (marker blocks only), `.claude/` thin loaders, and `sb-os.json` at the vault root. Wiki content — leaf indexes (`wiki/concepts/concepts.md`, `wiki/entities/entities.md`, `wiki/topics/topics.md`, `wiki/sources/{origin}/{origin}.md`), raw leaf indexes (`raw/{origin}/{origin}.md`), source pages, concept pages, entity pages, topic pages, and the `logs/` queues — is created and maintained EXCLUSIVELY by `/sb-wiki-lint` and `/sb-wiki-ingest`. Re-running `install.py --upgrade` is safe at any time and will not modify, overwrite, or delete any wiki content.

## Page types

Currently 4: **Concept**, **Entity**, **Topic**, **Source**. Type identity is enforced by both folder placement and frontmatter `type:` field.

The list is **extensible** — new page types may be added when a real ingest pattern hits a gap not covered by the current 4. Operational `CLAUDE.md` files must call out the extensibility so agents know they can propose new types via the user (not auto-create).

### Concept

The **idea itself**. Definable in one sentence. Stable over time.

| Test | Concept passes if |
|------|-------------------|
| Can the user write a 1-sentence definition that would survive on Wikipedia? | Yes |
| Is the definition stable over time (modulo refinement)? | Yes |
| Is it a singular noun or noun phrase? | Yes |

Examples: `model-context-protocol`, `retrieval-augmented-generation`, `world-models`, `compound-engineering`, `knowledge-graphs`, `code-execution-pattern`, `self-supervised-learning`.

### Entity

A specific named thing — tool, person, company, product, model. Concrete identity, not an abstraction.

Examples: `claude-code`, `langgraph`, `dspy`, `mem0`, `cognee`, `karpathy`, `boris-cherny`, `yann-lecun`, `anthropic`, `cloudflare`, `gemini-3.1-pro`, `kimi-k2.5`.

### Topic

The **conversation around an idea or entity**. Plural framing. Evolves over time.

| Test | Topic passes if |
|------|-----------------|
| Can the user write a 1-sentence definition? | No — it's a question, comparison, or survey |
| Is it stable? | No — "state of X" evolves |
| Is the framing plural / landscape / debate? | Yes |

Examples: `local-llms-landscape`, `ai-memory-systems`, `mcp-evolution`, `mcp-debate`, `claude-code-workflows`, `agent-frameworks-comparison`, `compound-engineering-adoption`, `anthropic-vs-openai`.

**Discriminator rule**: Concept = the idea or entity itself (`compound-engineering` is a methodology; `anthropic` is a company). Topic = the conversation around it (`compound-engineering-adoption` is the discussion of who's adopting it, how, with what results; `anthropic-vs-openai` is the comparison).

**Tie-breaker**: when in doubt, start as Concept or Entity. Promote to Topic only when finding "and there are N variants of this, evolving over time."

### Source

A per-source synthesis. 1:1 with a raw file (Markdown or PDF). Combines agent-written content with the user's `My take` reflection (v5 — question and dive-deeper reflections route to `{wiki_root}/questions.md`, not to the source page). Sources are the **entry points** of the wiki — flexibility in their structure is required, not optional.

Naming: filename mirrors the raw counterpart's stem exactly, always with a `.md` extension (a PDF raw `Foo.pdf` yields source page `Foo.md`; the `raw:` frontmatter wikilinks `[[Foo.pdf]]`).

## Module extensions

The four page types above are the **base set**. Other sb-os modules MAY add their own page types, entity kinds, sections, and lint rules without editing the base wiki. The mechanism is registration + an additive merge at run start.

**Registration.** A module is activated by listing its name in `sb-os.json` → `wiki_extensions` (a list). When the field is absent or empty, no extension loads.

**Load — Step 0.** `/sb-wiki-ingest` and `/sb-wiki-lint` each run a **Step 0 — Load extensions** before their first native step. Step 0 reads `sb-os.json` → `wiki_extensions`; for each listed module it locates that module's `wiki-ext/` folder and MERGES its definition files — `page-types.ext.md`, `frontmatter-schemas.ext.md`, `section-menus.ext.md`, `lint-rules.ext.md` — into the active rule set for that run.

**Additive-only.** Extension page types, entity kinds, sections, and lint rules are ADDED to the base set — they NEVER replace or override a base definition.

**Base-unchanged.** When `wiki_extensions` is absent or empty, Step 0 is a no-op and the base four-type wiki behaves exactly as specified throughout this document.

**Domain-clean guard.** The base shared definition files (`page-types.md`, `frontmatter-schemas.md`, `section-menus.md`) are NEVER edited to add a module's content. Each module ships its additions in its own `wiki-ext/` folder; the base files carry only base behavior.

## Folder structure

```
3. Resources/knowledge-base/
├── purpose.md                    OPTIONAL regulatory file — focus lens for ingest (not a page; lint skips it)
├── questions.md                  OPTIONAL user open-questions queue (not a page; lint OWNS sweep/graduate/prune)
├── open-gaps.md                  lint-generated read-only aggregate of all open questions, both homes (not a page)
├── logs/                         actionable queue folder — split by entry type (lint excludes it from the wiki walk)
│   ├── topics.md                 candidate-topic queue
│   ├── mentions.md               candidate-mention queue (concept + entity, classification inline)
│   └── theses.md                 proposed-new-thesis + speculative-thesis-update queue
├── raw/
│   ├── {origin}/                 articles, podcasts, papers — by source origin
│   │   ├── {origin}.md           leaf index (factual, with Wiki column)
│   │   └── {date}-{slug}.md      verbatim source (immutable)
│   └── studies/                  study sessions: /tutor outputs + multi-source notes
│       ├── studies.md            leaf index
│       └── {date}-{slug}.md      raw study session content
└── wiki/
    ├── concepts/
    │   ├── concepts.md           leaf index
    │   └── {slug}.md
    ├── entities/
    │   ├── entities.md           leaf index
    │   └── {slug}.md
    ├── topics/
    │   ├── topics.md             leaf index
    │   └── {slug}.md
    └── sources/
        ├── {origin}/             mirrors raw/{origin}/
        │   ├── {origin}.md       leaf index (factual + My take column)
        │   └── {date}-{slug}.md
        └── studies/              mirrors raw/studies/
            ├── studies.md
            └── {date}-{slug}.md
```

Type folders are stable — `concepts/`, `entities/`, `topics/`, `sources/` never rename or reorganize. Per-kind subfolders WITHIN a type folder are an opt-in subdivision pattern proposed by lint when one kind grows large enough to warrant separation (see "Folder subdivision" below). Pre-subdivision, every type folder is flat.

`{wiki_root}/purpose.md` is an **optional regulatory file**, not a wiki page and not raw — the regulatory-layer twin of this locked schema (full spec in "Regulatory layer — purpose.md" below). It is a root-level sibling of `raw/`, `wiki/`, and `logs/`; lint never walks it (it lives outside the `wiki/` and `raw/` subtrees) and MUST skip it entirely. Absent → ingest behaves exactly as today.

`{wiki_root}/questions.md` is an **optional** user open-questions queue and `{wiki_root}/open-gaps.md` is its **lint-generated, read-only** cross-wiki aggregate — neither is a wiki page or raw (full spec in "Questions layer — questions.md" below). Both are root-level siblings of `raw/`, `wiki/`, `logs/`, and `purpose.md`; lint skips them from page/orphan/stub checks. Absent `questions.md` → ingest/lint behave exactly as today.

## Folder subdivision

Per-kind subfolders within a type folder are an opt-in pattern lint proposes when one kind crosses the proposal threshold. Subdivision is structural — pages physically move into the subfolder; wikilinks still resolve by filename (Obsidian Settings → Files & Links → "New link format" = Shortest path when possible — required, see README "Obsidian setup").

### Threshold

| Pages with one `kind:` value in a type folder | Lint behavior |
|-----------------------------------------------|---------------|
| <10 | Silent — no signal |
| ≥10 | PROPOSE — surface a SUBDIVISION PROPOSAL block in the lint report; user accepts/rejects per kind (threshold authority: `../workflows/shared/folder-structure.md` § "Stability Rules") |

Single floor, no warning intermediate. Subdivision remains opt-in per-kind at the proposal block — the user can defer indefinitely. A subfolder that turns out to be misfragmented can be reverted by manual move-back; lint surfaces low-population subfolders in subsequent passes if a kind contracts.

### Naming policy

Subfolder name defaults to the kind value. Apply a domain prefix ONLY when the kind term is generic across domains the vault might cover.

| Kind | Subfolder name | Rationale |
|------|----------------|-----------|
| `model` | `ai-models/` | Prefix — "models" is generic (statistical, financial, mental, ML). Vault covers AI today; prefix anticipates other domains. |
| `person` | `persons/` | No prefix — universal. |
| `company` | `organizations/` | No prefix; renamed for inclusivity (covers labs, institutions, governments). |
| `tool` | `tools/` | No prefix initially. Promote to `ai-tools/` if the vault later hosts non-AI tools and ambiguity surfaces. |
| `product` | `products/` | No prefix initially. |
| `benchmark` | `ai-benchmarks/` | Prefix — "benchmark" spans domains (sports, finance). Today AI-only. |
| `data-format` | `data-formats/` | No prefix — universal. |
| `inference-scaffold` (concept) | `inference-scaffolds/` | No prefix. |
| `automation-economics` (concept) | `automation-economics/` | No prefix; kind already plural-shaped — do NOT append `s`. |
| `cognitive-displacement` (concept) | `cognitive-displacements/` | No prefix. |
| `ai-collaboration-model` (concept) | `ai-collaboration-models/` | No prefix. |

The prefix decision is reversible. Lint may propose a rename when a non-prefixed kind acquires its first cross-domain page (e.g., a non-AI tool surfaces — propose `tools/` → `ai-tools/` + new domain folder).

### Subdivision artifacts (created on user accept)

| Artifact | Owner | Notes |
|----------|-------|-------|
| `wiki/{type}/{subfolder}/` directory | Lint | Created when first page moves in |
| `wiki/{type}/{subfolder}/{subfolder}.md` leaf index | Lint | Format `\| File \| Description \|`; same as type-folder leaf index |
| `wiki/{type}/{type}.md` parent index (rewritten) | Lint | Becomes a ROUTER — `\| Subfolder \| Holds \| Index \|` plus a `## Flat pages` section listing pages whose kind has not graduated to a subfolder. Format detail in `wiki/workflows/shared/index-formats.md` "Type-Folder Router Index" section |
| `wiki/{type}/CLAUDE.md` (created or updated) | Lint | Marker-block managed (`<!-- sb:start v=1 -->...<!-- sb:end -->`); inside markers lists subfolder routing rules; outside markers preserved as user content |
| Page moves | Lint | Each moved page's frontmatter `last-touched:` is updated; body unchanged |
| Inbound wikilinks | Lint | NOT rewritten — Obsidian's filename-based shortest-path resolution carries them across the move (required Obsidian config) |
| `lint` log entry | Lint | Standard `lint` H2 entry plus a `subdivision:` field listing each subfolder created and page count |

### Mixed structure is permitted

Within one type folder, some kinds may have graduated to subfolders while others remain flat. Example: `entities/ai-models/` and `entities/persons/` exist; pages with `kind: product` (count <10) stay at `entities/` root. Agents follow the parent CLAUDE.md routing table to decide.

### Ingest routing

When a stub fires for a kind that already has a subfolder, the stub MUST be created at `wiki/{type}/{subfolder}/{slug}.md`, NOT at `wiki/{type}/{slug}.md`. Ingest step 5 reads the parent `wiki/{type}/CLAUDE.md` marker-block routing table to resolve the destination. Kinds without a subfolder write to the type-folder root.

### Topics and sources are excluded

| Type folder | Subdivision policy |
|-------------|--------------------|
| `concepts/`, `entities/` | Subject to subdivision per the thresholds above |
| `topics/` | Subdivision deferred until ≥20 topic pages exist (the count is currently <5); review revisits when threshold approaches |
| `sources/` | Already subdivided by `origin/` — no further subdivision proposed by this rule |

## Asset folder

Local storage for images and other binary attachments referenced by source pages and wiki pages. The standard is **flat, single shared folder** at `{wiki_root}/raw/_assets/`. Karpathy-style workflow: after clipping a page or article into `raw/{origin}/`, the user runs Obsidian's core "Download attachments for current file" command (introduced in Obsidian 1.8.0, January 2025) to download all referenced external images locally. This keeps images viewable by LLMs on demand and immune to upstream URL rot.

### Path

`{wiki_root}/raw/_assets/` — single shared folder at the root of `raw/`. Flat. No per-source or per-note subfolders.

**Why flat.** Obsidian's core "Download attachments for current file" command follows the global "Default location for new attachments" setting and does NOT support per-file subfolder templates (`${filename}`, `${noteFileName}`, etc., as of Obsidian 1.9.6). Every download for every note lands in the same destination. The schema standardizes on that destination rather than fighting it.

### Maintained by

The user, via Obsidian. Configuration: Obsidian Settings → Files and links → "Default location for new attachments" → `raw/_assets`. The user binds the "Download attachments for current file" command to a hotkey (e.g. Ctrl+Shift+D) and runs it after each clip.

**Agents NEVER write to `raw/_assets/` unless the user explicitly directs them to handle specific files or images.** Neither `sb-wiki-ingest`, `sb-wiki-lint`, `sb-wiki-create-topic`, nor `sb-wiki-query` create, move, rename, or delete files inside `raw/_assets/` on their own initiative. The user's explicit mention of a file or image to handle IS the required direction (see `/sb-wiki-ingest` write-surface contract § "Ingest write rules — A10").

### Filenames

Whatever Obsidian writes — typically the original remote filename, or `Image 1.jpg` / `Image 2.jpg` patterns when filenames collide or are missing. (A known Obsidian 1.9.6 bug affects this renaming; fix pending upstream.) When `sb-wiki-ingest` moves a user-directed screenshot image into `raw/_assets/`, it MUST rename the image to a descriptive slug (NEVER preserve a name like "Captura de tela …").

### Referencing assets

Source pages (`raw/{origin}/*.md`) and wiki pages (`wiki/concepts/*.md`, `wiki/entities/*.md`, `wiki/topics/*.md`, `wiki/sources/*.md`) reference assets via standard Obsidian image embeds: `![[filename.png]]`, `![[filename.jpg]]`, etc. Obsidian resolves these via its global attachment search; no folder-relative path is required in the embed.

### Lint behavior — SKIP entirely

`raw/_assets/` is NOT a raw origin. It has no source pages, no wiki sources index, no leaf index. Lint MUST NOT:

| Behavior | Required state |
|----------|----------------|
| Create an index file at `raw/_assets/_assets.md` | NEVER. `raw/_assets/` is not an origin. |
| Walk `raw/_assets/` as part of raw-origin sweeps (step 7 of `/sb-wiki-lint`) | NEVER. Skip the directory entirely. |
| Count files inside `raw/_assets/` toward orphan detection (in or out) | NEVER. Assets are out of scope for orphan computation in BOTH directions — they are not eligible to be orphans, and image embeds inside them do not count as inbound links. |
| Enforce filename conventions inside `raw/_assets/` | NEVER (except the descriptive-slug rename rule applied by `sb-wiki-ingest` on user-directed moves — see above). |
| Treat `raw/_assets/` as an origin folder for any other purpose | NEVER. |

Workflows that walk `{wiki_root}/raw/` MUST explicitly exclude `raw/_assets/` from their iteration sets.

### Pre-existing exceptions

A vault MAY have legacy asset folders nested inside specific origin subdirectories (for example, `raw/mails/assets/{message-folder}/`, written historically by tools like `gmail-bridge` before this standard existed). These are NOT the standard going forward. New assets land in `{wiki_root}/raw/_assets/`. Existing legacy structures are user-owned, untouched by lint and any other sb-os component, and may be migrated to the standard at the user's discretion.

## Naming convention

| Element | Rule |
|---------|------|
| Wiki page filename | `lowercase-kebab.md` |
| Source page filename | mirrors raw counterpart **exactly**, including the date format the origin uses (`YYYY-MM-DD-slug.md` for `every/`, `YYYY_MM_DD-slug.md` for `mails/`, etc.). Agents do NOT normalize date formats. |
| Wikilinks anywhere | use the format that matches the target file's actual filename |
| Wikilinks in body | `[[slug.md]]` (with `.md` extension, matching existing index format) |
| Wikilinks in frontmatter | `"[[slug.md]]"` (quoted) |
| Type folder | disambiguates collisions; same slug may exist in `concepts/` and `entities/`. **Forbidden**: same slug in `concepts/` and `topics/` (if reclassified, the old slug retires) |

### Raw PDF title-conformance

A raw **PDF** filename MUST equal the kebab-slug of the paper's actual title (the title printed on the document; mirrored in the raw index `Title` column). Cryptic publisher/repository names (arXiv IDs like `2602.21012v1.pdf`, scan dumps like `kolmbook-eng-scan.pdf`) do NOT reflect the title and are renamed. Scope: PDF raw sources ONLY — markdown raw sources arrive title-named from the clipper and are exempt.

| Element | Rule |
|---------|------|
| Canonical PDF name | `{title-slug}.pdf` — no date prefix (papers are identified by title) |
| Mirrored source page | `{title-slug}.md` (existing mirror rule) |
| Title source | The title on the document; the raw index `Title` column is the maintained record lint compares against |
| Owner | `/sb-wiki-ingest` renames at ingest (step 1.5, before the source page exists); `/sb-wiki-lint` detects + proposes renames for already-ingested PDFs (step 7.6, user-gated) |
| Collision | If `{title-slug}.pdf` already exists, NEVER overwrite — the raw is a duplicate; ingest halts, lint flags it for merge/delete |
| Immutability | A rename changes the FILENAME only; raw content is never edited. This is the sole permitted mutation of a raw file |

**Title-slug algorithm.** (1) Lowercase the title. (2) Replace each run of whitespace and `+ / : – —` with a single `-`. (3) Remove `? ! , . " ' ( ) [ ]`. (4) Collapse consecutive `-`; trim leading/trailing `-`. Acronyms lowercase (`AI` → `ai`). Example: `International AI Safety Report 2026` → `international-ai-safety-report-2026`.

## Frontmatter schemas

### Common (all types)
```yaml
---
type: concept | entity | topic | source
created: YYYY-MM-DD
last-touched: YYYY-MM-DD
related:
  - "[[other-page.md]]"
tags: [<type>]              # MUST include the page's `type:` value; further tags optional, free-form
---
```

**Type tag (mandatory).** Every wiki page carries its `type:` value as an entry in `tags:` (a concept page carries `concept`, a thesis page `thesis`, an index file `index`, …). Rationale: Obsidian's graph-view groups color nodes by `tag:` but cannot key on an arbitrary frontmatter field — the type tag makes the page taxonomy visible and colorable in the graph. Page-creating workflows write it at birth; `/sb-wiki-lint` enforces it everywhere via the deterministic type-tag sync (auto-applied, see `/sb-wiki-lint` step 7). Additional user tags are free-form and always preserved — the sync only appends, never removes.

### Concept pages add
```yaml
kind: <free-form string>    # e.g., methodology, pattern, principle, protocol, theory, algorithm — no predefined enum
```
Rationale: kinds don't drive schema behavior (no kind-conditional sections, no validation), so the enum is open.

### Entity pages add
```yaml
kind: tool | person | company | product | model | benchmark | data-format
```
Use case: Dataview filtering ("all tools" / "all people I follow"). Predefined because the enum is small and stable. Naming policy: each enum value MUST pass the blind-reader test — a reader with zero context understands what kind of thing the value names. Generic terms (`pattern`, `spec`, `dynamic`) FAIL this test and accumulate heterogeneous entries; specific terms (`benchmark`, `data-format`) succeed. New values are added only when the wiki acquires multiple ill-fitting occupants of an existing slot AND the proposed name passes the blind-reader test. Future additions: `protocol` is reserved for MCP/HTTP/gRPC when the first one ingests.

### Source pages add
```yaml
raw: "[[YYYY-MM-DD-slug.md]]"
url: https://...
author: "..."
```
Rationale: `read-date` is not used — `created` covers the same intent (ingest = read in practice). Add a separate field only if a "read but not yet ingested" workflow surfaces.

### Topic pages
No additional frontmatter. While unpromoted, a topic candidate lives in `logs/topics.md` as a `candidate-topic` entry; once the page exists, that entry is removed (resolution = page exists).

### `type: index` — agent-owned index files

`type: index` is the frontmatter value for every agent-maintained index file: wiki leaf indexes (`concepts.md`, `entities.md`, `topics.md`, per-kind subfolder indexes), type-folder router indexes, and wiki sources origin indexes (`wiki/sources/{origin}/{origin}.md`). It is NOT a synthesis page type — index files are excluded from stub detection, orphan detection, and page-type section checks exactly as before. Index files carry the minimal frontmatter `type: index` + `tags: [index]` (the type-tag rule above applies — `index` is the tag); `created`/`related` are not required. `/sb-wiki-lint`'s type-tag sync adds this frontmatter to any index file missing it (an index file is deterministically recognizable: filename stem equals its parent directory name).

### `type: purpose` — non-page regulatory value

`type: purpose` is a valid frontmatter value reserved for the single regulatory file `{wiki_root}/purpose.md` (see "Regulatory layer — purpose.md"). It is **NOT a page type** and MUST NOT be added to the page-type enum (`concept | entity | topic | source`). A file carrying `type: purpose` is excluded from page-type checks, leaf indexes, and orphan detection — it is regulatory configuration, not synthesis. This is base behavior, registered identically in the runtime shared file `wiki/workflows/shared/frontmatter-schemas.md` (not a `wiki-ext`).

### `type: questions` / `type: questions-index` — non-page values

`type: questions` is reserved for the single file `{wiki_root}/questions.md`, and `type: questions-index` for the single lint-generated file `{wiki_root}/open-gaps.md` (see "Questions layer — questions.md"). Neither is a page type — do NOT add either to the page-type enum (`concept | entity | topic | source`). A file carrying either value is excluded from page-type checks, leaf indexes, and orphan detection — it is queue/aggregate data, not synthesis. This is base behavior, registered identically in the runtime shared file `wiki/workflows/shared/frontmatter-schemas.md` (not a `wiki-ext`).

### Status field — DEFERRED

Stub-state is detected structurally (see Stub policy). No `status:` frontmatter field at v1. Revisit only if lint surfaces a real need after the first 5–10 ingests.

### `sources:` field — NOT USED

Provenance lives in the Sources section at the end of body (footnote definitions). Lint can derive a sources list at query time if needed.

## Section structure (per type)

Section structure is **flexible** — required sections are marked, optional sections are selected by the agent based on source signal and page kind. Empty user-half sections on Source pages do not count toward stub-state.

### Concept page

Required: `Definition`, `Sources`.

Optional menu:

| Section | When to include |
|---------|-----------------|
| `How it works` | Mechanics or process — skip for purely abstract concepts |
| `Why it matters` | Significance in current AI/PM/finance landscape — usually included |
| `Open variants / debates` | Only when contradictions or evolution detected; cites them |
| `Related` | Wikilinks to entities + topics; usually included |

Definition is 1–2 sentence factual definition (Wikipedia-style); other sections agent-written, neutral.

### Entity page

Required: `What it is`, `Sources`.

Optional menu (agent picks per `kind:`):

| Section | When to include |
|---------|-----------------|
| `Notable facts` | Bulleted facts from sources — usually included |
| `How it works` | Mechanics — for tools, products, models, protocols |
| `History` | For long-lived entities (people, companies); pivotal moments |
| `Architecture` | For tools, models, products — technical structure |
| `Variants` | For products/models with multiple versions |
| `How I use it / Why it matters to me` | For tools the user actively uses |
| `Related` | Wikilinks; usually included |

Wikipedia-style entities (people, companies, models) may need a wider section set than tool entities — the menu accommodates both.

### Topic page

Required: `Scope`, `Sources`.

Optional menu (agent picks per topic shape — debate / comparison / landscape / decision-frame / evolution):

| Section | When to include |
|---------|-----------------|
| `Key positions / Angles` | Debate or comparison topics |
| `Key concepts` | Wikilinks to concepts; usually included |
| `Key entities` | Wikilinks to entities; usually included |
| `Open questions` | What's unresolved; usually included |
| `Consequences` | Downstream effects of the positions |
| `Timeline` | Evolution-shaped topics — chronological pivots |
| `Stakeholders` | Decision-frame topics — who's affected |
| `Decision criteria` | Decision-frame topics — how positions are evaluated |

### Source page

Required: `Sources`.

**Agent half** — optional menu (agent picks per source kind: article / paper / podcast / study / repo):

| Section | When to include |
|---------|-----------------|
| `Substance` | Paraphrased prose synthesis of the source — usually included |
| `Notable quotes` | Verbatim quotations only — kept distinct from `Substance` for MECE (paraphrase vs. verbatim) |
| `Connections` | Wiki pages this updates / contradicts; each connection states *why* (one clause); usually included |
| `Methodology` | For studies, papers — the method, dataset, sample, limitations |
| `Counterpoints` | Where the source disagrees with itself or with prior wiki claims |

**User half** (separated by `---`):

| Section | Owner |
|---------|-------|
| `My take` | The user — why it mattered, what surprised, agreements/disagreements |

`Open questions` and `Dive deeper` are NOT source-page sections (v5 — questions-layer). Question content from Stage-2 reflection routes to `{wiki_root}/questions.md` instead (see "Questions layer — questions.md"). The **topic** `Open questions` menu is unchanged.

The `---` separators visually mark agent-half / user-half / sources.

The `My take` user-half section is created as an **empty shell** (heading only, no content) by ingest step 2 — not stub-flagged when empty (this is the page's natural post-ingest state). The user fills it via Stage 2 of the ingest checkpoint OR later in Obsidian editor.

## Citation format

| Layer | Format | Maintained by |
|-------|--------|---------------|
| Inline in body | `[^N]` at point of claim | Agent (during ingest) |
| Sources section | `[^N]: [[YYYY-MM-DD-slug.md]]` (footnote defs ARE wikilinks; Obsidian indexes them in the graph) | Agent (during ingest, renumbered by lint) |
| Frontmatter `sources:` | NOT USED | — |

The user never writes citations manually. Renumbering on edit is agent-handled.

**Footnote rules:**
- Citation targets are wiki pages, NEVER raw files. Concept, entity, and topic pages cite **source pages** (`wiki/sources/`). Raw files are referenced ONLY by their 1:1 source page (the `raw:` frontmatter field and that source page's own Sources footnote).
- One footnote per source, never merged. Multi-source claims get multiple markers on the same sentence: `...claim X[^1][^2][^3]`.
- Lint rebuilds the Sources section by reading inline `[^N]` markers. If the user manually added prose context within a footnote definition (e.g., `[^1]: [[file.md]] — note: this is the original`), lint preserves user prose; only renumbers.
- Stale-definition removal is REPORT-ONLY — lint NEVER auto-removes a footnote definition. A def with no inline reference is mechanically indistinguishable from stub provenance (stubs are born with defs and no inline markers; later ingests append inline-cited sections while the original def stays unreferenced), and auto-removal strips the page's only graph edge to that source. Lint reports unreferenced defs for hand-reconciliation. A page whose definitions have ZERO inline markers is the ingest-built stub-provenance shape — not a finding, never touched. Set mismatches (inline marker without definition, duplicate definitions) are content defects — reported, never auto-repaired.

## Wiki sources index format

Each `wiki/sources/{origin}/{origin}.md` index:

```markdown
| File | What it says | My take |
|------|--------------|---------|
| [[YYYY-MM-DD-slug.md]] | 1-sentence factual summary (≤280 chars). | 1-sentence opinion: why I cared. |
```

- `What it says` is agent-written during ingest (factual derivative of the source's `Substance` section).
- `My take` is **agent-derived from the source page's `My take` section** during ingest and refreshed during lint. **The source page is canonical; the index entry is derived. The user never writes the index manually.**
- The `My take` cell encodes one of three explicit states. **Blank is BANNED** as a state marker — every row carries one of the three values below.
- Stale-by-7d acceptable for skim purpose; agents may fall back to reading the source page if deeper signal is needed.

### `My take` cell — three states (NEVER blank)

The `My take` cell distinguishes **pre-reflect** (the user has not yet been prompted, or skipped the prompt — action pending) from **post-reflect-empty** (the user reflected and intentionally recorded no take — final). Blank cannot encode this distinction; explicit tokens can.

| State | Token in cell | Meaning | Source page state |
|-------|---------------|---------|-------------------|
| Pre-reflect | `pending` | Stage 2 was skipped, ignored, or never reached — the source page's `My take` section is an empty shell awaiting user action. | `My take` heading present, body empty |
| Post-reflect-empty | `—` (em-dash, U+2014) | Stage 2 ran and the user explicitly routed reflection content to `questions.md` without recording a take. Finalized. | `My take` heading present, body empty while Stage 2 captured one or more `questions.md` entries (`seeded-by:` this source) |
| Reflected | 1-sentence opinion derived from the source page's `My take` section (≤280 chars; truncate with ellipsis if longer). Table-safe: wikilinks flattened to display text BEFORE truncation, remaining literal `\|` escaped — the cell must never split the 3-column row | The user filled `My take` on the source page. Index cell mirrors the take. | `My take` heading present, body has substantive content |

**Rationale.** The two empty states have different downstream behaviors (see below) and different remediations from the user's standpoint. Blank conflates them. Two human-readable, typographically distinct tokens preserve the distinction at a glance and let lint detect each state programmatically. `pending` was chosen for its action-pending semantics (a verb-shaped keyword the user reads as "needs me to act"); `—` (em-dash) was chosen for its long-standing convention as a typographic null marker (the user reads it as "nothing here, intentionally").

### Lint and ingest behavior per state

| State | Written by | When | Lint behavior |
|-------|-----------|------|---------------|
| `pending` | `sb-wiki-ingest` step 8 (initial) AND step 11 if Stage 2 is skipped, ignored, or receives no routed content | At end of ingest when no take was captured | The 7-day staleness rule applies — lint may re-sync (no-op if source page's `My take` body is still empty) |
| `—` | `sb-wiki-ingest` step 11 if Stage 2 routes reflection content to `questions.md` while `My take` remains empty — see Stage 2 finalization rule below | At end of Stage 2 | Final. The 7-day staleness rule does NOT apply — `—` rows do NOT age out. Lint preserves `—` on every pass (no-op). |
| Reflected (1-sentence preview) | `sb-wiki-ingest` step 11 if the user filled `My take`; refreshed by `sb-wiki-lint` step 6 on every run | At end of Stage 2 / on every lint pass | Re-sync from the source page's `My take` section on every run, preserving the three-state distinction (if the source page's `My take` body is now empty after previously having content, the lint downgrades the cell to `—` only if a `pending` state cannot be inferred — see "Re-sync algorithm" below) |

**Stage 2 finalization rule.** The `—` token is written ONLY when the user explicitly engaged Stage 2 and routed reflection content to `questions.md` (a question / dive-deeper captured as a `questions.md` entry) while leaving `My take` empty. If the user answered `n`, ignored the prompt, or sent an unrelated next command, the cell stays `pending` — the user did not produce a finalization signal.

**Re-sync algorithm (lint step 6).** For each row:
- If the source page's `My take` section has substantive content → write the 1-sentence preview (overwriting the prior cell value).
- If the source page's `My take` section is empty AND the cell currently reads `—` → preserve `—` (already finalized).
- If the source page's `My take` section is empty AND the cell currently reads `pending` → preserve `pending`.
- If the source page's `My take` section is empty AND the cell currently reads anything else (legacy blank, stray content, etc.) → write `pending` (default to action-pending; safer to over-prompt the user than to over-finalize).

The raw index (`raw/{origin}/{origin}.md`) keeps its existing format with `Wiki` column — factual only, no opinion. Raw indexes are created and maintained by lint (see `/sb-wiki-lint`).

## Topic creation rules

**Agent NEVER auto-creates topic pages.** All topic creation flows through the `sb-wiki-create-topic` skill — agent-invokable mid-ingest when the user accepts a proposed topic, AND auto-discovered by Claude Code when the user later expresses intent to create or promote a topic (e.g., "create a topic for X", "promote the mcp-debate candidate"). The skill has no slash command — invocation is intent-driven.

The agent detects 3 candidate-topic triggers and:
1. Logs them in `logs/topics.md` as `candidate-topic` H2 entries.
2. Surfaces them inline at the Stage 1 ingest checkpoint as **PROPOSED TOPICS** — the user can accept-now (agent invokes `sb-wiki-create-topic` skill mid-run) or defer (the candidate-topic log entry persists; the user may promote later by expressing intent, which auto-fires the `sb-wiki-create-topic` skill).

### Existing topic updates (ingest)

Topic pages are plural-framed and accrete substance over time as new sources land in their scope. During ingest, the agent detects which existing topic pages this source plausibly extends, and proposes those updates at Stage 1 alongside PROPOSED TOPICS. The user accepts/rejects per topic; the agent NEVER auto-appends to a topic page without explicit acceptance.

**Relevance detection — two tiers.** A source is a candidate update for an existing topic page in either the FIRM tier (mechanical wikilink/slug match — high confidence) or the SPECULATIVE tier (new-stub conceptual fit — low confidence, capped, default-reject).

**Firm tier.** Fires when AT LEAST ONE of these mechanical matches holds:

| Match | Definition |
|-------|------------|
| Key-concept/entity overlap | The source's `Substance` bullets wikilink ≥1 page that the topic page wikilinks in its `Key concepts` or `Key entities` section |
| Related-frontmatter overlap | The source's substance entities/concepts overlap (≥1) with the topic's `related:` frontmatter wikilinks |
| Topic slug match | The topic slug appears in the source title OR in a `Substance` bullet |

Firm-tier detection is mechanical — exact wikilink comparison or exact slug match. Semantic-only matches do NOT fire firm.

**Firm-tier read-shortlist (I/O rule — detection semantics unchanged).** Coverage MUST stay total, but the agent MUST NOT read every topic page to achieve it. Detect candidates deterministically without page reads: (a) topic-slug matches from a directory listing of `wiki/topics/` filenames; (b) wikilink-overlap candidates from ONE `grep`/`ripgrep` alternation pass over `wiki/topics/` for the source's substance-wikilinked page filenames — both wikilink match types (`Key concepts`/`Key entities` sections AND `related:` frontmatter) manifest as that filename text inside the topic file. Then READ ONLY the union of matched pages to confirm which mechanical condition holds, dropping grep false-positives (a wikilink hit outside the qualifying locations). The semantic tier is FORBIDDEN as a firm-tier shortlist: a top-k cutoff can silently exclude a topic with a genuine mechanical match, and silent mode auto-applies firm fires — that safety argument rests on total mechanical coverage (see "Mechanical-fire invariant", § "Retrieval tiers — hybrid search").

**Speculative tier (new-stub conceptual fit).** Fires when ALL of these hold:

| Condition | Definition |
|-----------|------------|
| New stub | Candidate is a `stub-candidates` entry created in THIS ingest run — never an existing page |
| Token overlap | The stub's preamble (1–2 sentence factual sentence written at step 5) shares ≥2 substantive tokens with the topic's `Scope` text. Tokenization: lowercase, strip stopwords (`the/a/an/of/for/in/on/and/or/to/is/are/with/by/that/this/it/as`), preserve kebab-case as a single token (`marginal-returns-to-intelligence` matches `marginal returns` if both tokens appear in scope). Scope text comes from the topics leaf index `Scope` cells (`wiki/topics/topics.md`) — ONE read covers every topic; a topic missing its index row is read directly (its `Scope` section) |
| Semantic fire (additive, tier-gated) | When the semantic tier is available (§ "Retrieval tiers — hybrid search"), a (stub, topic) pair ALSO qualifies when the stub's probe call (one per stub-candidate, shared with the near-duplicate probe — see Stub policy § "Near-duplicate probe") returns that topic page among its results. Tier unavailable → token-overlap fires only (the floor) |
| Cap | Maximum 2 speculative fires per ingest. If >2 candidates qualify, rank token fires above semantic-only fires; among token fires by overlap count (descending); among semantic-only fires by helper score (descending). Keep top 2, drop the rest silently — re-detected on future ingests of related sources (no log entry) |
| Dedupe | If a topic already fires firm for this source, suppress its speculative fire (firm wins) — applies to token AND semantic fires |

Speculative-tier token fires are computed (not LLM-judged); semantic fires are tier-gated helper results. Both are heuristic in confidence. The tier is rendered in a SEPARATE block at Stage 1 (`SPECULATIVE TOPIC UPDATES (low-confidence, default reject)`) and defaults to reject — same default as firm, but the separation signals confidence to the user. Each row's overlap cell names its signal: `tokens: <t1>, <t2>` or `semantic: <score>`.

**Update behavior on user accept (append-only).** The agent updates the topic page following the same append-only protection used for entity/concept pages:

| Operation | Detail |
|-----------|--------|
| Add citation | Append `[^N]: [[<source-page-filename>]]` to the topic's `Sources` section (renumber locally; lint normalizes globally) |
| Append section entry | Add ONE bullet under the topic-shape-appropriate section (`Key positions / Angles` for debate-shaped topics; `Timeline` for evolution-shaped; otherwise `Key concepts` / `Key entities` if the source introduces a new wikilinkable page; otherwise no body bullet — citation-only update) with inline `[^N]` marker |
| Bump frontmatter | Update `last-touched: <today>` |
| NEVER overwrite | Existing prose, `Scope`, position bullets, or `Open questions` content stays untouched. Append-only, per stub-policy "Append-Only Protection" |

**No log entry.** Topic updates are recorded by the page content itself (append-only edits). The log is an actionable queue, not an accretion history.

| Trigger | Structural anchor | Status |
|---------|-------------------|--------|
| **Contradiction** | Agent extracts claims from the new source. For each existing wiki page on the same entity/concept, compares claims. To fire: (a) **quote both claims verbatim** in the candidate log entry, (b) classify scope as `same-scope-opposing` / `different-scope` / `temporal-shift` / `partial-overlap`. **Only `same-scope-opposing` fires** a `candidate-topic` and a `> [!warning] Disputed` callout on the affected page. Other classifications log informationally (no candidate). | Active day 1 |
| **Evolution** | Two or more sources with different read/publish dates make divergent claims about the same concept/entity. Single-source temporal phrases ("future of X", "next-gen") alone do **NOT** fire. Both required: ≥2 dated sources AND divergent claims. | Active day 1 |
| **Cross-application** | Phrase pattern "X for Y" / "X-powered Y" / "using X to do Y" where BOTH X and Y are existing wiki pages (**exact wikilink match required**, no fuzzy semantic matching), AND ≥2 sources reference the same X-for-Y pairing | Defined; expected low fire-rate until wiki has ≥10 pages with cross-pollination |

When Contradiction fires `same-scope-opposing`, the agent ALSO adds a `> [!warning] Disputed` callout to the affected concept/entity page citing both sources, BEFORE the user promotes the candidate.

**Studies workflow note**: studies (`/tutor` outputs and multi-source notes) flow `raw/studies/` → source page → distilled into entity/concept/topic pages by `/sb-wiki-ingest`. **A single study source typically distills into multiple wiki page types in one ingest** — e.g., a `/tutor` session on graph databases may produce a Concept page (`knowledge-graphs.md`), an Entity page (`cypher.md`), and a candidate-topic if cross-application emerges (`knowledge-graphs-for-agent-memory`). There is no separate "user-study trigger" — the 3 triggers above already detect patterns within and across study sources.

## Stub policy

### Page granularity (apply BEFORE stub creation, at ingest step 3)

Cluster candidate names into page-level units before deciding how many stubs to create. The mechanical fire rule operates on the cluster representative, NOT on every constituent name. Bullet writers in step 2 must name entities/concepts at page-cluster granularity — sub-cluster names appear in prose without wikilinks.

Decision tests (apply in order, per pair of candidates):

| # | Test | If YES | If NO |
|---|------|--------|-------|
| 1 | Are they instances of the same family/series differing only in a parameter (version, size, generation, edition, phase, period, era)? | ONE parent page covering variants. A variant gets its own stub ONLY when the source treats it as a standalone subject (≥1 dedicated paragraph or named section). | Continue to test 2. |
| 2 | Is one a whole/system and the other a property/parameter/part that cannot stand independently of the whole? | ONE page (property becomes a section of the whole). | Continue to test 3. |
| 3 | Are they co-members of a group (siblings) co-mentioned but not co-substantive in this source? | Split by collective identity: a named collective → ONE Concept/Topic (or Entity if a named org); an ad-hoc co-mention set → individual candidates, NEVER a synthetic group slug. Per-member stub only with standalone treatment. | Continue to test 4. |
| 4 | Is one a producer/maintainer/author and the other its product/work? | TWO pages — distinct identities. | TWO pages — independent. |

The clustering decision is the AGENT'S RESPONSIBILITY upstream of mechanical fire. Step 2 substance-bullet writers must respect the cluster set: name only page-level entities/concepts; sub-cluster names go in prose without wikilinks.

Domain-neutral examples and the operational reference: `wiki/workflows/shared/stub-policy.md` § "Page Granularity".

### Stub creation (ingest)

The agent auto-creates a stub Concept or Entity page when the cluster representative appears in EITHER of the two mechanical branches OR fires the discretionary branches:

1. **A `Substance` bullet** (the agent's own output from step 2) — MECHANICAL fire on the cluster representative.
2. **Source title/headline** — fires only when the title name ALSO appears in a `Substance` bullet (see "Title-branch rule" below). Title-only names go to discretion.
3. **An extracted Notable Quote** — DISCRETIONARY (see "Notable Quote stub creation" below).

If none of the three branches fire, log a `candidate-mention` in `logs/mentions.md` for periodic review by lint. Do NOT create a page.

#### Near-duplicate probe (non-skippable)

Exact-slug existence is checked mechanically before any stub is created (unchanged — a slug that exists routes to the update path). The probe MUST ALSO check ACROSS ALL KINDS and the `wiki/theses/` namespace (vault-wide filename uniqueness) — a slug must not already exist in a sibling type folder (`concepts/` vs `entities/` is allowed per the naming convention, but `concepts/` vs `topics/` is forbidden) OR as a thesis page filename. **Stub routing MUST validate against the kind-routing table** (per schema § "Folder subdivision" naming policy) BEFORE writing — catching a `kind: tool` landing in `organizations/`, a financial benchmark landing in `ai-benchmarks/`, etc. Both the probe and routing-validation are NON-SKIPPABLE gates: every stub-candidate MUST pass both before creation.

When the semantic tier is available (§ "Retrieval tiers — hybrid search"), the agent ADDITIONALLY probes each stub-candidate for an existing page covering the SAME referent under a DIFFERENT slug: ONE helper call per stub-candidate — `search "<candidate name> — <planned preamble>" --type concept,entity,topic --k 8`. The call's topic hits feed the speculative tier (§ "Existing topic updates") — one call serves both probes. Concept/entity hits trigger the same-referent test:

| Test outcome | Action |
|--------------|--------|
| The hit denotes the SAME thing — synonym, alias, spelling/formatting variant (e.g. `llm-as-judge` vs `llm-as-a-judge`) | Do NOT create the stub. Reroute the candidate to the `existing-pages` set — the source's perspective lands on the existing page via the step-4 append-only update path |
| The hit is merely RELATED (parent, sibling, instance, neighbor) OR same-referent is UNCERTAIN | Create the stub (baseline behavior). When in doubt, create — a duplicate stub is lint-recoverable; a wrong merge misroutes content onto the wrong page |

Tier unavailable → exact-slug check + cross-kind + theses-namespace check + routing-validation only (the floor).

#### Title-branch rule

The source title alone does NOT compel a stub. A title hook ("One X and you...", "How Y changed everything") often names something the source merely USES rather than discusses. Apply the relevance heuristic for any name that appears ONLY in the title (not in any `Substance` bullet):

| Question | If YES | If NO |
|----------|--------|-------|
| Would this stub plausibly become a real concept/entity page given the source's actual content (recurrence, framing weight, the user's known interests)? | Create the stub | Log `candidate-mention` instead |

Names appearing in BOTH the title AND a `Substance` bullet remain mechanical fire — the bullet branch carries them.

#### Notable Quote stub creation (agent discretion)

The Notable-Quote branch is **agent discretion**, NOT mechanical extraction. A passing mention surfaced inside a Notable Quote does NOT compel a stub.

For each entity/concept name surfaced ONLY by a Notable Quote (i.e., not by source title and not by a `Substance` bullet), the agent applies the relevance heuristic before creating a stub:

| Question | If YES | If NO |
|----------|--------|-------|
| Would this stub plausibly become a real concept/entity page given the source context (recurrence, framing weight, the user's known interests)? | Create the stub | Log `candidate-mention` instead |

**Trade-off (state explicitly).** Discretion risks under-stubbing — a stub that would have grown into a real page is deferred to a `candidate-mention`. Mechanical extraction risks bloat — every name dropped inside a quote becomes a shallow stub that never matures.

**Discretion wins** because lint can later catch missing entity references via broken-wikilink detection (an under-stubbed name surfaces the moment another page tries to link to it), but lint cannot easily prune mass-produced shallow stubs without false positives.

The `Substance`-bullet branch remains mechanical — those artifacts are short, agent-curated, and high-signal by construction (and now subject to the page-granularity heuristic upstream). The Title and Notable Quote branches carry discretion.

**Reference example.** At p6-6 of the sb-wiki-build plan, 5 stubs were created from Notable Quotes where 3 were warranted. Agent discretion would have prevented the 2 shallow stubs that the lint then had to flag as orphaned.

### Stub state (lint detection)

A page is detected as a stub structurally:

| Condition | Stub? |
|-----------|-------|
| Frontmatter + brief preamble (≤2 sentences) + Sources section, but main content sections empty or absent | YES |
| At least 1 main content section has substantive content (>50 words) | NO |

By construction, stubs created via ingest match the stub-state definition. Lint flags stubs aged >30 days.

Note: empty user-half sections on Source pages do NOT count toward stub-state — Source pages are stubs only if their agent-half (`Substance` / `Notable quotes` / `Connections`) is empty.

## Regulatory layer — purpose.md

`{wiki_root}/purpose.md` is an **optional** regulatory file that gives `/sb-wiki-ingest` a **focus lens**: it biases how deeply a source is synthesized, which entities/concepts become pages, and how topics are suggested — toward the user's stated focus areas — and **flags** sources that match nothing. It is the regulatory-layer twin of this locked schema. It never drops content and never alters any deterministic rule.

### Artifact, location, optionality

| Property | Rule |
|----------|------|
| Location | `{wiki_root}/purpose.md` — root-level sibling of `raw/`, `wiki/`, `logs/`. NOT a wiki page (not under `wiki/`), NOT raw. |
| Frontmatter | `type: purpose` — a non-page regulatory value (excluded from page-type checks, indexes, orphan detection; see "Frontmatter schemas" § `type: purpose`). |
| Optionality | Absent → lens OFF → ingest behaves **exactly** as today. Mirrors the `wiki_extensions` Step 0 no-op contract. |
| Malformed | Warn and proceed lens-OFF; NEVER abort the ingest. |
| Ownership | Vault content (personal). Only the *mechanism* that reads it ships in sb-os. Lint never edits it and MUST skip it entirely. |

### Format

```markdown
---
type: purpose
last-touched: YYYY-MM-DD
---

# Wiki Purpose

## Mission
1–3 sentences: why this wiki exists and the lens sources are read through.

## Focus areas
Subjects to treat with MORE depth and bias topic/stub suggestions toward.
- **<area name>** — <one-line scope note>
- ...
(Optional tiering via `### Primary` / `### Secondary` subheadings.)

## Down-weight signals
Source shapes/subjects to treat with LESS discretionary depth — never dropped.
- <signal> — <why>

## Quality bar
Editorial preferences applied during synthesis
(e.g., favor primary sources; mechanism over hype; prefer dated/sourced claims).

## Out of purpose
Subjects that match nothing here → trigger the Stage-1 off-purpose flag.
(May be left implicit: "anything not in Focus areas.")
```

### Parsing contract

| Section | Lens use |
|---------|----------|
| `## Focus areas` | The match set for classification (in-focus detection). |
| `## Down-weight signals` | Hints that push a source toward the peripheral band. |
| `## Quality bar` | Synthesis preferences applied while writing the source page. Does NOT influence index `What it says` phrasing (see Index neutrality guard). |
| `## Out of purpose` | Optional explicit off-purpose list; if absent, off-purpose = "matches no Focus area". |

### Classification model

At the open of ingest Step 2 (raw content from Step 1 + parsed purpose from Step 0.5 both available), classify the source into exactly **one** band, keying off the **primary** subject — not incidental mentions (same discipline as the existing Tecer-relevance axes):

| Band | Definition | Effect |
|------|------------|--------|
| **in-focus** | Primary subject matches ≥1 `Focus area` | Dial discretionary treatment **UP** (richer) |
| **peripheral** | Not a focus match, but not noise (or hits a `Down-weight signal`) | Baseline; lean terse on discretionary extras — "down-weight, never below baseline" |
| **off-purpose** | Matches **no** `Focus area` (or appears in `Out of purpose`) | Baseline treatment **+ Stage-1 flag**; if the user proceeds, treat as peripheral |

Registered `wiki_extensions` (e.g. `finance`) add page types (`thesis`, `decision`) and their own ingest triggers. Classification applies to extension page types too (key off primary subject); extension-registered triggers are **mechanical — untouched** by the lens, exactly like the base triggers. A `purpose.md` SHOULD cover active-extension domains so extension sources are not spuriously flagged off-purpose.

### Core principle — discretionary-only modulation

The lens touches **only the surfaces ingest already resolves by agent judgment**. Every mechanical/deterministic rule's **logic** is untouched — though its *output* may still shift when a modulated discretionary input feeds it ("untouched branch" ≠ "identical output"; bounded by determinism guarantees #2/#4 below). This is what makes the feature safe in the locked schema.

| Mechanical — **UNTOUCHED** by the lens | Discretionary — **modulated** by the lens |
|----------------------------------------|--------------------------------------------|
| Substance-bullet stub branch (fires on cluster-representative match) | Depth/granularity of the `Substance` section |
| Candidate-topic trigger **detection** (contradiction / evolution / cross-application; **+ extension triggers** e.g. candidate-thesis) | Which optional source sections to include (Notable quotes / Methodology / Counterpoints) |
| Citation rules (`[^N]`, one footnote per source) | Title-only & Notable-Quote stub branches (already "agent discretion" today) |
| Append-only protection | Cluster-granularity choices — **dial-UP only** (in-focus); peripheral floored at baseline per guarantee #4 |
| Index updates (raw, sources, concepts, entities, topics) | Speculative topic-tier **ranking** (within the existing top-2 cap) |
| Log entry shapes; Stage-2 reflection | Stage-1 **presentation** (classification line + off-purpose flag) |

> **Index neutrality guard (the `What it says` edge case).** The wiki sources index `What it says` cell is LLM-derived from the (lens-modulated) `Substance` section, so a dialed-up in-focus Substance could bleed editorial framing into the index. Guard: write `What it says` **band-neutral** — the same factual core claim regardless of band. The index *update mechanism* stays mechanical/untouched; only the source-cell phrasing carries this neutrality rule. `Quality bar` does NOT influence index phrasing.

### Per-step modulation

Lens hooks live at ingest Steps **2, 5, 3·7b, 10**; Step 6 trigger-detection is **untouched**. (Step-number key below maps these to `/sb-wiki-ingest`.)

| Ingest step | Lens effect | in-focus | peripheral | off-purpose |
|-------------|-------------|----------|------------|-------------|
| **0.5 — Load purpose** *(new)* | Read + parse `{wiki_root}/purpose.md`. Absent → lens OFF (flow identical to today). Malformed → warn, proceed lens-OFF. | — | — | — |
| **2 open — Classify** | Compute band from raw vs `Focus areas`. | tag in-focus | tag peripheral | tag off-purpose |
| **2 — `Substance` depth** *(discretionary)* | Depth dial. | finer granularity, fuller Substance; include warranted optional sections; apply `Quality bar` | baseline granularity; optional sections only if clearly warranted | baseline (becomes peripheral once user proceeds) |
| **5 — Substance-bullet stub branch** *(mechanical)* | **Untouched** — fires exactly as today. | as today | as today | as today |
| **5 — Title-only & Notable-Quote stub branches** *(discretionary)* | Bias the existing relevance heuristic. | lean **fire**; finer cluster granularity | lean **demote** to `candidate-mention` | as peripheral |
| **6 — Trigger detection** *(mechanical)* | **Untouched** — all fires recorded as today. | as today | as today | as today |
| **3·7b — Speculative topic ranking** *(discretionary)* | Re-rank within the existing top-2 cap by focus overlap. | focus overlap orders / breaks ties | — | — |
| **10 — Trigger presentation** *(discretionary)* | Priority annotation only; **no fire suppressed**. | surfaced first, tagged `focus` | surfaced, untagged | surfaced, untagged |
| **10 — Stage 1 checkpoint** *(discretionary)* | Add classification line; off-purpose flag. | `purpose: in-focus` | `purpose: peripheral` | `⚠ off-purpose` banner + proceed/abort |
| **4, 4.5, 7, 8, 9, 11** | **Untouched.** | — | — | — |

**Step-number key (maps to `/sb-wiki-ingest`).** Depth dial + classification = **Step 2** (Write source page). Stub branches (Substance-bullet mechanical; Title-only / Notable-Quote discretionary) fire at **Step 5** (Create stubs). "Step 3·7b" = **Step 3, clause 7b** (Speculative tier — speculative candidate-topic-updates, capped at 2). Trigger **detection** = **Step 6** (mechanical, untouched). Trigger **presentation** + classification line + off-purpose banner = **Step 10** (Stage 1 checkpoint).

### Off-purpose flag (Step 10)

Extend the existing `INGEST PREVIEW` header and reuse the existing `accept-all` / `abort` controls — no new control verb. The classification band is appended to the preview header:

```
INGEST PREVIEW — <slug>   [purpose: in-focus | peripheral | ⚠ off-purpose]
```

When `off-purpose`, prepend an **advisory** banner above the file-changes table:

```
⚠ Off-purpose — this source matches no focus area in purpose.md.
   Ingest anyway?  (accept-all proceeds · abort discards)
```

All standard Stage-1 controls (`accept-all` / `reject N` / `abort`, plus the topic decisions) remain available — the banner only foregrounds the proceed/abort framing; it NEVER auto-aborts. Lens OFF (no `purpose.md`) → no classification line, no banner — preview identical to today.

**Silent / bulk mode.** `silent` mode (used by `/sb-wiki-ingest-all`) shows no Stage-1 banner; instead it includes the source's purpose band in the structured summary it returns, and `/sb-wiki-ingest-all` lists every off-purpose ingest in its final report for human review. In silent mode the band is informational — it never auto-aborts.

### Optionality & determinism guarantees

1. `purpose.md` absent → ingest output **identical** to today.
2. The lens **never alters mechanical branch _logic_**; it shapes only discretionary _inputs_ (synthesis depth, cluster granularity, optional-section inclusion). Those inputs may change a mechanical branch's _outputs_ (which stubs fire, index rows) — bounded by #3 and #4 — but no branch _rule_ changes.
3. The lens **never** drops content and **never** suppresses a detected trigger → "down-weight, never drop" holds.
4. Peripheral treatment is **floored at today's baseline, _including cluster granularity_** → the lens may lean terser on optional discretionary extras but **never coarsens clustering below baseline**, so no source becomes thinner (fewer stubs/links) than it would be today. Dial-UP for in-focus (finer granularity, more stubs) is the intended, allowed direction.
5. Malformed `purpose.md` → warn and proceed lens-OFF (never abort the ingest).

## Questions layer — questions.md

`{wiki_root}/questions.md` is an **optional** registry of the **user's open questions** — a queue-style inbox (framed as actionable, **not a log**) that the wiki gradually answers as sources land and topics form. Questions are captured during ingest (Stage-2 reflection), on a `/sb-wiki-query` miss, in chat, or by direct Obsidian edit. The **answer-scan** revisits open questions at ingest (active) and lint (periodic) and accretes cited answers inline until each question **graduates** to a page or is **retired**. It never drops content and never alters any deterministic rule.

### Artifact, location, optionality

| Property | Rule |
|----------|------|
| Location | `{wiki_root}/questions.md` — root-level sibling of `raw/`, `wiki/`, `logs/`, `purpose.md`. NOT a wiki page (not under `wiki/`), NOT raw. |
| Frontmatter | `type: questions` — a non-page value (excluded from page-type checks, indexes, orphan detection; see "Frontmatter schemas" § `type: questions`). |
| Optionality | Absent → questions layer OFF → ingest/lint behave **exactly** as today. Mirrors the `purpose.md` no-op contract. |
| Malformed | Warn and proceed as if absent; NEVER abort the ingest or lint. |
| Ownership | Vault content (personal). Only the *mechanism* that reads/writes it ships in sb-os. |
| Maintenance owner | **Lint OWNS** `questions.md` maintenance — sweep, graduation proposals, prune, and the `open-gaps.md` regeneration (see "The answer-scan" below). When the file is absent, lint skips it entirely. |

### Entry schema

Each entry is an H2 heading (same shape family as the wiki log entries under `logs/`). The runtime mirror of this shape is `wiki/workflows/shared/question-entry-shapes.md`.

```markdown
## [YYYY-MM-DD] <question text>
relates:
- "[[<page>.md]]"          # 0..n wikilinks to the pages the question concerns
seeded-by: "[[<source>.md]]"  # OPTIONAL — present when captured during ingest; absent when hand-added
answer:
- <claim that partially or fully answers it> [^1]   # accretes inline over scans; each bullet cited

[^1]: [[<source>.md]]
```

| Field | Rule |
|-------|------|
| H2 heading | `## [YYYY-MM-DD] <question>` — the capture date in brackets, then the question text. |
| `relates:` | 0..n quoted wikilinks to the concept/entity/topic/source pages the question concerns. May be empty for a cross-cutting question tied to no existing page. |
| `seeded-by:` | Optional single quoted wikilink to the source that surfaced the question at ingest. Absent when the question was hand-added (chat, `/sb-wiki-query` miss, or Obsidian). |
| `answer:` | Accretes inline as a bulleted list; each bullet carries an `[^N]` citation, with `[^N]: [[<source>.md]]` footnote defs (reuse the wiki citation convention — see "Citation format"; do NOT reinvent). |

**NO `status` field.** State is **inferred**: a question is `answered` iff an `answer:` block with at least one bullet exists, else `open`. `kind` and `origin` are **deliberately absent** — everything is a question (no question/thread distinction), and the two-homes model removes the need to record where a question came from.

### Two homes

| Home | Holds | How it resolves |
|------|-------|-----------------|
| **Topic `Open questions`** (stays on the topic page — menu UNCHANGED) | agent-authored gaps for *that* topic | the scan answers it → **strike the line, fold the answer into the topic body** via the existing `PROPOSED TOPIC UPDATES` append-only machinery. No entry ever moves into `questions.md`. |
| **`questions.md`** | the **user's** registered questions, including cross-cutting ones tied to no existing topic | inline `answer:` accretes → **graduate** to a page (via `sb-wiki-create-topic`) **or** **retire** → entry **REMOVED** from the file. |

Consequence: there is no single pane showing every open question across the wiki — `open-gaps.md` (below) recovers that view as a lint-generated aggregate over **both** homes.

### Lifecycle

```
open ──(scan / query / manual answer accretes inline)──▶ answered
   answered ──(lint GRADUATION PROPOSAL accepted)──▶ promoted ⇒ REMOVED (the page is the record)
   answered/open ──(user retires)─────────────────▶ retired   ⇒ REMOVED
```

- `open` and `answered` are the only transient states, inferred from `answer:` presence; neither is stored as a field.
- **Graduation** invokes the existing `sb-wiki-create-topic` skill (which carries its own `extend N` / `new` overlap check) — the agent **NEVER auto-authors** a topic page.
- Resolution signal is the wiki's existing model: **the page exists ⇒ the queue entry is gone** (same principle as `candidate-topic` in `logs/topics.md`). Retirement removes the entry on user judgment with no page.

### The answer-scan (the engine, not a store)

The scan matches open questions in **both** homes against new and existing wiki content. It runs in two places:

| Where | Behavior |
|-------|----------|
| **Ingest** (`/sb-wiki-ingest`, active) | Load `questions.md` (skip if absent). Match the new source against open questions in both homes — token overlap is the floor signal; when the semantic tier is available, a candidate ALSO fires when the helper, queried with the open question text (`search "<question>" --k 5`), returns THIS ingest's source page among its results (the source page is on disk from step 2; the first helper call of the run self-syncs it into the index, later calls pass `--no-sync`). Then surface a **`PROPOSED ANSWERS`** block at the Stage-1 checkpoint alongside the existing proposal blocks. **Default reject.** On accept: topic-home → strike the line + fold the answer into the topic body (append-only + cite); `questions.md` → append an inline `answer:` bullet (cited). Silent mode auto-**rejects** all proposed answers (same posture as topic updates). |
| **Lint** (`/sb-wiki-lint`, periodic) | A `questions.md` step (skip if absent): **sweep** every open question (both homes) against the existing wiki for now-available answers (off the ingest hot-path → may be more thorough than ingest's mechanical match; when the semantic tier is available, the sweep uses `sb-wiki-search.py` per § "Retrieval tiers — hybrid search" to match questions against wiki content); **GRADUATION PROPOSAL** — surface mature `answered` entries → on accept invoke `sb-wiki-create-topic` (user-gated, same model as `SUBDIVISION` / `RENAME`); **prune** — remove `questions.md` entries that are promoted (page exists) or retired; verify `relates:` / `seeded-by:` wikilinks resolve via the existing wikilink check; **regenerate `open-gaps.md`**. |

> **Validation window — ON.** Three heuristics are run ON for an initial validation window (≈ first 10 graduations / scans) before their wording is frozen here, exactly as the `purpose.md` design did: (1) the **graduation maturity** heuristic (when an accreted answer is "ripe" for a page); (2) the **scan match thresholds** (how much wikilink/token overlap fires a `PROPOSED ANSWER` — starting point: mirror the speculative-topic tier, ≥2 shared substantive tokens — AND the semantic membership check's `--k 5` cutoff); (3) the **lint sweep thoroughness** (how much more than ingest's mechanical match the sweep does). Tune in the window, then freeze.

### `open-gaps.md` — lint-generated aggregate

| Property | Rule |
|----------|------|
| Location | `{wiki_root}/open-gaps.md` — root-level sibling of `questions.md`. NOT a wiki page, NOT raw. |
| Frontmatter | `type: questions-index` — a non-page value (excluded from page-type checks, indexes, orphan detection; see "Frontmatter schemas" § `type: questions`). |
| Generation | **Lint-generated, READ-ONLY** — regenerated in full on every lint run. The user never hand-edits it; edits are overwritten. |
| Content | Aggregates every open question across **both** homes — `questions.md` entries AND topic-page `Open questions` lines — with backlinks to the home (the topic page, or the `questions.md` entry). Recovers the single-pane visibility the two-homes model gives up. |
| Optionality | Absent `questions.md` AND no topic `Open questions` → lint produces an empty or skipped `open-gaps.md`; presence of the file is never required for ingest/lint to run. |

### Optionality & determinism guarantees

1. `questions.md` absent → ingest/lint output **identical** to today (no-op contract).
2. The scan **proposes**, never silently rewrites — every answer and graduation is user-gated (default reject), like the existing topic-update and subdivision/rename proposals.
3. The scan **never drops** wiki content; topic-question resolution is an **append-only** topic update plus a strike of the answered line.
4. Graduation **never auto-authors** a topic page — it routes through `sb-wiki-create-topic`.
5. Malformed `questions.md` → warn and proceed as if absent (never abort the ingest or lint).

## Retrieval tiers — hybrid search

Wiki retrieval is **availability-gated**: a zero-dependency deterministic floor that always works, upgraded by a semantic tier when its prerequisites are present. Consumers MUST degrade down the ladder gracefully — the semantic tier is NEVER a required dependency, and a vault with no API key, no Python, or no index behaves exactly as the floor describes.

| Tier | Mechanism | Available when |
|------|-----------|----------------|
| **Semantic (hybrid)** | `sb-wiki-search.py` — SQLite FTS5 keyword ranking + Voyage embedding cosine, RRF-fused | Voyage key available (see Key resolution below) and the script runs (exit 0) |
| **Keyword (FTS5-only)** | Same script, vector arm off — ranked BM25 keyword search, zero API calls | Key absent but the script runs |
| **Deterministic floor** | Leaf indexes + wikilink graph + `grep`/`ripgrep` substring search | Always — the contract minimum |

Two consumption patterns, one invariant:

| Pattern | What the tier does | Examples |
|---------|--------------------|----------|
| **Retrieval** | Finds pages relevant to a natural-language question | `/sb-wiki-query` candidate picking; lint answer-sweep |
| **Read-narrowing** | Shortlists which pages an operation READS, replacing exhaustive page walks | Ingest near-duplicate stub probe; speculative topic-update fires |

**Mechanical-fire invariant.** The semantic tier NEVER decides a MECHANICAL fire (firm topic updates, `Substance`-bullet stubs, Step 6 trigger detection). Mechanical rules keep TOTAL coverage through deterministic means — directory listings, leaf indexes, `grep` alternation passes — and the semantic tier only narrows reads ABOVE that floor or adds DISCRETIONARY/SPECULATIVE candidates (which are user-gated or default-reject). A semantic top-k cutoff is never allowed to silently exclude a page from a mechanical rule's scope.

### The helper script

`{sb_os_path}/wiki/scripts/sb-wiki-search.py` — invoked from the vault root with the active Python interpreter:

```bash
python {sb_os_path}/wiki/scripts/sb-wiki-search.py search "<natural-language query>" --k 8 [--type concept,entity,topic,source,thesis,decision] [--json] [--no-sync]
python {sb_os_path}/wiki/scripts/sb-wiki-search.py index          # build / refresh the index
python {sb_os_path}/wiki/scripts/sb-wiki-search.py status         # freshness + mode as JSON
```

Multi-call operations (e.g. an ingest probing several stub-candidates): the FIRST helper call of the run syncs the index (picking up pages the run already wrote); subsequent calls in the same run SHOULD pass `--no-sync` — the tree has not changed since.

| Property | Rule |
|----------|------|
| Key resolution | The Voyage key resolves from the `VOYAGE_API_KEY` environment variable first, else from `{vault_root}/.user/config/env/.env` — the STANDARD location for local API keys in an sb-os vault. One `KEY=value` line per key (`VOYAGE_API_KEY=...`). The file is user-owned and MUST be gitignored (keep a tracked `.env.example` with empty values for new-machine setup). Missing file or empty value → keyword-only mode, never an error. |
| Index artifact | `{wiki_root}/.sb-wiki-search/index.db` — DERIVED data, machine-local. Never commit it (add the folder to the vault `.gitignore`); deleting it is always safe (rebuilt by the next `index`/`search`). |
| Scope | `{wiki_root}/wiki/**/*.md` pages only — leaf/origin indexes, `CLAUDE.md`, `raw/`, the `logs/` queue folder, and root-level queues (`questions.md`, `open-gaps.md`, `purpose.md`) are NEVER indexed. Extension page trees (e.g. `wiki/theses/`, `wiki/decisions/`) are included automatically. |
| Self-healing | `search` re-syncs before answering: changed/added/removed pages are detected (mtime+size prefilter, sha256 confirm) and re-indexed incrementally. Results never go stale; unchanged files are never re-embedded. |
| Read-only | The script only READS wiki content. It never writes a wiki page, index cell, or queue entry — judgment-bearing cells stay LLM-owned per the lint contract. |
| Installer | `install.py` never creates, reads, or writes the index artifact (installer scope guarantee unchanged). Lint never walks it (`.sb-wiki-search/` is a root-level dot-folder sibling of `wiki/` and `raw/`, outside both lint subtrees). |
| Privacy | With a Voyage key available, page text is sent to the Voyage API to be embedded. Key absent → FTS5-only mode and nothing leaves the machine. |
| Failure | Script missing, Python missing, or exit code 2 (unresolvable `wiki_root`) → consumers drop to the deterministic floor silently. A search error NEVER aborts the consuming operation. |

### Consumers

| Operation | Where the tier plugs in |
|-----------|------------------------|
| `/sb-wiki-query` | Steps 2–3 — ALWAYS-ON when the tier is available: deterministic picks (direct hits + filename matching, no leaf-index reads) UNIONED with semantic results on every query; leaf-index scoring + grep are the floor when unavailable |
| `/sb-wiki-ingest` | Step 3 near-duplicate stub probe (Stub policy § "Near-duplicate probe"); Step 3·7b speculative-tier semantic fires; Step 3·7c answer-scan semantic check. The FIRM tier never consumes the semantic tier — its read-shortlist is deterministic (listing + grep) per § "Existing topic updates" |
| `/sb-wiki-lint` | Step 7.7a questions answer-sweep — matching open questions against existing wiki content |
| `sb-wiki-create-topic` | Step 1.5 scope-overlap check — surface overlap candidates beyond the `Scope`-cell comparison |
| `sb-fin-create-thesis` (finance ext) | Step 1.3 scope-overlap check — same pattern over `wiki/theses/` |
| Any agent reading the wiki | Per the `{wiki_root}/CLAUDE.md` Retrieval rule — search before bulk-reading |

## Operations

Four operations covering the wiki lifecycle:

| Component | Type | Invoked by | Purpose |
|-----------|------|------------|---------|
| `/sb-wiki-ingest <slug>` | Slash command | The user | Distill a raw source into wiki pages |
| `/sb-wiki-ingest-all [origin]` | Slash command | The user | Backfill: ingest every non-ingested raw source via batched Opus subagents, then lint |
| `sb-wiki-create-topic` | Skill (auto-discovered) | Agent mid-ingest, OR auto-fired when the user expresses intent | Create a topic page from a candidate or freshly-proposed topic |
| `/sb-wiki-lint` | Slash command | The user | Health check + index maintenance for `raw/` and `wiki/` |
| `/sb-wiki-query <question>` | Slash command | The user | Synthesize an answer from wiki + optionally file the result back |

### `/sb-wiki-ingest`

Two invocations: `/sb-wiki-ingest <slug>` (default, interactive) and `/sb-wiki-ingest silent <slug>` (non-interactive — see "Silent (non-interactive) mode" below). `<slug>` is a raw filename or unique substring.

| Step | Operation | Owner |
|------|-----------|-------|
| 0 | **Load extensions** (runs before Step 1) — MERGE each registered module's `wiki-ext/` definitions into the active rule set per Module extensions §; no-op when `wiki_extensions` is absent/empty | Agent |
| 1 | Read raw file — resolve `<slug>` against `raw/{origin}/*.md` and `raw/{origin}/*.pdf`; read PDFs natively (page-range requests for large files) | Agent |
| 1.5 | **PDF title-conformance rename** (PDF sources only; markdown skips) — compute `{title-slug}` from the paper's title (Naming convention § "Raw PDF title-conformance"); if the PDF stem differs, rename `raw/{origin}/{stem}.pdf` → `{title-slug}.pdf` BEFORE the source page is created, so the source page and every footnote are born title-named (no referrer propagation needed). Collision → error-halt and ask (silent: `failed (duplicate raw)`). Filename-only — content immutable. **PDF text-twin rule:** when ingesting a PDF that has no Markdown twin in the same `raw/{origin}/`, MUST extract a durable text twin (`{title-slug}.md`) alongside the PDF using `pypdf`-extraction; NEVER delete or replace the PDF (preserve both); the source page `raw:` frontmatter wikilinks the `.md` twin AND the page carries `Original PDF: [[{title-slug}.pdf]]` as a body line immediately after the frontmatter block. PDFs that arrived WITH a pre-existing Markdown twin skip extraction (twin already present). | Agent |
| 1.7 | **Content-duplicate check** (all sources — markdown AND PDF; runs after step 1.5) — detect that this raw duplicates an ALREADY-INGESTED source before any wiki write. Two deterministic signals, either fires: **(a) URL match** — the raw's frontmatter `url`/`source`, normalized (lowercase host, strip scheme + `www.` + query + fragment + trailing slash), equals the normalized `url:` of ANY existing source page under `wiki/sources/` (one grep alternation over `url:` lines); **(b) Title match** — the raw's title, normalized (lowercase, non-alphanumeric collapsed to single spaces), equals the title of an already-ingested raw (one whose source page exists) in ANY origin. On fire (interactive): error-halt and ask — abort (skip the duplicate) or proceed (ingest anyway). Silent: `failed (content-duplicate)` — see silent override. No fire → proceed to step 2. This complements step 1.5 (PDF filename collision); it catches re-clips, dated twins, and cross-origin duplicates regardless of filename. | Agent |
| 2 | Write `wiki/sources/{origin}/{date}-{slug}.md` (`.md` extension even for a PDF source) (`Substance` and `Connections` always; `Notable quotes` / `Methodology` / `Counterpoints` per source kind; user-half sections present as empty shells with headings only). **Substance bullets MUST name entities/concepts at page-cluster granularity** per Page granularity § — sub-cluster names go in prose without wikilinks | Agent |
| 3 | Identify entity/concept mentions; **cluster candidates by page-granularity** (variants, whole+part, siblings, producer+work — see Page granularity §); for each cluster representative, apply the stub-creation rule (Substance bullet = mechanical; title-only = discretion; Notable Quote = discretion), then the **near-duplicate probe** when the semantic tier is available (Stub policy § "Near-duplicate probe" — same-referent hit reroutes to the update path). ALSO detect existing topic pages relevant to this source per "Existing topic updates" § — deterministic read-shortlist (slug listing + ONE grep alternation pass), reading ONLY matched topic pages; the semantic tier NEVER shortlists the firm tier — build the `candidate-topic-updates` sets | Agent |
| 4 | Update existing entity/concept pages with new perspective + citation; populate `Open variants / debates` section if Contradiction fires. **Agent NEVER overwrites a main section that already contains substantive content (>50 words) — only appends new sections, adds bullets to existing lists, or adds footnote definitions to Sources. User-fleshed content is treated as authoritative.** Existing topic pages are NOT updated at this step — they go through the Stage 1 user gate per "Existing topic updates" § | Agent |
| 5 | Create stubs for new entities/concepts that meet the rule | Agent |
| 6 | Detect candidate-topic triggers (Contradiction, Evolution, Cross-application); add `> [!warning] Disputed` callouts on Contradiction-`same-scope-opposing` | Agent |
| 7 | Update raw index: `Wiki = Yes`. **Tier-specific rule:** raw-index ROW missing → CREATE it; raw-index FILE missing → LOG A WARNING and do NOT create (lint owns raw-index files); wiki-sources index FILE missing → CREATE with header (step 8 responsibility). | Agent |
| 8 | Update wiki sources index (`What it says` filled; `My take` set to `pending` — populated post Stage 2 per the three-state rule). Index FILE missing → CREATE with header row. | Agent |
| 9 | Append `candidate-topic` entries to `logs/topics.md` and `candidate-mention` entries to `logs/mentions.md` when triggered (the actionable queues). NO `ingest` / `concept-created` / `entity-created` / `topic-updated` entries — created pages and updates are recorded by the pages themselves | Agent |
| 10 | **Stage 1 checkpoint**: present structured table + PROPOSED TOPICS block; the user accepts-all / rejects N / aborts file changes; per topic: accept (agent invokes `sb-wiki-create-topic` skill now) / defer (keeps as candidate in log). Approved changes commit before Stage 2 begins. | Agent + User |
| 11 | **Stage 2 checkpoint** (optional, post-commit): present reflection prompt after approved changes are committed. The user can ignore it, decline it, or answer with freeform reflection content in any order. The agent routes content by intent — `My take` → the source page `My take` section; questions / dive-deepers → `{wiki_root}/questions.md` entries (`seeded-by:` this source) — writes the routed content, and syncs the `My take` column to the wiki sources index. | Agent + User |

**No mid-flow user input during steps 1–9.** All user interaction happens at steps 10–11.

#### Ingest write rules (component contract)

These are binding constraints on ALL write operations performed by `/sb-wiki-ingest`. They apply in both default and silent modes.

**A7 — Thesis pages are scribe-only.**
`/sb-wiki-ingest` MUST NEVER create or edit ANY page under `wiki/theses/`. Thesis-relevant figures, conclusions, or data encountered during ingest MUST be reported in the structured RETURN (or the Stage 1 checkpoint table) — they are NEVER written to a thesis page by the ingest component. Thesis authoring and editing is exclusively the domain of `sb-fin-create-thesis`.

**D24 — Two-tier T4 write rule.**
A raw T4 framing (a specific below-bar claim extracted verbatim from a source) MUST live on its SOURCE page only. A SYNTHESIZED below-bar verdict MAY live on the ENTITY page WITH attribution (`per {source}, T4 — see [[source-page]]`). Entity pages MUST NEVER absorb a raw T4 claim unattributed.

**A10 — Ingest file and image routing.**

| Rule | Requirement |
|------|-------------|
| **A — Relocate referenced files into raw via the designated capture tool** | When the user directs ingest to handle a file NOT yet in `raw/{origin}/` (in Downloads, or parked in `raw/_unrouted/`), route it into `raw/{origin}/{title-slug}.{ext}` via the workspace's DESIGNATED sole raw-capture tool — the SOLE raw writer, NEVER an ad-hoc file move. Guard: fire ONLY on explicit ingest/capture intent. Infer `origin` from URL/content and CONFIRM when ambiguous (routing error risk). For files already in `raw/_unrouted/`, this IS the staging→`raw/{origin}/` move. |
| **B — Screenshot images → `_assets/` + embedded in place** | When the user explicitly mentions a file has images and provides their paths (e.g. from `C:\Users\...\Screenshots`), the ingesting agent MUST: (1) move each image into `{wiki_root}/raw/_assets/` renamed to a descriptive slug (NEVER a name like "Captura de tela …"); (2) embed `![[slug.png]]` in the raw Markdown at the position each image appears, using image-read + surrounding context; (3) FLAG any placement it is unsure of — NEVER silently guess placement. The user's explicit mention of the file/images IS the required direction to write under `raw/_assets/`. |

#### Stage 1 checkpoint format

```
INGEST PREVIEW — <source slug>

| # | file | action | preview |
|---|------|--------|---------|
| 1 | wiki/sources/blog-cloudflare/2026-XX-XX-code-mode.md | new | <first paragraph of Substance> |
| 2 | wiki/concepts/model-context-protocol.md | updated | + section "Code Mode perspective" |
| 3 | wiki/concepts/code-execution-pattern.md | new (stub) | <preamble first sentence> |
| 4 | wiki/entities/cloudflare.md | new (stub) | <preamble first sentence> |
| 5 | logs/topics.md, logs/mentions.md | appended | candidate-topic + candidate-mention entries (only if triggered) |
| 6 | raw/blog-cloudflare/blog-cloudflare.md | row updated | Wiki = Yes |
| 7 | wiki/sources/blog-cloudflare/blog-cloudflare.md | row added | new entry |

PROPOSED TOPICS:
| # | name | trigger | sources |
|---|------|---------|---------|
| 1 | mcp-debate | contradiction (same-scope-opposing) | [[2026-XX-XX-code-mode-mcp.md]], [[2026-XX-XX-bye-bye-mcp.md]] |

PROPOSED TOPIC UPDATES:
| # | topic | match | proposed change |
|---|-------|-------|-----------------|
| 1 | [[mcp-evolution.md]] | key-concept overlap ([[model-context-protocol.md]]) | + bullet under "Timeline" + citation |

SPECULATIVE TOPIC UPDATES (low-confidence, default reject):
| # | topic | overlap | proposed change |
|---|-------|---------|-----------------|
| 1 | [[ai-capability-skepticism.md]] | tokens: bottleneck, intelligence ([[marginal-returns-to-intelligence.md]]) | + bullet under "Key positions / Angles" + citation |

File changes: accept-all | reject N (e.g. "reject 3,4") | abort
Topic decisions: accept N (creates now) | defer N (logs as candidate) | (default: defer all)
Topic updates: accept N (applies append-only update) | reject N (skip) | (default: reject all)
Speculative updates: accept N (applies append-only update) | reject N (skip) | (default: reject all)
```

- `accept-all`: all file changes commit immediately; then the agent presents Stage 2 as an optional post-commit prompt.
- `reject N`: the agent rolls back the listed numbered items only (deletes new files, reverts edits, removes log entries scoped to those changes). Other changes commit immediately. The `Wiki = Yes` row update may be downgraded to `Wiki = Partial` if the source page itself is not rejected but downstream pages were. If the source page remains committed, the agent presents Stage 2 as an optional post-commit prompt.
- `abort`: the agent rolls back everything. Raw index `Wiki` stays `No`. The source page is not created.
- Topic `accept N`: agent invokes the `sb-wiki-create-topic` skill mid-run with the proposed topic name; the skill removes the promoted `candidate-topic` entry from the log (the topic page is now the record).
- Topic `defer N`: candidate-topic entry persists in log; the user may promote later by expressing intent (auto-fires the `sb-wiki-create-topic` skill).
- Topic update `accept N`: agent applies the append-only update to the topic page per "Existing topic updates" §. No log entry — the page records its own content.
- Topic update `reject N` (default when omitted): no change to the topic page; no log entry. The detection is not preserved as a candidate — re-detected on future ingests if relevance recurs.

#### Stage 2 checkpoint format

After Stage 1 acceptance and commit:

```
Committed approved ingest changes.

Reflect on this source? (y/n, or write any reflection now)

You can answer in any order:
- My take — why this mattered
- Open questions — what's unclear
- Dive deeper — follow-ups to pursue
```

Stage 2 is non-blocking: the ingest is already complete when this prompt appears. If the user ignores it and sends an unrelated next command, treat that command as the next task, not as reflection.

The user can answer with a bundled, out-of-order reflection. The agent routes by intent:

- `My take`: "my take", "take", "why it mattered", "o que eu achei", "minha visão", "minha leitura".
- `Open questions`: "open questions", "question", "dúvida", "pergunta", "unclear", "não entendi".
- `Dive deeper`: "dive deeper", "deep dive", "deep diver", "dive deepr", "follow up", "aprofundar", "quero dive deeper em", "quero me aprofundar em".

Explicit or semantically clear content MUST go to its matching destination even if it arrives while another category is displayed. `My take` content → the source page `My take` section. `Open questions` and `Dive deeper` content → `{wiki_root}/questions.md` entries (`seeded-by:` this source; one entry per question/dive-deeper) per "Questions layer — questions.md" and `question-entry-shapes.md`; they are NOT written back to the source page (v5 — the source page carries `My take` only). Example: "quero dive deeper em graph databases" becomes a `questions.md` entry, never a source-page section. If a response contains multiple routed spans, route each span to its matching destination. If a response contains substantive text with no routing signal, write it under `My take`. If routing is ambiguous and misrouting would change meaning, ask one targeted clarification.

The agent re-syncs the `My take` index cell per the three-state rule defined under "Wiki sources index format" — write the 1-sentence preview if `My take` was filled; write `—` if Stage 2 routed `Open questions` or `Dive deeper` content to `questions.md` while `My take` stayed empty; leave `pending` if Stage 2 was declined, ignored, or produced no routed content.

#### Silent (non-interactive) mode

`/sb-wiki-ingest silent <slug>` runs the SAME 11-step flow with EVERY user-interaction point auto-resolved to a fixed default. It exists so a caller (an orchestrator subagent, a research-mode auto-ingest, `/sb-wiki-ingest-all`) ingests a source end-to-end with NO prompts and receives a machine-parseable result. Steps 0–9 are IDENTICAL to the default mode. The mode changes the two checkpoints (Stage 1 auto-resolution — including the v5 firm-topic-update auto-apply below — and Stage 2 skip) and the slug-disambiguation behavior; everything else (clustering, stub rules, append-only protection, citation discipline, candidate-trigger detection) is unchanged.

The default (interactive) mode is the behavior specified throughout this section. When the `silent` keyword is ABSENT, NONE of the silent overrides below apply — the command behaves EXACTLY as the default-mode spec above.

**Auto-resolved defaults (silent):**

| Decision point | Default mode | Silent override |
|----------------|--------------|-----------------|
| Stage 1 file changes (step 10) | User chooses `accept-all` / `reject N` / `abort` | Auto `accept-all` — commit every staged file change. NEVER `reject`, NEVER `abort`. |
| Proposed topics (step 10 PROPOSED TOPICS) | User picks `accept N` / `defer N` (default defer all) | `defer` ALL — every `candidate-topic` log entry persists; NEVER invoke `sb-wiki-create-topic` mid-run. |
| Firm topic updates (step 10 PROPOSED TOPIC UPDATES — genuine firm-tier entries ONLY; answer-origin entries excluded, see PROPOSED ANSWERS row) | User picks `accept N` / `reject N` (default reject all) | **`accept` ALL — APPLY each via the step-4.5 append-only machinery** (append the `[^N]: [[<raw-filename>]]` footnote + the staged body bullet under the topic-shape-appropriate section; bump `last-touched`; append-only protection NEVER overwrites existing prose). Write ONE audit record per applied update into the summary `Flags` field. This INVERTS the prior silent posture (was reject-all) — interactive mode still defaults to reject. The firm tier is mechanical (wikilink/slug match, no semantic "feels relevant"), so unattended apply stays safe. |
| Speculative topic updates (step 10 SPECULATIVE TOPIC UPDATES) | User picks `accept N` / `reject N` (default reject all) | `reject` ALL. Write ONE audit record per rejected speculative update into `Flags`. NEVER apply unattended. |
| Proposed answers (step 10 PROPOSED ANSWERS — both homes; INCLUDES answer-origin firm entries staged by Step 3·7c) | User picks `accept N` / `reject N` (default reject all) | `reject` ALL. Write ONE audit record per rejected proposed answer into `Flags`. NEVER apply unattended (no `questions.md` `answer:` accretion; no topic-home strike-and-fold). |
| Stage 2 reflection (step 11) | Optional post-commit prompt | SKIPPED entirely — never presented, never awaited. The source page user-half stays empty shells; the wiki sources index `My take` cell stays `pending` (set at step 8). |
| Mid-flow HALT | A `<slug>` resolving to multiple raw files HALTS at step 1 for disambiguation | No HALT — see slug-resolution rule below. |

Only the FIRM tier of genuine topic updates auto-applies; speculative updates and proposed answers (including answer-origin firm entries) NEVER auto-apply. The audit records above are emitted to the structured-summary `Flags` channel (the existing caller-facing field — NO new log entry type, NO parallel log; the `topic-updated` type is retired per "Resolution signal" below and the queues hold no accretion/history entries). The applied topic page is its own durable record; `Flags` is the per-run audit trail `/sb-wiki-ingest-all` aggregates into its final-report counts (firm applied / speculative rejected / answers rejected). This is the v5 silent-mode behavior change.

This silent mode is the SINGLE source of the non-interactive ingest semantics. `/sb-wiki-ingest-all` no longer carries its own copy — its subagents invoke `/sb-wiki-ingest silent <slug>` and inherit these defaults. A change here changes every caller; never re-state these defaults in a caller.

**Content-duplicate (silent).** A step-1.7 fire does NOT halt: RETURN `failed (content-duplicate: duplicate of <existing-raw>)` and ingest nothing — with EXACTLY ONE permitted write: set this raw's index row to `Wiki = Duplicate (of [[<existing-raw>]])` so re-runs and `/sb-wiki-ingest-all` discovery skip it durably. The duplicate raw file itself is NEVER deleted — disposition (delete vs. re-point) is the user's call, surfaced by the caller's report.

**Slug resolution (silent).** The caller MUST pass a precise slug. A `<slug>` that resolves to MULTIPLE raw files is an ERROR in silent mode (NOT a disambiguation prompt): return `failed (slug ambiguous: N matches)` and ingest nothing. An exact filename match always wins and is never ambiguous. A `<slug>` resolving to ZERO raw files is `failed (slug not found)`.

**Return — structured summary (silent).** Instead of presenting checkpoints, silent mode RETURNS a structured summary the caller parses. The summary MUST contain, for the single source:

| Field | Content |
|-------|---------|
| Per-file status | EXACTLY ONE of: `committed` (all staged changes committed) \| `partial (<reason>)` (source page committed, ≥1 staged change failed mid-commit — `<reason>` names what failed) \| `failed (<reason>)` (nothing committed — `<reason>` is `slug ambiguous: N matches`, `slug not found`, `duplicate raw: {title-slug}.pdf exists`, `content-duplicate: duplicate of <existing-raw>`, or the abort cause) |
| New slugs | The list of NEW concept/entity page slugs created this run (filename stems, no `.md`); empty list if none |
| Flags | Any scope-overlap detections, lint-relevant flags, and silent-mode audit records surfaced during the run (e.g. a `same-scope-opposing` Contradiction callout written, a deferred `candidate-topic`, a firm topic-update applied, a rejected speculative update, a rejected proposed answer); empty if none. The firm-apply / speculative-reject / answer-reject audit records are the v5 silent-mode audit trail — one line per record naming the topic page (or question), the action, and the citing source; `/sb-wiki-ingest-all` aggregates them into its final-report counts |

Silent mode runs the full append-only protection, clustering, and trigger detection of the default flow — `partial`/`failed` reflect ONLY commit-time or slug-resolution outcomes, never a skipped step. The mode NEVER writes a topic page and NEVER runs `/sb-wiki-lint` (cross-origin healing and topic promotion stay the caller's job).

### `/sb-wiki-ingest-all`

`/sb-wiki-ingest-all [origin]`. Orchestration-only command: it ingests every raw source that has no source page yet (`wiki/sources/{origin}/{stem}.md` absent) by dispatching subagents that each run `/sb-wiki-ingest` unchanged. It adds NO ingestion logic — `/sb-wiki-ingest` remains the sole authority on how one source is distilled.

| Step | Operation | Owner |
|------|-----------|-------|
| 1 | Run `sb-wiki-ingest-all-manifest.py` → JSON of non-ingested sources (`.md` + `.pdf`) with per-file approx `token_estimate` and per-origin token sums. "Ingested" = source page exists. Excludes asset folders; includes `studies` and any `_`-prefixed origin except assets. SKIPS raw files whose raw-index row is `Wiki = Duplicate (…)` — confirmed content-duplicates are never re-targeted | Script |
| 2 | The same script (`--plan`) greedily packs each origin's files into batches ≤50,000 source tokens (a lone file >50,000 or null estimate is its own batch — a source is never split), schedules waves (wave K = batch K of each origin; distinct origins → parallel-safe; cap 5 concurrent; same-origin batches always serialized), and assigns each batch a `model`: `sonnet` when the batch's token sum ≤25,000 and every file has a non-null estimate, else `opus` | Script |
| 3 | Read the plan's batches and waves verbatim — no agent re-packing, no re-scheduling | Agent |
| 4 | Dispatch one subagent per batch per wave on the batch's planned `model`; subagents run `/sb-wiki-ingest silent <slug>` (silent mode owns every checkpoint auto-resolution — see "Silent (non-interactive) mode"), one file at a time | Agent + Subagents |
| 5 | After the last wave, run `/sb-wiki-lint` to dedupe cross-origin duplicate stubs, renumber footnotes, repair indexes, and prune the log | Agent |
| 6 | Report committed/partial/failed counts, cross-origin duplicate slugs, and the lint outcome | Agent |
| 7 | Create the run's SINGLE git commit (see Git discipline) — never per source, per batch, or per wave | Agent |

**Git discipline.** No git command runs during ingestion — subagents NEVER git-commit, and the orchestrator NEVER commits per source, per batch, or per wave. When the vault root is a git repository, the orchestrator creates EXACTLY ONE git commit after step 6, covering every change the run produced (source pages, stubs, indexes, log entries, lint heals). When it is not, skip step 7 — nothing else changes. The per-file status `committed` refers to staged FILE changes written to disk (the Stage-1 commit gate), never to git.

**Why origin-serial.** Same-origin sources reuse the same entities/concepts, so concurrent ingestion races to create the same stub. Serializing per origin removes the dense-overlap collisions; the rarer cross-origin collisions (globally-common entities) are healed by the step-5 lint pass. There is no user checkpoint during the run — each subagent runs `/sb-wiki-ingest silent`, which auto-resolves both checkpoints; the only interactive surface is lint's step-9 report at the end.

### `sb-wiki-create-topic`

A skill agents can invoke mid-ingest (when the user accepts a PROPOSED TOPIC at Stage 1) OR auto-fired by Claude Code when the user later expresses intent to create or promote a topic (e.g., "create a topic for X", "promote the mcp-debate candidate"). No slash command — invocation is intent-driven.

| Step | Operation | Owner |
|------|-----------|-------|
| 1 | Resolve topic name; if from a candidate, load the candidate-topic log entry (claim A, claim B, trigger, sources) | Agent |
| 1.5 | **Scope-overlap check (semantic, not slug).** Read `wiki/topics/topics.md` and compare the proposed scope sentence to every existing row's `Scope` cell. When the semantic tier is available (§ "Retrieval tiers — hybrid search"), ALSO run `sb-wiki-search.py search "<proposed scope sentence>" --type topic` and treat its hits as overlap candidates the `Scope`-cell comparison may have missed. If overlap is plausible (shared subject, shared sources, shared positions, sibling/sub-debate framing), surface three options to the user: `extend N` (append a new `Position` / `Angle` to the existing topic; no new page), `new` (proceed with a new sibling-cross-linked topic), or `abort`. Skipped only when the caller (e.g., `/sb-wiki-query` Step 7a) passes `overlap-checked: true` proving the check already ran upstream. Slug-collision check from step 1 is necessary but NOT sufficient — both checks must pass. | Agent + User |
| 2 | Write `wiki/topics/{slug}.md` with frontmatter, `Scope` (required), `Sources` (required), and optional sections per topic shape (see Topic page menu). On `new` from step 1.5, also append the new topic's wikilink to the overlapping topic's `related:` frontmatter (sibling cross-link). | Agent |
| 3 | Cross-link from triggering concept/entity pages: add wikilink to the new topic in their `Related` section | Agent |
| 4 | If promoted from a candidate, REMOVE that `candidate-topic` entry from `logs/topics.md` (the topic page is now the record — resolution = page exists). No `topic-created` entry is written | Agent |
| 5 | Update `wiki/topics/topics.md` leaf index with the new entry | Agent |

When invoked mid-ingest, no separate user checkpoint — the parent `/sb-wiki-ingest` Stage 1 acceptance covers it AND the step 1.5 overlap prompt fires inline before commit. When auto-fired by user intent, the agent runs step 1.5 first, then confirms the proposed sections + scope sentence with the user before writing (single confirmation checkpoint, two distinct prompts when overlap is detected).

### `/sb-wiki-lint`

Single command: `/sb-wiki-lint`. Runs across `raw/` and `wiki/` folders. Mostly read-only; deterministic index sync writes are auto-applied (no diff to accept). Judgment-bearing index cells are never script-filled.

Before walking the tree, agents run this command from the vault root with the active Python interpreter:

```bash
python {sb_os_path}/wiki/scripts/sb-wiki-lint-deterministic.py --apply --report {wiki_root}/lint-deterministic-report.json
```

The script executes the deterministic halves of steps 1, 2, 3, 4, 5, 6, 7, 7.5, 7.6, and 8 in one pass — index sync writes, type-tag sync (every page's `tags:` includes its `type:` value; index files missing `type:` get `type: index`), stub/orphan/footnote-state detection, unresolved-Disputed-callout detection (>30d, no resolving topic page), broken-wikilink classification (bucket A unique fold-match vs needs-judgment), log prune-test (unknown types kept + reported), `questions.md` link check, PDF title-conformance detection, subdivision detection — and emits `judgment_needed`. The agent reads every queued item, reads the referenced file, and fills the required semantic index cell. Agents NEVER re-derive these detections via LLM file walks. Three additional surfaces: `--prune-log` executes the step-8 log prune (lint-contract-authorized); `--execute-renames <plan.json>`, `--execute-subdivision <plan.json>`, and `--execute-link-fixes <plan.json>` are USER-GATED executors invoked only after a step-9 accept — `CLAUDE.md` routing rows and first-time router rewrites stay agent-applied (the script returns them as pending work, never editing CLAUDE.md itself). Report-key-to-step mapping: `sb-wiki-lint.md` § "Deterministic Helper".

| Step | Operation |
|------|-----------|
| 0 | **Load extensions** (runs before Step 1) — MERGE each registered module's `wiki-ext/` definitions (including its `lint-rules.ext.md`) into the active rule set per Module extensions §; no-op when `wiki_extensions` is absent/empty |
| 1 | Walk all wiki pages — detect stubs (structural rule) and record age via `created` |
| 2 | Walk all wiki pages — detect orphans (no inbound wikilinks). **Orphan-detection scope is STRICT** — see "Orphan-detection scope" below |
| 3 | **Deterministic.** Detect unresolved Disputed callouts in concepts/entities — flagged date (first `YYYY-MM-DD` in the callout body) >30 days old AND no referenced topic page exists to resolve it (resolution = page exists). Callouts with no resolving topic AND no parseable date surface as `unparseable` for manual review |
| 4 | Walk `logs/topics.md` — flag `candidate-topic` entries aged >30 days whose topic page does NOT yet exist (resolution = page exists, so a candidate with a live page is not "aging", it is spent and pruned at step 8). ALSO walk `logs/theses.md` — flag every `speculative-thesis-update` as awaiting investor decision (never auto-pruned — the target thesis page already exists, so "page exists" is not a resolution signal); `proposed-new-thesis` resolves like `candidate-topic` (spent → pruned at step 8) |
| 5 | **Deterministic + judgment.** Verify wikilinks resolve (broken if target file missing); CLASSIFY each broken link — `bucket A` (unique casefold+accent+quote/dash fold-match to an existing file → auto-fixable, exact `suggestion`) or `needs-judgment` (LLM splits into bucket B = genuinely-missing concept/entity to author as a stub, vs bucket C = unresolvable/duplicate, reported only). Ambiguous targets (≥2 fold-candidates) report candidates and default to C |
| 6 | For each `wiki/sources/{origin}/` — re-sync `My take` column from each source page's `My take` section per the three-state rule (`pending` / `—` / reflected preview — see "Wiki sources index format" §); renumber footnotes (safe bijections only); REPORT unreferenced defs and set mismatches per "Citation format" § — stale-def removal is never auto-applied |
| 7 | For each `raw/{origin}/` — verify `{origin}.md` index exists; if missing, create it with the standard `\| File \| Title \| Date \| Wiki \|` columns. For each raw file in `{origin}/`, ensure a row exists with `Wiki = No` (default) or `Yes/Partial` (preserved). Same for `raw/studies/studies.md`. **Index creation and maintenance is the agent's job**, not the user's. Also: **type-tag sync** (deterministic, auto-applied) — every page under `wiki/` gets its `type:` value appended to `tags:` when absent (append-only, user tags preserved); index files (stem = parent dir name) missing `type:` get `type: index` + `tags: [index]`; non-index pages with no resolvable `type:` are reported, never guessed. Per Frontmatter schemas § "Type tag (mandatory)". |
| 7.5 | Folder-subdivision detection. For `wiki/concepts/` and `wiki/entities/`, group pages by `kind:` frontmatter. Surface kinds at ≥10 pages as a SUBDIVISION PROPOSAL block (threshold authority: `../workflows/shared/folder-structure.md` § "Stability Rules"). Skip `wiki/topics/` (count <20) and `wiki/sources/` (already subdivided by origin). On user accept at step 9, the agent creates `{type}/{subfolder}/`, leaf index, parent CLAUDE.md marker-block routing rules, moves pages, and rewrites parent index as router. The folder structure and indexes are the record — NO log entry. Naming and policy per schema § "Folder subdivision". |
| 7.6 | **PDF title-conformance detection.** For each PDF in `raw/{origin}/`, compare the stem to the kebab-slug of the raw index `Title` (Naming convention § "Raw PDF title-conformance"). Mismatch + no name collision → `rename-proposals` row; mismatch + `{title-slug}.pdf` already exists → `duplicate-raws` finding (no rename). Detection only — execution is USER-GATED at step 9, updating the full referrer set per "PDF title-conformance (lint)" below. Markdown sources exempt. |
| 8 | Prune the `logs/*.md` files: DELETE every `candidate-topic` / `candidate-mention` / `proposed-new-thesis` entry whose matching page now exists (resolution = page exists), and DELETE any retired history entries (`ingest`, `concept-created`, `entity-created`, `topic-created`, `topic-updated`, `topic-coverage-candidate`, `lint`, `query`). NO `lint` entry is written — findings live in the report only. `candidate-mention` entries with no matching page are NEVER auto-aged; they persist until the page exists or the user dismisses them. `speculative-thesis-update` entries are NEVER auto-pruned (no "page exists" signal — they resolve on explicit user action via `sb-fin-create-thesis` extend or dismiss; lint ages + surfaces them). Entries of an UNKNOWN type (neither active nor retired) are KEPT and surfaced in the report for manual routing — never auto-deleted |
| 9 | Present findings to the user (read-only summary for findings 1-7; the `candidate-mention` review queue is surfaced here). USER-GATED interactive blocks: LINK-FIX PROPOSAL (bucket-A broken links → accept runs `--execute-link-fixes`), MISSING-PAGE PROPOSAL (bucket-B → accept authors a web-verified stub), RENAME PROPOSAL, SUBDIVISION PROPOSAL, and (questions layer ON) PROPOSED ANSWERS + GRADUATION PROPOSAL — each accepts all / accepts N / rejects / defers |

#### Lint output format

Step 7 does not authorize scripts to write blank or guessed semantic cells. Concept/entity `Description` cells (leaf indexes + router `## Flat pages` tables) ARE auto-filled by `sb-wiki-fill-index-descriptions.py` from each page's lead definition sentence (wikilinks flattened, footnote/emphasis stripped, truncated to one sentence) — these pages are authored definition-first, so the lead line IS the description. A page with NO clean lead sentence is REPORTED as `weak`, NEVER written; weak `Description` cells stay LLM-owned. `Scope` (topics) and `What it says` (sources) still require LLM judgment and are never script-filled. Raw index `Title` is script-safe only when it comes from frontmatter or an H1; filename slug guesses are forbidden.

```
LINT REPORT — 2026-04-30 09:00

Stubs aged >30 days (3): [[X.md]], [[Y.md]], [[Z.md]]
Orphans (no inbound) (2): [[A.md]], [[B.md]]
Unresolved Disputed callouts (1): [[mcp-debate.md]] — flagged 2026-04-12
Candidate-topics aging without promotion (1): "mcp-debate" — logged 2026-04-12
Broken wikilinks (4): A=1 auto-fixable | B=2 need a page | C=1 unresolvable
Index sync — wiki/sources My take refreshed: 4 source pages
Index sync — raw indexes: 1 created (raw/studies/studies.md), 3 rows added across raw/{origins}
Type tags synced: 5 pages (type appended to tags), 1 index given type: index
Footnotes renumbered: 2 source pages
PDF renames proposed (N): <old>.pdf → <title-slug>.pdf, …
Duplicate raws — title-slug already taken (N): <old>.pdf ≡ <existing>.pdf

LINK-FIX PROPOSAL — bucket-A broken links | accept all | accept N | reject | defer (default defer; --execute-link-fixes rewrites the links only on accept)
MISSING-PAGE PROPOSAL — bucket-B broken links | accept all | accept N | reject | defer (default defer; web-verified stub authored only on accept)
RENAME PROPOSAL — accept all | accept N | reject | defer (default defer; renames + referrer rewrites apply only on accept)

No action required for read-mostly findings (index sync auto-applied). LINK-FIX, MISSING-PAGE, RENAME, and SUBDIVISION PROPOSAL are the interactive blocks.
```

#### PDF title-conformance (lint)

Step 7.6 compares each raw PDF stem to the kebab-slug of its raw-index `Title`. Mismatches surface as a RENAME PROPOSAL block; execution is user-gated (same model as subdivision). On user `accept`, for each rename the agent updates the FULL referrer set atomically — a filesystem rename does NOT trigger Obsidian backlink updates:

| Referrer | Update |
|----------|--------|
| Raw PDF | `raw/{origin}/{old}.pdf` → `{title-slug}.pdf` |
| Source page | `wiki/sources/{origin}/{old}.md` → `{title-slug}.md` |
| Source `raw:` frontmatter | `[[{old}.pdf]]` → `[[{title-slug}.pdf]]` |
| Footnote definitions | every `[^N]: [[{old}.pdf]]` on any wiki page → `[[{title-slug}.pdf]]` |
| Raw index `File` cell | `[[{old}.pdf]]` → `[[{title-slug}.pdf]]` |
| Wiki sources index `File` cell | `[[{old}.md]]` → `[[{title-slug}.md]]` |
| Other wikilinks + `logs/*.md` | any `[[{old}.md]]` / `[[{old}.pdf]]` → new stem |

Mechanically: rewrite SCOPED wikilink patterns only — targets `[[{old-stem}.pdf` and `[[{old-stem}.md` (any `#anchor`/`|alias` tail), which cover every referrer row above — in NON-raw `.md` files (`wiki/**`, `logs/*.md`) plus raw index files (`raw/{origin}/{origin}.md`); then move the two files. NEVER a blind global string replace: raw content file bodies are immutable, and `http(s)://` URLs containing the old stem (arXiv, repository deep links) are NEVER rewritten. After the move, verify remaining `{old-stem}` occurrences are only legitimate remnants (external URLs, raw bodies). `duplicate-raws` are reported, never auto-renamed — the user merges or deletes them.

#### Orphan-detection scope (STRICT)

Orphan-detection is the lint signal for "the wiki is not actually building knowledge about this entity / concept / topic." It MUST be computed against synthesis pages only — not against every file in `{wiki_root}/`.

| Scope | Files |
|-------|-------|
| **In scope for inbound-link computation** | `wiki/concepts/*.md`, `wiki/entities/*.md`, `wiki/topics/*.md` — and ONLY these |
| **Out of scope** (do NOT count as inbound links toward orphan status) | the `logs/*.md` queue files, `wiki/sources/{origin}/{origin}.md` indexes, raw source pages under `raw/`, `wiki/sources/{origin}/<date>-<slug>.md` source pages, and any leaf index file (`concepts.md`, `entities.md`, `topics.md`, `{origin}.md`, `studies.md`) |

**Rationale.** Log entries and source-page footnote definitions are EVIDENCE OF MENTION, not synthesis. An entity referenced only by a `logs/*.md` queue file, only by a source page, or only by a raw index is an entity the wiki has noticed but is not actively cross-linking from real synthesis. Orphan-detection is meant to surface exactly these — pages that exist as stubs but have not earned a place in the actual knowledge graph. Forcing inbound links to come from real wiki content (concept / entity / topic pages) keeps the bar high and preserves the orphan signal's diagnostic value.

**Practical implication.** A new stub created from a source page's `Notable Quotes` will, by design, be flagged as an orphan on the next lint run if no concept/entity/topic page links to it from its body or `Related` section. This is correct behavior, not a false positive — the orphan flag is the lint asking the user (or a future ingest) whether the stub deserves real synthesis.

#### purpose.md — SKIP entirely (v1)

`/sb-wiki-lint` MUST skip `{wiki_root}/purpose.md` entirely — NEVER flag it as orphan, stray, or stub; NEVER index it; NEVER count it in orphan detection (in or out). It is regulatory configuration (`type: purpose`), not a wiki page. This holds structurally: lint walks only the `wiki/` and `raw/` subtrees (steps 1–7), and `purpose.md` is a root-level sibling outside both — so it is never walked. Mirrors the existing `raw/_assets/` skip contract. No semantic purpose-lint in v1 (off-purpose-drift / thin-focus / gap detection are parked backlog).

### `/sb-wiki-query`

Single command: `/sb-wiki-query <question>`. Returns a synthesized answer; optionally files the answer back as a wiki page.

| Step | Operation | Owner |
|------|-----------|-------|
| 1 | Parse question; identify candidate page types (concept / entity / topic) and likely keywords | Agent |
| 2 | Pick candidates deterministically. Tier available: direct page references + exact/substring filename matches from directory listings of the candidate-type leaf folders — NO leaf-index reads. Tier unavailable (floor): read leaf indexes (`concepts.md`, `entities.md`, `topics.md`) and score rows by name match + index summary | Agent |
| 3 | Retrieve per § "Retrieval tiers — hybrid search". Tier available: run `sb-wiki-search.py` with the question verbatim on EVERY query (never only on a miss) and UNION results with step-2 picks. Tier unavailable: `grep` / `ripgrep` over `wiki/` content only when step 2 yielded nothing (deterministic floor). Union still empty → expand to `raw/` (grep only) | Agent |
| 4 | Read picked pages; if depth needed, follow wikilinks to neighbors | Agent |
| 5 | Synthesize answer with inline citations to wiki pages (`[[page.md]]`) and source pages (footnote definitions) | Agent |
| 6 | Present answer + offer to file as a wiki page (Concept / Entity / Topic) if "valuable enough" — the user picks file/skip | Agent + User |
| 7 | If filed: for Topic, run a scope-overlap pre-check against `wiki/topics/topics.md` (offering `extend N` / `new` / `abort` to the user) before invoking `sb-wiki-create-topic` with `overlap-checked: true` — `extend N` writes the synthesized answer as a new `Position` / `Angle` on the existing topic and skips skill invocation; for Concept / Entity, write directly to `wiki/concepts/` / `wiki/entities/`; no log entry is written (`query` is a retired type — the filed page is the record) | Agent + User |

#### Query output format

```
QUERY — "What's the contradiction between code-mode and bye-bye-mcp on MCP?"

Sources consulted: [[model-context-protocol.md]], [[code-execution-pattern.md]], [[2026-XX-XX-code-mode-mcp.md]], [[2026-XX-XX-bye-bye-mcp.md]]

Answer:
The contradiction is same-scope-opposing on MCP's value at production scale. [[model-context-protocol.md]] surfaces the dispute via a `> [!warning] Disputed` callout citing both sources[^1][^2]. Code Mode (Cloudflare) argues MCP works when collapsed to a code-execution boundary[^1]. Bye-Bye-MCP argues MCP went sideways for a specific use case where direct API calls were simpler[^2].

[^1]: [[2026-XX-XX-code-mode-mcp.md]]
[^2]: [[2026-XX-XX-bye-bye-mcp.md]]

File this answer as a wiki page? (y/n) — type [c]oncept | [e]ntity | [t]opic | [s]kip
```

If filed as Topic, the agent invokes `sb-wiki-create-topic` with the proposed name; the user can edit the name before commit.

## Log entry types

The logs are ACTIONABLE QUEUES, not an event history. They hold ONLY items awaiting a user action. Completed events (ingests, page creations, topic updates, lint runs, filed queries) are NEVER logged — their provenance already lives in the source pages, the raw indexes, and the wiki pages themselves.

The queue is SPLIT into three per-type files under `{wiki_root}/logs/` (the deterministic prune maps filename → entry-type — there is no single `log.md`):

| File | Entry type(s) |
|------|---------------|
| `logs/topics.md` | `candidate-topic` |
| `logs/mentions.md` | `candidate-mention` (concept + entity unified; `classification:` inline) |
| `logs/theses.md` | `proposed-new-thesis`, `speculative-thesis-update` |

4 types active. Each entry is an H2 heading: `## [YYYY-MM-DD HH:MM] type | brief`.

| Type | File | Trigger | Awaiting action | Leaves the queue when |
|------|------|---------|-----------------|------------------------|
| `candidate-topic` | `logs/topics.md` | Auto-fired during `ingest` or `lint` when 1 of 3 triggers fires. Standalone H2 entry — does NOT reference a parent ingest | Decide whether to promote via the `sb-wiki-create-topic` skill | The topic page exists (create-topic removes the entry on promotion; lint prunes any candidate whose topic page exists) |
| `candidate-mention` | `logs/mentions.md` | Auto-fired during `ingest` step 3 when an entity/concept name surfaces but the stub-creation rule does NOT fire (per Stub policy). Standalone H2 entry | Review → promote to a stub, or dismiss | The matching page exists (lint prunes), or the user dismisses it. NEVER auto-aged — mentions persist until actioned |
| `proposed-new-thesis` | `logs/theses.md` | Fired on the investor path when a new-thesis trigger fires (per `finance/wiki-ext/candidate-thesis-triggers.md`). Standalone H2 entry | Decide whether to promote via `sb-fin-create-thesis` | The thesis page exists — create-thesis removes the entry on promotion; lint prunes by filename against `wiki/theses/` pages (resolves like `candidate-topic`) |
| `speculative-thesis-update` | `logs/theses.md` | Fired on the investor path when a speculative change to an EXISTING thesis is proposed (e.g. a thesis-invalidation signal). Standalone H2 entry | `sb-fin-create-thesis` extend applies it on user action, or the user dismisses | The user acts or dismisses. **Lint NEVER auto-prunes it** — the target page already exists, so "page exists" is not a resolution signal; lint ages + surfaces it as "awaiting investor decision" |

**Resolution signal = the page exists** — for `candidate-topic`, `candidate-mention`, and `proposed-new-thesis`. There is no `topic-created` / `concept-created` / `entity-created` / `ingest` / `topic-updated` / `query` / `lint` entry. A candidate is "spent" the moment its page exists; lint detects this by filename and removes the entry. This replaces the old `topic-created`-as-resolution-signal model. The EXCEPTION is `speculative-thesis-update`: its thesis page already exists, so it resolves EXPLICIT-ONLY (the user acts or dismisses) and lint never auto-prunes it. Thesis changes NEVER auto-apply (hard rule A7) — `logs/theses.md` is a surface-only proposal queue; every promotion/update flows through `sb-fin-create-thesis` with user approval.

**Unknown types.** An entry whose type is neither active nor retired is NON-CANONICAL — a writer violated the queue contract. Lint KEEPS it and surfaces it in the LINT REPORT for manual routing; it NEVER auto-deletes unknown content. Personal capture types are never registered into this enum — the logs hold exclusively the active types; personal captures route to vault files instead.

### Entry shapes

```markdown
## [2026-04-30 14:32] candidate-topic | mcp-debate
- trigger: contradiction (same-scope-opposing)
- between: [[2026-XX-XX-code-mode-mcp.md]] and [[2026-XX-XX-bye-bye-mcp.md]]
- claim A (verbatim): "MCP works in code-mode form when collapsed to..."
- claim B (verbatim): "MCP went sideways for our use case..."
- promote via: sb-wiki-create-topic skill (express intent: "create the mcp-debate topic")

## [2026-04-30 14:32] candidate-mention | sandboxing
- name: sandboxing
- classification: concept
- reason: stub rule did not fire (name not in source title, Notable Quote, or Substance bullet)

## [2026-06-09 10:15] proposed-new-thesis | ai-capex-overbuild
- thesis: <one-line statement of the proposed new thesis>
- trigger: recurring-claim | mispricing-signal | thesis-shaped-page-created
- sources: [[2026-06-08-some-source.md]]
- promote via: sb-fin-create-thesis (express intent: "create the ai-capex-overbuild thesis")

## [2026-06-09 10:15] speculative-thesis-update | ai-capex-overbuild
- target thesis: [[ai-capex-overbuild.md]]
- trigger: thesis-invalidation
- change: <one-line statement of the proposed change to the existing thesis>
- source: [[2026-06-08-some-source.md]]
- apply via: sb-fin-create-thesis extend (user decision REQUIRED — never auto-applies; lint never auto-prunes)
```

A `proposed-new-thesis` `<brief>` MUST be the thesis page slug — lint resolves it by filename against `wiki/theses/` pages (resolution = page exists), like `candidate-topic`. A `speculative-thesis-update` carries no filename-prune contract (the page already exists); its `target thesis:` wikilink identifies the existing page the proposed change applies to.

Pre-v1 logs may contain retired history types (`ingest`, `concept-created`, `entity-created`, `topic-created`, `topic-updated`, `topic-coverage-candidate`, `lint`, `query`). Lint removes them on its next pass.

## Retired log entry types (pre-v1)

These types were logged in earlier versions and are NO LONGER written. Lint prunes them from existing logs.

| Retired type | Was | Why removed |
|------|-----|-------------|
| `ingest` | Anchor entry per source | Provenance lives in the source page `raw:` field + raw index |
| `concept-created` / `entity-created` | Stub-creation record | The page is the record |
| `topic-created` | Topic-creation + candidate resolution signal | Replaced by "page exists" resolution |
| `topic-updated` | Append-only accretion record | Page history lives in the page |
| `topic-coverage-candidate` | Dropped speculative match | Low-signal; re-detected on future ingests |
| `lint` | Lint-run summary | Lint surfaces findings in its report, not the log |
| `query` | Filed-answer record | The filed page is the record |

## Component structure

Each wiki capability is its own component under the `sb-` prefix (alongside other sb-os components such as `sb-vault-ops`, `sb-tutor`, `sb-archivist`). No umbrella `sb-wiki` skill — capabilities are independent.

Source files live in the sb-os repo under `sb-os/workflows/sb-wiki-*/`. Skills and commands installed into `.claude/` are **thin loaders** that point back to those source files (per architecture doc §4 loader pattern). Editing installed loaders is forbidden — the source is the repo. Re-running `python install.py` regenerates loaders.

| Component | Type | Source (sb-os repo) | Installed loader (vault) | Purpose |
|-----------|------|--------------------|--------------------------|---------|
| `sb-wiki-ingest` | Slash command | `sb-os/workflows/sb-wiki-ingest/` | `.claude/commands/sb-wiki-ingest.md` | User-invocable end-to-end ingest |
| `sb-wiki-ingest-all` | Slash command | `sb-os/workflows/sb-wiki-ingest-all/` | `.claude/commands/sb-wiki-ingest-all.md` | User-invocable batch backfill of all non-ingested sources (orchestration only) |
| `sb-wiki-create-topic` | Skill (auto-discovered) | `sb-os/workflows/sb-wiki-create-topic/` | `.claude/skills/sb-wiki-create-topic/SKILL.md` | Agent-invokable mid-ingest; auto-fires when the user expresses topic-creation intent |
| `sb-wiki-lint` | Slash command | `sb-os/workflows/sb-wiki-lint/` | `.claude/commands/sb-wiki-lint.md` | User-invocable health check + index maintenance |
| `sb-wiki-query` | Slash command | `sb-os/workflows/sb-wiki-query/` | `.claude/commands/sb-wiki-query.md` | User-invocable synthesized query |

Workflows hold all logic. Slash commands and skills are thin loaders only.

This schema doc lives at its canonical home: `3-resources/tools/sb-os/wiki/docs/wiki-schema.md` (inside the sb-os repo). Relocated from `1-projects/second-brain-evolution/sb-wiki-build/wiki-schema.md` at sb-os v2 build time (p2-1).

> **Configurability.** Wiki workflows resolve `{wiki_root}` from `sb-os.json` at runtime — never hardcoded. The `wiki/`, `raw/`, and `logs/` paths are derived as `{wiki_root}/wiki/`, `{wiki_root}/raw/`, and `{wiki_root}/logs/`. Per architecture doc §3, the user-context root for any YAML companions used by wiki workflows resolves through `sb-os.json` → `user_context_root` (default `.user/context/`).

## Deferred / open

| Item | Status | Revisit when |
|------|--------|--------------|
| `status:` frontmatter field | Deferred (use structural detection) | If lint surfaces a real need after first 5–10 ingests |
| Tag policy on wiki pages | Deferred (wikilinks primary) | If a specific need emerges |
| `/sb-wiki-reclassify` (concept↔topic migration) | Deferred | When a real reclassification need surfaces |
| Cross-application trigger fire-rate | Defined; will fire when ≥2 wiki pages get co-mentioned in ≥2 sources | When wiki has ≥10 pages |
| Browse affordance in lint output | Deferred | After 1–2 months of lint usage if a compounding-gap is felt |
| Voice-dictate `/sb-wiki-reflect` separate command | Deferred | If Stage 2 inline prompt proves insufficient |
| 5th page type (`Framing` for personal lenses) | Open | If a real ingest hits a gap not covered by current 4 types or by Source `My take` / Topic `Open questions` |
| Multi-source ingest, re-ingest of updated raw, raw deletion handling | Not designed | When a real use-case emerges |
| Page lifecycle past stub (mature → stale → archived) | Not designed | When real signals emerge |
| Concurrent edit handling | Single-user vault, low risk | If conflicts surface |
| `wiki/concepts/graph-databases.md` first-create | The source file lives in `raw/`. The first `/sb-wiki-ingest` of that source follows the standard flow: a source page in `wiki/sources/` is created first; the concept page at `wiki/concepts/graph-databases.md` is auto-created as a stub only if the stub rule fires (`graph-databases` in source title or in an extracted Notable Quote / Substance bullet — see Stub policy) | First ingest of the source |

## Downstream impact (propagation queue)

These edits happen at sb-os v2 build time. Until v2 lands, the user's vault retains its current pre-cutover state and only the items marked **already applied** apply today.

**sb-os repo (v2 build):**

- **NEW `sb-os/workflows/sb-wiki-ingest/`, `sb-wiki-create-topic/`, `sb-wiki-lint/`, `sb-wiki-query/`**: workflow source files implementing the four operations defined above.
- **`sb-os/wiki/docs/wiki-schema.md`**: this schema doc, relocated from `1-projects/second-brain-evolution/sb-wiki-build/wiki-schema.md` at v2 build time (p2-1). Now at canonical home.
- **`sb-os/install/module-manifest.json`**: add the four `sb-wiki-*` components so the installer generates loaders.
- **`sb-os/wiki/claude-mds/wiki.md`** (managed CLAUDE.md source per architecture §4): replace the v1 placeholder with operational rules referencing this schema (page types — call out extensibility, ingest flow, stub policy, citation format, index rules, lint's raw-index responsibility). Installs to `{vault}/{wiki_root}/CLAUDE.md`.
- **`sb-os/install.py`**: confirm `wiki_root` prompt persists into `sb-os.json` (already in v1 per architecture §6 manifest schema); v2 adds the `sb-wiki-*` loader generation.

**Vault-side (post `python install.py` to v2):**

- **`{wiki_root}/CLAUDE.md`** (managed): rewritten by the installer from `sb-os/wiki/claude-mds/wiki.md` per the §6 marker block protocol — content inside `<!-- sb:start v=1 -->...<!-- sb:end -->` is replaced; user content outside markers is preserved.
- **NEW `{wiki_root}/raw/studies/CLAUDE.md`**: operational rules for study captures (filename pattern `YYYY-MM-DD-{slug}.md`, immutability, relationship to ingest). User-owned per architecture §7 ("Subfolder CLAUDE.mds within PARA are user-owned, untouched by sb-os") — created on first `sb-wiki-ingest` of a study source if absent, or by the user manually.
- **NEW (folder + leaf indexes, created lazily as origins surface; lint creates missing raw indexes automatically)**: `{wiki_root}/raw/studies/`, `raw/studies/studies.md`, `wiki/concepts/`, `wiki/concepts/concepts.md`, `wiki/entities/`, `wiki/entities/entities.md`, `wiki/topics/`, `wiki/topics/topics.md`, `wiki/sources/`, `wiki/sources/{origin}/{origin}.md`.
- **User-area CLAUDE.mds that route study output**: any user-side CLAUDE.md that points `/sb-tutor` or multi-source notes at a learning area should route to `{wiki_root}/raw/studies/` (matches root CLAUDE.md hard-rule already in place pre-cutover).

**v4 — purpose-lens propagation (queued by this schema change):**

This schema section ("Regulatory layer — purpose.md", the folder-structure row, the `type: purpose` frontmatter note, and the lint skip-guarantee) is the spec; the following edits implement it. Until they land, the lens is undefined in the runtime workflows.

- **`wiki/workflows/sb-wiki-ingest/sb-wiki-ingest.md`**: implement Step 0.5 (load/parse `purpose.md`; absent → lens OFF; malformed → warn, lens-OFF) and the lens modulation at Steps 2, 5, 3·7b, 10 (Step 6 trigger-detection untouched); carry the purpose band in the silent-mode structured summary; add a Path Resolution row for `{wiki_root}/purpose.md`; add a Failure Mode row (malformed → warn, lens-OFF).
- **`wiki/claude-mds/wiki.md`** (managed CLAUDE.md source): document the regulatory file + optionality in the marker block; re-run `python install.py` to rewrite `{wiki_root}/CLAUDE.md`.
- **Runtime shared files (base behavior, already applied with this schema change):** `wiki/workflows/shared/frontmatter-schemas.md` (non-page `type: purpose` note) and `wiki/workflows/shared/folder-structure.md` (`purpose.md` tree entry + lint-skip row).

**Already applied (user's pre-cutover vault):**

- Root `CLAUDE.md` routing row: `Study session output (sb-tutor, multi-source notes)` → `3. Resources/knowledge-base/raw/studies/` (append). Listed for completeness of the propagation record.
