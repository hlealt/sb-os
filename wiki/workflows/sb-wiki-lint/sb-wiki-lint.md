---
name: sb-wiki-lint
description: Structural and citation lint + index maintenance for `raw/` and `wiki/` — detect stubs, orphans, unresolved Disputed callouts, aging candidate-topics, broken wikilinks; auto-apply index sync writes (sources index `File | Description` migration, footnote renumber, raw-index creation, wiki leaf-index creation); when the optional questions layer is ON, sweep open questions for now-available answers and surface mature entries for graduation as user-gated proposals; present read-only findings to the user.
---

# sb-wiki-lint

Structural and citation lint + index maintenance pass across `{wiki_root}/raw/` and `{wiki_root}/wiki/`. Implements the 9-step lint flow defined in the wiki schema. Read-mostly: deterministic index sync writes are auto-applied; judgment-bearing index cells are filled by the LLM before the final report.

## Schema Source

Read `3-resources/tools/sb-os/wiki/docs/wiki-schema.md` — Operations § "/sb-wiki-lint" — for canonical step definitions. This workflow body implements that spec verbatim. Schema deviations require updating the schema first.

## Path Resolution

| Symbol | Resolution |
|--------|------------|
| `{wiki_root}` | Read from `sb-os.json` at vault root → `wiki_root` field. Resolve via `install/manifest.py` (`manifest.read(vault_root)`). Never hardcode. |
| `{user_context_root}` | Read from `sb-os.json` → `user_context_root`. Never hardcode. |
| `{wiki_root}/wiki/` | Wiki page tree (concepts, entities, topics, sources). |
| `{wiki_root}/raw/` | Raw source tree. |
| `{wiki_root}/logs/` | Actionable queue folder — `logs/topics.md` (`candidate-topic`), `logs/mentions.md` (`candidate-mention`), `logs/theses.md` (`proposed-new-thesis` + `speculative-thesis-update`). |

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

## Extension Files

Optional-feature step bodies and Step 9 response handlers live in `extensions/` and load JIT per the gate at each site — they are NEVER bulk-loaded. A clean lint run with the questions layer OFF reads only `ext-open-gaps.md`.

| File | Loaded by | Load condition |
|------|-----------|----------------|
| `extensions/ext-questions-sweep.md` | Step 7.7 | Questions layer ON (`{wiki_root}/questions.md` present + parseable) |
| `extensions/ext-open-gaps.md` | Step 8.5 | EVERY run (always-emit) |
| `extensions/handler-link-fix.md` | Step 9 | LINK-FIX set non-empty |
| `extensions/handler-missing-page.md` | Step 9 | MISSING-PAGE set non-empty |
| `extensions/handler-subdivision.md` | Step 9 | SUBDIVISION set non-empty |
| `extensions/handler-rename.md` | Step 9 | RENAME set non-empty |
| `extensions/handler-proposed-answers.md` | Step 9 | PROPOSED ANSWERS set non-empty (layer ON) |
| `extensions/handler-graduation.md` | Step 9 | GRADUATION set non-empty (layer ON) |

## Invocation

`/sb-wiki-lint`. No arguments. Walks the entire wiki and raw trees in one pass.

## Read-Mostly Behavior

This workflow is read-mostly by contract. Auto-applied writes are SCOPED to index sync only. Subdivision execution writes (step 7.5) are USER-GATED — only on explicit accept at step 9.

The auto-applied index-sync writes (migrate sources index to `File | Description`, renumber footnotes, create/maintain raw + wiki leaf indexes, fill concept/entity `Description` cells, type-tag sync, prune the `logs/` files) are owned SOLELY by their step bodies — Steps 6, 7, and 8 are the sole scope authority for each; this table does NOT restate them. Only the questions-layer skip-if-absent rows and the USER-GATED executor rows below carry authorization semantics not fully resolved inside a single step:

| Write | Scope | Authorization |
|-------|-------|--------------|
| Prune promoted/retired entries from `questions.md` (step 8) — delete entries whose matching wiki page now exists (promoted) or that the user retired, by the same "page exists" test as the `candidate-mention` prune | `{wiki_root}/questions.md` | Auto-applied — no user diff. Skipped entirely when `questions.md` is absent |
| Regenerate `open-gaps.md` wholesale (step 8.5) — overwrite the read-only cross-wiki aggregate of all open questions (both homes) | `{wiki_root}/open-gaps.md` | Auto-applied — no user diff. ALWAYS emitted (empty-state file when nothing to aggregate); never skipped |
| Regenerate `missing-links.md` wholesale (step 7.8) — overwrite the read-only missing-link proposal report (signal-1) | `{wiki_root}/missing-links.md` | Auto-applied — no user diff (report-only; written only under `--apply`). It contains PROPOSALS, never links — applying a link is the USER-GATED `update-links` row below |
| Missing-link apply (step 9 MISSING-LINK PROPOSAL accept) — append `[[target]]` to the source page's `related:` + `[[source]]` to the target's `related:` (append-only), via `update-links --plan <plan.json>` | `related:` frontmatter of accepted source + target pages under `{wiki_root}/wiki/**` | USER-GATED — executed only on `accept` at step 9. Append-only + idempotent; NEVER auto-links |
| Folder subdivision execution (step 7.5) — create `{type}/{subfolder}/`, leaf index, marker-block CLAUDE.md, rewrite parent index as router, MOVE pages | `{wiki_root}/wiki/{concepts,entities}/...` | USER-GATED — executed only on `accept` at step 9 |
| PDF title-conformance rename execution (step 7.6) — rename raw PDF + source page, rewrite all referrers (frontmatter, footnotes, both indexes, `logs/*.md`) | `{wiki_root}/raw/{origin}/`, `{wiki_root}/wiki/...`, `{wiki_root}/logs/*.md` | USER-GATED — executed only on `accept` at step 9 |
| Questions answer-sweep apply (step 7.7) — accrete a cited `answer:` bullet on a `questions.md` entry, OR strike + fold a topic-home `Open questions` answer into the topic body (append-only) | `{wiki_root}/questions.md`, `{wiki_root}/wiki/topics/*.md` | USER-GATED — applied only on `accept` at step 9. Skipped entirely when `questions.md` is absent |
| Graduation execution (step 9 GRADUATION PROPOSAL) — invoke `sb-wiki-create-topic` for an accepted mature `questions.md` entry (NEVER auto-author a page) | (the skill writes the page; lint writes nothing directly) | USER-GATED — invoked only on `accept` at step 9. Skipped entirely when `questions.md` is absent |
| Broken-link bucket-A fix execution (step 9 LINK-FIX PROPOSAL) — rewrite `[[old…]]`→`[[new…]]` wikilinks via `--execute-link-fixes` | wikilink text inside `{wiki_root}/wiki/**` pages (`#anchor`/`\|alias` preserved); NEVER `raw/` | USER-GATED — executed only on `accept` at step 9 |
| Missing-page bucket-B stub authoring (step 9 MISSING-PAGE PROPOSAL) — author a web-verified stub per `../shared/stub-policy.md` for an accepted genuinely-missing target | `{wiki_root}/wiki/concepts/` or `entities/` (matching `kind:` subfolder) | USER-GATED — authored only on `accept` at step 9 |
| Candidate-topic dismissal (step 9 CANDIDATE-TOPIC PROMOTION block) — delete the dismissed entry (H2 header + body) from `logs/topics.md`. Promotion itself writes nothing from lint — the `sb-wiki-create-topic` skill owns the page write, the topics-index row, and the promoted entry's removal | `{wiki_root}/logs/topics.md` | USER-GATED — executed only on explicit `dismiss N` at step 9 |

