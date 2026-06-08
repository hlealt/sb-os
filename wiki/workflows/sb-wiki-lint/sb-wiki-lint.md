---
name: sb-wiki-lint
description: Health check + index maintenance for `raw/` and `wiki/` — detect stubs, orphans, unresolved Disputed callouts, aging candidate-topics, broken wikilinks; auto-apply index sync writes (wiki sources `My take` re-sync, footnote renumber, raw-index creation, wiki leaf-index creation); when the optional questions layer is ON, sweep open questions for now-available answers and surface mature entries for graduation as user-gated proposals; present read-only findings to the user.
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
| `../shared/folder-structure.md` | 1, 2, 5, 7, 7.5, 8.5 |
| `../shared/stub-policy.md` | 1, 7.7 |
| `../shared/section-menus.md` | 1, 3 |
| `../shared/frontmatter-schemas.md` | 1, 4, 7.5, 8.5 |
| `../shared/naming-convention.md` | 5, 7.6 |
| `../shared/citation-format.md` | 6 |
| `../shared/index-formats.md` | 6, 7, 7.5 |
| `../shared/log-entry-shapes.md` | 4, 8 |
| `../shared/question-entry-shapes.md` | 5, 7.7, 8, 8.5 |

## Invocation

`/sb-wiki-lint`. No arguments. Walks the entire wiki and raw trees in one pass.

## Read-Mostly Behavior

This workflow is read-mostly by contract. Auto-applied writes are SCOPED to index sync only. Subdivision execution writes (step 7.5) are USER-GATED — only on explicit accept at step 9.

| Write | Scope | Authorization |
|-------|-------|--------------|
| Re-sync wiki sources `My take` column from each source page (step 6) | `{wiki_root}/wiki/sources/{origin}/{origin}.md` | Auto-applied — no user diff |
| Renumber footnotes — safe bijections only; stale-def removal is REPORT-ONLY per `../shared/citation-format.md` (step 6) | Per source page touched | Auto-applied — no user diff |
| Create missing raw `{origin}.md` indexes; add missing rows with `Wiki = No` default (step 7) | `{wiki_root}/raw/{origin}/{origin}.md`, `{wiki_root}/raw/studies/studies.md` | Auto-applied — no user diff |
| Create missing wiki leaf indexes (`concepts.md`, `entities.md`, `topics.md`) (step 7) | `{wiki_root}/wiki/concepts/concepts.md`, `entities/entities.md`, `topics/topics.md` | Auto-applied — no user diff |
| Fill concept/entity `Description` cells from each page's lead definition sentence; weak pages (no clean lead sentence) reported, never written (step 7) | concept/entity leaf indexes + router `## Flat pages` tables under `{wiki_root}/wiki/{concepts,entities}/` | Auto-applied — no user diff |
| Type-tag sync (step 7) — append each page's `type:` value to its `tags:` frontmatter when absent (append-only, user tags preserved); add `type: index` + `tags: [index]` to index files missing `type:` | Every page under `{wiki_root}/wiki/` | Auto-applied — no user diff |
| Prune spent/retired entries from `log.md` (step 8) — delete `candidate-topic`/`candidate-mention` entries whose page now exists, and delete retired history entries | `{wiki_root}/log.md` | Auto-applied — no user diff |
| Prune promoted/retired entries from `questions.md` (step 8) — delete entries whose matching wiki page now exists (promoted) or that the user retired, by the same "page exists" test as the `candidate-mention` prune | `{wiki_root}/questions.md` | Auto-applied — no user diff. Skipped entirely when `questions.md` is absent |
| Regenerate `open-gaps.md` wholesale (step 8.5) — overwrite the read-only cross-wiki aggregate of all open questions (both homes) | `{wiki_root}/open-gaps.md` | Auto-applied — no user diff. ALWAYS emitted (empty-state file when nothing to aggregate); never skipped |
| Folder subdivision execution (step 7.5) — create `{type}/{subfolder}/`, leaf index, marker-block CLAUDE.md, rewrite parent index as router, MOVE pages | `{wiki_root}/wiki/{concepts,entities}/...` | USER-GATED — executed only on `accept` at step 9 |
| PDF title-conformance rename execution (step 7.6) — rename raw PDF + source page, rewrite all referrers (frontmatter, footnotes, both indexes, `log.md`) | `{wiki_root}/raw/{origin}/`, `{wiki_root}/wiki/...`, `{wiki_root}/log.md` | USER-GATED — executed only on `accept` at step 9 |
| Questions answer-sweep apply (step 7.7) — accrete a cited `answer:` bullet on a `questions.md` entry, OR strike + fold a topic-home `Open questions` answer into the topic body (append-only) | `{wiki_root}/questions.md`, `{wiki_root}/wiki/topics/*.md` | USER-GATED — applied only on `accept` at step 9. Skipped entirely when `questions.md` is absent |
| Graduation execution (step 9 GRADUATION PROPOSAL) — invoke `sb-wiki-create-topic` for an accepted mature `questions.md` entry (NEVER auto-author a page) | (the skill writes the page; lint writes nothing directly) | USER-GATED — invoked only on `accept` at step 9. Skipped entirely when `questions.md` is absent |

