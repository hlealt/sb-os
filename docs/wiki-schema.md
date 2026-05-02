# Wiki Schema (v3 — post-reconciliation)

> **Status:** Locked design. Operational spec for the Karpathy-style wiki layer shipped by **sb-os v2** (per `sb-os-build/second-brain-os-architecture.md` §12 and Decisions Log #12). sb-os v1 ships only the `wiki_root` config slot in `sb-os.json` (default `3-resources/knowledge-base/`), the empty default folder, and a placeholder managed `CLAUDE.md` at `{wiki_root}/CLAUDE.md`. The schema, the four `sb-wiki-*` components, and any populated wiki content described below are out of v1 scope — they ship in **sb-os v2**. Agents and CLAUDE.md files reference this document only after v2 lands.

## Purpose & context

Defines schema and operational rules for the wiki layer shipped by sb-os v2. Pattern source: [Karpathy's LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f). Wiki content lives at `{wiki_root}/` (vault-side, user data), where `{wiki_root}` is the configurable path persisted in `sb-os.json` at install time (default `3-resources/knowledge-base/`). All paths in this document that begin with `3. Resources/knowledge-base/` are pre-cutover examples — read them as `{wiki_root}/` once sb-os is installed.

Goal: turn high-volume reading (articles, podcasts, papers, repos, study sessions) into compounding knowledge — cross-referenced, contradiction-flagged, queryable.

User mode preference: **query-driven** (asks the agent rather than browses), with **mandatory cross-linking on ingest** so wikilinks-graph stays viable as fallback. **No browse-mode affordance in lint v1.**

Audience: future agents executing wiki ingest / create-topic / lint / query operations, and the user reviewing those operations.

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

Type folders are stable. Topic-folder organization (e.g., `wiki/concepts/ai/`) is explicitly NOT pre-organized — let it emerge after ≥20 wiki pages.

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
kind: tool | person | company | product | model
```
Use case: Dataview filtering ("all tools" / "all people I follow"). Predefined because the enum is small and stable.

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
- If the source page's `My take` is empty (Stage 2 skipped), the index `My take` cell stays blank until the user fills the source page; lint syncs on the next pass.
- Stale-by-7d acceptable for skim purpose; agents may fall back to reading the source page if deeper signal is needed.

The raw index (`raw/{origin}/{origin}.md`) keeps its existing format with `Wiki` column — factual only, no opinion. Raw indexes are created and maintained by lint (see `/sb-wiki-lint`).

## Topic creation rules

**Agent NEVER auto-creates topic pages.** All topic creation flows through the `sb-wiki-create-topic` skill — agent-invokable mid-ingest when the user accepts a proposed topic, AND auto-discovered by Claude Code when the user later expresses intent to create or promote a topic (e.g., "create a topic for X", "promote the mcp-debate candidate"). The skill has no slash command — invocation is intent-driven.

The agent detects 3 candidate-topic triggers and:
1. Logs them in `log.md` as `candidate-topic` H2 entries.
2. Surfaces them inline at the Stage 1 ingest checkpoint as **PROPOSED TOPICS** — the user can accept-now (agent invokes `sb-wiki-create-topic` skill mid-run) or defer (the candidate-topic log entry persists; the user may promote later by expressing intent, which auto-fires the `sb-wiki-create-topic` skill).

| Trigger | Structural anchor | Status |
|---------|-------------------|--------|
| **Contradiction** | Agent extracts claims from the new source. For each existing wiki page on the same entity/concept, compares claims. To fire: (a) **quote both claims verbatim** in the candidate log entry, (b) classify scope as `same-scope-opposing` / `different-scope` / `temporal-shift` / `partial-overlap`. **Only `same-scope-opposing` fires** a `candidate-topic` and a `> [!warning] Disputed` callout on the affected page. Other classifications log informationally (no candidate). | Active day 1 |
| **Evolution** | Two or more sources with different read/publish dates make divergent claims about the same concept/entity. Single-source temporal phrases ("future of X", "next-gen") alone do **NOT** fire. Both required: ≥2 dated sources AND divergent claims. | Active day 1 |
| **Cross-application** | Phrase pattern "X for Y" / "X-powered Y" / "using X to do Y" where BOTH X and Y are existing wiki pages (**exact wikilink match required**, no fuzzy semantic matching), AND ≥2 sources reference the same X-for-Y pairing | Defined; expected low fire-rate until wiki has ≥10 pages with cross-pollination |

When Contradiction fires `same-scope-opposing`, the agent ALSO adds a `> [!warning] Disputed` callout to the affected concept/entity page citing both sources, BEFORE the user promotes the candidate.

**Studies workflow note**: studies (`/tutor` outputs and multi-source notes) flow `raw/studies/` → source page → distilled into entity/concept/topic pages by `/sb-wiki-ingest`. **A single study source typically distills into multiple wiki page types in one ingest** — e.g., a `/tutor` session on graph databases may produce a Concept page (`knowledge-graphs.md`), an Entity page (`cypher.md`), and a candidate-topic if cross-application emerges (`knowledge-graphs-for-agent-memory`). There is no separate "user-study trigger" — the 3 triggers above already detect patterns within and across study sources.

## Stub policy

### Stub creation (ingest)

The agent auto-creates a stub Concept or Entity page when the entity/concept name appears in EITHER:
1. **Source title/headline**, OR
2. **An extracted Notable Quote OR a `Substance` bullet** (the agent's own output from step 2 of the ingest workflow).

Deterministic — tied to artifacts the agent has already produced, not to recounting the source.

Otherwise, the agent logs a `candidate-mention` in `log.md` for periodic review by lint.

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
| 2 | Write `wiki/sources/{origin}/{date}-{slug}.md` (`Substance` and `Connections` always; `Notable quotes` / `Methodology` / `Counterpoints` per source kind; user-half sections present as empty shells with headings only) | Agent |
| 3 | Identify entities/concepts mentioned; for each, check stub-creation rule (title or `Notable Quote` / `Substance` bullet hit) | Agent |
| 4 | Update existing entity/concept pages with new perspective + citation; populate `Open variants / debates` section if Contradiction fires. **Agent NEVER overwrites a main section that already contains substantive content (>50 words) — only appends new sections, adds bullets to existing lists, or adds footnote definitions to Sources. User-fleshed content is treated as authoritative.** | Agent |
| 5 | Create stubs for new entities/concepts that meet the rule | Agent |
| 6 | Detect candidate-topic triggers (Contradiction, Evolution, Cross-application); add `> [!warning] Disputed` callouts on Contradiction-`same-scope-opposing` | Agent |
| 7 | Update raw index: `Wiki = Yes` | Agent |
| 8 | Update wiki sources index (`What it says` filled; `My take` left blank — populated post Stage 2) | Agent |
| 9 | Append `ingest` entry to `log.md` summarizing operations + candidates (separate `candidate-topic`, `concept-created`, `entity-created` H2 entries when triggered) | Agent |
| 10 | **Stage 1 checkpoint**: present structured table + PROPOSED TOPICS block; the user accepts-all / rejects N / aborts file changes; per topic: accept (agent invokes `sb-wiki-create-topic` skill now) / defer (keeps as candidate in log) | Agent + User |
| 11 | **Stage 2 checkpoint** (optional): present source page draft; agent prompts for `My take` / `Open questions` / `Dive deeper`. The user can fill or skip. If filled, agent writes user-half sections AND syncs the `My take` column to the wiki sources index. | Agent + User |

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

File changes: accept-all | reject N (e.g. "reject 3,4") | abort
Topic decisions: accept N (creates now) | defer N (logs as candidate) | (default: defer all)
```

- `accept-all`: all file changes commit.
- `reject N`: the agent rolls back the listed numbered items only (deletes new files, reverts edits, removes log entries scoped to those changes). Other changes commit. The `Wiki = Yes` row update may be downgraded to `Wiki = Partial` if the source page itself is not rejected but downstream pages were.
- `abort`: the agent rolls back everything. Raw index `Wiki` stays `No`. The source page is not created.
- Topic `accept N`: agent invokes the `sb-wiki-create-topic` skill mid-run with the proposed topic name; appends `topic-created` entry to log.
- Topic `defer N`: candidate-topic entry persists in log; the user may promote later by expressing intent (auto-fires the `sb-wiki-create-topic` skill).

#### Stage 2 checkpoint format

After Stage 1 acceptance:

```
Reflect on this source? (y/n)

[If y, agent presents the source page user-half (empty) and prompts each section in turn:]

My take — why did this matter? (type or speak; "skip" to leave blank)
Open questions — what's unclear? (type or speak; "skip")
Dive deeper — what to follow up on? (type or speak; "skip")
```

Skip is allowed at any prompt. Skipped sections remain empty; the user can fill later in Obsidian editor. If at least one section is filled, the agent re-syncs the `My take` index column.

### `sb-wiki-create-topic`

A skill agents can invoke mid-ingest (when the user accepts a PROPOSED TOPIC at Stage 1) OR auto-fired by Claude Code when the user later expresses intent to create or promote a topic (e.g., "create a topic for X", "promote the mcp-debate candidate"). No slash command — invocation is intent-driven.

| Step | Operation | Owner |
|------|-----------|-------|
| 1 | Resolve topic name; if from a candidate, load the candidate-topic log entry (claim A, claim B, trigger, sources) | Agent |
| 2 | Write `wiki/topics/{slug}.md` with frontmatter, `Scope` (required), `Sources` (required), and optional sections per topic shape (see Topic page menu) | Agent |
| 3 | Cross-link from triggering concept/entity pages: add wikilink to the new topic in their `Related` section | Agent |
| 4 | Append `topic-created` entry to `log.md`; if from a candidate, reference the original candidate by timestamp | Agent |
| 5 | Update `wiki/topics/topics.md` leaf index with the new entry | Agent |

When invoked mid-ingest, no separate user checkpoint — the parent `/sb-wiki-ingest` Stage 1 acceptance covers it. When auto-fired by user intent, the agent confirms the proposed sections + scope sentence with the user before writing (single checkpoint).

### `/sb-wiki-lint`

Single command: `/sb-wiki-lint`. Runs across `raw/` and `wiki/` folders. Mostly read-only; index sync writes are auto-applied (no diff to accept).

| Step | Operation |
|------|-----------|
| 1 | Walk all wiki pages — detect stubs (structural rule) and record age via `created` |
| 2 | Walk all wiki pages — detect orphans (no inbound wikilinks); skip leaf indexes |
| 3 | Walk wiki concept/entity pages — detect unresolved Disputed callouts (older than 30 days without resolution) |
| 4 | Walk `log.md` — detect candidate-topics aging without promotion (>30 days) |
| 5 | Walk all wiki pages — verify wikilinks resolve (broken if target file missing); collect broken links |
| 6 | For each `wiki/sources/{origin}/` — re-sync `My take` column from each source page's `My take` section; renumber footnotes; remove stale footnote definitions |
| 7 | For each `raw/{origin}/` — verify `{origin}.md` index exists; if missing, create it with the standard `\| File \| Title \| Date \| Wiki \|` columns. For each raw file in `{origin}/`, ensure a row exists with `Wiki = No` (default) or `Yes/Partial` (preserved). Same for `raw/studies/studies.md`. **Index creation and maintenance is the agent's job**, not the user's. |
| 8 | Append `lint` entry to `log.md` summarizing findings: stubs aged, orphans, unresolved callouts, candidates aging, broken links, index sync count, raw indexes created/updated |
| 9 | Present findings to the user (read-only summary; no diff to apply) |

#### Lint output format

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
| 7 | If filed: invoke `sb-wiki-create-topic` skill (for Topic) or write directly to `wiki/concepts/` / `wiki/entities/` (for Concept / Entity); append `query` entry to `log.md` | Agent |

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

8 types active at v1. Each entry is an H2 heading: `## [YYYY-MM-DD HH:MM] type | brief`.

| Type | Trigger | User action surfaced |
|------|---------|----------------------|
| `ingest` | `/sb-wiki-ingest <slug>` | Review diff at Stage 1; reflect at Stage 2 if desired |
| `candidate-topic` | Auto-fired during `ingest` or `lint` when 1 of 3 triggers fires. **Always a sibling H2 entry** (not nested under the parent ingest), referenced from the parent ingest entry by timestamp | Decide whether to promote via the `sb-wiki-create-topic` skill (express intent to fire it) |
| `candidate-mention` | Auto-fired during `ingest` step 3 when an entity/concept name surfaces but the stub-creation rule does NOT fire (per Stub policy). **Sibling H2 entry**, referenced from the parent ingest by timestamp | None — informational; lint reviews periodically and may promote to a stub if the name recurs |
| `concept-created` | Auto-fired during `ingest` when a stub Concept is created. **Sibling H2 entry**, referenced from the parent ingest by timestamp | None — informational; greppable by type |
| `entity-created` | Auto-fired during `ingest` when a stub Entity is created. **Sibling H2 entry**, referenced from the parent ingest by timestamp | None — informational; greppable by type |
| `topic-created` | `sb-wiki-create-topic` skill (mid-ingest acceptance OR user-intent-driven invocation) | None — closes the loop. Lets lint know which candidates are spent |
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

Source files live in the sb-os repo under `sb-os/workflows/sb-wiki-*/`. Skills and commands installed into `.claude/` are **thin loaders** that point back to those source files (per architecture doc §4 loader pattern). Editing installed loaders is forbidden — the source is the repo. Re-running `sb-os install --upgrade` regenerates loaders.

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
- **`sb-os/admin/install/module-manifest.json`**: add the four `sb-wiki-*` components so the installer generates loaders.
- **`sb-os/claude-mds/wiki.md`** (managed CLAUDE.md source per architecture §4): replace the v1 placeholder with operational rules referencing this schema (page types — call out extensibility, ingest flow, stub policy, citation format, index rules, lint's raw-index responsibility). Installs to `{vault}/{wiki_root}/CLAUDE.md`.
- **`sb-os/install.py`**: confirm `wiki_root` prompt persists into `sb-os.json` (already in v1 per architecture §6 manifest schema); v2 adds the `sb-wiki-*` loader generation.

**Vault-side (post `sb-os install --upgrade` to v2):**

- **`{wiki_root}/CLAUDE.md`** (managed): rewritten by the installer from `sb-os/claude-mds/wiki.md` per the §6 marker block protocol — content inside `<!-- sb:start v=1 -->...<!-- sb:end -->` is replaced; user content outside markers is preserved.
- **NEW `{wiki_root}/raw/studies/CLAUDE.md`**: operational rules for study captures (filename pattern `YYYY-MM-DD-{slug}.md`, immutability, relationship to ingest). User-owned per architecture §7 ("Subfolder CLAUDE.mds within PARA are user-owned, untouched by sb-os") — created on first `sb-wiki-ingest` of a study source if absent, or by the user manually.
- **NEW (folder + leaf indexes, created lazily as origins surface; lint creates missing raw indexes automatically)**: `{wiki_root}/raw/studies/`, `raw/studies/studies.md`, `wiki/concepts/`, `wiki/concepts/concepts.md`, `wiki/entities/`, `wiki/entities/entities.md`, `wiki/topics/`, `wiki/topics/topics.md`, `wiki/sources/`, `wiki/sources/{origin}/{origin}.md`.
- **User-area CLAUDE.mds that route study output**: any user-side CLAUDE.md that points `/sb-tutor` or multi-source notes at a learning area should route to `{wiki_root}/raw/studies/` (matches root CLAUDE.md hard-rule already in place pre-cutover).

**Already applied (user's pre-cutover vault):**

- Root `CLAUDE.md` routing row: `Study session output (sb-tutor, multi-source notes)` → `3. Resources/knowledge-base/raw/studies/` (append). Listed for completeness of the propagation record.