NEVER edit page bodies, frontmatter (other than `last-touched` on indexes and on pages moved by subdivision, the append-only type-tag sync per step 7, and wikilink-target rewrites performed by a user-accepted PDF title-conformance rename per step 7.6), or any user-authored content from this workflow. NEVER delete pages. NEVER write a `lint` entry — lint findings live in the report only. Lint's ONLY writes to the `logs/*.md` and `questions.md` queues are the prunes Step 8 itemizes and the USER-GATED step-9 candidate-topic dismissal (delete the dismissed entry from `logs/topics.md`, only on explicit `dismiss N`) — it never edits the body of an entry it keeps. `open-gaps.md` is lint-generated and READ-ONLY — lint OVERWRITES it wholesale each run; the user's edits to it are not preserved.

**`raw/_assets/` is OUT OF SCOPE for this workflow.** No reads, no writes, no walks, no index creation, no orphan-detection participation, no filename validation. The folder is user-maintained via Obsidian's "Download attachments for current file" command (per `../shared/folder-structure.md` "Asset Folder" and schema § "Asset folder"). Treat it as if it were not present in the tree. Same exclusion applies to any pre-existing legacy asset folder nested under a specific origin (e.g., `raw/mails/assets/`) — user-owned, untouched.

## Deterministic Helper

Before Step 1, run the deterministic helper from the vault root with the active Python interpreter:

```bash
python {sb_os_path}/wiki/scripts/sb-wiki-lint-deterministic.py --apply --report {wiki_root}/lint-deterministic-report.json
python {sb_os_path}/wiki/scripts/sb-wiki-fill-index-descriptions.py --apply
```

Run both, in order — the first owns the deterministic index-row + footnote work; the second (step 7) fills concept/entity `Description` cells from each page's lead definition sentence and reports pages with no clean lead sentence as `weak` (those stay LLM-owned). The helper is mandatory. It executes the deterministic halves of the lint steps in one pass — NEVER re-derive these by walking files with LLM reads. Consume the JSON report keys per this map:

| Report key | Feeds step | Content |
|------------|-----------|---------|
| `dirty_set` | 6, 7, 7.7 | Wiki-root-relative paths of pages changed since the last run (all pages on `--full` or first-run/state-fallback). LLM read passes are scoped to this set. |
| `writes`, `judgment_needed` | 6, 7 | Auto-applied index writes; queue of judgment-bearing cells (incl. `row-shape` malformed rows) |
| `detected.stubs_aged_gt30`, `stubs_fresh_count`, `stubs_no_created` | 1 | Stub state + age (user-half exemption applied) |
| `detected.orphans` | 2 | STRICT-scope orphans (concept/entity/topic inbound only) |
| `detected.disputed_callouts`, `disputed_callouts_unparseable` | 3 | Unresolved Disputed callouts (>30d, no resolving topic page); callouts with no resolving topic AND no parseable date surface as `unparseable` for manual review |
| `detected.broken_wikilinks` | 5 | Classified broken-wikilink inventory — each row `{source, target, bucket, suggestion, candidates}`. `bucket: "A"` = unique fold-match (auto-fixable, `suggestion` = exact existing filename); `bucket: "needs-judgment"` = no unique match (LLM splits B/C; `candidates` non-empty when ambiguous) |
| `detected.questions_broken_links` | 5 | `questions.md` `relates:`/`seeded-by:` targets that do not resolve (absent file → key empty) |
| `detected.footnote_issues`, `provenance_only_count`, `renumbered` | 6 | Set-mismatch findings (report-only); pages with defs-and-no-inline (never touched); safe-bijection renumbers auto-applied under `--apply` |
| `detected.log_spent_entries`, `log_retired_entries`, `log_unknown_type_entries`, `log_aging_candidate_topics`, `log_unparseable_timestamps`, `log_awaiting_thesis_decisions` | 4, 8, 9 | Prune-test results + aged candidates (each row `{slug, logged, age_days, trigger}`; floor = `--candidate-age-floor`, default 7 days, `0` = every pending candidate — feeds the step-9 CANDIDATE-TOPIC PROMOTION block) + candidate-topic headers with no parseable date (kept, report-only) + non-canonical entries (kept) + `speculative-thesis-update` entries surfaced as awaiting investor decision (never auto-pruned) |
| `detected.type_tags` | 7 | Type-tag sync results — `tags_added` / `type_index_added` counts (auto-applied under `--apply`) + `unresolved` pages whose `type:` cannot be derived deterministically (surface in the LINT REPORT for the user) |
| `detected.rename_proposals`, `duplicate_raws`, `title_disambiguation_needed` | 7.6 | PDF title-conformance detection; same-title collisions surface as disambiguation, never proposals |
| `detected.md_duplicate_raws`, `md_duplicate_raws_limit` | 7.6 | Raw-`.md` duplicate detection (U10) — each row `{raw, signal, matches}` where `signal` is `content-hash`/`url`/`title` and `matches` is the already-ingested source it duplicates. Report-only; never auto-deleted. `md_duplicate_raws_limit` is the stated detector limit (catches same-title/URL/byte-identical, NOT reworded same-material) |
| `detected.subdivision_proposals`, `subdivision_stragglers`, `kind_missing`, `generic_kind_flags` | 7.5 | Folder-subdivision detection |
| `detected.raw_wiki_healed`, `raw_wiki_dangling` | 7 | Stale `Wiki=No`→`Yes` heals (rows whose 1:1 source page exists — auto-applied under `--apply`) + dangling rows (File cell → missing raw file — report-only, never auto-deleted) |
| `detected.missing_links`, `missing_links_hub_suppressed`, `missing_links_hub_suppressed_count`, `missing_links_report`, `missing_links_rejected_registry` | 7.8 | Missing-link proposals (signal-1, report-only). `missing_links` is the MAIN actionable list — multi-word-target rows `{term, target, source, mentions}`, sorted by `#mentions` desc: a target page's exact name appears as UNLINKED prose in the source page where a page by that name exists (case/hyphen-insensitive). Excludes already-linked + owner-rejected pairs. **ADX-7:** single-token-target rows (`ai.md`, `llm.md`) are held out into `missing_links_hub_suppressed` (+ `_count`) — retained, never dropped. `missing_links_report` is the report filename (`missing-links.md`, both sections) written under `--apply` that the Step-9 MISSING-LINK handler reads (MAIN section); `missing_links_rejected_registry` is the owner-rejected registry filename (`missing-links-rejected.md`). NEVER auto-linked — the human-gated `update-links` sub-command applies accepted rows |

Execution flags — the helper also owns the mechanical halves of the write paths:

| Flag | Class | Used at |
|------|-------|---------|
| `--apply` | Safe auto-apply | The mandatory pre-Step-1 run — index sync writes + safe footnote renumber |
| `--prune-log` | Safe auto-apply (lint-contract-authorized) | Step 8 — deletes spent + retired entries across the `logs/*.md` files exactly as steps 8.2-8.4 specify; unknown types, plain headings, and `speculative-thesis-update` entries always survive |
| `--candidate-age-floor <days>` | Detection tuning (no writes) | The mandatory pre-Step-1 run — sets the step-4 aged-candidate floor for `detected.log_aging_candidate_topics` (default 7; `0` = every pending candidate) |
| `--execute-renames <plan.json>` | USER-GATED executor | Step 9, on RENAME PROPOSAL accept — plan rows `{origin, old_stem, new_stem}`; rewrites scoped wikilink patterns in non-raw files + raw indexes only, then moves the two files (per step 7.6 execution) |
| `--execute-subdivision <plan.json>` | USER-GATED executor | Step 9, on SUBDIVISION PROPOSAL accept — plan rows `{type_folder, slug, target_subfolder}`; moves pages, bumps `last-touched`, performs index row surgery. `CLAUDE.md` routing rows and first-time router rewrites are returned as `claude_md_pending`/errors for the AGENT to apply — the script never edits CLAUDE.md |
| `--execute-link-fixes <plan.json>` | USER-GATED executor | Step 9, on LINK-FIX PROPOSAL accept — plan rows `{file, old, new}` (`file` wiki-root-relative, `old`/`new` exact filenames); rewrites `[[old…]]`→`[[new…]]` preserving any `#anchor`/`\|alias` tail, scoped to `wiki/**` only (rows pointing outside `wiki/` are rejected, never written) |

NEVER run an executor flag without an explicit user accept at step 9. After any executor run, apply every `claude_md_pending` row and resolve every error surfaced in `detected.renames` / `detected.subdivision`.

**State-file lifecycle.** The report JSON written to `{wiki_root}/lint-deterministic-report.json` IS the incremental-lint state file — it persists between runs and carries the per-page content stamps from the previous run. Key behaviors:

- **Never manually delete it.** Deleting the file forces the next run to behave as `--full` (all pages dirty), silently discarding accumulated incremental state. If a run produced a bad state, re-run with `--full` rather than deleting.
- **`--full` flag.** Passing `--full` to the helper treats every tracked page as dirty regardless of stored stamps; the report carries `"full_mode": true`. Use it when you want guaranteed full coverage (e.g., after an interrupted lint run where LLM passes did not complete — the `stamp_commit_policy` field in the report explains when this is advisable).
- **First run / state absent or corrupt.** The helper falls back automatically to full-mode and records `"state_fallback_reason"` in the report (values: `"first-run"`, `"corrupt-state"`, or `"schema-mismatch (…)"`). The lint never crashes on a missing or unparseable state file.
- **Executor runs do NOT update state.** Executor flags (`--execute-renames`, `--execute-subdivision`, `--execute-link-fixes`) compute no stamps; the helper guards against writing an executor-mode report over the state file, so running an executor with `--report` is safe and NEVER clobbers accumulated stamps.
- **`runs_completed` counter.** The state file carries a `"runs_completed"` integer — incremented by 1 and persisted on every NON-execute helper run (check + apply modes), absent treated as 0, surviving corrupt-state full-fallback (a fallback run persists `runs_completed: 1`). Executor runs NEVER touch it (the execute-mode report is not persisted). It approximates "complete lint runs" by counting helper invocations and is the durable close signal the Step 7.7a/7.7b validation windows count against.

The helper MUST NOT fill judgment-bearing cells. `Description` (sources, topics, concepts, entities) requires LLM judgment. After the helper runs, read the JSON report and resolve every `judgment_needed` item by reading the referenced file and writing the required semantic cell before Step 8.

## Flow

Steps 1-8.5 run unattended. Step 8 PRUNES the `logs/` files (deletes spent candidates + retired history; NEVER a `speculative-thesis-update`; writes NO `lint` entry) and, when the questions layer is ON, PRUNES `questions.md` (deletes promoted entries whose page now exists + retired entries, by the same "page exists" test). Step 8.5 REGENERATES `{wiki_root}/open-gaps.md` wholesale — a read-only cross-wiki aggregate of every open question across both homes (always emitted, empty-state when nothing is open; skipped only as a no-op when the questions layer is OFF and no topic has an open question). Step 9 is read-only for findings 1-7 and surfaces the `candidate-mention` review queue; when step 4 surfaced a non-empty aged-candidate set, the report includes a USER-GATED `CANDIDATE-TOPIC PROMOTION` block (promote → invoke `sb-wiki-create-topic` per accepted candidate, NEVER auto-author; dismiss → delete that entry from `logs/topics.md`); when step 5 classified broken links into buckets, the report includes a USER-GATED `LINK-FIX PROPOSAL` block (bucket A — accept → run `--execute-link-fixes` to rewrite the typo/encoding links) and a `MISSING-PAGE PROPOSAL` block (bucket B — accept → author a web-verified stub per `../shared/stub-policy.md`); bucket C is reported only. When step 7.5 produced a non-empty `subdivision-proposals` set, the LINT REPORT at step 9 includes a SUBDIVISION PROPOSAL block that requires a user decision (accept all / accept N / reject / defer). On user accept, the agent executes the subdivision per step 7.5 § "Subdivision execution" (no log entry). Likewise, when step 7.6 produced a non-empty `rename-proposals` set, the report includes a RENAME PROPOSAL block; on user accept the agent executes the rename + full referrer rewrite per step 7.6 § "PDF title-conformance execution". When the questions layer is ON (step 7.7), the report additionally surfaces any answer-sweep matches as a USER-GATED `PROPOSED ANSWERS` block (accept → accrete a cited `answer:` bullet on the `questions.md` entry, or strike + fold a topic-home answer append-only) and any mature `questions.md` entries as a USER-GATED `GRADUATION PROPOSAL` block (accept → invoke `sb-wiki-create-topic`, NEVER auto-author). The agent must perform the LLM judgment pass from the deterministic helper report before Step 8.

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
| **Files OUT OF SCOPE as inbound-link sources** | the `logs/*.md` queue files, `wiki/sources/{origin}/{origin}.md` indexes, `wiki/sources/{origin}/<date>-<slug>.md` source pages, raw source pages under `raw/`, `raw/{origin}/{origin}.md` raw indexes, all leaf indexes (`concepts.md`, `entities.md`, `topics.md`, `studies.md`), and **everything inside `raw/_assets/`** (binary attachments — image embeds inside source/wiki pages do NOT count as inbound links toward orphan status) |

1. Build the eligible-orphan set: every concept/entity/topic page (excluding leaf indexes).
2. Build the inbound-link map: scan ONLY concept/entity/topic page bodies, frontmatter `related:` lists, and `Sources` section footnote definitions for `[[<target>.md]]` references. Do NOT scan source pages, log entries, raw files, or any leaf index.
3. Mark a page as `orphan` if zero in-scope inbound wikilinks point to its filename. Wikilinks from out-of-scope files (log mentions, source-page footnote definitions, raw indexes) do NOT count toward inbound — they are evidence of mention, not synthesis.
4. Build `orphans` set. Capture page filenames for the LINT REPORT.

**Rationale.** Forcing inbound links to come from real wiki content (concept / entity / topic pages) keeps the orphan bar high and preserves the signal's diagnostic value. A stub created from a Notable Quote will, by design, be flagged as an orphan on the next lint run if no concept/entity/topic page links to it — this is correct behavior, not a false positive (per schema § "Orphan-detection scope (STRICT)").

### Step 3 — Detect unresolved Disputed callouts (deterministic)

Consume `detected.disputed_callouts` from the helper — do NOT re-walk pages by LLM. The helper walks `{wiki_root}/wiki/concepts/` and `entities/` (skipping leaf indexes), detects `> [!warning] Disputed` callouts per `../shared/section-menus.md` "Contradiction — Disputed Callout", and applies the resolution rule: a callout is RESOLVED when it references a topic page (`See topic [[slug.md]]`) that exists (resolution = page exists). An UNRESOLVED callout has no existing resolving topic page AND a flagged date (the first `YYYY-MM-DD` in the callout body) >30 days old.

