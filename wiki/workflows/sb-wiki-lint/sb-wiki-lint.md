---
name: sb-wiki-lint
description: Health check + index maintenance for `raw/` and `wiki/` — detect stubs, orphans, unresolved Disputed callouts, aging candidate-topics, broken wikilinks; auto-apply index sync writes (wiki sources `My take` re-sync, footnote renumber, raw-index creation, wiki leaf-index creation); present read-only findings to the user.
---

# sb-wiki-lint

Health check + index maintenance pass across `{wiki_root}/raw/` and `{wiki_root}/wiki/`. Implements the 9-step lint flow defined in the wiki schema. Read-mostly: deterministic index sync writes are auto-applied; judgment-bearing index cells are filled by the LLM before the final report.

## Schema Source

Read `3-resources/tools/sb-os/wiki/docs/wiki-schema.md` — Operations § "/sb-wiki-lint" — for canonical step definitions. This workflow body implements that spec verbatim. Schema deviations require updating the schema first.

## Path Resolution

| Symbol | Resolution |
|--------|------------|
| `{wiki_root}` | Read from `sb-os.json` at vault root → `wiki_root` field. Resolve via `install/manifest.py` (`manifest.read(vault_root)`). Never hardcode. |
| `{user_context_root}` | Read from `sb-os.json` → `user_context_root`. Never hardcode. |
| `{wiki_root}/wiki/` | Wiki page tree (concepts, entities, topics, sources). |
| `{wiki_root}/raw/` | Raw source tree. |
| `{wiki_root}/log.md` | Actionable queue — `candidate-topic` + `candidate-mention` entries only. |

## Shared Data Files

These files codify rules referenced across multiple `sb-wiki-*` workflows. Load only the files relevant to the active step.

| File | Used by step |
|------|--------------|
| `../shared/folder-structure.md` | 1, 2, 5, 7, 7.5 |
| `../shared/stub-policy.md` | 1 |
| `../shared/section-menus.md` | 1, 3 |
| `../shared/frontmatter-schemas.md` | 1, 4, 7.5 |
| `../shared/naming-convention.md` | 5 |
| `../shared/citation-format.md` | 6 |
| `../shared/index-formats.md` | 6, 7, 7.5 |
| `../shared/log-entry-shapes.md` | 4, 8 |

## Invocation

`/sb-wiki-lint`. No arguments. Walks the entire wiki and raw trees in one pass.

## Read-Mostly Behavior

This workflow is read-mostly by contract. Auto-applied writes are SCOPED to index sync only. Subdivision execution writes (step 7.5) are USER-GATED — only on explicit accept at step 9.

| Write | Scope | Authorization |
|-------|-------|--------------|
| Re-sync wiki sources `My take` column from each source page (step 6) | `{wiki_root}/wiki/sources/{origin}/{origin}.md` | Auto-applied — no user diff |
| Renumber footnotes; remove stale footnote definitions (step 6) | Per source page touched | Auto-applied — no user diff |
| Create missing raw `{origin}.md` indexes; add missing rows with `Wiki = No` default (step 7) | `{wiki_root}/raw/{origin}/{origin}.md`, `{wiki_root}/raw/studies/studies.md` | Auto-applied — no user diff |
| Create missing wiki leaf indexes (`concepts.md`, `entities.md`, `topics.md`) (step 7) | `{wiki_root}/wiki/concepts/concepts.md`, `entities/entities.md`, `topics/topics.md` | Auto-applied — no user diff |
| Prune spent/retired entries from `log.md` (step 8) — delete `candidate-topic`/`candidate-mention` entries whose page now exists, and delete retired history entries | `{wiki_root}/log.md` | Auto-applied — no user diff |
| Folder subdivision execution (step 7.5) — create `{type}/{subfolder}/`, leaf index, marker-block CLAUDE.md, rewrite parent index as router, MOVE pages | `{wiki_root}/wiki/{concepts,entities}/...` | USER-GATED — executed only on `accept` at step 9 |

NEVER edit page bodies, frontmatter (other than `last-touched` on indexes and on pages moved by subdivision), or any user-authored content from this workflow. NEVER delete pages. NEVER write a `lint` entry — lint findings live in the report only. The log is an actionable queue (`candidate-topic` + `candidate-mention` only); lint MAY delete entries that are spent (page exists) or retired (history types), but NEVER edits the body of a `candidate-topic`/`candidate-mention` it keeps, and NEVER auto-deletes a `candidate-mention` whose page does not yet exist.

