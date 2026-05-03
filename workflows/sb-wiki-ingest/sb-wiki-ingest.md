---
name: sb-wiki-ingest
description: Distill a raw source into wiki pages — write source page, update existing entity/concept pages with append-only protection, create stubs, detect candidate-topic triggers, update indexes, append log, present Stage 1 + Stage 2 checkpoints.
---

# sb-wiki-ingest

End-to-end ingest of a single raw source into the Karpathy-style wiki layer. Implements the 11-step flow defined in the wiki schema. All user interaction is gated to Stage 1 (step 10) and Stage 2 (step 11). Steps 1–9 run without mid-flow user input.

## Schema Source

Read `3-resources/tools/sb-os/docs/wiki-schema.md` — Operations § "/sb-wiki-ingest" — for canonical step definitions. This workflow body implements that spec verbatim. Schema deviations require updating the schema first.

## Path Resolution

| Symbol | Resolution |
|--------|------------|
| `{wiki_root}` | Read from `sb-os.json` at vault root → `wiki_root` field. Resolve via `admin/install/manifest.py` (`manifest.read(vault_root)`). Never hardcode. |
| `{user_context_root}` | Read from `sb-os.json` → `user_context_root`. Never hardcode. |
| `{wiki_root}/wiki/` | Wiki page tree (concepts, entities, topics, sources). |
| `{wiki_root}/raw/` | Raw source tree. **EXCLUDES `raw/assets/`** (user-maintained binary attachments — per `../_shared/wiki/folder-structure.md` "Asset Folder"). This workflow NEVER reads or writes `raw/assets/`. |
| `{wiki_root}/log.md` | Single append-only event log. |

## Shared Data Files

These files codify rules referenced across multiple `sb-wiki-*` workflows. Load only the files relevant to the active step.

| File | Used by step |
|------|--------------|
| `../_shared/wiki/page-types.md` | 3 |
| `../_shared/wiki/frontmatter-schemas.md` | 2, 5 |
| `../_shared/wiki/section-menus.md` | 2, 4 |
| `../_shared/wiki/stub-policy.md` | 3, 4, 5 |
| `../_shared/wiki/citation-format.md` | 2, 4 |
| `../_shared/wiki/log-entry-shapes.md` | 9 |
| `../_shared/wiki/index-formats.md` | 7, 8 |
| `../_shared/wiki/naming-convention.md` | 2, 5 |
| `../_shared/wiki/folder-structure.md` | 2, 5 |
| `./data/candidate-topic-triggers.md` | 6 |

## Invocation

`/sb-wiki-ingest <slug>` where `<slug>` is a raw filename or unique substring.

## Flow

No mid-flow user input during steps 1–9. All user interaction occurs at steps 10 (Stage 1) and 11 (Stage 2).

### Step 1 — Read raw file

1. Resolve `<slug>` against `{wiki_root}/raw/`:
   - Exact filename match wins.
   - Otherwise match unique substring across `{wiki_root}/raw/{origin}/*.md` and `{wiki_root}/raw/studies/*.md`.
   - Multiple matches → halt and ask the user to disambiguate before any other action.
2. Read the raw file in full. Capture origin (`{origin}` = parent folder name; `studies` is a valid origin).
3. Note the source kind from origin and content shape: `article` | `paper` | `podcast` | `study` | `repo`.

### Step 2 — Write source page

Write `{wiki_root}/wiki/sources/{origin}/{date}-{slug}.md`. Filename mirrors the raw counterpart EXACTLY — preserve the date format the origin uses (`YYYY-MM-DD-slug.md`, `YYYY_MM_DD-slug.md`, etc.). Do NOT normalize date formats.

Frontmatter per `../_shared/wiki/frontmatter-schemas.md` Source schema:

```yaml
---
type: source
created: <today YYYY-MM-DD>
last-touched: <today YYYY-MM-DD>
raw: "[[<raw-filename>]]"
url: <source URL if present in raw>
author: <author if present in raw>
related: []
tags: []
---
```

Section structure per `../_shared/wiki/section-menus.md` Source page entry:

| Half | Sections to write |
|------|-------------------|
| Agent half | `Substance` (always); `Connections` (always); `Notable quotes` / `Methodology` / `Counterpoints` per source kind selection rules |
| Separator | `---` |
| User half | `My take`, `Open questions`, `Dive deeper` — empty shells (heading only, no body) |
| Separator | `---` |
| Sources | `Sources` section — required |

Citations: emit inline `[^N]` markers at every claim derived from the raw, then append `[^N]: [[<raw-filename>]]` definitions in the `Sources` section per `../_shared/wiki/citation-format.md`.

### Step 3 — Identify entities and concepts

1. Extract candidate entity and concept mentions from the raw source AND from the agent-written `Substance` and `Notable quotes` sections of the source page produced in step 2.
2. For each candidate, classify as `entity` or `concept` per `../_shared/wiki/page-types.md` discriminator rule.
3. For each candidate, check existence under `{wiki_root}/wiki/concepts/{slug}.md` and `{wiki_root}/wiki/entities/{slug}.md`.
4. Apply the stub-creation rule per `../_shared/wiki/stub-policy.md`. The source-title branch and the `Substance`-bullet branch are MECHANICAL — fire on match. The Notable-Quote branch is AGENT DISCRETION — apply the relevance heuristic in `../_shared/wiki/stub-policy.md` "Notable Quote Stub Creation" section before deciding to fire. A passing mention surfaced only in a Notable Quote does NOT compel a stub; demote to `candidate-mention` if the heuristic does not pass.
5. Build three working sets for downstream steps:
   - `existing-pages` — pages that already exist (handled in step 4)
   - `stub-candidates` — new pages whose stub-creation rule fires (handled in step 5)
   - `mention-only` — names that did NOT clear the stub rule, including Notable-Quote-only mentions that the discretion heuristic demoted (logged as `candidate-mention` in step 9)

### Step 4 — Update existing entity/concept pages

For each page in `existing-pages`:

1. Read the target page in full.
2. Apply append-only protection per `../_shared/wiki/stub-policy.md` "Append-Only Protection" section.
3. If Contradiction-`same-scope-opposing` fires (detected in step 6 against this page's existing claims), populate the `Open variants / debates` section AND prepend a `> [!warning] Disputed` callout per `../_shared/wiki/section-menus.md` "Contradiction — Disputed Callout" section.
4. Update `last-touched: <today>` in frontmatter.
5. Append inline `[^N]` markers in any newly-written prose tied to this source, with matching `[^N]: [[<raw-filename>]]` definition in `Sources`. Number footnotes locally per page; lint renumbers across pages later. Format per `../_shared/wiki/citation-format.md`.

### Step 5 — Create stubs

For each entry in `stub-candidates`:

1. Resolve target path: `{wiki_root}/wiki/concepts/{slug}.md` (concept) or `{wiki_root}/wiki/entities/{slug}.md` (entity).
2. Slug per `../_shared/wiki/naming-convention.md` — `lowercase-kebab.md`. Forbidden: same slug already present in a sibling type folder (concepts vs topics is forbidden per schema; concepts vs entities is allowed).
3. Write frontmatter per `../_shared/wiki/frontmatter-schemas.md` (Concept adds `kind:` free-form string; Entity adds `kind:` from enum `tool | person | company | product | model`).
4. Write a 1–2 sentence preamble derived from the raw source.
5. Write the required sections empty:
   - Concept: `Definition` (1 factual sentence) + `Sources` (with the current `[^N]: [[<raw-filename>]]` definition)
   - Entity: `What it is` (1 factual sentence) + `Sources`
6. Do NOT populate optional sections — stub-state per `../_shared/wiki/stub-policy.md` requires main content sections empty or absent.

### Step 6 — Detect candidate-topic triggers

Run all three triggers per `./data/candidate-topic-triggers.md`. For each fire, record the data needed for the step 9 log entry and the step 10 PROPOSED TOPICS block.

| Trigger | Action on fire |
|---------|----------------|
| Contradiction (`same-scope-opposing` only — other scopes log informationally, no candidate) | Stage `> [!warning] Disputed` callout for the affected concept/entity page (applied at step 4 if the page exists, OR queued onto the new stub if step 5 created it). Capture verbatim quotes from both sides + scope classification. |
| Evolution | Capture both source dates and the divergent claims. Single-source temporal phrases do NOT fire — both required: ≥2 dated sources AND divergent claims. |
| Cross-application | Capture the X-for-Y phrase + both wiki page slugs (exact wikilink match required) + the ≥2 sources referencing the pairing. |

If no triggers fire, leave the candidate set empty — Stage 1 omits the PROPOSED TOPICS block.

### Step 7 — Update raw index

1. Resolve raw index: `{wiki_root}/raw/{origin}/{origin}.md` (or `{wiki_root}/raw/studies/studies.md`).
2. Locate the row whose `File` column wikilinks the current raw filename.
3. Set `Wiki = Yes` in that row. Format per `../_shared/wiki/index-formats.md` raw index entry.
4. If the row does not exist → create it (lint owns raw-index creation, but ingest may add a missing row defensively). If the index file itself is missing → log a warning entry for lint to handle; do not block the ingest.

### Step 8 — Update wiki sources index

1. Resolve wiki sources index: `{wiki_root}/wiki/sources/{origin}/{origin}.md`.
2. If the index file does not exist → create it with header row per `../_shared/wiki/index-formats.md` wiki sources index format: `| File | What it says | My take |`.
3. Add (or update) the row for the current source:
   - `File`: `[[<date>-<slug>.md>]]` matching the source page filename exactly.
   - `What it says`: 1-sentence factual summary (≤280 chars) derived from the source page's `Substance` section.
   - `My take`: write `pending` at this step (NEVER blank — see `../_shared/wiki/index-formats.md` "`My take` Cell — Three States" section). Stage 2 (step 11) may overwrite this cell with a 1-sentence reflected preview, with `—` (em-dash) if the user finalizes empty, or leave it as `pending` if the user declines reflection.

### Step 9 — Append log entries

Append entries to `{wiki_root}/log.md` per `../_shared/wiki/log-entry-shapes.md`. Entries are H2 headings: `## [YYYY-MM-DD HH:MM] <type> | <brief>`. Multiple entries from one ingest are siblings (NOT nested), each referenceable by timestamp.

| Entry | When emitted | Sibling entries cross-referenced from |
|-------|--------------|----------------------------------------|
| `ingest` | Always — anchor entry summarizing source + downstream entries by timestamp | parent of all below |
| `concept-created` | Once per stub Concept created in step 5 | back-references parent `ingest` timestamp |
| `entity-created` | Once per stub Entity created in step 5 | back-references parent `ingest` timestamp |
| `candidate-topic` | Once per trigger fire from step 6 | back-references parent `ingest` timestamp; promotion via `sb-wiki-create-topic` skill |
| `candidate-mention` | Once per name in `mention-only` set from step 3 | informational; lint reviews periodically |

Use the same `[YYYY-MM-DD HH:MM]` timestamp for every sibling emitted in this run so cross-references resolve cleanly.

### Step 10 — Stage 1 checkpoint

Present the user with a structured preview of all proposed file changes AND the PROPOSED TOPICS block. No file writes commit until the user responds. Format VERBATIM:

```
INGEST PREVIEW — <source slug>

| # | file | action | preview |
|---|------|--------|---------|
| 1 | wiki/sources/<origin>/<date>-<slug>.md | new | <first paragraph of Substance> |
| 2 | wiki/concepts/<slug>.md | updated | + section "<new section name>" |
| 3 | wiki/concepts/<slug>.md | new (stub) | <preamble first sentence> |
| 4 | wiki/entities/<slug>.md | new (stub) | <preamble first sentence> |
| 5 | log.md | appended | ingest + concept-created + entity-created + candidate-topic entries |
| 6 | raw/<origin>/<origin>.md | row updated | Wiki = Yes |
| 7 | wiki/sources/<origin>/<origin>.md | row added | new entry |

PROPOSED TOPICS:
| # | name | trigger | sources |
|---|------|---------|---------|
| 1 | <topic-slug> | <contradiction (same-scope-opposing) | evolution | cross-application> | [[<src1>]], [[<src2>]] |

File changes: accept-all | reject N (e.g. "reject 3,4") | abort
Topic decisions: accept N (creates now) | defer N (logs as candidate) | (default: defer all)
```

Omit the PROPOSED TOPICS block entirely if no triggers fired in step 6.

User response handling:

| Response | Behavior |
|----------|----------|
| `accept-all` | Commit all file changes. Proceed to step 11. |
| `reject N` (or comma list, e.g. `reject 3,4`) | Roll back ONLY the listed numbered items: delete new files for those rows, revert edits, remove log entries scoped to those changes. Other changes commit. If a downstream page (e.g., row 3) is rejected but the source page (row 1) is not, downgrade the raw index update from `Wiki = Yes` to `Wiki = Partial` in row 6. |
| `abort` | Roll back EVERYTHING. Raw index `Wiki` stays `No`. Source page is not created. Log entries removed. Skip step 11. |
| Topic `accept N` (per topic row) | Invoke the `sb-wiki-create-topic` skill mid-run with the proposed topic name. The skill writes the topic page, updates `wiki/topics/topics.md`, cross-links from triggering concept/entity pages, and appends a `topic-created` log entry referencing the candidate timestamp. |
| Topic `defer N` (per topic row, default if user omits a topic decision) | The `candidate-topic` log entry persists. The user may promote later by expressing intent — Claude Code auto-fires the `sb-wiki-create-topic` skill. |

Default behavior when the user omits per-topic decisions: defer all topics.

### Step 11 — Stage 2 checkpoint

Optional reflection pass. Skip entirely if Stage 1 was aborted. Format VERBATIM:

```
Reflect on this source? (y/n)

[If y, agent presents the source page user-half (empty) and prompts each section in turn:]

My take — why did this matter? (type or speak; "skip" to leave blank)
Open questions — what's unclear? (type or speak; "skip")
Dive deeper — what to follow up on? (type or speak; "skip")
```

Handling:

| User response | Behavior |
|---------------|----------|
| `n` to reflection prompt | Skip step 11 entirely. Source page user-half stays empty. Wiki sources index `My take` cell stays `pending` (set at step 8). End run. |
| `skip` at any per-section prompt | Leave that section empty. Continue to next prompt. |
| Any other text at a per-section prompt | Write the text under that section heading on the source page. |

After all three section prompts, re-sync the wiki sources index `My take` cell per `../_shared/wiki/index-formats.md` "`My take` Cell — Three States" section. Source page is canonical; index is derived. **NEVER leave the cell blank.**

| Stage 2 outcome | Index `My take` cell value |
|-----------------|----------------------------|
| `My take` per-section prompt was filled with text | 1-sentence reflected preview derived from the source page's `My take` section (≤280 chars; truncate with ellipsis) |
| `My take` per-section prompt was `skip`-ed AND at least one of `Open questions` or `Dive deeper` was filled (Stage 2 finalization rule — user reflected but chose to record no take) | `—` (em-dash, U+2014) |
| All three per-section prompts were `skip`-ed (Stage 2 entered but no content captured) | `pending` (no change from step 8 — Stage 2 did not produce a finalization signal) |

End of flow.

## Failure Modes

| Failure | Behavior |
|---------|----------|
| `<slug>` resolves to multiple raw files | Halt at step 1; ask user to disambiguate. No writes. |
| `{wiki_root}` cannot be resolved from `sb-os.json` | Halt before step 1; surface error. No writes. |
| Stage 1 not yet reached when the user interrupts | Roll back any partial writes from steps 2–8. |
| `sb-wiki-create-topic` skill fails mid-Stage-1 acceptance | Mark the topic row as failed; keep the `candidate-topic` log entry; proceed with the rest of the acceptance. |
| Raw index file missing at step 7 | Log a warning for lint; do not block the ingest. |
| Wiki sources index file missing at step 8 | Create it with header row; proceed. |