NEVER edit page bodies, frontmatter (other than `last-touched` on indexes and on pages moved by subdivision, the append-only type-tag sync per step 7, and wikilink-target rewrites performed by a user-accepted PDF title-conformance rename per step 7.6), or any user-authored content from this workflow. NEVER delete pages. NEVER write a `lint` entry — lint findings live in the report only. The log is an actionable queue (`candidate-topic` + `candidate-mention` only); lint MAY delete entries that are spent (page exists) or retired (history types), but NEVER edits the body of a `candidate-topic`/`candidate-mention` it keeps, and NEVER auto-deletes a `candidate-mention` whose page does not yet exist. `questions.md` is the parallel user queue: lint MAY delete an entry that is promoted (matching wiki page now exists) or retired (by the same "page exists" test the `candidate-mention` prune uses), but NEVER edits the body of a kept entry and NEVER prunes a merely-answered entry that has not yet graduated. `open-gaps.md` is lint-generated and READ-ONLY — lint OVERWRITES it wholesale each run; the user's edits to it are not preserved.

**`raw/assets/` is OUT OF SCOPE for this workflow.** No reads, no writes, no walks, no index creation, no orphan-detection participation, no filename validation. The folder is user-maintained via Obsidian's "Download attachments for current file" command (per `../shared/folder-structure.md` "Asset Folder" and schema § "Asset folder"). Treat it as if it were not present in the tree. Same exclusion applies to any pre-existing legacy asset folder nested under a specific origin (e.g., `raw/mails/assets/`) — user-owned, untouched.

## Deterministic Helper

Before Step 1, run the deterministic helper from the vault root with the active Python interpreter:

```bash
python {sb_os_path}/wiki/scripts/sb-wiki-lint-deterministic.py --apply --report {wiki_root}/lint-deterministic-report.json
python {sb_os_path}/wiki/scripts/sb-wiki-fill-index-descriptions.py --apply
```

Run both, in order — the first owns the deterministic index-row + footnote work; the second (step 7) fills concept/entity `Description` cells from each page's lead definition sentence and reports pages with no clean lead sentence as `weak` (those stay LLM-owned). The helper is mandatory. It executes the deterministic halves of the lint steps in one pass — NEVER re-derive these by walking files with LLM reads. Consume the JSON report keys per this map:

| Report key | Feeds step | Content |
|------------|-----------|---------|
| `writes`, `judgment_needed` | 6, 7 | Auto-applied index writes; queue of judgment-bearing cells (incl. `row-shape` malformed rows) |
| `detected.stubs_aged_gt30`, `stubs_fresh_count`, `stubs_no_created` | 1 | Stub state + age (user-half exemption applied) |
| `detected.orphans` | 2 | STRICT-scope orphans (concept/entity/topic inbound only) |
| `detected.broken_wikilinks` | 5 | Unresolved wikilink inventory |
| `detected.questions_broken_links` | 5 | `questions.md` `relates:`/`seeded-by:` targets that do not resolve (absent file → key empty) |
| `detected.footnote_issues`, `provenance_only_count`, `renumbered` | 6 | Set-mismatch findings (report-only); pages with defs-and-no-inline (never touched); safe-bijection renumbers auto-applied under `--apply` |
| `detected.log_spent_entries`, `log_retired_entries`, `log_unknown_type_entries`, `log_aging_candidate_topics` | 4, 8 | Prune-test results + aging candidates + non-canonical entries (kept) |
| `detected.type_tags` | 7 | Type-tag sync results — `tags_added` / `type_index_added` counts (auto-applied under `--apply`) + `unresolved` pages whose `type:` cannot be derived deterministically (surface in the LINT REPORT for the user) |
| `detected.rename_proposals`, `duplicate_raws`, `title_disambiguation_needed` | 7.6 | PDF title-conformance detection; same-title collisions surface as disambiguation, never proposals |
| `detected.subdivision_proposals`, `subdivision_stragglers`, `kind_missing`, `generic_kind_flags` | 7.5 | Folder-subdivision detection |

Execution flags — the helper also owns the mechanical halves of the write paths:

| Flag | Class | Used at |
|------|-------|---------|
| `--apply` | Safe auto-apply | The mandatory pre-Step-1 run — index sync writes + safe footnote renumber |
| `--prune-log` | Safe auto-apply (lint-contract-authorized) | Step 8 — deletes spent + retired `log.md` entries exactly as steps 8.2-8.4 specify; unknown types and plain headings always survive |
| `--execute-renames <plan.json>` | USER-GATED executor | Step 9, on RENAME PROPOSAL accept — plan rows `{origin, old_stem, new_stem}`; rewrites scoped wikilink patterns in non-raw files + raw indexes only, then moves the two files (per step 7.6 execution) |
| `--execute-subdivision <plan.json>` | USER-GATED executor | Step 9, on SUBDIVISION PROPOSAL accept — plan rows `{type_folder, slug, target_subfolder}`; moves pages, bumps `last-touched`, performs index row surgery. `CLAUDE.md` routing rows and first-time router rewrites are returned as `claude_md_pending`/errors for the AGENT to apply — the script never edits CLAUDE.md |

NEVER run an executor flag without an explicit user accept at step 9. After any executor run, apply every `claude_md_pending` row and resolve every error surfaced in `detected.renames` / `detected.subdivision`.

The helper MUST NOT fill judgment-bearing cells. `Description`, `Scope`, and `What it says` require LLM judgment. After the helper runs, read the JSON report and resolve every `judgment_needed` item by reading the referenced file and writing the required semantic cell before Step 8.

## Flow