**`raw/assets/` is OUT OF SCOPE for this workflow.** No reads, no writes, no walks, no index creation, no orphan-detection participation, no filename validation. The folder is user-maintained via Obsidian's "Download attachments for current file" command (per `../shared/folder-structure.md` "Asset Folder" and schema § "Asset folder"). Treat it as if it were not present in the tree. Same exclusion applies to any pre-existing legacy asset folder nested under a specific origin (e.g., `raw/mails/assets/`) — user-owned, untouched.

## Deterministic Helper

Before Step 1, run the deterministic helper from the vault root with the active Python interpreter:

```bash
python 3-resources/tools/sb-os/wiki/scripts/sb-wiki-lint-deterministic.py --apply --report 3-resources/knowledge-base/lint-deterministic-report.json
```

The helper is mandatory. It performs only script-safe work: raw index creation when `Title` and `Date` are deterministic, wiki leaf-index header creation, wiki source `My take` re-sync, broken-wikilink inventory, and a JSON queue named `judgment_needed`.

The helper MUST NOT fill judgment-bearing cells. `Description`, `Scope`, and `What it says` require LLM judgment. After the helper runs, read the JSON report and resolve every `judgment_needed` item by reading the referenced file and writing the required semantic cell before Step 8.

## Flow

Steps 1-8 run unattended. Step 8 PRUNES `log.md` (deletes spent candidates + retired history; writes NO `lint` entry). Step 9 is read-only for findings 1-7 and surfaces the `candidate-mention` review queue; when step 7.5 produced a non-empty `subdivision-proposals` set, the LINT REPORT at step 9 includes a SUBDIVISION PROPOSAL block that requires a user decision (accept all / accept N / reject / defer). On user accept, the agent executes the subdivision per step 7.5 § "Subdivision execution" (no log entry). The agent must perform the LLM judgment pass from the deterministic helper report before Step 8.

### Step 1 — Walk all wiki pages; detect stubs and record age

1. Walk `{wiki_root}/wiki/concepts/`, `{wiki_root}/wiki/entities/`, `{wiki_root}/wiki/topics/`, and `{wiki_root}/wiki/sources/{*}/` per `../shared/folder-structure.md`. Skip leaf indexes (`concepts.md`, `entities.md`, `topics.md`, `{origin}.md`).
2. For each page, apply the structural stub-state rule per `../shared/stub-policy.md` "Stub State (lint detection)" section. Source pages: apply the user-half exemption from the same file.
3. For each detected stub, read `created:` from frontmatter (per `../shared/frontmatter-schemas.md` common block). Compute age in days from today.
4. Build `stubs-aged` set: stubs with age >30 days. Capture page filename for the LINT REPORT.

### Step 2 — Walk all wiki pages; detect orphans

**Orphan-detection scope is STRICT.** Inbound-link computation considers ONLY synthesis pages — not log entries, not source pages, not raw indexes, not leaf indexes. The orphan signal exists to surface entities/concepts/topics the wiki has noticed but is not actively cross-linking from real synthesis.

| Scope | Files |
|-------|-------|
| **Pages eligible to BE orphans** | `wiki/concepts/*.md`, `wiki/entities/*.md`, `wiki/topics/*.md` (excluding leaf indexes `concepts.md`, `entities.md`, `topics.md`) |
| **Files in scope as INBOUND-LINK SOURCES** | The same set above — `wiki/concepts/*.md`, `wiki/entities/*.md`, `wiki/topics/*.md` (excluding leaf indexes) |
| **Files OUT OF SCOPE as inbound-link sources** | `log.md`, `wiki/sources/{origin}/{origin}.md` indexes, `wiki/sources/{origin}/<date>-<slug>.md` source pages, raw source pages under `raw/`, `raw/{origin}/{origin}.md` raw indexes, all leaf indexes (`concepts.md`, `entities.md`, `topics.md`, `studies.md`), and **everything inside `raw/assets/`** (binary attachments — image embeds inside source/wiki pages do NOT count as inbound links toward orphan status) |

1. Build the eligible-orphan set: every concept/entity/topic page (excluding leaf indexes).
2. Build the inbound-link map: scan ONLY concept/entity/topic page bodies, frontmatter `related:` lists, and `Sources` section footnote definitions for `[[<target>.md]]` references. Do NOT scan source pages, log entries, raw files, or any leaf index.
3. Mark a page as `orphan` if zero in-scope inbound wikilinks point to its filename. Wikilinks from out-of-scope files (log mentions, source-page footnote definitions, raw indexes) do NOT count toward inbound — they are evidence of mention, not synthesis.
4. Build `orphans` set. Capture page filenames for the LINT REPORT.