1. Read `detected.disputed_callouts` — each row `{page, flagged, age_days}`. This IS the `unresolved-disputed` set for the LINT REPORT.
2. Read `detected.disputed_callouts_unparseable` — callouts with no resolving topic AND no parseable date (cannot be aged). Surface these in the LINT REPORT for manual review; never silently drop them.

### Step 4 — Walk the `logs/` queues; detect aging candidate-topics + awaiting thesis decisions

Consume the deterministic helper's `detected.log_aging_candidate_topics` and `detected.log_awaiting_thesis_decisions` — do NOT re-walk by LLM.

1. Read `{wiki_root}/logs/topics.md` and `{wiki_root}/logs/theses.md` in full.
2. Locate every `candidate-topic` H2 entry (in `logs/topics.md`) and every `proposed-new-thesis` / `speculative-thesis-update` entry (in `logs/theses.md`) per `../shared/log-entry-shapes.md`.
3. For each, parse the entry timestamp from the H2 header. Compute age in days.
4. Resolution = page exists. A `candidate-topic` is SPENT if a topic page matching its slug exists at `{wiki_root}/wiki/topics/` (flat or any subfolder); a `proposed-new-thesis` is SPENT if a thesis page matching its slug exists at `{wiki_root}/wiki/theses/`. Spent entries are pruned at step 8, NOT reported as aging.
5. Mark a `candidate-topic` as `aging` if age ≥ the candidate age floor (default 7 days; helper flag `--candidate-age-floor`, `0` = every pending candidate) AND its topic page does NOT exist. Consume rows verbatim from `detected.log_aging_candidate_topics` (`{slug, logged, age_days, trigger}`) — they feed BOTH the report's aging line AND the step-9 CANDIDATE-TOPIC PROMOTION block. Candidate-topic headers with no parseable date (`detected.log_unparseable_timestamps`) cannot be aged — surface them in the report for manual review; never silently drop them.
6. Surface EVERY `speculative-thesis-update` as `awaiting investor decision` (slug + logged date + age). These NEVER auto-prune — the target thesis page already exists, so "page exists" is not a resolution signal (DEC-2); the user resolves them via `sb-fin-create-thesis` extend or dismiss.
7. Build `candidates-aging` and `awaiting-thesis-decisions` sets: slug + logged date for the LINT REPORT.

### Step 5 — Verify wikilinks resolve; classify broken links (deterministic + judgment)

Consume `detected.broken_wikilinks` from the helper — do NOT re-walk pages by LLM. The helper extracts every `[[<target>.md]]` from each wiki page (body, frontmatter `related:`, footnote defs), verifies the target against actual filenames in `{wiki_root}/wiki/{concepts,entities,topics,sources}/` and `{wiki_root}/raw/{*}/` (EXCLUDING `raw/_assets/`; image embeds `![[…non-md]]` skipped), and classifies each unresolved target.

1. Read `detected.broken_wikilinks`. Each row is `{source, target, bucket, suggestion, candidates}`:
   - **`bucket: "A"`** — a UNIQUE existing file fold-matches the target (typo / curly-quote / dash / accent / case). `suggestion` is the exact existing filename. Auto-fixable: feeds the LINK-FIX PROPOSAL at step 9 (executed via `--execute-link-fixes`).
   - **`bucket: "needs-judgment"`** — no unique fold-match. Split it by judgment into:
     - **bucket B** — `target` is a plausible concept/entity that genuinely belongs in the wiki but was never created (e.g. `nrel.md`, `sempra.md`). Feeds the MISSING-PAGE PROPOSAL at step 9 (on accept, author a web-verified stub).
     - **bucket C** — not a real thing, a duplicate of an existing page under a different name, or a reference that should not exist. Reported for the user — never auto-fixed or unlinked.
     - When `candidates` is non-empty (≥2 existing files share the fold key), the target is AMBIGUOUS — surface the candidates and treat as bucket C (user disambiguates) unless one is the obvious intent.
2. **`questions.md` link resolution (skip if the questions layer is OFF — `{wiki_root}/questions.md` absent or malformed).** Read `detected.questions_broken_links` from the helper (the `relates:`/`seeded-by:` targets in `questions.md` that do not resolve). Treat `questions.md` as the source location. Report only — questions-layer broken links are NOT classified into A/B/C and are NOT auto-repaired.
3. Build the `broken-wikilinks` set for the LINT REPORT as bucket counts: A (auto-fixable) / B (needs page) / C (unresolvable), plus the `questions.md` broken targets.

### Step 6 — Migrate and maintain wiki sources index; renumber footnotes; remove stale footnote definitions

The wiki sources index uses the unified 2-column `| File | Description |` format (U11). The helper's `migrate_sources_index_to_description` pass migrates any legacy 3-col `| File | What it says | My take |` index to the 2-col form (the `What it says` text is preserved verbatim as `Description`; the `My take` cell is dropped — the user's reflection lives in the source page's `## My take` body section, untouched). An already-2-col index is left byte-stable. A bespoke layout is reported, never force-rewritten.

For each `{wiki_root}/wiki/sources/{origin}/` directory (including `studies/`):

1. Read `{origin}.md` (or `studies.md`). Header format per `../shared/index-formats.md` "Wiki Sources Index" section: `| File | Description |`.
2. For each row, ensure the `Description` cell is filled. `Description` cells are LLM-owned — if the deterministic helper reports a missing or blank `Description` cell, read the source page and write a 1-sentence factual description.
3. Capture `sources-resynced` count for the LINT REPORT.

For each wiki page (concepts, entities, topics, source pages):

1. Apply footnote rules per `../shared/citation-format.md`:
   - Renumber inline `[^N]` markers and matching `[^N]: [[<filename>.md]]` definitions sequentially per page (start at `[^1]`).
   - Preserve user prose appended to a definition (e.g., `[^1]: [[file.md]] — note: this is the original`).
   - NEVER auto-remove a footnote definition. A def with no inline reference is mechanically indistinguishable from stub provenance (stubs are born with defs and no inline markers; later ingests append inline-cited sections while the original def stays unreferenced) — auto-removal strips the page's graph edge to that source. REPORT unreferenced defs in the LINT REPORT for hand-reconciliation.
   - A page with definitions and ZERO inline markers is the ingest-built stub-provenance shape (`../shared/stub-policy.md`) — not a finding; never touched.
   - Set mismatches (inline marker without definition, duplicate definitions) are content defects: report in the LINT REPORT, never auto-repair.
2. Capture `footnotes-renumbered` count (pages touched) for the LINT REPORT.

### Step 7 — Verify and create raw indexes; verify wiki leaf indexes

For each `{wiki_root}/raw/{origin}/` directory (including `studies/`), **EXCLUDING `raw/_assets/`** (per `../shared/folder-structure.md` "Asset Folder" — `raw/_assets/` is NOT a raw origin and MUST NOT receive an `_assets.md` leaf index, MUST NOT be walked as part of raw-origin maintenance, and MUST NOT have its filenames validated):