Steps 1-8.5 run unattended. Step 8 PRUNES `log.md` (deletes spent candidates + retired history; writes NO `lint` entry) and, when the questions layer is ON, PRUNES `questions.md` (deletes promoted entries whose page now exists + retired entries, by the same "page exists" test). Step 8.5 REGENERATES `{wiki_root}/open-gaps.md` wholesale — a read-only cross-wiki aggregate of every open question across both homes (always emitted, empty-state when nothing is open; skipped only as a no-op when the questions layer is OFF and no topic has an open question). Step 9 is read-only for findings 1-7 and surfaces the `candidate-mention` review queue; when step 7.5 produced a non-empty `subdivision-proposals` set, the LINT REPORT at step 9 includes a SUBDIVISION PROPOSAL block that requires a user decision (accept all / accept N / reject / defer). On user accept, the agent executes the subdivision per step 7.5 § "Subdivision execution" (no log entry). Likewise, when step 7.6 produced a non-empty `rename-proposals` set, the report includes a RENAME PROPOSAL block; on user accept the agent executes the rename + full referrer rewrite per step 7.6 § "PDF title-conformance execution". When the questions layer is ON (step 7.7), the report additionally surfaces any answer-sweep matches as a USER-GATED `PROPOSED ANSWERS` block (accept → accrete a cited `answer:` bullet on the `questions.md` entry, or strike + fold a topic-home answer append-only) and any mature `questions.md` entries as a USER-GATED `GRADUATION PROPOSAL` block (accept → invoke `sb-wiki-create-topic`, NEVER auto-author). The agent must perform the LLM judgment pass from the deterministic helper report before Step 8.

### Step 0 — Load extensions

Read `sb-os.json` at vault root → `wiki_extensions` field (a list of registered module names; resolve via `install/manifest.py`, never hardcode). For each listed module, locate its `wiki-ext/` folder and MERGE its `page-types.ext.md`, `frontmatter-schemas.ext.md`, `section-menus.ext.md`, and `lint-rules.ext.md` into the active rule set for this run. Extension page types, entity kinds, sections, and lint rules are ADDED to — never replace — the base set. If `wiki_extensions` is absent or empty, run with the base behavior unchanged. Process every later step against the merged rule set.

Lint MERGES each registered module's `lint-rules.ext.md`. Extension lint rules are SCOPED to that module's folders and entity kinds — they fire ONLY on pages within those scopes and NEVER on a general-wiki run. A general-wiki run (no matching folders/kinds present, or no extension registered) applies the base lint rules only.

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
5. **`questions.md` link resolution (skip if the questions layer is OFF — `{wiki_root}/questions.md` absent or malformed).** When `questions.md` is present and parseable, parse every H2 entry per `../shared/question-entry-shapes.md` and extract each `relates:` wikilink and each `seeded-by:` wikilink. Verify each target resolves by the SAME rule as item 3 (exact filename match in `wiki/concepts/`, `entities/`, `topics/`, `sources/{*}/`, or `raw/{*}/`, EXCLUDING `raw/assets/`). Treat the `questions.md` filename as the source location for any broken target. Do NOT rewrite or repair links — report only.
6. Build `broken-wikilinks` set: source-page filename (or `questions.md` for a broken `relates:`/`seeded-by:` target) + missing target for the LINT REPORT.

### Step 6 — Re-sync wiki sources `My take` column; renumber footnotes; remove stale footnote definitions

For each `{wiki_root}/wiki/sources/{origin}/` directory (including `studies/`):

1. Read `{origin}.md` (or `studies.md`). Header format per `../shared/index-formats.md` "Wiki Sources Index" section: `| File | What it says | My take |`.
2. For each row, locate the source page at `{wiki_root}/wiki/sources/{origin}/{filename}`. Read the page's `My take` section.
3. Apply the three-state re-sync rule per `../shared/index-formats.md` "`My take` Cell — Three States" section. **NEVER leave the cell blank** — every row carries `pending`, `—`, or a 1-sentence reflected preview.

   | Source page's `My take` body | Current cell value | Action |
   |------------------------------|--------------------|--------|
   | Has substantive content | Any | Write 1-sentence reflected preview (≤280 chars; truncate with ellipsis; table-safe — flatten wikilinks to display text BEFORE truncating, escape remaining literal `\|`), overwriting prior cell value |
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
   - NEVER auto-remove a footnote definition. A def with no inline reference is mechanically indistinguishable from stub provenance (stubs are born with defs and no inline markers; later ingests append inline-cited sections while the original def stays unreferenced) — auto-removal strips the page's graph edge to that source. REPORT unreferenced defs in the LINT REPORT for hand-reconciliation.
   - A page with definitions and ZERO inline markers is the ingest-built stub-provenance shape (`../shared/stub-policy.md`) — not a finding; never touched.
   - Set mismatches (inline marker without definition, duplicate definitions) are content defects: report in the LINT REPORT, never auto-repair.
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
5. For each page in the leaf folder, ensure a row exists for that page. Concept/entity `Description` cells are auto-filled by `sb-wiki-fill-index-descriptions.py` (run in the Deterministic Helper step) from each page's lead definition sentence; topic `Scope` cells stay LLM-filled. Never leave judgment-bearing columns blank.
6. Capture `wiki-leaf-indexes-created` count and `wiki-leaf-rows-added` total for the LINT REPORT.

**Type-tag sync (deterministic, auto-applied by the helper):** every page under `{wiki_root}/wiki/` MUST carry its `type:` frontmatter value as an entry in `tags:` (per `../shared/frontmatter-schemas.md` — Obsidian graph groups color by `tag:`, not frontmatter fields). The helper appends the missing tag (append-only — existing user tags are NEVER removed or reordered); index files (filename stem = parent directory name) missing `type:` get `type: index` + `tags: [index]`, creating the frontmatter block when absent. Non-index pages whose `type:` cannot be derived deterministically are reported in `detected.type_tags.unresolved` — surfaced in the LINT REPORT, never guessed. Capture `tags_added` and `type_index_added` for the LINT REPORT.

