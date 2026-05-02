---
name: sb-wiki-lint
description: Health check + index maintenance for `raw/` and `wiki/` — detect stubs, orphans, unresolved Disputed callouts, aging candidate-topics, broken wikilinks; auto-apply index sync writes (wiki sources `My take` re-sync, footnote renumber, raw-index creation, wiki leaf-index creation); present read-only findings to the user.
---

# sb-wiki-lint

Health check + index maintenance pass across `{wiki_root}/raw/` and `{wiki_root}/wiki/`. Implements the 9-step lint flow defined in the wiki schema. Read-mostly: index sync writes are auto-applied (no diff to accept); the user is presented with findings only.

## Schema Source

Read `3-resources/tools/sb-os/docs/wiki-schema.md` — Operations § "/sb-wiki-lint" — for canonical step definitions. This workflow body implements that spec verbatim. Schema deviations require updating the schema first.

## Path Resolution

| Symbol | Resolution |
|--------|------------|
| `{wiki_root}` | Read from `sb-os.json` at vault root → `wiki_root` field. Resolve via `admin/install/manifest.py` (`manifest.read(vault_root)`). Never hardcode. |
| `{user_context_root}` | Read from `sb-os.json` → `user_context_root`. Never hardcode. |
| `{wiki_root}/wiki/` | Wiki page tree (concepts, entities, topics, sources). |
| `{wiki_root}/raw/` | Raw source tree. |
| `{wiki_root}/log.md` | Single append-only event log. |

## Shared Data Files

These files codify rules referenced across multiple `sb-wiki-*` workflows. Load only the files relevant to the active step.

| File | Used by step |
|------|--------------|
| `../_shared/wiki/folder-structure.md` | 1, 2, 5, 7 |
| `../_shared/wiki/stub-policy.md` | 1 |
| `../_shared/wiki/section-menus.md` | 1, 3 |
| `../_shared/wiki/frontmatter-schemas.md` | 1, 4 |
| `../_shared/wiki/naming-convention.md` | 5 |
| `../_shared/wiki/citation-format.md` | 6 |
| `../_shared/wiki/index-formats.md` | 6, 7 |
| `../_shared/wiki/log-entry-shapes.md` | 4, 8 |

## Invocation

`/sb-wiki-lint`. No arguments. Walks the entire wiki and raw trees in one pass.

## Read-Mostly Behavior

This workflow is read-mostly by contract. Auto-applied writes are SCOPED to index sync only:

| Write | Scope | Authorization |
|-------|-------|--------------|
| Re-sync wiki sources `My take` column from each source page (step 6) | `{wiki_root}/wiki/sources/{origin}/{origin}.md` | Auto-applied — no user diff |
| Renumber footnotes; remove stale footnote definitions (step 6) | Per source page touched | Auto-applied — no user diff |
| Create missing raw `{origin}.md` indexes; add missing rows with `Wiki = No` default (step 7) | `{wiki_root}/raw/{origin}/{origin}.md`, `{wiki_root}/raw/studies/studies.md` | Auto-applied — no user diff |
| Create missing wiki leaf indexes (`concepts.md`, `entities.md`, `topics.md`) (step 7) | `{wiki_root}/wiki/concepts/concepts.md`, `entities/entities.md`, `topics/topics.md` | Auto-applied — no user diff |
| Append `lint` entry to `log.md` (step 8) | `{wiki_root}/log.md` | Auto-applied — no user diff |

NEVER edit page bodies, frontmatter (other than `last-touched` on indexes), or any user-authored content from this workflow. NEVER delete pages. NEVER modify candidate-topic, candidate-mention, concept-created, entity-created, topic-created, ingest, query, or prior lint entries in `log.md`.

## Flow

No mid-flow user input. All 9 steps run unattended. Output is a single LINT REPORT presented at step 9.

### Step 1 — Walk all wiki pages; detect stubs and record age

1. Walk `{wiki_root}/wiki/concepts/`, `{wiki_root}/wiki/entities/`, `{wiki_root}/wiki/topics/`, and `{wiki_root}/wiki/sources/{*}/` per `../_shared/wiki/folder-structure.md`. Skip leaf indexes (`concepts.md`, `entities.md`, `topics.md`, `{origin}.md`).
2. For each page, apply the structural stub-state rule per `../_shared/wiki/stub-policy.md` "Stub State (lint detection)" section. Source pages: apply the user-half exemption from the same file.
3. For each detected stub, read `created:` from frontmatter (per `../_shared/wiki/frontmatter-schemas.md` common block). Compute age in days from today.
4. Build `stubs-aged` set: stubs with age >30 days. Capture page filename for the LINT REPORT.

### Step 2 — Walk all wiki pages; detect orphans

1. Walk every wiki page per `../_shared/wiki/folder-structure.md`. Skip leaf indexes.
2. Build a set of inbound wikilinks per page: scan ALL wiki page bodies, frontmatter `related:` lists, and `Sources` section footnote definitions for `[[<target>.md]]` references.
3. Mark a page as `orphan` if zero inbound wikilinks point to its filename.
4. Build `orphans` set. Capture page filenames for the LINT REPORT.