**Rationale.** Forcing inbound links to come from real wiki content (concept / entity / topic pages) keeps the orphan bar high and preserves the signal's diagnostic value. A stub created from a Notable Quote will, by design, be flagged as an orphan on the next lint run if no concept/entity/topic page links to it — this is correct behavior, not a false positive (per schema § "Orphan-detection scope (STRICT)").

### Step 3 — Walk wiki concept/entity pages; detect unresolved Disputed callouts

1. Walk `{wiki_root}/wiki/concepts/` and `{wiki_root}/wiki/entities/`. Skip leaf indexes.
2. Detect `> [!warning] Disputed` callouts per `../shared/section-menus.md` "Contradiction — Disputed Callout" section.
3. For each callout, parse the referenced candidate-topic timestamp (e.g., `[YYYY-MM-DD HH:MM]`) embedded in the callout body. Compute age in days from that timestamp.
4. Mark a callout as `unresolved` if age >30 days AND the candidate-topic it references has not been promoted (no topic page exists resolving the dispute — resolution = page exists).
5. Build `unresolved-disputed` set: page filename + flagged date for the LINT REPORT.

### Step 4 — Walk `log.md`; detect aging candidate-topics

1. Read `{wiki_root}/log.md` in full.
2. Locate every `candidate-topic` H2 entry per `../shared/log-entry-shapes.md`.
3. For each, parse the entry timestamp from the H2 header. Compute age in days.
4. Resolution = page exists. A candidate is SPENT if a topic page matching its slug exists at `{wiki_root}/wiki/topics/` (flat or any subfolder). Spent candidates are pruned at step 8, NOT reported as aging.
5. Mark a candidate as `aging` if age >30 days AND its topic page does NOT exist.
6. Build `candidates-aging` set: candidate slug + logged date for the LINT REPORT.

### Step 5 — Walk all wiki pages; verify wikilinks resolve

1. Walk every wiki page per `../shared/folder-structure.md`. Skip leaf indexes.
2. Extract all `[[<target>.md]]` wikilinks from each page body, frontmatter `related:` list, and footnote definitions per `../shared/naming-convention.md`.
3. For each wikilink, verify the target file exists. Resolution rule: `<target>.md` must match an actual filename in `{wiki_root}/wiki/concepts/`, `entities/`, `topics/`, `sources/{*}/`, or `{wiki_root}/raw/{*}/` — EXCLUDING `raw/assets/` (assets are binary attachments, not wiki targets, per `../shared/folder-structure.md` "Asset Folder"). Filename match is exact — wikilinks preserve the date format the target file uses (per `../shared/naming-convention.md`).
4. Image-embed wikilinks (`![[<target>.<ext>]]` where `<ext>` is `png`, `jpg`, `jpeg`, `gif`, `webp`, `svg`, `pdf`, or any non-`md` extension) are SKIPPED at this step. Obsidian resolves embeds via global attachment search; they target `raw/assets/` (or pre-existing exception folders), which lint does not validate.
5. Build `broken-wikilinks` set: source-page filename + missing target for the LINT REPORT.

### Step 6 — Re-sync wiki sources `My take` column; renumber footnotes; remove stale footnote definitions

For each `{wiki_root}/wiki/sources/{origin}/` directory (including `studies/`):

1. Read `{origin}.md` (or `studies.md`). Header format per `../shared/index-formats.md` "Wiki Sources Index" section: `| File | What it says | My take |`.
2. For each row, locate the source page at `{wiki_root}/wiki/sources/{origin}/{filename}`. Read the page's `My take` section.
3. Apply the three-state re-sync rule per `../shared/index-formats.md` "`My take` Cell — Three States" section. **NEVER leave the cell blank** — every row carries `pending`, `—`, or a 1-sentence reflected preview.

   | Source page's `My take` body | Current cell value | Action |
   |------------------------------|--------------------|--------|
   | Has substantive content | Any | Write 1-sentence reflected preview (≤280 chars; truncate with ellipsis), overwriting prior cell value |
   | Empty | `—` | Preserve `—` (final, do NOT age out) |
   | Empty | `pending` | Preserve `pending` |
   | Empty | Anything else (legacy blank, stray content) | Write `pending` (default to action-pending; safer to over-prompt than to over-finalize) |