**Judgment-bearing cell rule:** Steps above never authorize blank semantic cells. Concept/entity `Description` cells are auto-filled by `sb-wiki-fill-index-descriptions.py` from the page's lead definition sentence; the agent fills ONLY the pages that helper reports as `weak` (no clean lead sentence) by reading the page and writing the cell. `Scope` (topics) and `What it says` (sources) remain fully LLM-owned — if the deterministic helper reports a missing row for those cells, the agent MUST read the referenced page and write the semantic cell before Step 8 (the log-prune pass).

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

Run the mechanical moves and index row surgery via the deterministic helper: `--execute-subdivision <plan.json>` (plan rows `{type_folder, slug, target_subfolder}`), then apply its `claude_md_pending` rows and any first-time router rewrite yourself — the helper never edits CLAUDE.md or authors router/leaf `Description` judgment content. The procedure below is the contract the executor + agent jointly implement. For each accepted subfolder:

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

### Step 7.6 — PDF title-conformance detection

For each PDF raw source in `{wiki_root}/raw/{origin}/` (EXCLUDING `raw/assets/`):

1. Read the raw index `Title` for that file (raw indexes are verified/created at step 7, so titles are present). Compute `{title-slug}` per `../shared/naming-convention.md` § "Raw PDF Title-Conformance" → "Title-slug algorithm".
2. Stem already equals `{title-slug}` → skip.
3. Stem differs AND no `raw/{origin}/{title-slug}.pdf` exists → add a `rename-proposals` row: `{old-stem}`, `{title-slug}`, origin.
4. Stem differs BUT `raw/{origin}/{title-slug}.pdf` already exists → add to `duplicate-raws` findings (NO rename proposed — the title slug is taken; this raw duplicates an already-ingested paper).

Detection ONLY — NEVER rename at this step. Markdown raw sources are out of scope (clipper-named). Build `rename-proposals` and `duplicate-raws` for the LINT REPORT and the step 9 gate.

#### PDF title-conformance execution (only on user accept at step 9)

Run accepted renames via the deterministic helper: `--execute-renames <plan.json>` (plan rows `{origin, old_stem, new_stem}`) — it implements the scoped rewrite + moves + verify below and reports `skipped_url_mentions`/`errors` for review. For each accepted rename, update the FULL referrer set atomically — a filesystem rename does NOT trigger Obsidian backlink updates:

1. Rewrite referrers with SCOPED WIKILINK PATTERNS ONLY — NEVER a blind global string replace:
   - **Patterns:** wikilink/embed targets `[[{old-stem}.pdf` and `[[{old-stem}.md` (with any `#anchor` or `|alias` tail) → same form with `{title-slug}`. These cover every referrer: body wikilinks, `[^N]:` footnote definitions, quoted frontmatter values (`raw:`, `related:`), the raw index `File` cell, the wiki sources index `File` cell, and `log.md` references.
   - **File scope:** NON-raw `.md` files only — `{wiki_root}/wiki/**` and `{wiki_root}/log.md` — plus raw INDEX files (`raw/{origin}/{origin}.md`; indexes are agent-owned). NEVER edit a raw content file body (raw-immutability contract).
   - **Exempt:** `http(s)://` URL strings that happen to contain `{old-stem}` (arXiv, repository deep links) and plain-prose stem mentions — NEVER rewritten, in any file.
2. Move `raw/{origin}/{old-stem}.pdf` → `raw/{origin}/{title-slug}.pdf`.
3. Move `wiki/sources/{origin}/{old-stem}.md` → `wiki/sources/{origin}/{title-slug}.md`.
4. The raw PDF content is never edited — rename only. NO log entry — the renamed files and rewritten links are the record.
5. Verify: search remaining `{old-stem}` occurrences under `{wiki_root}`. Expect ONLY legitimate remnants (external URLs, raw content bodies). Surface unexpected remnants in the LINT REPORT.

`duplicate-raws` findings are REPORTED, never auto-renamed — the user merges (repoint references to the canonical copy, then delete the duplicate raw + source page) or deletes them manually.

### Step 7.7 — Questions answer-sweep + graduation detection (skip-if-absent)