1. Verify `{origin}.md` (or `studies.md`) exists. If missing, CREATE it with the standard raw index header per `../shared/index-formats.md` "Raw Index" section: `| File | Wiki |` (ADX-9/ADX-10). A legacy 4-col/3-col index is MIGRATED to this 2-col form (`Wiki` value preserved verbatim) by the helper.
2. For each raw file in the directory, ensure a row exists in the index. If missing, add the fully-deterministic row `| [[file]] | No |` (File + Wiki only — no Title/Date to derive).
3. Index creation and maintenance is the agent's job, not the user's (per schema § "/sb-wiki-lint" step 7 and `../shared/folder-structure.md` "Creation Rules" table).
4. If a row already exists, preserve its `Wiki` value (`Yes`, `Partial`, `No`, or `Duplicate (…)`) — EXCEPT the stale-`No` heal in item 6.
5. Capture `raw-indexes-created` count, `raw-rows-added` total, and unresolved raw rows from `judgment_needed` for the LINT REPORT.
6. **Stale-`Wiki=No` heal + dangling report (deterministic, auto-applied by the helper).** The helper flips a row's `Wiki` cell `No`→`Yes` when the raw's 1:1 source page exists — EITHER the source page's `raw:` frontmatter names this raw OR a same-stem source page exists under `wiki/sources/{origin}/`. ONLY an exact `No` is flipped (`Partial` / `Duplicate (…)` / `Yes` are NEVER touched); this closes the Step-1.7 content-duplicate gate's stale-`No` masking class (the gate keys its comparison set on source-page existence, so a stale `No` once hid a real duplicate). A row whose File-cell raw file is ABSENT on disk is reported as `raw_wiki_dangling` — NEVER auto-flipped, NEVER auto-deleted (a raw may have been moved; the user disposes phantoms manually). Consume `detected.raw_wiki_healed` and `detected.raw_wiki_dangling` for the LINT REPORT.

For each wiki leaf folder (`{wiki_root}/wiki/concepts/`, `entities/`, `topics/`):

1. Verify the leaf index exists (`concepts.md`, `entities.md`, `topics.md`).
2. If `wiki/topics/topics.md` is missing, CREATE it with the 2-column header `| File | Description |` (per `shared/folder-structure.md` "Creation Rules" table; topics-leaf-index format defined alongside `sb-wiki-create-topic`).
3. If `wiki/topics/topics.md` exists with a different column layout (user-customized), preserve the user's columns. Operate accordingly: read filenames from the `File` column; do NOT rewrite the layout.
4. For `wiki/concepts/concepts.md` and `wiki/entities/entities.md`: create with the standard wiki leaf-index header (`| File | Description |`) if missing. Preserve user-customized layouts when present.
5. For each page in the leaf folder, ensure a row exists for that page. Concept/entity `Description` cells are auto-filled by `sb-wiki-fill-index-descriptions.py` (run in the Deterministic Helper step) from each page's lead definition sentence; topic `Description` cells stay LLM-filled. Never leave judgment-bearing columns blank.
6. Capture `wiki-leaf-indexes-created` count and `wiki-leaf-rows-added` total for the LINT REPORT.

**Type-tag sync (deterministic, auto-applied by the helper):** every page under `{wiki_root}/wiki/` MUST carry its `type:` frontmatter value as an entry in `tags:` (per `../shared/frontmatter-schemas.md` — Obsidian graph groups color by `tag:`, not frontmatter fields). The helper appends the missing tag (append-only — existing user tags are NEVER removed or reordered); index files (filename stem = parent directory name) missing `type:` get `type: index` + `tags: [index]`, creating the frontmatter block when absent. Non-index pages whose `type:` cannot be derived deterministically are reported in `detected.type_tags.unresolved` — surfaced in the LINT REPORT, never guessed. Capture `tags_added` and `type_index_added` for the LINT REPORT.

**Judgment-bearing cell rule:** Steps above never authorize blank semantic cells. Concept/entity `Description` cells are auto-filled by `sb-wiki-fill-index-descriptions.py` from the page's lead definition sentence; the agent fills ONLY the pages that helper reports as `weak` (no clean lead sentence) AND whose path is in `dirty_set` — skip weak pages absent from `dirty_set` (unchanged since last run). `Description` (topics and sources) remains fully LLM-owned — if the deterministic helper reports a missing row for those cells, the agent MUST read the referenced page and write the semantic cell before Step 8 (the log-prune pass). The dirty-set gate does NOT apply to missing-row fills: the helper detects a missing index row full-corpus, so the agent fills any reported missing cell regardless of whether the page is in `dirty_set` (the index has a hole; skipping the fill leaves it corrupt until a `--full` run).

### Step 7.5 — Folder-subdivision detection

Detect kinds within `wiki/concepts/` and `wiki/entities/` that have grown large enough to warrant per-kind subfolders. Skip `wiki/topics/` and `wiki/sources/` per schema § "Folder subdivision" — Topics-Sources-Excluded.

1. For `wiki/concepts/` and `wiki/entities/`:
   1. Walk all pages (skip leaf indexes and any existing per-kind subfolder indexes — those pages have already graduated).
   2. Group pages by `kind:` frontmatter value. Pages without a `kind:` value are tracked separately as `kind-missing` and surface in the LINT REPORT for the user to address.
   3. For each `kind:` value, count pages.
   4. Mark counts (threshold authority: `../shared/folder-structure.md` § "Stability Rules"):
      - <10 pages → silent.
      - ≥10 pages → `subdivision-proposal` (kind name + count + suggested subfolder name per the naming policy in schema § "Folder subdivision" → "Naming policy"; sample first 5 page filenames).
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

For each PDF raw source in `{wiki_root}/raw/{origin}/` (EXCLUDING `raw/_assets/`):

1. Read the PDF's title (raw index no longer carries `Title` — ADX-9/ADX-10): the helper uses the source page's `title:` frontmatter (else first H1) for an ingested PDF, or a not-yet-migrated legacy 4-col raw-index Title in transition; a PDF with no title source is skipped (no proposal). Compute `{title-slug}` per `../shared/naming-convention.md` § "Raw PDF Title-Conformance" → "Title-slug algorithm".
2. Stem already equals `{title-slug}` → skip.
3. Stem differs AND no `raw/{origin}/{title-slug}.pdf` exists → add a `rename-proposals` row: `{old-stem}`, `{title-slug}`, origin.
4. Stem differs BUT `raw/{origin}/{title-slug}.pdf` already exists → add to `duplicate-raws` findings (NO rename proposed — the title slug is taken; this raw duplicates an already-ingested paper).

Detection ONLY — NEVER rename at this step. Markdown raw sources are out of scope for title-conformance RENAME (clipper-named). Build `rename-proposals` and `duplicate-raws` for the LINT REPORT and the step 9 gate.

**Raw-`.md` duplicate detection (U10 — deterministic, report-only).** Consume `detected.md_duplicate_raws` from the helper — do NOT re-walk by LLM. The helper flags any NOT-yet-ingested raw `.md` whose normalized title OR normalized URL OR exact byte content-hash matches an already-ingested source. Each row is `{raw, signal, matches}`: `signal` is `content-hash` (byte-identical), `url`, or `title`; `matches` is the already-ingested source (or backing raw) it duplicates. This is REPORT-ONLY — surface every row in the LINT REPORT; NEVER auto-delete, rename, or mutate a raw (the user merges or deletes manually, the same posture as `duplicate-raws`). **Limit (state it in the report — `detected.md_duplicate_raws_limit`):** catches same-title / same-URL / byte-identical; does NOT catch reworded same-material.

#### PDF title-conformance execution (only on user accept at step 9)