4. The source page is canonical. NEVER modify the source page's `My take` content.
5. Capture `sources-resynced` count for the LINT REPORT.

**Staleness behavior.** The 7-day staleness rule for `My take` re-sync applies to `pending` rows ONLY. `—` rows are final and do NOT age out. Reflected rows are refreshed every lint pass.

For each wiki page (concepts, entities, topics, source pages):

1. Apply footnote rules per `../shared/citation-format.md`:
   - Renumber inline `[^N]` markers and matching `[^N]: [[<filename>.md]]` definitions sequentially per page (start at `[^1]`).
   - Preserve user prose appended to a definition (e.g., `[^1]: [[file.md]] — note: this is the original`).
   - Remove footnote definitions from the `Sources` section that are no longer referenced inline.
2. Capture `footnotes-renumbered` count (pages touched) for the LINT REPORT.

### Step 7 — Verify and create raw indexes; verify wiki leaf indexes

For each `{wiki_root}/raw/{origin}/` directory (including `studies/`), **EXCLUDING `raw/assets/`** (per `../shared/folder-structure.md` "Asset Folder" — `raw/assets/` is NOT a raw origin and MUST NOT receive an `assets.md` leaf index, MUST NOT be walked as part of raw-origin maintenance, and MUST NOT have its filenames validated):

1. Verify `{origin}.md` (or `studies.md`) exists. If missing, CREATE it with the standard raw index header per `../shared/index-formats.md` "Raw Index" section: `| File | Title | Date | Wiki |`.
2. For each raw file in the directory, ensure a row exists in the index. If missing, add the row only when `Title` and `Date` are deterministic from frontmatter, an H1, or the filename date.
3. Index creation and maintenance is the agent's job, not the user's (per schema § "/sb-wiki-lint" step 7 and `../shared/folder-structure.md` "Creation Rules" table).
4. If a row already exists, preserve its `Wiki` value (`Yes`, `Partial`, or `No`).
5. Capture `raw-indexes-created` count, `raw-rows-added` total, and unresolved raw rows from `judgment_needed` for the LINT REPORT.

For each wiki leaf folder (`{wiki_root}/wiki/concepts/`, `entities/`, `topics/`):

1. Verify the leaf index exists (`concepts.md`, `entities.md`, `topics.md`).
2. If `wiki/topics/topics.md` is missing, CREATE it with the 2-column header `| File | Scope |` (per `shared/folder-structure.md` "Creation Rules" table; topics-leaf-index format defined alongside `sb-wiki-create-topic`).
3. If `wiki/topics/topics.md` exists with a different column layout (user-customized), preserve the user's columns. Operate accordingly: read filenames from the `File` column; do NOT rewrite the layout.
4. For `wiki/concepts/concepts.md` and `wiki/entities/entities.md`: create with the standard wiki leaf-index header (`| File | Description |`) if missing. Preserve user-customized layouts when present.
5. For each page in the leaf folder, ensure a row exists for that page. If missing, read the page and add a row with a semantic `Description` or `Scope`; never leave judgment-bearing columns blank.
6. Capture `wiki-leaf-indexes-created` count and `wiki-leaf-rows-added` total for the LINT REPORT.

**Judgment-bearing cell rule:** Steps above never authorize blank semantic cells. `Description`, `Scope`, and `What it says` require LLM judgment. If the deterministic helper reports a missing row for those cells, the agent MUST read the referenced page and write the semantic cell before Step 8 (the log-prune pass).

### Step 7.5 — Folder-subdivision detection

Detect kinds within `wiki/concepts/` and `wiki/entities/` that have grown large enough to warrant per-kind subfolders. Skip `wiki/topics/` and `wiki/sources/` per schema § "Folder subdivision" — Topics-Sources-Excluded.

1. For `wiki/concepts/` and `wiki/entities/`:
   1. Walk all pages (skip leaf indexes and any existing per-kind subfolder indexes — those pages have already graduated).
   2. Group pages by `kind:` frontmatter value. Pages without a `kind:` value are tracked separately as `kind-missing` and surface in the LINT REPORT for the user to address.
   3. For each `kind:` value, count pages.
   4. Mark counts:
      - <5 pages → silent.
      - ≥5 pages → `subdivision-proposal` (kind name + count + suggested subfolder name per the naming policy in schema § "Folder subdivision" → "Naming policy"; sample first 5 page filenames).