Resolve `{wiki_root}/questions.md`. **Absent → questions layer OFF**: hold EMPTY `questions-answer-proposals` and `graduation-proposals` sets; skip this ENTIRE step; the Step 9 `PROPOSED ANSWERS` and `GRADUATION PROPOSAL` blocks are omitted and the run is identical to today (optionality guarantee #1). **Present but malformed** (unreadable, invalid frontmatter, or no parseable H2 entries): WARN and treat as absent — hold EMPTY sets, skip the step; NEVER abort the lint (guarantee #5). **Present and parseable**: parse every H2 entry per `../shared/question-entry-shapes.md` and proceed. State is INFERRED — an entry is `open` iff it has no `answer:` block or zero `answer:` bullets, else `answered`. Per `../../docs/wiki-schema.md` § "Questions layer — questions.md" → "The answer-scan" (Lint row).

Detection ONLY — this step NEVER writes. It builds two proposal sets that the user gates at Step 9; apply/invoke happens at Step 9 on explicit accept.

#### 7.7a — Answer-sweep (both homes → `questions-answer-proposals`)

Sweep every **open** question in BOTH homes against the EXISTING wiki for now-available answers:

| Home | Open-question source |
|------|----------------------|
| **Topic-home** | Each non-struck `Open questions` line on each `{wiki_root}/wiki/topics/*.md` page (walked at Step 1). |
| **`questions.md`** | Each open entry (no `answer:` block or zero `answer:` bullets). |

For each open question, scan the existing wiki — concept/entity/topic page bodies plus source-page `Substance` sections — for content that answers it. This sweep is OFF the ingest hot-path, so it MAY be MORE THOROUGH than ingest's ≥2-shared-substantive-token mechanical match (Step 3·7b/3·7c of `sb-wiki-ingest.md`): the floor is the same ≥2-token signal, and the sweep MAY additionally fire on a lightly-semantic read (a page that materially addresses the question without sharing 2 surface tokens). It remains a PROPOSAL surface — it NEVER auto-applies.

When the semantic tier is available (schema § "Retrieval tiers — hybrid search"), run the sweep through the helper — per open question, from the vault root: `python {sb_os_path}/wiki/scripts/sb-wiki-search.py search "<question text>" --k 5 --json` — and treat each hit page as a candidate answering page. The helper widens recall; it NEVER lowers the proposal bar (the match-threshold rules above still decide what fires). Tier unavailable → run the sweep with grep/LLM reads exactly as before; a helper failure NEVER aborts the lint.

> **Validation window — ON (§13 fuzzy thresholds).** The EXACT lint-sweep thoroughness — purely mechanical (≥2 shared substantive tokens, mirrored from `sb-wiki-ingest.md` Step 3·7b) vs. lightly-semantic (also fires when a page materially addresses the question without 2 shared surface tokens) — is run ON for an initial validation window (≈ first 10 scans) before its wording is frozen here, exactly as the `purpose.md` design did. Tune in the window, then freeze. Per `../../docs/wiki-schema.md` § "Questions layer — questions.md" → "The answer-scan" validation-window note (heuristic 3, lint sweep thoroughness).

For each fire, capture into `questions-answer-proposals`: the home (`topic` or `questions.md`); the question identity (topic page path + the verbatim `Open questions` line for a topic-home fire; the `questions.md` entry's H2 heading for a `questions.md` fire); the answering page filename; and the proposed `answer:` claim — a 1-sentence claim derived from the answering page that addresses the question, carrying the citation `[^N]: [[<answering-page>.md]]`.

These are surfaced as a USER-GATED `PROPOSED ANSWERS` block at Step 9. Apply happens ONLY on accept, reusing the SAME append-only / inline-`answer:` handling as `sb-wiki-ingest.md` Step 10 (the ingest p3-2 path) — NEVER a parallel write path:

- **`questions.md` row** — append the 1-sentence claim as a new `- <claim> [^N]` bullet under the entry's `answer:` field (create the `answer:` field if absent), with a matching `[^N]: [[<answering-page>.md]]` footnote def, per `../shared/question-entry-shapes.md`. State flips `open → answered` by inference (≥1 bullet) — write NO `status` field. NEVER overwrite an existing bullet; accrete only.
- **topic-home row** — STRIKE the matched `Open questions` line in place (`~~…~~`, never delete it) and FOLD the answer into the topic body under the topic-shape-appropriate section, with an inline `[^N]` marker and a matching `[^N]: [[<answering-page>.md]]` def in the topic's `Sources`; bump `last-touched: <today>`. Append-only protection applies — NEVER overwrite existing prose.

Rejecting a row leaves the entry/topic untouched; the match is not preserved — it re-detects on a future sweep if overlap recurs.

#### 7.7b — Graduation detection (`questions.md` only → `graduation-proposals`)

Scan every **answered** `questions.md` entry (≥1 `answer:` bullet) for maturity. Topic-home questions never graduate (they resolve in place on the topic page) — graduation is `questions.md`-only. Mark a maturity heuristic for each answered entry; entries that look MATURE feed `graduation-proposals` (the entry H2 + a 1-line answer preview + its `relates:` targets) for the Step 9 GRADUATION PROPOSAL block.

> **Validation window — ON (§13 fuzzy thresholds).** The EXACT graduation maturity heuristic — when an accreted `answer:` is "ripe" for a page (starting point: an entry with ≥2 accreted `answer:` bullets from distinct sources, OR a single bullet the user has marked, surfaces as mature) — is run ON for an initial validation window (≈ first 10 graduations) before its wording is frozen here, exactly as the `purpose.md` design did. Tune in the window, then freeze. Per `../../docs/wiki-schema.md` § "Questions layer — questions.md" → "The answer-scan" validation-window note (heuristic 1, graduation maturity).

Detection ONLY. Build `graduation-proposals` for the Step 9 GRADUATION PROPOSAL block. The graduated entry is NOT pruned here — pruning of a promoted entry (page now exists) is owned by Step 8; this step only PROPOSES.

### Step 8 — Prune the log

The log is an actionable queue. Lint NEVER writes a `lint` entry — findings live in the LINT REPORT (step 9) only. Lint's only write to `log.md` is PRUNING. Execute the prune via the deterministic helper's `--prune-log` flag (it implements items 2-4 below exactly); the rules below remain the contract the flag implements:

1. Read `{wiki_root}/log.md` in full. Parse H2 entries per `../shared/log-entry-shapes.md`.
2. DELETE every retired-type entry (`ingest`, `concept-created`, `entity-created`, `topic-created`, `topic-updated`, `topic-coverage-candidate`, `lint`, `query`) — these are no longer active. Remove the full entry (header + body).
3. DELETE every `candidate-topic` whose matching topic page exists at `{wiki_root}/wiki/topics/` (flat or subfolder) — spent (resolution = page exists).
4. DELETE every `candidate-mention` whose matching page exists anywhere under `{wiki_root}/wiki/` (any type, flat or subfolder) — spent. Match by the entry's slug/`name:` normalized to the page filename.
5. KEEP every `candidate-topic` and `candidate-mention` whose page does NOT yet exist. NEVER auto-age a `candidate-mention` — it persists until its page exists or the user dismisses it. NEVER edit the body of a kept entry.
6. KEEP every entry whose type is neither active nor retired — NON-CANONICAL per `../shared/log-entry-shapes.md` "Unknown Types". NEVER delete or edit it; capture it for the LINT REPORT `Non-canonical log entries` line so the user routes it manually.
7. Preserve the file preamble. Capture `entries-pruned` count (by reason: spent vs retired) for the LINT REPORT.

**`questions.md` prune (skip-if-absent — `{wiki_root}/questions.md` absent or malformed → skip this whole sub-step; nothing else changes).** When `questions.md` is present and parseable, prune it by the SAME "page exists" mechanism the `candidate-mention` clause (item 4) uses — do NOT invent a parallel test. Read `{wiki_root}/questions.md` in full and parse every H2 entry per `../shared/question-entry-shapes.md`, then:

1. DELETE every entry that is **promoted** — a matching wiki page now exists anywhere under `{wiki_root}/wiki/` (any type, flat or subfolder). Apply the EXACT "page exists" test from item 4: match the entry's question/`relates:` target slug normalized to a page filename. Resolution = page exists (the page is the record; the graduation handoff from the GRADUATION PROPOSAL completes here once `sb-wiki-create-topic` has authored the page). Remove the full entry (H2 header + all `relates:`/`seeded-by:`/`answer:` lines + footnote defs).
2. DELETE every entry the user has **retired** (per the entry lifecycle in `../shared/question-entry-shapes.md` — a retired entry is REMOVED from `questions.md`, no terminal state stored). Remove the full entry as in item 1.
3. KEEP every entry that is **open** (no `answer:` block or zero `answer:` bullets) or merely **answered** (≥1 `answer:` bullet) but neither promoted nor retired — an answered-but-not-yet-graduated entry persists until it graduates (page exists) or the user retires it. NEVER edit the body of a kept entry; NEVER prune an entry solely because it has accreted an answer.
4. Fold `questions.md` removals into the `entries-pruned` count (reason: promoted vs retired) for the LINT REPORT.

### Step 8.5 — Regenerate `open-gaps.md` (cross-wiki open-questions aggregate)

REGENERATE `{wiki_root}/open-gaps.md` wholesale on every lint run — a READ-ONLY aggregate that recovers the single-pane visibility the two-homes model gives up (per `../../docs/wiki-schema.md` § "Questions layer — questions.md" → "`open-gaps.md` — lint-generated aggregate"). This is a VIEW, not a store: lint OVERWRITES the entire file each run; the user never hand-edits it (edits are overwritten). NEVER append; NEVER preserve prior content. Run AFTER Step 8 so the just-pruned `questions.md` state is reflected (promoted/retired entries are already gone and never surface as open gaps).

Collect the open-question set from BOTH homes:

| Home | Source | Open test |
|------|--------|-----------|
| **Topic-home** | Each `Open questions` line on each `{wiki_root}/wiki/topics/*.md` page (walked at Step 1). | The line is NOT struck (`~~…~~` lines are resolved — EXCLUDE them). |
| **`questions.md`** | Each entry parsed per `../shared/question-entry-shapes.md` (skip if `questions.md` absent or malformed). | The entry is `open` — no `answer:` block or zero `answer:` bullets. EXCLUDE answered entries (≥1 bullet). |

**Empty-state — ALWAYS emit the file (never skip).** When `questions.md` is absent AND no topic page has an unresolved `Open questions` line, WRITE `open-gaps.md` with its frontmatter + both headings and the per-section empty-state line (row rule 3) under each — do NOT skip generation and do NOT leave a stale prior file in place. Rationale: a stale `open-gaps.md` left from a previous run (when questions existed) would misreport the current state; an always-present empty file is self-documenting and keeps the view honest. (Documented as a shape.md Decision.)

Write the file with this exact shape (frontmatter `type: questions-index` per `../shared/frontmatter-schemas.md`):

```markdown
---
type: questions-index
last-touched: <today YYYY-MM-DD>
---

# Open gaps

> Lint-generated, READ-ONLY — regenerated in full on every `/sb-wiki-lint` run. Do NOT hand-edit; edits are overwritten. Aggregates every OPEN question across both homes (topic pages + `questions.md`). Resolve a question in its home; it drops off this view on the next lint.

## Topic-home open questions (N)

| Question | Topic |
|----------|-------|
| <verbatim Open questions line text> | [[<topic-slug>.md]] |

## `questions.md` open questions (N)

| Question | Home | Relates |
|----------|------|---------|
| [YYYY-MM-DD] <question text> | [[questions.md]] | [[<page>.md]], … |
```

Row rules:

1. **Topic-home rows** — one row per non-struck `Open questions` line. `Question` = the verbatim line text (strip the leading list marker). `Topic` = a `[[<topic-slug>.md]]` backlink to the home topic page.
2. **`questions.md` rows** — one row per open entry. `Question` = the entry's `[YYYY-MM-DD] <question text>` H2 text verbatim, written as PLAIN table text (not inside a wikilink — the `[YYYY-MM-DD]` brackets and `?` in a question break Obsidian's `#`-heading-anchor syntax, so a heading-anchor link is NOT used). `Home` = a plain `[[questions.md]]` file backlink to the queue. `Relates` = the entry's `relates:` targets as `[[<page>.md]]` links joined by `, ` (write `—` when `relates:` is empty/absent).
3. Section header counts `(N)` reflect the rows in that section. Omit NEITHER section — when a section has zero rows, keep the heading and write the empty-state line `_No open questions._` beneath it.
4. Capture `open-gaps-regenerated` (total open-question rows written, or `empty` when both sections are empty) for the LINT REPORT.

`open-gaps.md` is EXCLUDED from every validation walk (Steps 1–5, 7): it carries `type: questions-index` (a non-page value) and is a root-level sibling outside `wiki/` and `raw/`, so it is never walked for stub/orphan/index checks (per `../shared/folder-structure.md` "Questions Layer Files" → "`open-gaps.md`" and `../shared/frontmatter-schemas.md` § "`type: questions` / `type: questions-index`"). Lint GENERATES it here; it never participates as a lint target.

### Step 9 — Present findings to the user

Present the LINT REPORT VERBATIM in the format below. Read-only for findings 1-7; the interactive parts (each present only when its proposal set is non-empty) are the RENAME PROPOSAL, SUBDIVISION PROPOSAL, PROPOSED ANSWERS, and GRADUATION PROPOSAL blocks — auto-applied writes from steps 6-8 have already committed. The PROPOSED ANSWERS and GRADUATION PROPOSAL blocks are omitted entirely when the questions layer is OFF (`questions.md` absent or malformed).

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
Type tags synced: <N> pages (type appended to tags), <M> indexes given type: index (omit when both zero); unresolved type (K): <file> — <reason>
Footnotes renumbered: <N> source pages
Pages without `kind:` (N): [[<file>.md]]
Log pruned: <N> spent (page now exists), <M> retired history entries removed
Non-canonical log entries (N): "<type> | <brief>" — kept, route manually (omit when zero)
Questions pruned: <N> promoted (page now exists), <M> retired entries removed (omit when questions layer OFF)
Open gaps regenerated: <N> open questions across both homes → open-gaps.md (or "empty" / omit when questions layer OFF and no topic open questions)
Candidate-mentions to review (N): "<slug>", "<slug>", … (the actionable queue — promote to a stub or dismiss)
Duplicate raws — title-slug already taken (N): <old>.pdf ≡ <existing>.pdf (merge or delete manually)

RENAME PROPOSAL — PDF title-conformance (omit block entirely when empty):
| # | origin | old filename | → new filename |
|---|--------|--------------|----------------|
| 1 | papers | 2602.21012v1.pdf | international-ai-safety-report-2026.pdf |

Decisions: accept all | accept N (e.g. "accept 1") | reject | defer
(Default if the user does not respond: defer all — proposals persist in the next lint run.)

SUBDIVISION PROPOSAL (omit block entirely when empty):
| # | type | kind | count | suggested subfolder | sample pages |
|---|------|------|-------|---------------------|--------------|
| 1 | entities | person | 7 | persons/ | yann-lecun, mike-brown, … |
| 2 | entities | benchmark | 5 | ai-benchmarks/ | browsecomp-plus, longbenchpro, … |

Decisions: accept all | accept N (e.g. "accept 1") | reject | defer
(Default if the user does not respond: defer all — proposals persist in the next lint run.)

PROPOSED ANSWERS — questions answer-sweep (omit block entirely when empty or the questions layer is OFF):
| # | question | home | answering page | proposed resolution |
|---|----------|------|----------------|---------------------|
| 1 | <question text> | [[<topic-slug>.md]] | [[<answering-page>.md]] | strike "Open questions" line + fold answer into "<section-name>" + citation |
| 2 | <question text> | questions.md | [[<answering-page>.md]] | + answer: bullet on the entry + citation |

Decisions: accept N (e.g. "accept 1,2") applies the answer | reject (default) — no change, re-detected next sweep
(Default if the user does not respond: reject all — no answer applied; re-detected on the next sweep if overlap recurs.)

GRADUATION PROPOSAL — mature `questions.md` entries (omit block entirely when empty or the questions layer is OFF):
| # | entry | answer preview | relates |
|---|-------|----------------|---------|
| 1 | [YYYY-MM-DD] <question text> | <1-line preview of the accreted answer> | [[<page>.md]] |

Decisions: accept all | accept N (e.g. "accept 1") | reject | defer
(Default if the user does not respond: defer all — entries persist in questions.md and re-surface next lint run.)
(On accept, the agent invokes the `sb-wiki-create-topic` skill — it NEVER auto-authors a page. The graduated entry is pruned by step 8 once the page exists.)

No action required for findings 1-7 (lint is read-mostly; index sync + log prune auto-applied). The candidate-mention queue is yours to work through at your pace — nothing is auto-deleted.
```

Omit any zero-count line with empty list (e.g., `Broken wikilinks (0)` may be elided when the body would be empty). The wiki leaf indexes line is omitted when both counts are 0. The `Questions pruned` line is omitted when the questions layer is OFF (`questions.md` absent or malformed); the `Open gaps regenerated` line is omitted only when the questions layer is OFF AND no topic has an open question (the empty-state file is still written per Step 8.5, but there is nothing to report). The SUBDIVISION PROPOSAL block is omitted when the proposal set is empty. The PROPOSED ANSWERS block is omitted when `questions-answer-proposals` is empty (or the questions layer is OFF). The GRADUATION PROPOSAL block is omitted when `graduation-proposals` is empty (or the questions layer is OFF). The trailing closing line is REQUIRED.

User response handling for SUBDIVISION PROPOSAL:

| Response | Behavior |
|----------|----------|
| `accept all` | Execute every proposed subdivision per the procedure in step 7.5 § "Subdivision execution". No log entry — the new folder structure and indexes are the record. |
| `accept N` (e.g. `accept 1,2`) | Execute the listed proposals only. Other proposals defer. |
| `reject` | All proposals defer; surface as warnings in the next lint run. |
| `defer` (default) | Same as `reject` for this run; proposals re-surface in subsequent runs as long as the kind remains ≥10 pages. |

User response handling for RENAME PROPOSAL:

| Response | Behavior |
|----------|----------|
| `accept all` | Execute every proposed rename per step 7.6 § "PDF title-conformance execution" — rename raw + source page and rewrite the full referrer set. No log entry. |
| `accept N` (e.g. `accept 1,2`) | Execute the listed renames only. Others defer. |
| `reject` | All renames defer; re-surface next run. |
| `defer` (default) | Same as `reject` for this run; proposals re-detect next run while the mismatch persists. |

User response handling for PROPOSED ANSWERS (questions answer-sweep, step 7.7a):

| Response | Behavior |
|----------|----------|
| `accept N` (e.g. `accept 1,2`) — **`questions.md` row** | Append an inline `answer:` bullet to that `questions.md` entry per `../shared/question-entry-shapes.md`: add the 1-sentence claim as a new `- <claim> [^N]` bullet under the entry's `answer:` field (create the field if absent), with a matching `[^N]: [[<answering-page>.md]]` footnote def. State flips `open → answered` by inference (≥1 bullet) — write NO `status` field. NEVER overwrite an existing bullet; accrete only. No log entry. |
| `accept N` (e.g. `accept 1,2`) — **topic-home row** | STRIKE the matched `Open questions` line in place (`~~…~~`, never delete) and FOLD the answer into the topic body under the topic-shape-appropriate section with an inline `[^N]` marker + a matching `[^N]: [[<answering-page>.md]]` def in `Sources`; bump `last-touched: <today>`. Append-only protection per `../shared/stub-policy.md` "Append-Only Protection" applies — NEVER overwrite existing prose. NEVER auto-authors a page. No log entry — the topic page records its own content. |
| `reject` (default) | No change to any `questions.md` entry or topic page. No log entry. The match is not preserved — re-detected on the next sweep (or at ingest) if overlap recurs. |

User response handling for GRADUATION PROPOSAL (mature `questions.md` entries, step 7.7b):

| Response | Behavior |
|----------|----------|
| `accept all` | For EACH proposed entry, **invoke the `sb-wiki-create-topic` skill** with the entry's question + accreted `answer:` content + `relates:` targets as the proposed topic. The skill carries its OWN `extend N` (fold into an existing topic) / `new` (create a new page) overlap check and writes the page — lint NEVER authors a page directly. The graduated entry is NOT removed here; step 8 prunes it on the next lint run once the page exists (resolution = page exists). No log entry. |
| `accept N` (e.g. `accept 1,2`) | Invoke `sb-wiki-create-topic` for the listed entries only, exactly as `accept all` above. Other entries defer. |
| `reject` | All entries defer; the answered entries persist in `questions.md` and re-surface as GRADUATION PROPOSAL rows next lint run. |
| `defer` (default) | Same as `reject` for this run; mature entries re-surface in subsequent runs until graduated or retired. |

**Graduation NEVER auto-authors.** A page is created ONLY by `sb-wiki-create-topic` on explicit user accept. Lint proposes; the skill authors. This preserves the schema rule "Agent NEVER auto-creates topic pages" (`../../docs/wiki-schema.md` § "Topic page" and "Questions layer — questions.md" → Lifecycle).

End of flow.

## Failure Modes

| Failure | Behavior |
|---------|----------|
| `{wiki_root}` cannot be resolved from `sb-os.json` | Halt before step 1; surface error. No writes. |
| `{wiki_root}/log.md` missing | Skip step 4 candidate-topic detection; capture `candidates-aging = 0`. Step 8 prunes only — if `log.md` is absent there is nothing to prune; skip it (do NOT create the file). |
| `{wiki_root}/questions.md` absent | Questions layer OFF — skip step 7.7 entirely (hold EMPTY `questions-answer-proposals` and `graduation-proposals`); skip the `questions.md` link-resolution branch at step 5; skip the step-8 `questions.md` prune sub-step; omit the Step 9 `PROPOSED ANSWERS` and `GRADUATION PROPOSAL` blocks. Step 8.5 still runs but aggregates ONLY topic-home open questions — write `open-gaps.md` with the topic-home section populated (or the empty-state file when no topic has an open question); the `questions.md` section shows its empty-state line. Do NOT create `questions.md`. Every other step is identical to today (optionality guarantee #1). |
| `{wiki_root}/questions.md` malformed (unreadable, invalid frontmatter, or no parseable H2 entries) | WARN and treat as absent — skip step 7.7, the step-5 `questions.md` branch, and the step-8 `questions.md` prune sub-step; omit both Step 9 questions blocks. Step 8.5 behaves as in the absent row (topic-home only). NEVER abort the lint (guarantee #5). |
| `{wiki_root}/wiki/` or `{wiki_root}/raw/` missing | Skip walks for the missing tree; capture zero counts for affected sets. Continue with remaining steps. |
| Source page referenced by a `wiki/sources/{origin}/{origin}.md` row does not exist | Skip the row at step 6 `My take` re-sync; do NOT remove the row (user may resolve manually). Capture in `sources-resynced` only when the page exists. |
| Raw file referenced by a `raw/{origin}/{origin}.md` row does not exist | Leave the row in place at step 7; do NOT remove it (user may have moved the raw file). |
| Wiki leaf index user-customized layout (`wiki/topics/topics.md`, `wiki/concepts/concepts.md`, or `wiki/entities/entities.md`) | Preserve at step 7; do NOT rewrite the layout. Operate against the existing `File` column for row presence checks. |
| Footnote definition in body uses non-standard form (e.g., text-only without wikilink) | Skip the entry at step 6 footnote renumber; preserve user content. Do NOT auto-correct. |