Run accepted renames via the deterministic helper: `--execute-renames <plan.json>` (plan rows `{origin, old_stem, new_stem}`) — it implements the scoped rewrite + moves + verify below and reports `skipped_url_mentions`/`errors` for review. For each accepted rename, update the FULL referrer set atomically — a filesystem rename does NOT trigger Obsidian backlink updates:

1. Rewrite referrers with SCOPED WIKILINK PATTERNS ONLY — NEVER a blind global string replace:
   - **Patterns:** wikilink/embed targets `[[{old-stem}.pdf` and `[[{old-stem}.md` (with any `#anchor` or `|alias` tail) → same form with `{title-slug}`. These cover every referrer: body wikilinks, `[^N]:` footnote definitions, quoted frontmatter values (`raw:`, `related:`), the raw index `File` cell, the wiki sources index `File` cell, and `logs/*.md` references.
   - **File scope:** NON-raw `.md` files only — `{wiki_root}/wiki/**` and the `{wiki_root}/logs/*.md` queue files — plus raw INDEX files (`raw/{origin}/{origin}.md`; indexes are agent-owned). NEVER edit a raw content file body (raw-immutability contract).
   - **Exempt:** `http(s)://` URL strings that happen to contain `{old-stem}` (arXiv, repository deep links) and plain-prose stem mentions — NEVER rewritten, in any file.
2. Move `raw/{origin}/{old-stem}.pdf` → `raw/{origin}/{title-slug}.pdf`.
3. Move `wiki/sources/{origin}/{old-stem}.md` → `wiki/sources/{origin}/{title-slug}.md`.
4. The raw PDF content is never edited — rename only. NO log entry — the renamed files and rewritten links are the record.
5. Verify: search remaining `{old-stem}` occurrences under `{wiki_root}`. Expect ONLY legitimate remnants (external URLs, raw content bodies). Surface unexpected remnants in the LINT REPORT.

`duplicate-raws` findings are REPORTED, never auto-renamed — the user merges (repoint references to the canonical copy, then delete the duplicate raw + source page) or deletes them manually.

### Step 7.7 — Questions answer-sweep + graduation detection (skip-if-absent)

