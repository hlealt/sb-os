# Wiki Schema (v3 — post-reconciliation)

> **Status:** Locked design. Operational spec for the Karpathy-style wiki layer shipped by **sb-os v2** (per `sb-os-build/second-brain-os-architecture.md` §12 and Decisions Log #12). sb-os v1 ships only the `wiki_root` config slot in `sb-os.json` (default `3-resources/knowledge-base/`), the empty default folder, and a placeholder managed `CLAUDE.md` at `{wiki_root}/CLAUDE.md`. The schema, the four `sb-wiki-*` components, and any populated wiki content described below are out of v1 scope — they ship in **sb-os v2**. Agents and CLAUDE.md files reference this document only after v2 lands.

## Purpose & context

Defines schema and operational rules for the wiki layer shipped by sb-os v2. Pattern source: [Karpathy's LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f). Wiki content lives at `{wiki_root}/` (vault-side, user data), where `{wiki_root}` is the configurable path persisted in `sb-os.json` at install time (default `3-resources/knowledge-base/`). All paths in this document that begin with `3. Resources/knowledge-base/` are pre-cutover examples — read them as `{wiki_root}/` once sb-os is installed.

Goal: turn high-volume reading (articles, podcasts, papers, repos, study sessions) into compounding knowledge — cross-referenced, contradiction-flagged, queryable.

User mode preference: **query-driven** (asks the agent rather than browses), with **mandatory cross-linking on ingest** so wikilinks-graph stays viable as fallback. **No browse-mode affordance in lint v1.**

Audience: future agents executing wiki ingest / create-topic / lint / query operations, and the user reviewing those operations.

## Installer scope guarantee

The sb-os installer (`install.py`) NEVER reads or writes any file under `{wiki_root}/wiki/` or `{wiki_root}/raw/`. The installer's write surface is limited to: managed CLAUDE.mds (marker blocks only), `.claude/` thin loaders, and `sb-os.json` at the vault root. Wiki content — leaf indexes (`wiki/concepts/concepts.md`, `wiki/entities/entities.md`, `wiki/topics/topics.md`, `wiki/sources/{origin}/{origin}.md`), raw leaf indexes (`raw/{origin}/{origin}.md`), source pages, concept pages, entity pages, topic pages, and `log.md` — is created and maintained EXCLUSIVELY by `/sb-wiki-lint` and `/sb-wiki-ingest`. Re-running `install.py --upgrade` is safe at any time and will not modify, overwrite, or delete any wiki content.

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

A per-source synthesis. 1:1 with a raw file. Combines agent-written content with user-written reflections (My take / Open questions / Dive deeper). Sources are the **entry points** of the wiki — flexibility in their structure is required, not optional.

Naming: filename mirrors the raw counterpart exactly.

## Folder structure

```
3. Resources/knowledge-base/
├── log.md                        single append-only event log
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

## Folder subdivision

Per-kind subfolders within a type folder are an opt-in pattern lint proposes when one kind crosses the proposal threshold. Subdivision is structural — pages physically move into the subfolder; wikilinks still resolve by filename (Obsidian Settings → Files & Links → "New link format" = Shortest path when possible — required, see README "Obsidian setup").

### Threshold

| Pages with one `kind:` value in a type folder | Lint behavior |
|-----------------------------------------------|---------------|
| <5 | Silent — no signal |
| ≥5 | PROPOSE — surface a SUBDIVISION PROPOSAL block in the lint report; user accepts/rejects per kind |

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

Local storage for images and other binary attachments referenced by source pages and wiki pages. The standard is **flat, single shared folder** at `{wiki_root}/raw/assets/`. Karpathy-style workflow: after clipping a page or article into `raw/{origin}/`, the user runs Obsidian's core "Download attachments for current file" command (introduced in Obsidian 1.8.0, January 2025) to download all referenced external images locally. This keeps images viewable by LLMs on demand and immune to upstream URL rot.

### Path

`{wiki_root}/raw/assets/` — single shared folder at the root of `raw/`. Flat. No per-source or per-note subfolders.

**Why flat.** Obsidian's core "Download attachments for current file" command follows the global "Default location for new attachments" setting and does NOT support per-file subfolder templates (`${filename}`, `${noteFileName}`, etc., as of Obsidian 1.9.6). Every download for every note lands in the same destination. The schema standardizes on that destination rather than fighting it.

### Maintained by

The user, via Obsidian. Configuration: Obsidian Settings → Files and links → "Default location for new attachments" → `raw/assets`. The user binds the "Download attachments for current file" command to a hotkey (e.g. Ctrl+Shift+D) and runs it after each clip.

**Agents NEVER write to `raw/assets/`.** Neither `sb-wiki-ingest`, `sb-wiki-lint`, `sb-wiki-create-topic`, nor `sb-wiki-query` create, move, rename, or delete files inside `raw/assets/`. The folder is user-owned content, populated by Obsidian's own command.

### Filenames

Whatever Obsidian writes — typically the original remote filename, or `Image 1.jpg` / `Image 2.jpg` patterns when filenames collide or are missing. (A known Obsidian 1.9.6 bug affects this renaming; fix pending upstream.) Agents do NOT enforce a filename convention inside `raw/assets/`.

### Referencing assets

Source pages (`raw/{origin}/*.md`) and wiki pages (`wiki/concepts/*.md`, `wiki/entities/*.md`, `wiki/topics/*.md`, `wiki/sources/*.md`) reference assets via standard Obsidian image embeds: `![[filename.png]]`, `![[filename.jpg]]`, etc. Obsidian resolves these via its global attachment search; no folder-relative path is required in the embed.

### Lint behavior — SKIP entirely

`raw/assets/` is NOT a raw origin. It has no source pages, no wiki sources index, no leaf index. Lint MUST NOT:

| Behavior | Required state |
|----------|----------------|
| Create an index file at `raw/assets/assets.md` | NEVER. `raw/assets/` is not an origin. |
| Walk `raw/assets/` as part of raw-origin sweeps (step 7 of `/sb-wiki-lint`) | NEVER. Skip the directory entirely. |
| Count files inside `raw/assets/` toward orphan detection (in or out) | NEVER. Assets are out of scope for orphan computation in BOTH directions — they are not eligible to be orphans, and image embeds inside them do not count as inbound links. |
| Enforce filename conventions inside `raw/assets/` | NEVER. Obsidian writes whatever names it writes. |
| Treat `raw/assets/` as an origin folder for any other purpose | NEVER. |

Workflows that walk `{wiki_root}/raw/` MUST explicitly exclude `raw/assets/` from their iteration sets.

### Pre-existing exceptions

A vault MAY have legacy asset folders nested inside specific origin subdirectories (for example, `raw/mails/assets/{message-folder}/`, written historically by tools like `gmail-bridge` before this standard existed). These are NOT the standard going forward. New assets land in `{wiki_root}/raw/assets/`. Existing legacy structures are user-owned, untouched by lint and any other sb-os component, and may be migrated to the standard at the user's discretion.

## Naming convention

| Element | Rule |
|---------|------|
| Wiki page filename | `lowercase-kebab.md` |
| Source page filename | mirrors raw counterpart **exactly**, including the date format the origin uses (`YYYY-MM-DD-slug.md` for `every/`, `YYYY_MM_DD-slug.md` for `mails/`, etc.). Agents do NOT normalize date formats. |
| Wikilinks anywhere | use the format that matches the target file's actual filename |
| Wikilinks in body | `[[slug.md]]` (with `.md` extension, matching existing index format) |
| Wikilinks in frontmatter | `"[[slug.md]]"` (quoted) |
| Type folder | disambiguates collisions; same slug may exist in `concepts/` and `entities/`. **Forbidden**: same slug in `concepts/` and `topics/` (if reclassified, the old slug retires) |

## Frontmatter schemas

### Common (all types)
```yaml
---
type: concept | entity | topic | source
created: YYYY-MM-DD
last-touched: YYYY-MM-DD
related:
  - "[[other-page.md]]"
tags: []                    # optional, free-form
---
```

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
No additional frontmatter. The trigger that produced the topic is recorded in `log.md` (the `candidate-topic` and `topic-created` entries).

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
| `Open questions` | The user — what's unclear, what to dive into |
| `Dive deeper` | The user — checklist of follow-ups |

The `---` separators visually mark agent-half / user-half / sources.

User-half sections are created as **empty shells** (heading only, no content) by ingest step 2 — not stub-flagged when empty (this is the page's natural post-ingest state). The user fills them via Stage 2 of the ingest checkpoint OR later in Obsidian editor.

## Citation format

| Layer | Format | Maintained by |
|-------|--------|---------------|
| Inline in body | `[^N]` at point of claim | Agent (during ingest) |
| Sources section | `[^N]: [[YYYY-MM-DD-slug.md]]` (footnote defs ARE wikilinks; Obsidian indexes them in the graph) | Agent (during ingest, renumbered by lint) |
| Frontmatter `sources:` | NOT USED | — |

The user never writes citations manually. Renumbering on edit is agent-handled.

**Footnote rules:**
- One footnote per source, never merged. Multi-source claims get multiple markers on the same sentence: `...claim X[^1][^2][^3]`.
- Lint rebuilds the Sources section by reading inline `[^N]` markers. If the user manually added prose context within a footnote definition (e.g., `[^1]: [[file.md]] — note: this is the original`), lint preserves user prose; only renumbers.
- Stale footnote definitions (no longer referenced inline) are removed by lint.

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
| Post-reflect-empty | `—` (em-dash, U+2014) | Stage 2 ran and the user explicitly recorded reflection content without a take. Finalized. | `My take` heading present, body empty while `Open questions` or `Dive deeper` has substantive content |
| Reflected | 1-sentence opinion derived from the source page's `My take` section (≤280 chars; truncate with ellipsis if longer) | The user filled `My take` on the source page. Index cell mirrors the take. | `My take` heading present, body has substantive content |

**Rationale.** The two empty states have different downstream behaviors (see below) and different remediations from the user's standpoint. Blank conflates them. Two human-readable, typographically distinct tokens preserve the distinction at a glance and let lint detect each state programmatically. `pending` was chosen for its action-pending semantics (a verb-shaped keyword the user reads as "needs me to act"); `—` (em-dash) was chosen for its long-standing convention as a typographic null marker (the user reads it as "nothing here, intentionally").

### Lint and ingest behavior per state

| State | Written by | When | Lint behavior |
|-------|-----------|------|---------------|
| `pending` | `sb-wiki-ingest` step 8 (initial) AND step 11 if Stage 2 is skipped, ignored, or receives no routed content | At end of ingest when no take was captured | The 7-day staleness rule applies — lint may re-sync (no-op if source page's `My take` body is still empty) |
| `—` | `sb-wiki-ingest` step 11 if Stage 2 receives `Open questions` or `Dive deeper` content while `My take` remains empty — see Stage 2 finalization rule below | At end of Stage 2 | Final. The 7-day staleness rule does NOT apply — `—` rows do NOT age out. Lint preserves `—` on every pass (no-op). |
| Reflected (1-sentence preview) | `sb-wiki-ingest` step 11 if the user filled `My take`; refreshed by `sb-wiki-lint` step 6 on every run | At end of Stage 2 / on every lint pass | Re-sync from the source page's `My take` section on every run, preserving the three-state distinction (if the source page's `My take` body is now empty after previously having content, the lint downgrades the cell to `—` only if a `pending` state cannot be inferred — see "Re-sync algorithm" below) |

**Stage 2 finalization rule.** The `—` token is written ONLY when the user explicitly engaged Stage 2 and routed reflection content to `Open questions` or `Dive deeper` while leaving `My take` empty. If the user answered `n`, ignored the prompt, or sent an unrelated next command, the cell stays `pending` — the user did not produce a finalization signal.

**Re-sync algorithm (lint step 6).** For each row:
- If the source page's `My take` section has substantive content → write the 1-sentence preview (overwriting the prior cell value).
- If the source page's `My take` section is empty AND the cell currently reads `—` → preserve `—` (already finalized).
- If the source page's `My take` section is empty AND the cell currently reads `pending` → preserve `pending`.
- If the source page's `My take` section is empty AND the cell currently reads anything else (legacy blank, stray content, etc.) → write `pending` (default to action-pending; safer to over-prompt the user than to over-finalize).

The raw index (`raw/{origin}/{origin}.md`) keeps its existing format with `Wiki` column — factual only, no opinion. Raw indexes are created and maintained by lint (see `/sb-wiki-lint`).

## Topic creation rules

**Agent NEVER auto-creates topic pages.** All topic creation flows through the `sb-wiki-create-topic` skill — agent-invokable mid-ingest when the user accepts a proposed topic, AND auto-discovered by Claude Code when the user later expresses intent to create or promote a topic (e.g., "create a topic for X", "promote the mcp-debate candidate"). The skill has no slash command — invocation is intent-driven.

The agent detects 3 candidate-topic triggers and:
1. Logs them in `log.md` as `candidate-topic` H2 entries.
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

**Speculative tier (new-stub conceptual fit).** Fires when ALL of these hold:

| Condition | Definition |
|-----------|------------|
| New stub | Candidate is a `stub-candidates` entry created in THIS ingest run — never an existing page |
| Token overlap | The stub's preamble (1–2 sentence factual sentence written at step 5) shares ≥2 substantive tokens with the topic's `Scope` section text. Tokenization: lowercase, strip stopwords (`the/a/an/of/for/in/on/and/or/to/is/are/with/by/that/this/it/as`), preserve kebab-case as a single token (`marginal-returns-to-intelligence` matches `marginal returns` if both tokens appear in scope) |
| Cap | Maximum 2 speculative fires per ingest. If >2 candidates qualify, rank by token-overlap count (descending), keep top 2, drop the rest as `topic-coverage-candidate` log entries (sibling of parent `ingest`, informational, lint reviews periodically) |
| Dedupe | If a topic already fires firm for this source, suppress its speculative fire (firm wins) |

Speculative tier is mechanical (token overlap is computed, not LLM-judged) but heuristic in confidence. It is rendered in a SEPARATE block at Stage 1 (`SPECULATIVE TOPIC UPDATES (low-confidence, default reject)`) and defaults to reject — same default as firm, but the separation signals confidence to the user.

**Update behavior on user accept (append-only).** The agent updates the topic page following the same append-only protection used for entity/concept pages:

| Operation | Detail |
|-----------|--------|
| Add citation | Append `[^N]: [[<raw-filename>]]` to the topic's `Sources` section (renumber locally; lint normalizes globally) |
| Append section entry | Add ONE bullet under the topic-shape-appropriate section (`Key positions / Angles` for debate-shaped topics; `Timeline` for evolution-shaped; otherwise `Key concepts` / `Key entities` if the source introduces a new wikilinkable page; otherwise no body bullet — citation-only update) with inline `[^N]` marker |
| Bump frontmatter | Update `last-touched: <today>` |
| NEVER overwrite | Existing prose, `Scope`, position bullets, or `Open questions` content stays untouched. Append-only, per stub-policy "Append-Only Protection" |

**Log entry.** Each accepted topic update emits a sibling `topic-updated` H2 entry in `log.md`, referenced from the parent `ingest` by timestamp.

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
| 3 | Are they co-members of a group (siblings) co-mentioned but not co-substantive in this source? | ONE group page. Per-member only when standalone treatment exists. | Continue to test 4. |
| 4 | Is one a producer/maintainer/author and the other its product/work? | TWO pages — distinct identities. | TWO pages — independent. |

The clustering decision is the AGENT'S RESPONSIBILITY upstream of mechanical fire. Step 2 substance-bullet writers must respect the cluster set: name only page-level entities/concepts; sub-cluster names go in prose without wikilinks.

Domain-neutral examples and the operational reference: `wiki/workflows/shared/stub-policy.md` § "Page Granularity".

### Stub creation (ingest)

The agent auto-creates a stub Concept or Entity page when the cluster representative appears in EITHER of the two mechanical branches OR fires the discretionary branches:

1. **A `Substance` bullet** (the agent's own output from step 2) — MECHANICAL fire on the cluster representative.
2. **Source title/headline** — fires only when the title name ALSO appears in a `Substance` bullet (see "Title-branch rule" below). Title-only names go to discretion.
3. **An extracted Notable Quote** — DISCRETIONARY (see "Notable Quote stub creation" below).

If none of the three branches fire, log a `candidate-mention` in `log.md` for periodic review by lint. Do NOT create a page.

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

## Operations

Four operations covering the wiki lifecycle:

| Component | Type | Invoked by | Purpose |
|-----------|------|------------|---------|
| `/sb-wiki-ingest <slug>` | Slash command | The user | Distill a raw source into wiki pages |
| `sb-wiki-create-topic` | Skill (auto-discovered) | Agent mid-ingest, OR auto-fired when the user expresses intent | Create a topic page from a candidate or freshly-proposed topic |
| `/sb-wiki-lint` | Slash command | The user | Health check + index maintenance for `raw/` and `wiki/` |
| `/sb-wiki-query <question>` | Slash command | The user | Synthesize an answer from wiki + optionally file the result back |

### `/sb-wiki-ingest`

Single command: `/sb-wiki-ingest <slug>` where slug is a raw filename or unique substring.

| Step | Operation | Owner |
|------|-----------|-------|
| 1 | Read raw file | Agent |
| 2 | Write `wiki/sources/{origin}/{date}-{slug}.md` (`Substance` and `Connections` always; `Notable quotes` / `Methodology` / `Counterpoints` per source kind; user-half sections present as empty shells with headings only). **Substance bullets MUST name entities/concepts at page-cluster granularity** per Page granularity § — sub-cluster names go in prose without wikilinks | Agent |
| 3 | Identify entity/concept mentions; **cluster candidates by page-granularity** (variants, whole+part, siblings, producer+work — see Page granularity §); for each cluster representative, apply the stub-creation rule (Substance bullet = mechanical; title-only = discretion; Notable Quote = discretion). ALSO walk `wiki/topics/*.md` and identify existing topic pages relevant to this source per the relevance-detection rule (see "Existing topic updates" §) — build a `candidate-topic-updates` set | Agent |
| 4 | Update existing entity/concept pages with new perspective + citation; populate `Open variants / debates` section if Contradiction fires. **Agent NEVER overwrites a main section that already contains substantive content (>50 words) — only appends new sections, adds bullets to existing lists, or adds footnote definitions to Sources. User-fleshed content is treated as authoritative.** Existing topic pages are NOT updated at this step — they go through the Stage 1 user gate per "Existing topic updates" § | Agent |
| 5 | Create stubs for new entities/concepts that meet the rule | Agent |
| 6 | Detect candidate-topic triggers (Contradiction, Evolution, Cross-application); add `> [!warning] Disputed` callouts on Contradiction-`same-scope-opposing` | Agent |
| 7 | Update raw index: `Wiki = Yes` | Agent |
| 8 | Update wiki sources index (`What it says` filled; `My take` set to `pending` — populated post Stage 2 per the three-state rule) | Agent |
| 9 | Append `ingest` entry to `log.md` summarizing operations + candidates (separate `candidate-topic`, `concept-created`, `entity-created` H2 entries when triggered) | Agent |
| 10 | **Stage 1 checkpoint**: present structured table + PROPOSED TOPICS block; the user accepts-all / rejects N / aborts file changes; per topic: accept (agent invokes `sb-wiki-create-topic` skill now) / defer (keeps as candidate in log). Approved changes commit before Stage 2 begins. | Agent + User |
| 11 | **Stage 2 checkpoint** (optional, post-commit): present reflection prompt after approved changes are committed. The user can ignore it, decline it, or answer with freeform reflection content in any order. The agent routes content to `My take` / `Open questions` / `Dive deeper` by intent, writes routed sections, and syncs the `My take` column to the wiki sources index. | Agent + User |

**No mid-flow user input during steps 1–9.** All user interaction happens at steps 10–11.

#### Stage 1 checkpoint format

```
INGEST PREVIEW — <source slug>

| # | file | action | preview |
|---|------|--------|---------|
| 1 | wiki/sources/blog-cloudflare/2026-XX-XX-code-mode.md | new | <first paragraph of Substance> |
| 2 | wiki/concepts/model-context-protocol.md | updated | + section "Code Mode perspective" |
| 3 | wiki/concepts/code-execution-pattern.md | new (stub) | <preamble first sentence> |
| 4 | wiki/entities/cloudflare.md | new (stub) | <preamble first sentence> |
| 5 | log.md | appended | ingest + concept-created + entity-created + candidate-topic entries |
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
- Topic `accept N`: agent invokes the `sb-wiki-create-topic` skill mid-run with the proposed topic name; appends `topic-created` entry to log.
- Topic `defer N`: candidate-topic entry persists in log; the user may promote later by expressing intent (auto-fires the `sb-wiki-create-topic` skill).
- Topic update `accept N`: agent applies the append-only update to the topic page per "Existing topic updates" §; appends `topic-updated` entry to log.
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

Explicit or semantically clear content MUST go to its matching section even if it arrives while another section is displayed. Example: "quero dive deeper em graph databases" goes under `Dive deeper`, never under `My take`. If a response contains multiple routed spans, write each span under its matching heading. If a response contains substantive text with no routing signal, write it under `My take`. If routing is ambiguous and misrouting would change meaning, ask one targeted clarification.

The agent re-syncs the `My take` index cell per the three-state rule defined under "Wiki sources index format" — write the 1-sentence preview if `My take` was filled; write `—` if Stage 2 produced `Open questions` or `Dive deeper` while `My take` stayed empty; leave `pending` if Stage 2 was declined, ignored, or produced no routed content.

### `sb-wiki-create-topic`

A skill agents can invoke mid-ingest (when the user accepts a PROPOSED TOPIC at Stage 1) OR auto-fired by Claude Code when the user later expresses intent to create or promote a topic (e.g., "create a topic for X", "promote the mcp-debate candidate"). No slash command — invocation is intent-driven.

| Step | Operation | Owner |
|------|-----------|-------|
| 1 | Resolve topic name; if from a candidate, load the candidate-topic log entry (claim A, claim B, trigger, sources) | Agent |
| 1.5 | **Scope-overlap check (semantic, not slug).** Read `wiki/topics/topics.md` and compare the proposed scope sentence to every existing row's `Scope` cell. If overlap is plausible (shared subject, shared sources, shared positions, sibling/sub-debate framing), surface three options to the user: `extend N` (append a new `Position` / `Angle` to the existing topic; no new page), `new` (proceed with a new sibling-cross-linked topic), or `abort`. Skipped only when the caller (e.g., `/sb-wiki-query` Step 7a) passes `overlap-checked: true` proving the check already ran upstream. Slug-collision check from step 1 is necessary but NOT sufficient — both checks must pass. | Agent + User |
| 2 | Write `wiki/topics/{slug}.md` with frontmatter, `Scope` (required), `Sources` (required), and optional sections per topic shape (see Topic page menu). On `new` from step 1.5, also append the new topic's wikilink to the overlapping topic's `related:` frontmatter (sibling cross-link). | Agent |
| 3 | Cross-link from triggering concept/entity pages: add wikilink to the new topic in their `Related` section | Agent |
| 4 | Append `topic-created` entry to `log.md`; if from a candidate, reference the original candidate by timestamp | Agent |
| 5 | Update `wiki/topics/topics.md` leaf index with the new entry | Agent |

When invoked mid-ingest, no separate user checkpoint — the parent `/sb-wiki-ingest` Stage 1 acceptance covers it AND the step 1.5 overlap prompt fires inline before commit. When auto-fired by user intent, the agent runs step 1.5 first, then confirms the proposed sections + scope sentence with the user before writing (single confirmation checkpoint, two distinct prompts when overlap is detected).

### `/sb-wiki-lint`

Single command: `/sb-wiki-lint`. Runs across `raw/` and `wiki/` folders. Mostly read-only; deterministic index sync writes are auto-applied (no diff to accept). Judgment-bearing index cells are never script-filled.

Before walking the tree, agents run this command from the vault root with the active Python interpreter:

```bash
python 3-resources/tools/sb-os/wiki/scripts/sb-wiki-lint-deterministic.py --apply --report 3-resources/knowledge-base/lint-deterministic-report.json
```

The script performs deterministic maintenance and emits `judgment_needed`. The agent reads every queued item, reads the referenced file, and fills the required semantic index cell before appending the lint log entry.

| Step | Operation |
|------|-----------|
| 1 | Walk all wiki pages — detect stubs (structural rule) and record age via `created` |
| 2 | Walk all wiki pages — detect orphans (no inbound wikilinks). **Orphan-detection scope is STRICT** — see "Orphan-detection scope" below |
| 3 | Walk wiki concept/entity pages — detect unresolved Disputed callouts (older than 30 days without resolution) |
| 4 | Walk `log.md` — detect candidate-topics aging without promotion (>30 days) |
| 5 | Walk all wiki pages — verify wikilinks resolve (broken if target file missing); collect broken links |
| 6 | For each `wiki/sources/{origin}/` — re-sync `My take` column from each source page's `My take` section per the three-state rule (`pending` / `—` / reflected preview — see "Wiki sources index format" §); renumber footnotes; remove stale footnote definitions |
| 7 | For each `raw/{origin}/` — verify `{origin}.md` index exists; if missing, create it with the standard `\| File \| Title \| Date \| Wiki \|` columns. For each raw file in `{origin}/`, ensure a row exists with `Wiki = No` (default) or `Yes/Partial` (preserved). Same for `raw/studies/studies.md`. **Index creation and maintenance is the agent's job**, not the user's. |
| 7.5 | Folder-subdivision detection. For `wiki/concepts/` and `wiki/entities/`, group pages by `kind:` frontmatter. Surface kinds at ≥5 pages as a SUBDIVISION PROPOSAL block. Skip `wiki/topics/` (count <20) and `wiki/sources/` (already subdivided by origin). On user accept at step 9, the agent creates `{type}/{subfolder}/`, leaf index, parent CLAUDE.md marker-block routing rules, moves pages, rewrites parent index as router, and appends a `subdivision:` field to the step-8 log entry. Naming and policy per schema § "Folder subdivision". |
| 8 | Append `lint` entry to `log.md` summarizing findings: stubs aged, orphans, unresolved callouts, candidates aging, broken links, index sync count, raw indexes created/updated, plus subdivision proposals and executed moves from step 7.5 |
| 9 | Present findings to the user (read-only summary for findings 1-7; SUBDIVISION PROPOSAL is the only interactive block — user accepts per kind or defers all) |

#### Lint output format

Step 7 does not authorize scripts to write blank semantic cells. `Description`, `Scope`, and `What it says` require LLM judgment. Raw index `Title` is script-safe only when it comes from frontmatter or an H1; filename slug guesses are forbidden.

```
LINT REPORT — 2026-04-30 09:00

Stubs aged >30 days (3): [[X.md]], [[Y.md]], [[Z.md]]
Orphans (no inbound) (2): [[A.md]], [[B.md]]
Unresolved Disputed callouts (1): [[mcp-debate.md]] — flagged 2026-04-12
Candidate-topics aging without promotion (1): "mcp-debate" — logged 2026-04-12
Broken wikilinks (0)
Index sync — wiki/sources My take refreshed: 4 source pages
Index sync — raw indexes: 1 created (raw/studies/studies.md), 3 rows added across raw/{origins}
Footnotes renumbered: 2 source pages

No action required (lint is read-mostly; index sync writes auto-applied).
```

#### Orphan-detection scope (STRICT)

Orphan-detection is the lint signal for "the wiki is not actually building knowledge about this entity / concept / topic." It MUST be computed against synthesis pages only — not against every file in `{wiki_root}/`.

| Scope | Files |
|-------|-------|
| **In scope for inbound-link computation** | `wiki/concepts/*.md`, `wiki/entities/*.md`, `wiki/topics/*.md` — and ONLY these |
| **Out of scope** (do NOT count as inbound links toward orphan status) | `log.md` entries, `wiki/sources/{origin}/{origin}.md` indexes, raw source pages under `raw/`, `wiki/sources/{origin}/<date>-<slug>.md` source pages, and any leaf index file (`concepts.md`, `entities.md`, `topics.md`, `{origin}.md`, `studies.md`) |

**Rationale.** Log entries and source-page footnote definitions are EVIDENCE OF MENTION, not synthesis. An entity referenced only by `log.md`, only by a source page, or only by a raw index is an entity the wiki has noticed but is not actively cross-linking from real synthesis. Orphan-detection is meant to surface exactly these — pages that exist as stubs but have not earned a place in the actual knowledge graph. Forcing inbound links to come from real wiki content (concept / entity / topic pages) keeps the bar high and preserves the orphan signal's diagnostic value.

**Practical implication.** A new stub created from a source page's `Notable Quotes` will, by design, be flagged as an orphan on the next lint run if no concept/entity/topic page links to it from its body or `Related` section. This is correct behavior, not a false positive — the orphan flag is the lint asking the user (or a future ingest) whether the stub deserves real synthesis.

### `/sb-wiki-query`

Single command: `/sb-wiki-query <question>`. Returns a synthesized answer; optionally files the answer back as a wiki page.

| Step | Operation | Owner |
|------|-----------|-------|
| 1 | Parse question; identify candidate page types (concept / entity / topic) and likely keywords | Agent |
| 2 | Read leaf indexes (`concepts.md`, `entities.md`, `topics.md`) — sub-agent picks pages by name match + index summary | Agent |
| 3 | If index lookup is ambiguous, fall back to `grep` / `ripgrep` over `wiki/` content (Karpathy fallback — never embeddings/RAG) | Agent |
| 4 | Read picked pages; if depth needed, follow wikilinks to neighbors | Agent |
| 5 | Synthesize answer with inline citations to wiki pages (`[[page.md]]`) and source pages (footnote definitions) | Agent |
| 6 | Present answer + offer to file as a wiki page (Concept / Entity / Topic) if "valuable enough" — the user picks file/skip | Agent + User |
| 7 | If filed: for Topic, run a scope-overlap pre-check against `wiki/topics/topics.md` (offering `extend N` / `new` / `abort` to the user) before invoking `sb-wiki-create-topic` with `overlap-checked: true` — `extend N` writes the synthesized answer as a new `Position` / `Angle` on the existing topic and skips skill invocation; for Concept / Entity, write directly to `wiki/concepts/` / `wiki/entities/`; append `query` entry to `log.md` | Agent + User |

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

10 types active at v1. Each entry is an H2 heading: `## [YYYY-MM-DD HH:MM] type | brief`.

| Type | Trigger | User action surfaced |
|------|---------|----------------------|
| `ingest` | `/sb-wiki-ingest <slug>` | Review diff at Stage 1; reflect at Stage 2 if desired |
| `candidate-topic` | Auto-fired during `ingest` or `lint` when 1 of 3 triggers fires. **Always a sibling H2 entry** (not nested under the parent ingest), referenced from the parent ingest entry by timestamp | Decide whether to promote via the `sb-wiki-create-topic` skill (express intent to fire it) |
| `candidate-mention` | Auto-fired during `ingest` step 3 when an entity/concept name surfaces but the stub-creation rule does NOT fire (per Stub policy). **Sibling H2 entry**, referenced from the parent ingest by timestamp | None — informational; lint reviews periodically and may promote to a stub if the name recurs |
| `topic-coverage-candidate` | Auto-fired during `ingest` step 3.7 speculative tier when more than 2 new-stub conceptual-fit matches exist for a given ingest (the cap drops the lower-ranked candidates). **Sibling H2 entry**, referenced from the parent ingest by timestamp | None — informational; lint reviews periodically and may surface them as topic-update suggestions on a future ingest of a related source |
| `concept-created` | Auto-fired during `ingest` when a stub Concept is created. **Sibling H2 entry**, referenced from the parent ingest by timestamp | None — informational; greppable by type |
| `entity-created` | Auto-fired during `ingest` when a stub Entity is created. **Sibling H2 entry**, referenced from the parent ingest by timestamp | None — informational; greppable by type |
| `topic-created` | `sb-wiki-create-topic` skill (mid-ingest acceptance OR user-intent-driven invocation) | None — closes the loop. Lets lint know which candidates are spent |
| `topic-updated` | `/sb-wiki-ingest` Stage 1 acceptance of a PROPOSED TOPIC UPDATE row (firm OR speculative tier). **Sibling H2 entry**, referenced from the parent ingest by timestamp. The entry's `match` field records which tier fired (`firm-{type}` or `speculative-token-overlap`) | None — informational; lint can audit accreted topics |
| `lint` | `/sb-wiki-lint` | Review findings: stubs aged, orphans, unresolved contradictions, candidates aging, raw index sync |
| `query` | `/sb-wiki-query`, only if the user files the answer back | None unless filed back as a wiki page |

### Entry shapes

```markdown
## [2026-04-30 14:32] ingest | Code Mode (Cloudflare)
- source: [[2026-XX-XX-code-mode-mcp.md]] (new)
- updated: [[model-context-protocol.md]] (+ Code Mode perspective)
- candidate-topic: see entry at 14:32
- concept-created: see entry at 14:32
- entity-created: see entry at 14:32

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
- from-ingest: 2026-04-30 14:32

## [2026-04-30 14:32] concept-created | code-execution-pattern
- page: [[code-execution-pattern.md]]
- kind: pattern
- from-ingest: 2026-04-30 14:32

## [2026-04-30 14:32] entity-created | cloudflare
- page: [[cloudflare.md]]
- kind: company
- from-ingest: 2026-04-30 14:32

## [2026-04-30 16:10] topic-created | mcp-debate
- resolves: candidate from 2026-04-30 14:32
- page: [[mcp-debate.md]]
- framing: "When MCP earns its complexity vs. when it doesn't"

## [2026-04-30 14:32] topic-updated | mcp-evolution
- page: [[mcp-evolution.md]]
- match: key-concept overlap ([[model-context-protocol.md]])
- change: + bullet under "Timeline" + footnote citation
- from-ingest: 2026-04-30 14:32

## [2026-05-07 09:00] lint | weekly health-check
- stubs aged >30d (3): [[X.md]], [[Y.md]], [[Z.md]]
- orphans (no inbound) (2): [[A.md]], [[B.md]]
- candidates aging (1): "mcp-debate" (logged 2026-04-12)
- broken wikilinks (0)
- index sync (wiki sources My take): 4 pages
- index sync (raw): 1 created, 3 rows added
```

## Component structure

Each wiki capability is its own component under the `sb-` prefix (alongside other sb-os components such as `sb-vault-ops`, `sb-tutor`, `sb-archivist`). No umbrella `sb-wiki` skill — capabilities are independent.

Source files live in the sb-os repo under `sb-os/workflows/sb-wiki-*/`. Skills and commands installed into `.claude/` are **thin loaders** that point back to those source files (per architecture doc §4 loader pattern). Editing installed loaders is forbidden — the source is the repo. Re-running `python install.py` regenerates loaders.

| Component | Type | Source (sb-os repo) | Installed loader (vault) | Purpose |
|-----------|------|--------------------|--------------------------|---------|
| `sb-wiki-ingest` | Slash command | `sb-os/workflows/sb-wiki-ingest/` | `.claude/commands/sb-wiki-ingest.md` | User-invocable end-to-end ingest |
| `sb-wiki-create-topic` | Skill (auto-discovered) | `sb-os/workflows/sb-wiki-create-topic/` | `.claude/skills/sb-wiki-create-topic/SKILL.md` | Agent-invokable mid-ingest; auto-fires when the user expresses topic-creation intent |
| `sb-wiki-lint` | Slash command | `sb-os/workflows/sb-wiki-lint/` | `.claude/commands/sb-wiki-lint.md` | User-invocable health check + index maintenance |
| `sb-wiki-query` | Slash command | `sb-os/workflows/sb-wiki-query/` | `.claude/commands/sb-wiki-query.md` | User-invocable synthesized query |

Workflows hold all logic. Slash commands and skills are thin loaders only.

This schema doc lives at its canonical home: `3-resources/tools/sb-os/docs/wiki-schema.md` (inside the sb-os repo). Relocated from `1-projects/second-brain-evolution/sb-wiki-build/wiki-schema.md` at sb-os v2 build time (p2-1).

> **Configurability.** Wiki workflows resolve `{wiki_root}` from `sb-os.json` at runtime — never hardcoded. The `wiki/`, `raw/`, and `log.md` paths are derived as `{wiki_root}/wiki/`, `{wiki_root}/raw/`, and `{wiki_root}/log.md`. Per architecture doc §3, the user-context root for any YAML companions used by wiki workflows resolves through `sb-os.json` → `user_context_root` (default `.user/context/`).

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
- **`sb-os/docs/wiki-schema.md`**: this schema doc, relocated from `1-projects/second-brain-evolution/sb-wiki-build/wiki-schema.md` at v2 build time (p2-1). Now at canonical home.
- **`sb-os/install/module-manifest.json`**: add the four `sb-wiki-*` components so the installer generates loaders.
- **`sb-os/wiki/claude-mds/wiki.md`** (managed CLAUDE.md source per architecture §4): replace the v1 placeholder with operational rules referencing this schema (page types — call out extensibility, ingest flow, stub policy, citation format, index rules, lint's raw-index responsibility). Installs to `{vault}/{wiki_root}/CLAUDE.md`.
- **`sb-os/install.py`**: confirm `wiki_root` prompt persists into `sb-os.json` (already in v1 per architecture §6 manifest schema); v2 adds the `sb-wiki-*` loader generation.

**Vault-side (post `python install.py` to v2):**

- **`{wiki_root}/CLAUDE.md`** (managed): rewritten by the installer from `sb-os/wiki/claude-mds/wiki.md` per the §6 marker block protocol — content inside `<!-- sb:start v=1 -->...<!-- sb:end -->` is replaced; user content outside markers is preserved.
- **NEW `{wiki_root}/raw/studies/CLAUDE.md`**: operational rules for study captures (filename pattern `YYYY-MM-DD-{slug}.md`, immutability, relationship to ingest). User-owned per architecture §7 ("Subfolder CLAUDE.mds within PARA are user-owned, untouched by sb-os") — created on first `sb-wiki-ingest` of a study source if absent, or by the user manually.
- **NEW (folder + leaf indexes, created lazily as origins surface; lint creates missing raw indexes automatically)**: `{wiki_root}/raw/studies/`, `raw/studies/studies.md`, `wiki/concepts/`, `wiki/concepts/concepts.md`, `wiki/entities/`, `wiki/entities/entities.md`, `wiki/topics/`, `wiki/topics/topics.md`, `wiki/sources/`, `wiki/sources/{origin}/{origin}.md`.
- **User-area CLAUDE.mds that route study output**: any user-side CLAUDE.md that points `/sb-tutor` or multi-source notes at a learning area should route to `{wiki_root}/raw/studies/` (matches root CLAUDE.md hard-rule already in place pre-cutover).

**Already applied (user's pre-cutover vault):**

- Root `CLAUDE.md` routing row: `Study session output (sb-tutor, multi-source notes)` → `3. Resources/knowledge-base/raw/studies/` (append). Listed for completeness of the propagation record.