### Step 3 — Walk wiki concept/entity pages; detect unresolved Disputed callouts

1. Walk `{wiki_root}/wiki/concepts/` and `{wiki_root}/wiki/entities/`. Skip leaf indexes.
2. Detect `> [!warning] Disputed` callouts per `../_shared/wiki/section-menus.md` "Contradiction — Disputed Callout" section.
3. For each callout, parse the referenced candidate-topic timestamp (e.g., `[YYYY-MM-DD HH:MM]`) embedded in the callout body. Compute age in days from that timestamp.
4. Mark a callout as `unresolved` if age >30 days AND no `topic-created` log entry references the same candidate timestamp (resolution signal).
5. Build `unresolved-disputed` set: page filename + flagged date for the LINT REPORT.

### Step 4 — Walk `log.md`; detect aging candidate-topics

1. Read `{wiki_root}/log.md` in full.
2. Locate every `candidate-topic` H2 entry per `../_shared/wiki/log-entry-shapes.md`.
3. For each, parse the entry timestamp from the H2 header. Compute age in days.
4. Mark a candidate as `aging` if age >30 days AND no `topic-created` entry exists referencing the same candidate timestamp via the `resolves: candidate from <timestamp>` field.
5. Build `candidates-aging` set: candidate slug + logged date for the LINT REPORT.

### Step 5 — Walk all wiki pages; verify wikilinks resolve

1. Walk every wiki page per `../_shared/wiki/folder-structure.md`. Skip leaf indexes.
2. Extract all `[[<target>.md]]` wikilinks from each page body, frontmatter `related:` list, and footnote definitions per `../_shared/wiki/naming-convention.md`.
3. For each wikilink, verify the target file exists. Resolution rule: `<target>.md` must match an actual filename in `{wiki_root}/wiki/concepts/`, `entities/`, `topics/`, `sources/{*}/`, or `{wiki_root}/raw/{*}/`. Filename match is exact — wikilinks preserve the date format the target file uses (per `../_shared/wiki/naming-convention.md`).
4. Build `broken-wikilinks` set: source-page filename + missing target for the LINT REPORT.

### Step 6 — Re-sync wiki sources `My take` column; renumber footnotes; remove stale footnote definitions

For each `{wiki_root}/wiki/sources/{origin}/` directory (including `studies/`):

1. Read `{origin}.md` (or `studies.md`). Header format per `../_shared/wiki/index-formats.md` "Wiki Sources Index" section: `| File | What it says | My take |`.
2. For each row, locate the source page at `{wiki_root}/wiki/sources/{origin}/{filename}`. Read the page's `My take` section.
3. If the source page's `My take` section has content, derive a 1-sentence opinion (≤280 chars; truncate with ellipsis) per `../_shared/wiki/index-formats.md` ownership rules and write it to the row's `My take` cell (overwriting the prior derived value). If the source page's `My take` section is empty, leave the row's `My take` cell blank.
4. The source page is canonical. NEVER modify the source page's `My take` content.
5. Capture `sources-resynced` count for the LINT REPORT.

For each wiki page (concepts, entities, topics, source pages):

1. Apply footnote rules per `../_shared/wiki/citation-format.md`:
   - Renumber inline `[^N]` markers and matching `[^N]: [[<filename>.md]]` definitions sequentially per page (start at `[^1]`).
   - Preserve user prose appended to a definition (e.g., `[^1]: [[file.md]] — note: this is the original`).
   - Remove footnote definitions from the `Sources` section that are no longer referenced inline.
2. Capture `footnotes-renumbered` count (pages touched) for the LINT REPORT.

### Step 7 — Verify and create raw indexes; verify wiki leaf indexes

For each `{wiki_root}/raw/{origin}/` directory (including `studies/`):

1. Verify `{origin}.md` (or `studies.md`) exists. If missing, CREATE it with the standard raw index header per `../_shared/wiki/index-formats.md` "Raw Index" section: `| File | Title | Date | Wiki |`.
2. For each raw file in the directory, ensure a row exists in the index. If missing, add the row with `Wiki = No` (default). If a row already exists, preserve its `Wiki` value (`Yes`, `Partial`, or `No`).
3. Index creation and maintenance is the agent's job, not the user's (per schema § "/sb-wiki-lint" step 7 and `../_shared/wiki/folder-structure.md` "Creation Rules" table).
4. Capture `raw-indexes-created` count and `raw-rows-added` total for the LINT REPORT.

For each wiki leaf folder (`{wiki_root}/wiki/concepts/`, `entities/`, `topics/`):