**Gate — questions layer.** Resolve `{wiki_root}/questions.md`. **Absent or malformed** (unreadable, invalid frontmatter, or no parseable H2 entries) → questions layer OFF: hold EMPTY `questions-answer-proposals` and `graduation-proposals` sets, SKIP this entire step, omit the Step 9 `PROPOSED ANSWERS` and `GRADUATION PROPOSAL` blocks, and do NOT read the extension — the run is identical to today (optionality guarantee #1; malformed-treated-as-absent is guarantee #5, NEVER abort). **Present and parseable** → questions layer ON: READ and execute `{sb_os_path}/wiki/workflows/sb-wiki-lint/extensions/ext-questions-sweep.md` in full (it carries the answer-sweep, the `sweep-gather` helper invocation, the dirty-set scoping, the two validation windows, and the graduation-detection pass). If that file is missing on disk, HALT naming the missing path — never silently skip the feature.

### Step 7.8 — Missing-link detection (signal-1, report-only)

Consume `detected.missing_links` from the helper — do NOT re-walk pages by LLM. The helper runs the deterministic prose-mention scan: for each ORDERED pair (source page, target page) where the target page's EXACT name appears as plain UNLINKED text in the source page's prose AND a page by that name exists, it proposes the link (case- and hyphen-insensitive; whole-token; counts only unlinked prose — never a name inside an existing wikilink, link, code span, footnote def, or frontmatter). Guards: a pair the source already links is not re-proposed; a pair recorded in `{wiki_root}/missing-links-rejected.md` is suppressed; a page never self-links. Rows are sorted by `#mentions` descending.

1. Read `detected.missing_links` — the MAIN actionable list, each row `{term, target, source, mentions}` (multi-word targets only). This is the MISSING-LINK proposal set for the LINT REPORT.
2. Under `--apply`, the helper has already WRITTEN the report file `{wiki_root}/missing-links.md` (report key `detected.missing_links_report`) with two sections — "Main proposals" + "Single-token-hub suppressed" — and the Step-9 MISSING-LINK handler reads the MAIN section. The scan NEVER writes a `[[link]]`; applying a link is the Step-9 user-gated `update-links` step ONLY.
3. **Single-token-hub suppression (ADX-7):** a proposal whose target name is a single token (no hyphen/space, e.g. `ai.md`, `llm.md`) is held OUT of the main list into `detected.missing_links_hub_suppressed` with a `detected.missing_links_hub_suppressed_count` — retained, never dropped. The MAIN list is multi-word-target only (high-precision). Report the suppressed count in the LINT REPORT (a one-line note); surface the proposal set per § "Missing-link convention" (schema). Build the MISSING-LINK PROPOSAL set from the MAIN list for the LINT REPORT.

Full convention (both stages, the `related:` cross-link contract, the rejected registry): schema § "Missing-link convention (`related:` cross-links)".

### Step 8 — Prune the logs

The `logs/` files are actionable queues. Lint NEVER writes a `lint` entry — findings live in the LINT REPORT (step 9) only. Lint's only write to the `logs/*.md` files is PRUNING. Execute the prune via the deterministic helper's `--prune-log` flag (it implements items 2-6 below exactly); the rules below remain the contract the flag implements:

1. Read every `{wiki_root}/logs/*.md` file in full. Parse H2 entries per `../shared/log-entry-shapes.md`.
2. DELETE every retired-type entry (`ingest`, `concept-created`, `entity-created`, `topic-created`, `topic-updated`, `topic-coverage-candidate`, `lint`, `query`) — these are no longer active. Remove the full entry (header + body).
3. DELETE every `candidate-topic` (in `logs/topics.md`) whose matching topic page exists at `{wiki_root}/wiki/topics/` (flat or subfolder) — spent (resolution = page exists).
4. DELETE every `candidate-mention` (in `logs/mentions.md`) whose matching page exists anywhere under `{wiki_root}/wiki/` (any type, flat or subfolder) — spent. Match by the entry's slug/`name:` normalized to the page filename.
5. DELETE every `proposed-new-thesis` (in `logs/theses.md`) whose matching thesis page exists at `{wiki_root}/wiki/theses/` (flat or subfolder) — spent (resolution = page exists, like `candidate-topic`).
6. KEEP every `candidate-topic`, `candidate-mention`, and `proposed-new-thesis` whose page does NOT yet exist. KEEP EVERY `speculative-thesis-update` unconditionally — NEVER auto-prune it (the target thesis page already exists, so "page exists" is not a resolution signal; it resolves only on user action via `sb-fin-create-thesis` extend or dismiss, per DEC-2). NEVER auto-age a `candidate-mention`. NEVER edit the body of a kept entry.
7. KEEP every entry whose type is neither active nor retired — NON-CANONICAL per `../shared/log-entry-shapes.md` "Unknown Types". NEVER delete or edit it; capture it for the LINT REPORT `Non-canonical log entries` line so the user routes it manually.
8. Preserve each file's preamble. Capture `entries-pruned` count (by reason: spent vs retired) for the LINT REPORT.

**`questions.md` prune (skip-if-absent — `{wiki_root}/questions.md` absent or malformed → skip this whole sub-step; nothing else changes).** When `questions.md` is present and parseable, prune it by the SAME "page exists" mechanism the `candidate-mention` clause (item 4) uses — do NOT invent a parallel test. Read `{wiki_root}/questions.md` in full and parse every H2 entry per `../shared/question-entry-shapes.md`, then:

1. DELETE every entry that is **promoted** — a matching wiki page now exists anywhere under `{wiki_root}/wiki/` (any type, flat or subfolder). Apply the EXACT "page exists" test from item 4: match the entry's question/`relates:` target slug normalized to a page filename. Resolution = page exists (the page is the record; the graduation handoff from the GRADUATION PROPOSAL completes here once `sb-wiki-create-topic` has authored the page). Remove the full entry (H2 header + all `relates:`/`seeded-by:`/`answer:` lines + footnote defs).
2. DELETE every entry the user has **retired** (per the entry lifecycle in `../shared/question-entry-shapes.md` — a retired entry is REMOVED from `questions.md`, no terminal state stored). Remove the full entry as in item 1.
3. KEEP every entry that is **open** (no `answer:` block or zero `answer:` bullets) or merely **answered** (≥1 `answer:` bullet) but neither promoted nor retired — an answered-but-not-yet-graduated entry persists until it graduates (page exists) or the user retires it. NEVER edit the body of a kept entry; NEVER prune an entry solely because it has accreted an answer.
4. Fold `questions.md` removals into the `entries-pruned` count (reason: promoted vs retired) for the LINT REPORT.

### Step 8.5 — Regenerate `open-gaps.md` (cross-wiki open-questions aggregate)

**Gate — always-emit (every run).** READ and execute `{sb_os_path}/wiki/workflows/sb-wiki-lint/extensions/ext-open-gaps.md` on EVERY lint run — `open-gaps.md` is regenerated wholesale every run (it loads whether the questions layer is ON or OFF, not only when proposals exist): when the layer is OFF it aggregates topic-home open questions only, and when nothing is open it still writes the empty-state file. Run it AFTER Step 8 so the just-pruned `questions.md` state is reflected. If that file is missing on disk, HALT naming the missing path — never silently skip the regeneration (a stale `open-gaps.md` misreports state).

### Step 9 — Present findings to the user

Present the LINT REPORT VERBATIM in the format below. Read-only for findings 1-7; the interactive parts (each present only when its proposal set is non-empty) are the LINK-FIX PROPOSAL, MISSING-PAGE PROPOSAL, RENAME PROPOSAL, SUBDIVISION PROPOSAL, CANDIDATE-TOPIC PROMOTION, PROPOSED ANSWERS, and GRADUATION PROPOSAL blocks — auto-applied writes from steps 6-8 have already committed. The PROPOSED ANSWERS and GRADUATION PROPOSAL blocks are omitted entirely when the questions layer is OFF (`questions.md` absent or malformed).

```
LINT REPORT — YYYY-MM-DD HH:MM

Stubs aged >30 days (N): [[X.md]], [[Y.md]], [[Z.md]]
Orphans (no inbound) (N): [[A.md]], [[B.md]]
Unresolved Disputed callouts (N): [[<page>.md]] — flagged YYYY-MM-DD
Disputed callouts needing manual review (N): [[<page>.md]] — no resolving topic + no parseable date (omit when zero)
Candidate-topics aging without promotion (N): "<slug>" — logged YYYY-MM-DD (age <a>d; acted on via the CANDIDATE-TOPIC PROMOTION block below)
Candidate-topics with unparseable timestamp (N): "<header>" — cannot be aged; review manually (omit when zero)
Thesis updates awaiting investor decision (N): "<slug>" — logged YYYY-MM-DD (never auto-pruned; resolve via sb-fin-create-thesis extend or dismiss) (omit when zero)
Broken wikilinks (N): A=<n> auto-fixable | B=<m> need a page | C=<k> unresolvable; questions.md broken (J): <target>, … (omit the questions.md clause when zero or layer OFF)
Index sync — wiki/sources Description synced: <N> source pages
Index sync — raw indexes: <N> created (raw/<origin>/<origin>.md), <M> rows added across raw/{origins}
Raw index — stale Wiki=No healed (<N>): raw/<origin>/<file> (1:1 source page exists) (omit when zero)
Raw index — dangling rows (<N>): raw/<origin>/<file> (File cell → missing raw file; dispose manually) (omit when zero)
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
Duplicate raw .md — matches already-ingested source (N): raw/<origin>/<file>.md ≡ <matches> [<signal>] (report-only — merge or delete manually) (omit when zero)
  Limit: <md_duplicate_raws_limit> (catches same-title/URL/byte-identical; NOT reworded same-material)
Missing links proposed (N): <term> → [[<target>]] in <source> (×<mentions>), … (signal-1, report-only → missing-links.md; acted on via the MISSING-LINK PROPOSAL block below); <H> single-token-hub rows suppressed (in missing-links.md, not actioned) (omit the line when N=0; omit the hub clause when H=0)

LINK-FIX PROPOSAL — broken-link bucket A (typo/encoding, auto-fixable) (omit block entirely when empty):
| # | source page | broken link | → existing file |
|---|-------------|-------------|-----------------|
| 1 | debasement-scarce-assets.md | [[…'the-debasement-trade'….md]] | …'the-debasement-trade'….md |

Decisions: accept all | accept N (e.g. "accept 1") | reject | defer
(Default if the user does not respond: defer all — broken links persist until repaired.)

MISSING-PAGE PROPOSAL — broken-link bucket B (genuinely-missing concept/entity) (omit block entirely when empty):
| # | broken target | referenced by | proposed type | proposed kind |
|---|---------------|---------------|---------------|---------------|
| 1 | miami-international-holdings.md | miaexdx.md, +1 | entity | organization |

Decisions: accept all | accept N (e.g. "accept 1") | reject | defer
(Default if the user does not respond: defer all — targets re-surface next lint run.)
(On accept, the agent authors a web-verified stub per `../shared/stub-policy.md` + `../shared/frontmatter-schemas.md`, then runs `sb-wiki-fill-index-descriptions.py --apply`. Bucket C — unresolvable — is reported in the Broken wikilinks line only; never auto-fixed.)

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

CANDIDATE-TOPIC PROMOTION — candidates aged ≥<floor> days without promotion (omit block entirely when empty):
| # | candidate | trigger | logged | age |
|---|-----------|---------|--------|-----|
| 1 | easy-money-cycle-end | evolution | 2026-05-27 | 14d |

Decisions: promote all | promote N (e.g. "promote 1,3") | dismiss N (e.g. "dismiss 2") | defer
(Default if the user does not respond: defer all — candidates persist in logs/topics.md and re-surface next lint run.)
(Rows come verbatim from `detected.log_aging_candidate_topics`; <floor> is the `--candidate-age-floor` value of the helper run, default 7. On promote, the agent invokes the `sb-wiki-create-topic` skill once per accepted candidate — it NEVER auto-authors a page; the skill writes the topic page, updates wiki/topics/topics.md, and removes the promoted entry from logs/topics.md. On dismiss, the agent deletes that single entry — H2 header + body — from logs/topics.md; no page is created, and a future ingest may legitimately re-propose the same candidate. Defer writes nothing.)

MISSING-LINK PROPOSAL — signal-1 prose-mention proposals (report-only detection; append-only apply on accept) (omit block entirely when empty):
| # | term | proposed-link | source page | #mentions |
|---|------|---------------|-------------|-----------|
| 1 | transformer | [[transformer.md]] | wiki/concepts/mechanisms/attention-mechanism.md | 3 |

Decisions: accept all | accept N (e.g. "accept 1,2") | reject N | defer
(Default if the user does not respond: defer all — proposals persist in missing-links.md and re-surface next lint run.)
(Rows come verbatim from `detected.missing_links`, sorted by #mentions desc. On accept, the agent appends `[[target]]` to the source page's `related:` AND `[[source]]` to the target's `related:` (append-only) via the `update-links` sub-command — NEVER auto-linked. On reject, the agent records the pair in missing-links-rejected.md so it is suppressed on every future run. Defer writes nothing. Hub-name rows (single-word targets like ai.md/llm.md) are low-precision — reject or defer them.)

No action required for findings 1-7 (lint is read-mostly; index sync + log prune auto-applied). The candidate-mention queue is yours to work through at your pace — nothing is auto-deleted.
```

Omit any zero-count line with empty list (e.g., `Broken wikilinks (0)` may be elided when the body would be empty). The wiki leaf indexes line is omitted when both counts are 0. The `Disputed callouts needing manual review` line is omitted when zero. The `Questions pruned` line is omitted when the questions layer is OFF (`questions.md` absent or malformed); the `Open gaps regenerated` line is omitted only when the questions layer is OFF AND no topic has an open question (the empty-state file is still written per Step 8.5, but there is nothing to report). The LINK-FIX PROPOSAL block is omitted when no bucket-A link exists; the MISSING-PAGE PROPOSAL block is omitted when no bucket-B target exists. The SUBDIVISION PROPOSAL block is omitted when the proposal set is empty. The PROPOSED ANSWERS block is omitted when `questions-answer-proposals` is empty (or the questions layer is OFF). The GRADUATION PROPOSAL block is omitted when `graduation-proposals` is empty (or the questions layer is OFF). The CANDIDATE-TOPIC PROMOTION block is omitted when `detected.log_aging_candidate_topics` is empty; the unparseable-timestamp line is omitted when `detected.log_unparseable_timestamps` is empty. The `Duplicate raw .md` line (and its `Limit:` sub-line) is omitted when `detected.md_duplicate_raws` is empty. The `Missing links proposed` line and the MISSING-LINK PROPOSAL block are omitted when `detected.missing_links` is empty. The trailing closing line is REQUIRED.

**Step 9 response handlers — per-set JIT load.** Each handler table below is loaded ONLY when its proposal set is non-empty (a clean run loads zero handlers). For each non-empty set, READ and execute the named extension file before applying the user's response; if the set is empty, the block is already omitted from the report (above) and the handler is NOT read. If a needed handler file is missing on disk, HALT naming the missing path.

| When this proposal set is non-empty | Set source | READ and follow |
|--------------------------------------|------------|-----------------|
| LINK-FIX (broken-link bucket A, step 5) | `detected.broken_wikilinks` bucket A — Step 5 | `{sb_os_path}/wiki/workflows/sb-wiki-lint/extensions/handler-link-fix.md` |
| MISSING-PAGE (broken-link bucket B, step 5) | `detected.broken_wikilinks` bucket B — Step 5 | `{sb_os_path}/wiki/workflows/sb-wiki-lint/extensions/handler-missing-page.md` |
| SUBDIVISION (step 7.5) | `detected.subdivision_proposals` — Step 7.5 | `{sb_os_path}/wiki/workflows/sb-wiki-lint/extensions/handler-subdivision.md` |
| RENAME (PDF title-conformance, step 7.6) | `detected.rename_proposals` — Step 7.6 | `{sb_os_path}/wiki/workflows/sb-wiki-lint/extensions/handler-rename.md` |
| MISSING-LINK (signal-1 prose-mention, step 7.8) | `detected.missing_links` — Step 7.8 | `{sb_os_path}/wiki/workflows/sb-wiki-lint/extensions/handler-missing-link.md` |
| PROPOSED ANSWERS (questions answer-sweep, step 7.7a — questions layer ON) | `questions-answer-proposals` — Step 7.7a (`ext-questions-sweep.md`) | `{sb_os_path}/wiki/workflows/sb-wiki-lint/extensions/handler-proposed-answers.md` |
| GRADUATION (mature `questions.md` entries, step 7.7b — questions layer ON) | `graduation-proposals` — Step 7.7b (`ext-questions-sweep.md`) | `{sb_os_path}/wiki/workflows/sb-wiki-lint/extensions/handler-graduation.md` |

The CANDIDATE-TOPIC PROMOTION block (set source: `detected.log_aging_candidate_topics`, step 4) has NO handler file — its handling is fully inline in the block text: `promote N` → invoke `sb-wiki-create-topic` once per accepted row; `dismiss N` → delete that entry (H2 header + body) from `{wiki_root}/logs/topics.md`; `defer` → no action.

**Graduation and candidate promotion NEVER auto-author.** A page is created ONLY by `sb-wiki-create-topic` on explicit user accept/promote (the GRADUATION handler and the CANDIDATE-TOPIC PROMOTION block text enforce this). Lint proposes; the skill authors. This preserves the schema rule "Agent NEVER auto-creates topic pages" (`../../docs/wiki-schema.md` § "Topic page" and "Questions layer — questions.md" → Lifecycle).

End of flow.

## Failure Modes

| Failure | Behavior |
|---------|----------|
| `{wiki_root}` cannot be resolved from `sb-os.json` | Halt before step 1; surface error. No writes. |
| `{wiki_root}/logs/` absent or empty | Skip step 4 candidate-topic + thesis detection; capture `candidates-aging = 0`, `awaiting-thesis-decisions = 0`. Step 8 prunes only — if no `logs/*.md` file exists there is nothing to prune; skip it (do NOT create the files). |
| `{wiki_root}/questions.md` absent | Questions layer OFF — skip step 7.7 entirely (hold EMPTY `questions-answer-proposals` and `graduation-proposals`); skip the `questions.md` link-resolution branch at step 5; skip the step-8 `questions.md` prune sub-step; omit the Step 9 `PROPOSED ANSWERS` and `GRADUATION PROPOSAL` blocks. Step 8.5 still runs but aggregates ONLY topic-home open questions — write `open-gaps.md` with the topic-home section populated (or the empty-state file when no topic has an open question); the `questions.md` section shows its empty-state line. Do NOT create `questions.md`. Every other step is identical to today (optionality guarantee #1). |
| `{wiki_root}/questions.md` malformed (unreadable, invalid frontmatter, or no parseable H2 entries) | WARN and treat as absent — skip step 7.7, the step-5 `questions.md` branch, and the step-8 `questions.md` prune sub-step; omit both Step 9 questions blocks. Step 8.5 behaves as in the absent row (topic-home only). NEVER abort the lint (guarantee #5). |
| `{wiki_root}/wiki/` or `{wiki_root}/raw/` missing | Skip walks for the missing tree; capture zero counts for affected sets. Continue with remaining steps. |
| Source page referenced by a `wiki/sources/{origin}/{origin}.md` row does not exist | Skip the row at step 6 `Description` sync; do NOT remove the row (user may resolve manually). Capture in `sources-resynced` only when the page exists. |
| Raw file referenced by a `raw/{origin}/{origin}.md` row does not exist | Leave the row in place at step 7; do NOT remove it (user may have moved the raw file). |
| Wiki leaf index user-customized layout (`wiki/topics/topics.md`, `wiki/concepts/concepts.md`, or `wiki/entities/entities.md`) | Preserve at step 7; do NOT rewrite the layout. Operate against the existing `File` column for row presence checks. |
| Footnote definition in body uses non-standard form (e.g., text-only without wikilink) | Skip the entry at step 6 footnote renumber; preserve user content. Do NOT auto-correct. |
