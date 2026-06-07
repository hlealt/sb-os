<!--
sb-os managed file — installs to `{vault}/{wiki_root}/CLAUDE.md` when the
wiki feature is enabled. `wiki_root` is configured in `sb-os.json` (default:
`3-resources/knowledge-base/`). Content INSIDE markers is overwritten on
`python install.py`; content OUTSIDE is preserved.

Operational rules summarize the locked schema at
`3-resources/tools/sb-os/wiki/docs/wiki-schema.md`. Edit the schema first if
behavior changes; this file follows.
-->

<!-- sb:start v=1 -->
# {wiki_root}/

Karpathy-style wiki layer — synthesis space for consumed external content. Path configured at install time (`wiki_root` in `sb-os.json`).

Raw consumption (articles, papers, transcripts, study sessions) lives under `{wiki_root}/raw/`; synthesized pages live under `{wiki_root}/wiki/`; a single actionable queue (open `candidate-topic` + `candidate-mention` items) lives at `{wiki_root}/log.md`.

Locked schema: `3-resources/tools/sb-os/wiki/docs/wiki-schema.md`. Operational details below summarize the schema — read the schema for the canonical spec.

> **Installer scope guarantee.** The sb-os installer (`install.py`) NEVER reads or writes anything under `{wiki_root}/wiki/` or `{wiki_root}/raw/` — wiki content (pages, indexes, `log.md`) is created and maintained EXCLUSIVELY by `/sb-wiki-ingest` and `/sb-wiki-lint`. Re-running `install.py --upgrade` is safe at any time. Full guarantee: schema § "Installer scope guarantee".

---

## Page Types

Four active types. The list is extensible — agents propose new types via the user when a real ingest pattern hits a gap, never auto-create a new type.

| Type | Definition | Folder |
|------|-----------|--------|
| **Concept** | The idea itself. Definable in one sentence. Stable over time | `wiki/concepts/` |
| **Entity** | A specific named thing — tool, person, company, product, model | `wiki/entities/` |
| **Topic** | The conversation around an idea or entity. Plural framing. Evolves over time | `wiki/topics/` |
| **Source** | Per-source synthesis. 1:1 with a raw file. Entry point of the wiki | `wiki/sources/{origin}/` |

Discriminator: Concept = the idea or entity itself; Topic = the conversation around it. When in doubt, start as Concept or Entity. Promote to Topic only when finding "there are N variants of this, evolving over time."

---

## Module Extensions

The wiki supports **module extensions** — other sb-os modules MAY add their own page types, entity kinds, sections, and lint rules without editing the base wiki.

When a module is listed in `sb-os.json` → `wiki_extensions`, `/sb-wiki-ingest` and `/sb-wiki-lint` run a **Step 0** that locates that module's `wiki-ext/` folder and MERGES its definition files into the active rule set for the run. Extension page types, entity kinds, sections, and lint rules are ADDED to the base set — never replace it. When `wiki_extensions` is absent or empty, Step 0 is a no-op and the base four-type wiki behaves unchanged.

---

## Regulatory Layer — purpose.md

`{wiki_root}/purpose.md` is an **OPTIONAL** regulatory file that gives `/sb-wiki-ingest` a **focus lens** — it biases how deeply a source is synthesized, which entities/concepts become pages, and how topics are suggested toward the user's stated focus areas, and flags sources that match nothing. It is the regulatory-layer twin of the locked schema. It never drops content and never alters a deterministic rule.

It is a root-level sibling of `raw/`, `wiki/`, and `log.md` — NOT a wiki page, NOT raw. It carries `type: purpose` (a non-page value excluded from page-type checks, indexes, and orphan detection). The user owns it; lint never edits it and skips it entirely.

**Optionality (no-op contract).** Absent → lens OFF → ingest behaves exactly as today; malformed → ingest warns and proceeds lens-OFF. Mirrors the `wiki_extensions` Step 0 no-op contract.

Canonical spec (artifact, format, parsing contract, classification bands, discretionary-only modulation, per-step effects, off-purpose flag): schema § "Regulatory layer — purpose.md".

---

## Questions Layer — questions.md

`{wiki_root}/questions.md` is an **OPTIONAL** registry of the **user's open questions** — a queue-style inbox (actionable, NOT a log) that the wiki gradually answers as sources land and topics form. Questions are captured at ingest (Stage-2 reflection), on a `/sb-wiki-query` miss, in chat, or by direct Obsidian edit. The **answer-scan** revisits open questions at ingest (active) and lint (periodic) and accretes cited answers inline until each question **graduates** to a page (via `sb-wiki-create-topic` — never auto-authored) or is **retired**. It never drops content and never alters a deterministic rule.