2. Build `subdivision-proposals` set for the LINT REPORT and step 8 log entry.
3. **Subdivision execution gate.** Subdivision proposals are EXECUTED only on explicit user accept at step 9. Pre-step-9 lint runs silently in the background; step 7.5 only DETECTS — it never moves files. Execution at step 9 follows the procedure in "Subdivision execution" below.

#### Subdivision proposal — naming policy lookup

Resolve the suggested subfolder name from the `kind:` value per schema § "Folder subdivision" → "Naming policy":

| `kind:` value | Suggested subfolder | Domain prefix? |
|---------------|---------------------|----------------|
| `model` | `ai-models/` | YES — "models" is generic across domains |
| `person` | `persons/` | NO — universal |
| `company` | `organizations/` | NO — universal (renamed for inclusivity) |
| `tool` | `tools/` | NO initially; flag rename if a non-AI tool surfaces |
| `product` | `products/` | NO initially |
| `benchmark` | `ai-benchmarks/` | YES — "benchmark" spans domains |
| `data-format` | `data-formats/` | NO — universal |
| `inference-scaffold` | `inference-scaffolds/` | NO |
| `automation-economics` | `automation-economics/` | NO — kind already plural-shaped, do NOT append `s` |
| `cognitive-displacement` | `cognitive-displacements/` | NO |
| `ai-collaboration-model` | `ai-collaboration-models/` | NO |
| Other / new kind | `{kind}s/` | Apply heuristic: prefix when the term is generic across domains the vault might cover; otherwise plain. Kind names MUST pass the blind-reader test (a reader with zero context understands what the kind contains). Generic terms (`pattern`, `spec`, `dynamic`) FAIL — split into more specific kinds. |

If a kind not in the table appears at threshold, surface the proposal with a `(naming heuristic applied)` annotation so the user can override.

#### Subdivision execution (only on user accept at step 9)

For each accepted subfolder:

1. Resolve target path: `{wiki_root}/wiki/{type}/{subfolder}/`. Create the directory if absent.
2. Create the leaf index `{wiki_root}/wiki/{type}/{subfolder}/{subfolder}.md` with header `| File | Description |` per `../shared/index-formats.md` "Wiki Leaf Indexes" section. For each page being moved, add a row with the same `Description` value the parent leaf index used; if the parent leaf row was missing or blank, generate a 1-sentence factual description from the page body (judgment-bearing).
3. For each page with `kind: {kind-value}` matching this subfolder:
   - Move the page from `{wiki_root}/wiki/{type}/{slug}.md` to `{wiki_root}/wiki/{type}/{subfolder}/{slug}.md`.
   - Update the page's `last-touched:` frontmatter to today.
   - Do NOT modify body content.
   - Inbound wikilinks are NOT rewritten — Obsidian's filename-based shortest-path resolution carries them across the move (the user must have configured "New link format" = `Shortest path when possible` per README "Obsidian setup"; if not, lint surfaces a warning and aborts subdivision execution to avoid breaking links).
4. Rewrite `{wiki_root}/wiki/{type}/{type}.md` (the parent index) as a ROUTER per `../shared/index-formats.md` "Type-Folder Router Index" section: `| Subfolder | Holds | Index |` table for each subfolder, plus a `## Flat pages` section listing pages whose kind has not graduated.
5. Create or update `{wiki_root}/wiki/{type}/CLAUDE.md` with marker-block routing rules per `../shared/index-formats.md` "Type-Folder Managed CLAUDE.md" section. Inside the markers, the agent writes the `Subfolder routing` table and `Flat pages` policy. Outside the markers, preserve user content verbatim.
6. Verify Obsidian-config precondition. If the vault's `.obsidian/app.json` exists and explicitly sets `newLinkFormat` to a value other than `shortest` (or empty), surface a warning in the LINT REPORT and ABORT this subdivision (no file moves committed). Default Obsidian behavior is shortest-path when the field is absent — that case proceeds.
7. Capture `subdivision-executed` count for the LINT REPORT: subfolder name + page count moved. No log entry is written for subdivision — the folder structure and indexes are the record.

### Step 8 — Prune the log

The log is an actionable queue. Lint NEVER writes a `lint` entry — findings live in the LINT REPORT (step 9) only. Lint's only write to `log.md` is PRUNING:

1. Read `{wiki_root}/log.md` in full. Parse H2 entries per `../shared/log-entry-shapes.md`.
2. DELETE every retired-type entry (`ingest`, `concept-created`, `entity-created`, `topic-created`, `topic-updated`, `topic-coverage-candidate`, `lint`, `query`) — these are no longer active. Remove the full entry (header + body).
3. DELETE every `candidate-topic` whose matching topic page exists at `{wiki_root}/wiki/topics/` (flat or subfolder) — spent (resolution = page exists).
4. DELETE every `candidate-mention` whose matching page exists anywhere under `{wiki_root}/wiki/` (any type, flat or subfolder) — spent. Match by the entry's slug/`name:` normalized to the page filename.
5. KEEP every `candidate-topic` and `candidate-mention` whose page does NOT yet exist. NEVER auto-age a `candidate-mention` — it persists until its page exists or the user dismisses it. NEVER edit the body of a kept entry.
6. Preserve the file preamble. Capture `entries-pruned` count (by reason: spent vs retired) for the LINT REPORT.

### Step 9 — Present findings to the user

Present the LINT REPORT VERBATIM in the format below. Read-only for findings 1-7; the SUBDIVISION PROPOSAL block (when present) is the only interactive part — auto-applied writes from steps 6-8 have already committed.

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
Pages without `kind:` (N): [[<file>.md]]
Log pruned: <N> spent (page now exists), <M> retired history entries removed
Candidate-mentions to review (N): "<slug>", "<slug>", … (the actionable queue — promote to a stub or dismiss)

SUBDIVISION PROPOSAL (omit block entirely when empty):
| # | type | kind | count | suggested subfolder | sample pages |
|---|------|------|-------|---------------------|--------------|
| 1 | entities | person | 7 | persons/ | yann-lecun, mike-brown, … |
| 2 | entities | benchmark | 5 | ai-benchmarks/ | browsecomp-plus, longbenchpro, … |

Decisions: accept all | accept N (e.g. "accept 1") | reject | defer
(Default if the user does not respond: defer all — proposals persist in the next lint run.)

No action required for findings 1-7 (lint is read-mostly; index sync + log prune auto-applied). The candidate-mention queue is yours to work through at your pace — nothing is auto-deleted.
```

Omit any zero-count line with empty list (e.g., `Broken wikilinks (0)` may be elided when the body would be empty). The wiki leaf indexes line is omitted when both counts are 0. The SUBDIVISION PROPOSAL block is omitted when the proposal set is empty. The trailing closing line is REQUIRED.

User response handling for SUBDIVISION PROPOSAL:

| Response | Behavior |
|----------|----------|
| `accept all` | Execute every proposed subdivision per the procedure in step 7.5 § "Subdivision execution". No log entry — the new folder structure and indexes are the record. |
| `accept N` (e.g. `accept 1,2`) | Execute the listed proposals only. Other proposals defer. |
| `reject` | All proposals defer; surface as warnings in the next lint run. |
| `defer` (default) | Same as `reject` for this run; proposals re-surface in subsequent runs as long as the kind remains ≥10 pages. |

End of flow.

## Failure Modes

| Failure | Behavior |
|---------|----------|
| `{wiki_root}` cannot be resolved from `sb-os.json` | Halt before step 1; surface error. No writes. |
| `{wiki_root}/log.md` missing | Skip step 4 candidate-topic detection; capture `candidates-aging = 0`. Step 8 prunes only — if `log.md` is absent there is nothing to prune; skip it (do NOT create the file). |
| `{wiki_root}/wiki/` or `{wiki_root}/raw/` missing | Skip walks for the missing tree; capture zero counts for affected sets. Continue with remaining steps. |
| Source page referenced by a `wiki/sources/{origin}/{origin}.md` row does not exist | Skip the row at step 6 `My take` re-sync; do NOT remove the row (user may resolve manually). Capture in `sources-resynced` only when the page exists. |
| Raw file referenced by a `raw/{origin}/{origin}.md` row does not exist | Leave the row in place at step 7; do NOT remove it (user may have moved the raw file). |
| Wiki leaf index user-customized layout (`wiki/topics/topics.md`, `wiki/concepts/concepts.md`, or `wiki/entities/entities.md`) | Preserve at step 7; do NOT rewrite the layout. Operate against the existing `File` column for row presence checks. |
| Footnote definition in body uses non-standard form (e.g., text-only without wikilink) | Skip the entry at step 6 footnote renumber; preserve user content. Do NOT auto-correct. |