1. Verify the leaf index exists (`concepts.md`, `entities.md`, `topics.md`).
2. If `wiki/topics/topics.md` is missing, CREATE it with the 2-column header `| File | Scope |` (per `_shared/wiki/folder-structure.md` "Creation Rules" table; topics-leaf-index format defined alongside `sb-wiki-create-topic`).
3. If `wiki/topics/topics.md` exists with a different column layout (user-customized), preserve the user's columns. Operate accordingly: read filenames from the `File` column; do NOT rewrite the layout.
4. For `wiki/concepts/concepts.md` and `wiki/entities/entities.md`: create with the standard wiki leaf-index header (`| File | Description |`) if missing. Preserve user-customized layouts when present.
5. For each page in the leaf folder, ensure a row exists for that page. If missing, add the row with `File = [[<filename>.md]]` and remaining columns blank for future agent population.
6. Capture `wiki-leaf-indexes-created` count and `wiki-leaf-rows-added` total for the LINT REPORT.

### Step 8 — Append `lint` log entry

Append a `lint` entry to `{wiki_root}/log.md` per `../_shared/wiki/log-entry-shapes.md` (Active Types — `lint` row). Entry is an H2 heading: `## [YYYY-MM-DD HH:MM] lint | <brief>`.

`<brief>` is a short label (e.g., `weekly health-check`, `manual run`). Default: `manual run`.

Required body fields summarizing findings from steps 1-7:

| Field | Value |
|-------|-------|
| `stubs aged >30d (N)` | List of `[[filename.md]]` from `stubs-aged` |
| `orphans (no inbound) (N)` | List of `[[filename.md]]` from `orphans` |
| `unresolved Disputed callouts (N)` | List of `[[filename.md]] — flagged YYYY-MM-DD` from `unresolved-disputed` |
| `candidates aging (N)` | List of `"<slug>" (logged YYYY-MM-DD)` from `candidates-aging` |
| `broken wikilinks (N)` | Count from `broken-wikilinks` (omit list if 0) |
| `index sync (wiki sources My take)` | `<sources-resynced>` pages |
| `index sync (raw)` | `<raw-indexes-created> created, <raw-rows-added> rows added` |
| `index sync (wiki leaf)` | `<wiki-leaf-indexes-created> created, <wiki-leaf-rows-added> rows added` (omit if both 0) |
| `footnotes renumbered` | `<footnotes-renumbered>` pages |

This log entry is `lint`-typed and standalone (NOT a sibling of any ingest entry) per `../_shared/wiki/log-entry-shapes.md` sibling-rule table.

### Step 9 — Present findings to the user

Present the LINT REPORT VERBATIM in the format below. Read-only output: no diff to accept; no file actions for the user to confirm; the auto-applied writes from steps 6-8 have already committed.

```
LINT REPORT — YYYY-MM-DD HH:MM

Stubs aged >30 days (N): [[X.md]], [[Y.md]], [[Z.md]]
Orphans (no inbound) (N): [[A.md]], [[B.md]]
Unresolved Disputed callouts (N): [[<page>.md]] — flagged YYYY-MM-DD
Candidate-topics aging without promotion (N): "<slug>" — logged YYYY-MM-DD
Broken wikilinks (N)
Index sync — wiki/sources My take refreshed: <N> source pages
Index sync — raw indexes: <N> created (raw/<origin>/<origin>.md), <M> rows added across raw/{origins}
Index sync — wiki leaf indexes: <N> created (wiki/<type>/<type>.md), <M> rows added across wiki/{concepts,entities,topics}
Footnotes renumbered: <N> source pages

No action required (lint is read-mostly; index sync writes auto-applied).
```

Omit any zero-count line with empty list (e.g., `Broken wikilinks (0)` may be elided when the body would be empty). The wiki leaf indexes line is omitted when both counts are 0. The trailing closing line is REQUIRED.

End of flow.

## Failure Modes

| Failure | Behavior |
|---------|----------|
| `{wiki_root}` cannot be resolved from `sb-os.json` | Halt before step 1; surface error. No writes. |
| `{wiki_root}/log.md` missing | Skip step 4 candidate-topic detection; capture `candidates-aging = 0`. Step 8 still appends — creating `log.md` if absent. |
| `{wiki_root}/wiki/` or `{wiki_root}/raw/` missing | Skip walks for the missing tree; capture zero counts for affected sets. Continue with remaining steps. |
| Source page referenced by a `wiki/sources/{origin}/{origin}.md` row does not exist | Skip the row at step 6 `My take` re-sync; do NOT remove the row (user may resolve manually). Capture in `sources-resynced` only when the page exists. |
| Raw file referenced by a `raw/{origin}/{origin}.md` row does not exist | Leave the row in place at step 7; do NOT remove it (user may have moved the raw file). |
| Wiki leaf index user-customized layout (`wiki/topics/topics.md`, `wiki/concepts/concepts.md`, or `wiki/entities/entities.md`) | Preserve at step 7; do NOT rewrite the layout. Operate against the existing `File` column for row presence checks. |
| Footnote definition in body uses non-standard form (e.g., text-only without wikilink) | Skip the entry at step 6 footnote renumber; preserve user content. Do NOT auto-correct. |