It is a root-level sibling of `raw/`, `wiki/`, `log.md`, and `purpose.md` — NOT a wiki page, NOT raw. It carries `type: questions` (a non-page value excluded from page-type checks, indexes, and orphan detection). **Lint OWNS** its maintenance — sweep, graduation proposals, prune, and regenerating the read-only cross-wiki aggregate `{wiki_root}/open-gaps.md` (`type: questions-index`).

**Two homes.** Topic `Open questions` stay on the topic page (menu UNCHANGED) and resolve in place — strike the line + fold the answer into the topic body via the existing `PROPOSED TOPIC UPDATES` append-only machinery. `questions.md` holds the user's registered questions (including cross-cutting ones tied to no page) and accretes an inline `answer:` until it graduates or is retired (entry then REMOVED). `open-gaps.md` recovers the single-pane view across both homes.

**Optionality (no-op contract).** Absent → questions layer OFF → ingest/lint behave exactly as today; malformed → warn and proceed as if absent, NEVER aborting ingest or lint. Mirrors the `purpose.md` no-op contract.

Canonical spec (artifact, entry schema, two-homes resolution, lifecycle, the answer-scan at ingest + lint, `open-gaps.md`, determinism guarantees): schema § "Questions layer — questions.md".

---

## Operations

Four operations cover the wiki lifecycle.

| Component | Type | Invoked by | Purpose |
|-----------|------|------------|---------|
| `/sb-wiki-ingest <slug>` | Slash command | User | Distill a raw source into wiki pages |
| `sb-wiki-create-topic` | Skill (auto-discovered) | Agent mid-ingest, OR auto-fired when user expresses topic-creation intent | Create a topic page from a candidate or fresh proposal |
| `/sb-wiki-lint` | Slash command | User | Health check + index maintenance for `raw/` and `wiki/` |
| `/sb-wiki-query <question>` | Slash command | User | Synthesize an answer from wiki + optionally file the result back |

### Ingest flow

`/sb-wiki-ingest <slug>` runs an 11-step flow. Steps 1-9 run without user input. Two checkpoints gate user interaction:

- **Stage 1 checkpoint** — agent presents an INGEST PREVIEW table of every planned file change plus a PROPOSED TOPICS block (if candidate-topic triggers fired). User responds: `accept-all` | `reject N` | `abort`; per topic: `accept N` (creates now) | `defer N` (logs as candidate). No file writes commit until the user responds.
- **Stage 2 checkpoint** (optional) — agent prompts the user for `My take`, `Open questions`, and `Dive deeper` on the source page. User can fill or skip each section; skipped sections stay empty on the source page. The agent re-syncs the wiki sources index `My take` cell per the three-state rule (`pending` / `—` / reflected preview) — see Index Rules below. The cell is NEVER blank.

---

## Retrieval

Before bulk-reading or grepping wiki pages — to answer a question, locate related pages, or check overlap — agents MUST first try the hybrid search helper (schema § "Retrieval tiers — hybrid search"). Run from the vault root:

```bash
python 3-resources/tools/sb-os/wiki/scripts/sb-wiki-search.py search "<natural-language query>" --k 8 [--type concept,entity,topic,source,thesis,decision] [--json]
```

The helper is read-only and self-syncs before answering (changed pages re-indexed incrementally — never run a manual index step first). Availability ladder: `VOYAGE_API_KEY` set → hybrid semantic+keyword; key absent → keyword-only (FTS5, zero API calls); helper missing or erroring → fall back to leaf indexes + `grep`/`ripgrep` (deterministic floor). A helper failure NEVER blocks the task — degrade and continue. Targeted reads of already-known pages need no search first.

---

## Stub Policy

Agent auto-creates a stub Concept or Entity page ONLY when the entity/concept name appears in EITHER:

1. **Source title/headline**, OR
2. **An extracted Notable Quote OR a `Substance` bullet** (the agent's own output from ingest step 2)

Deterministic — tied to artifacts the agent has already produced, not to recounting the source. If the rule does NOT fire, the agent logs a `candidate-mention` entry in `log.md` for periodic review by lint — never creates a page.

Lint detects stub-state structurally (frontmatter + ≤2-sentence preamble + Sources section, with main content sections empty or absent) and flags stubs aged >30 days. Empty user-half sections on Source pages do NOT count toward stub-state.

---

## Citation Format

| Layer | Format | Maintained by |
|-------|--------|---------------|
| Inline in body | `[^N]` at point of claim | Agent (during ingest) |
| Sources section | `[^N]: [[YYYY-MM-DD-slug.md]]` | Agent (during ingest); renumbered by lint |
| Frontmatter `sources:` | NOT USED | — |

Citation targets are wiki pages, NEVER raw files. Concept, entity, and topic pages cite **source pages** (`wiki/sources/`). Raw files are referenced ONLY by their 1:1 source page (the `raw:` frontmatter field and that source page's own Sources footnote).

Footnote definitions ARE wikilinks — Obsidian indexes them in the graph. One footnote per source, never merged. Multi-source claims get multiple markers on the same sentence: `...claim X[^1][^2][^3]`. Lint preserves any user prose appended to a definition; it only renumbers (safe bijections) — it NEVER auto-removes a definition, because an inline-unreferenced def is indistinguishable from stub provenance (the page's only graph edge to that source); unreferenced defs are reported for hand-reconciliation. Number footnotes locally per page (start from `[^1]`).

The user NEVER writes citations manually.

---

## Index Rules

The wiki maintains five indexes. The user NEVER writes indexes manually — agents create and maintain them.

| Index | Path | Format | Maintained by |
|-------|------|--------|---------------|
| Raw leaf index | `raw/{origin}/{origin}.md`, `raw/studies/studies.md` | `\| File \| Title \| Date \| Wiki \|` | Lint creates and maintains; ingest sets `Wiki = Yes` (or `Partial` on partial reject) |
| Wiki sources leaf index | `wiki/sources/{origin}/{origin}.md` | `\| File \| What it says \| My take \|` | Ingest writes `What it says` (factual derivative of source page's `Substance`); ingest/lint write `My take` (derived from source page's `My take` section); user fills the source page, never the index |
| Wiki concepts leaf index | `wiki/concepts/concepts.md` | `\| File \| Description \|` | Lint creates and maintains |
| Wiki entities leaf index | `wiki/entities/entities.md` | `\| File \| Description \|` | Lint creates and maintains |
| Wiki topics leaf index | `wiki/topics/topics.md` | `\| File \| Scope \|` | `sb-wiki-create-topic` writes new rows defensively; lint owns full creation and maintenance |

Lint's raw-index responsibility is explicit: every `raw/{origin}/` directory gets a `{origin}.md` index — if missing, lint CREATES it with the standard header; for each raw file, lint ensures a row exists with `Wiki = No` (default) or preserves the existing `Yes`/`Partial`/`No` value. Same for `raw/studies/studies.md`.

Source pages are CANONICAL — the wiki sources index `My take` column is DERIVED from the source page's `My take` section. Stale-by-7d acceptable for skim purpose.

The `My take` cell encodes one of three explicit states (NEVER blank): `pending` (Stage 2 not yet engaged — action awaiting), `—` em-dash (Stage 2 ran and user finalized empty), or a 1-sentence reflected preview. The 7-day staleness rule applies to `pending` rows only; `—` rows are final and do NOT age out. Full rules: schema § "Wiki sources index format" / `shared/index-formats.md` § "`My take` Cell — Three States".

If a leaf index exists with a user-customized column layout, lint preserves it — operates against the existing `File` column for row-presence checks; does NOT rewrite the layout.

---

## Folder Structure

| Path | Contents |
|------|----------|
| `{wiki_root}/log.md` | Actionable queue — 2 entry types: `candidate-topic` (promote or dismiss) and `candidate-mention` (review → stub or dismiss). Completed history is NOT logged; resolution = the page exists. Lint prunes spent entries |
| `{wiki_root}/raw/{origin}/` | Verbatim source files by origin (immutable — never edit) |
| `{wiki_root}/raw/studies/` | Study sessions (`/sb-tutor` outputs, multi-source notes) |
| `{wiki_root}/wiki/concepts/`, `wiki/entities/`, `wiki/topics/`, `wiki/sources/{origin}/` | Synthesized pages |

Type folders (`concepts/`, `entities/`, `topics/`, `sources/`) are STABLE — never reorganize or rename. Topic-folder sub-organization (e.g., `wiki/concepts/ai/`) is DEFERRED until ≥20 wiki pages. All folder and index creation is lazy.

Filenames use `lowercase-kebab.md`. Source page filenames mirror the raw counterpart EXACTLY — preserve the date format the origin uses; do NOT normalize. Raw **PDF** filenames must equal the kebab-slug of the paper's title — `/sb-wiki-ingest` renames non-conforming PDFs at ingest (step 1.5), `/sb-wiki-lint` proposes renames for existing ones (step 7.6, user-gated). Schema § "Raw PDF title-conformance".

---

## Asset Folder

Standard local-asset path: `{wiki_root}/raw/assets/` — flat, single shared folder. Maintained by the user via Obsidian's core "Download attachments for current file" command (Karpathy-style workflow: clip a source, then hotkey-download all referenced images locally). Configure once in Obsidian Settings → Files and links → "Default location for new attachments" → `raw/assets`. Reference from any page via `![[filename.png]]`. **Agents NEVER write to `raw/assets/`. Lint SKIPS it entirely** — not a raw origin, no leaf index, excluded from orphan detection. Full rules: schema § "Asset folder".

<!-- sb:end -->

<!-- Add your own content below — anything outside the sb:start/sb:end markers survives re-install. -->
