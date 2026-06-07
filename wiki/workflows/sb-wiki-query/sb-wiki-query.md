---
name: sb-wiki-query
description: Synthesize an answer to a user question from the wiki — parse question, read leaf indexes, fall back to hybrid semantic+keyword retrieval (sb-wiki-search.py) with grep/ripgrep as the deterministic floor, follow wikilinks for depth, synthesize with inline citations, present answer, offer to file the result back as a Concept/Entity/Topic page.
---

# sb-wiki-query

Synthesize an answer to a user question from the Karpathy-style wiki layer; optionally file the answer back as a wiki page. Implements the 7-step query flow defined in the wiki schema. Retrieval is availability-gated per schema § "Retrieval tiers — hybrid search" — hybrid semantic+keyword search when the tier is available, grep/ripgrep deterministic floor otherwise.

## Schema Source

Read `3-resources/tools/sb-os/wiki/docs/wiki-schema.md` — Operations § "/sb-wiki-query" — for canonical step definitions. This workflow body implements that spec verbatim. Schema deviations require updating the schema first.

## Retrieval Tiers

Schema § "Retrieval tiers — hybrid search" governs Step 3. Probe the semantic tier by invoking the helper once; degrade gracefully:

| Tier | Step 3 behavior |
|------|-----------------|
| Semantic / keyword (helper runs, exit 0, results) | `python {sb_os_path}/wiki/scripts/sb-wiki-search.py search "<question>" --k 8` — result pages feed `picks` |
| Deterministic floor (helper missing, errors, exit 2, or zero results) | `grep` / `ripgrep` substring search across `{wiki_root}/wiki/`, expanding to `{wiki_root}/raw/` |

The helper self-syncs its index before answering (changed pages re-indexed incrementally) — NEVER run a manual index step from this workflow. `{wiki_root}/raw/` expansion ALWAYS uses grep (raw is never indexed). A helper failure NEVER aborts the query — drop to the floor and continue.

## Path Resolution

| Symbol | Resolution |
|--------|------------|
| `{wiki_root}` | Read from `sb-os.json` at vault root → `wiki_root` field. Resolve via `install/manifest.py` (`manifest.read(vault_root)`). Never hardcode. |
| `{user_context_root}` | Read from `sb-os.json` → `user_context_root`. Never hardcode. |
| `{sb_os_path}` | Read from `sb-os.json` → `sb_os_path` field. Never hardcode. |
| `{wiki_root}/wiki/` | Wiki page tree (concepts, entities, topics, sources). |
| `{wiki_root}/raw/` | Raw source tree. |
| `{wiki_root}/log.md` | Actionable queue — `candidate-topic` + `candidate-mention` entries only. |
| `{wiki_root}/questions.md` | OPTIONAL questions-layer registry — the user's open questions, loaded at Step 0 ONLY to decide whether the register-as-open-question offer fires at a query miss. Root-level sibling of `raw/`, `wiki/`, `log.md`; NOT a wiki page, NOT raw. Absent → loaded as empty; the register offer still fires and CREATES the file on first capture. Per `../../docs/wiki-schema.md` § "Questions layer — questions.md". |

## Shared Data Files

These files codify rules referenced across multiple `sb-wiki-*` workflows. Load only the files relevant to the active step.

| File | Used by step |
|------|--------------|
| `../shared/page-types.md` | 1 |
| `../shared/folder-structure.md` | 2, 3, 7 |
| `../shared/index-formats.md` | 2 |
| `../shared/naming-convention.md` | 4, 5, 7 |
| `../shared/citation-format.md` | 5 |
| `../shared/frontmatter-schemas.md` | 7 |
| `../shared/section-menus.md` | 7 |
| `../shared/log-entry-shapes.md` | 7 |
| `../shared/question-entry-shapes.md` | 6 (register-as-open-question write) |

## Invocation

`/sb-wiki-query <question>` where `<question>` is a free-form natural-language question. Quote multi-word questions if the harness requires.

## Flow

Step 0 (load `questions.md`) and Steps 1–5 run without user input. Step 6 is the single user interaction (file-back decision; on a genuine miss it ALSO offers to register the question). Step 7 fires only if the user files the answer back.

### Step 0 — Load questions (register-offer gate)

Mirrors the `/sb-wiki-ingest` Step 0.6 load contract — load only, NEVER write here. This step decides only whether the Step 6 register-as-open-question offer fires; it does NOT gate any Step 1–5 logic.

1. Resolve `{wiki_root}/questions.md`.
2. **Absent** → hold an EMPTY question set. The register offer at Step 6 STILL fires on a genuine miss and CREATES `questions.md` on first capture (create-on-first-capture — an explicit user write intent materializes the registry; matches `/sb-wiki-ingest` Stage-2 create-on-first-capture). Proceed to Step 1.
3. **Malformed** (unreadable, invalid frontmatter, or no parseable H2 entries) → WARN and proceed as if absent (empty question set). NEVER abort the query. Proceed to Step 1.
4. **Present and parseable** → no parsing of individual entries is required; the file's existence means the register write at Step 6 APPENDS rather than creates. Proceed to Step 1.

### Step 1 — Parse question; identify candidate page types and keywords

1. Read `<question>` verbatim.
2. Classify candidate page types per `../shared/page-types.md` Discriminator Rule:
   - **Concept** — the question targets an idea, methodology, principle, or pattern definable in one sentence.
   - **Entity** — the question targets a specific named thing (tool, person, company, product, model).
   - **Topic** — the question targets a debate, comparison, landscape, decision-frame, or evolution (plural framing).
   - The question may target multiple types; build a `candidate-types` set with all that fire (e.g., a question about MCP may target both the `model-context-protocol` Concept and the `mcp-debate` Topic).
3. Extract keywords — the substantive nouns and noun phrases in the question. Apply lowercase-kebab transformation per `../shared/naming-convention.md` Slug Rules to derive candidate slug fragments. Build `keywords` set.
4. If the question explicitly references a wiki page filename (e.g., `[[mcp-debate.md]]` or "the mcp-debate page"), add the resolved slug to a `direct-hits` set; this short-circuits the index walk in step 2.

### Step 2 — Read leaf indexes; pick candidate pages

For each leaf folder selected by `candidate-types` from step 1 — `{wiki_root}/wiki/concepts/`, `{wiki_root}/wiki/entities/`, `{wiki_root}/wiki/topics/` per `../shared/folder-structure.md`:

1. Read the leaf index file (`concepts.md`, `entities.md`, `topics.md`).
2. Apply expected formats per `../shared/index-formats.md` Wiki Sources Index AND the leaf-index format conventions:
   - `wiki/topics/topics.md` → `| File | Scope |`
   - `wiki/concepts/concepts.md` and `wiki/entities/entities.md` → `| File | Description |`
3. Apply graceful degradation: if a leaf index exists with a different column layout (user-customized), parse the `File` column for the page filename and treat any other column as a free-form descriptor.
4. For each row, score the match by:
   - Exact slug match against `keywords` set (highest score)
   - Substring match of any keyword inside the `File` slug (medium score)
   - Substring match of any keyword inside the descriptor column (`Scope` / `Description` / user-defined) (low score)
5. Build `picks` set: top-scoring pages from each leaf folder. Combine with `direct-hits` from step 1.
6. If `picks` is empty after this pass for ALL `candidate-types`, mark the index lookup as `ambiguous` and proceed to step 3. Otherwise, skip step 3 and proceed to step 4.

If `wiki/sources/` may also hold relevant material (the question references a specific source slug, an origin, or a date), add matching source pages from `{wiki_root}/wiki/sources/{*}/` to `picks` using the same scoring against the wiki sources index per `../shared/index-formats.md`.

### Step 3 — Retrieval fallback: hybrid search, then grep floor

Fires only when step 2 marked the index lookup as `ambiguous`. Apply the Retrieval Tiers ladder above.

1. **Semantic tier.** From the vault root run `python {sb_os_path}/wiki/scripts/sb-wiki-search.py search "<question>" --k 8`, passing the user's question verbatim (full natural-language phrasing — NOT extracted keywords). Optionally constrain with `--type` when `candidate-types` from step 1 is a strict subset (e.g., `--type topic`). Each result line carries `path#anchor` — aggregate the result pages into `picks`.
2. **Floor.** If the helper is unavailable (missing, non-zero exit, runtime error) OR returned zero results, run the floor for each keyword in `keywords` from step 1 across `{wiki_root}/wiki/` content:
   - Use `ripgrep` (`rg`) when available; fall back to `grep -r` otherwise.
   - Search filenames AND file content (page bodies, frontmatter, footnote definitions).
   - Case-insensitive match.
3. If wiki search returns no hits from EITHER tier, expand the search to `{wiki_root}/raw/` for the same keywords (grep ONLY — raw is never indexed).
4. Aggregate hit pages into `picks` set. Deduplicate. If still empty, halt step 4 and proceed directly to step 5 with an empty-evidence answer ("No wiki pages match this question — answer cannot be synthesized from the current wiki content.").

### Step 4 — Read picked pages; follow wikilinks for depth

For each page in `picks` from steps 2–3:

1. Read the page in full at `{wiki_root}/wiki/{type}/{slug}.md` or `{wiki_root}/wiki/sources/{origin}/{filename}`.
2. Capture the page filename for the `Sources consulted:` line in step 5 output.
3. Determine if depth is needed: if the answer requires context from a wikilink referenced inside the picked page (e.g., a page's `Related` section names another page central to the question), follow the wikilink.
   - Resolve the wikilink to its target file per `../shared/naming-convention.md` Wikilinks rules (target filename match is exact, including date format).
   - Read the target file in full. Add to `picks-expanded` set.
4. Bound the expansion: follow wikilinks at most 2 hops deep from the original `picks` set to keep the synthesis context bounded. Do NOT expand source pages beyond their immediate footnote definitions.

### Step 5 — Synthesize answer with inline citations

1. Compose a synthesized answer that addresses `<question>` from the picked + expanded pages. The answer is prose (1–4 paragraphs typical) — not a list dump of page contents.
2. Cite every claim with inline `[[<page>.md]]` wikilinks for wiki pages AND inline `[^N]` markers for source pages per `../shared/citation-format.md`.
   - Wiki page references — `[[<slug>.md]]` directly inline at the point of claim.
   - Source page references — `[^N]` inline marker, with matching `[^N]: [[<source-filename>.md]]` definition in a `Sources consulted` footnote block at the end of the answer.
3. Number footnotes locally for this query starting at `[^1]`. Multi-source claims get multiple markers on the same sentence: `...claim X[^1][^2]`.
4. Use wikilink format per `../shared/naming-convention.md` Wikilinks rules — `[[<filename>.md]]` matching the target file's actual filename.
5. If the answer surfaces a contradiction between two wiki pages or two sources, flag it explicitly in the prose (e.g., "On X, [[page-a.md]] argues Y while [[page-b.md]] argues Z"). Do NOT add a `> [!warning] Disputed` callout in this step — that is the ingest workflow's responsibility (per `sb-wiki-ingest.md` step 6).

### Step 6 — Present answer + offer file-back (+ register on a genuine miss)

Present the answer to the user in the format below. The output VERBATIM matches the schema's `/sb-wiki-query` "QUERY" example layout. The file-back menu is presented on EVERY answer, unchanged.

```
QUERY — "<question>"

Sources consulted: [[<page-1>.md]], [[<page-2>.md]], [[<source-1>.md]], [[<source-2>.md]]

Answer:
<synthesized prose with inline [[wikilinks]] for wiki pages and [^N] markers for source citations>

[^1]: [[<source-1>.md]]
[^2]: [[<source-2>.md]]

File this answer as a wiki page? (y/n) — type [c]oncept | [e]ntity | [t]opic | [s]kip
```

User response handling for the file-back menu:

| Response | Behavior |
|----------|----------|
| `n` or `[s]kip` | Skip step 7. End run. No log entry written. |
| `[c]oncept` | Proceed to step 7 with target type `concept`. |
| `[e]ntity` | Proceed to step 7 with target type `entity`. |
| `[t]opic` | Proceed to step 7 with target type `topic`. |

If the user response is ambiguous (no clear `c`/`e`/`t`/`s` letter), re-prompt with the same menu. Do NOT default to skip silently.

#### 6m — Register-as-open-question offer (genuine miss ONLY)

Fires ONLY when the answer presented is the **empty-evidence answer** — i.e., Step 3 exhausted both retrieval tiers AND the `raw/` expansion with zero hits and Step 5 emitted the empty-evidence template ("No wiki pages match this question — answer cannot be synthesized from the current wiki content."). NEVER fires on a successful (evidence-backed) answer; filing such an answer back is the file-back menu's job, not this offer's.

On a genuine miss, present this offer ALONGSIDE the file-back menu (append it below the menu line):

```
This question can't be answered from the current wiki. Register it as an open question? (y/n)
```

User response handling for the register offer:

| Response | Behavior |
|----------|----------|
| `n`, `[s]kip`, or no register response | Do NOT write a `questions.md` entry. The file-back menu still governs whether step 7 runs. |
| `y` or equivalent register-yes | Write ONE `{wiki_root}/questions.md` entry per the shape below, then continue handling the file-back menu response (the two offers are independent). |

Register write — append one H2 entry to `{wiki_root}/questions.md` per `../shared/question-entry-shapes.md`:

- **H2 heading** `## [<today>] <question>` — `<today>` is the current date `YYYY-MM-DD`; `<question>` is the user's `<question>` verbatim.
- **`relates:`** 0..n quoted wikilinks to any wiki page the question concerns (the `picks` set from steps 2–3, if any survived; on a true empty-evidence miss `picks` is empty, so OMIT the `relates:` field entirely — it is a cross-cutting question).
- **OMIT `seeded-by:`** — this capture is USER-originated (a `/sb-wiki-query` miss), not ingest. Per `../shared/question-entry-shapes.md`, `seeded-by:` is absent when hand-added.
- **OMIT `answer:`** — a freshly registered question is born `open` (no `answer:` block).
- Write NO `status`, `kind`, or `origin` field.

**Create-on-first-capture:** if `{wiki_root}/questions.md` is absent (Step 0 held an empty set), CREATE it with frontmatter `type: questions`, then append the entry. This matches `/sb-wiki-ingest` Stage-2 create-on-first-capture — an explicit user write intent materializes the registry. If the file already exists, append only (never rewrite existing entries).

Worked entry (empty-evidence miss, no related page):

```markdown
## [2026-06-02] <the user's question verbatim>
```

### Step 7 — File the answer back; append `query` log entry

Fires only if the user picked `[c]oncept`, `[e]ntity`, or `[t]opic` in step 6.

#### 7a — File as Topic

If target type is `topic`:

1. Derive a proposed topic slug from the question and the synthesized answer (lowercase-kebab per `../shared/naming-convention.md`).
2. **Scope-overlap pre-check.** Before invoking `sb-wiki-create-topic`, read `{wiki_root}/wiki/topics/topics.md` and compare the proposed scope sentence to every existing row's `Scope` cell. If overlap is plausible (shared subject, shared sources, shared positions, sibling/sub-debate framing), halt and present the user with three options:
   - `extend N` — append the synthesized answer's content to the existing topic page (as a new `Position` / `Angle` or sub-section). No new page is written; skill is not invoked.
   - `new` — proceed to step 3 with sibling cross-linking (the existing topic gets a `related:` entry to the new one and vice versa).
   - `abort` — skip step 7 entirely; only the `query` log entry from step 7c is written.
   The skill's own scope-overlap check (Step 1.4) is the second safety net — but this pre-check fires first because the query workflow has the synthesized answer in hand and can frame the extend-vs-new decision better than the skill alone.
3. Invoke the `sb-wiki-create-topic` skill via the user-intent invocation mode. Pass:
   - The proposed topic slug.
   - The triggering pages (the `picks` set from steps 2–4) for cross-linking.
   - The source filenames cited in step 5 for the `Sources` section.
   - A scope sentence derived from the synthesized answer.
   - An `overlap-checked: true` flag so the skill knows the pre-check ran.
4. The `sb-wiki-create-topic` skill runs its own single confirmation checkpoint with the user (per `sb-wiki-create-topic.md` user-intent confirmation format) — DO NOT duplicate the confirmation here.
5. The `sb-wiki-create-topic` skill removes the resolved `candidate-topic` entry from `{wiki_root}/log.md` if the topic was promoted from one (no `topic-created` entry is written).

#### 7b — File as Concept or Entity

If target type is `concept` or `entity`:

1. Derive the slug from the question and the synthesized answer (lowercase-kebab per `../shared/naming-convention.md`). Verify it does not already exist at `{wiki_root}/wiki/{type}s/{slug}.md` — if it does, halt and surface the conflict; the user may rename or merge manually.
2. Verify slug collision rules per `../shared/naming-convention.md` Type Folder Collision Rules (concepts vs entities allowed; concepts/entities vs topics forbidden).
3. Write `{wiki_root}/wiki/concepts/{slug}.md` (concept) or `{wiki_root}/wiki/entities/{slug}.md` (entity). Create the leaf folder lazily if absent per `../shared/folder-structure.md`.
4. Frontmatter per `../shared/frontmatter-schemas.md`:
   - Common block (`type`, `created`, `last-touched`, `related` populated with the `picks` set wikilinks, `tags: []`).
   - Concept adds `kind:` (free-form string derived from the answer; e.g., `methodology`, `pattern`, `principle`).
   - Entity adds `kind:` from the enum `tool | person | company | product | model`.
5. Section structure per `../shared/section-menus.md`:
   - Concept required sections: `Definition` (1–2 sentences, factual, derived from the synthesized answer) + `Sources` (footnote definitions for every source cited in step 5).
   - Entity required sections: `What it is` (1 factual sentence, derived from the synthesized answer) + `Sources`.
   - Optional sections — agent picks per source signal. The synthesized answer's prose informs whether to include `How it works`, `Why it matters`, `Notable facts`, `Related`, etc. Do NOT include all optional sections by default.
6. Citations per `../shared/citation-format.md`: copy the inline `[^N]` markers and matching `[^N]: [[<source-filename>.md]]` definitions from the step 5 answer into the new page's body and `Sources` section.

#### 7c — No log entry

Do NOT write a `query` log entry. The log is an actionable queue, not a history; the filed page IS the record of the answer. Per `../shared/log-entry-shapes.md`, only `candidate-topic` and `candidate-mention` are active types.

If the target type was `topic`, `sb-wiki-create-topic` (per step 7a) removes the resolved `candidate-topic` entry if one existed; nothing else is logged.

End of flow.

## Failure Modes

| Failure | Behavior |
|---------|----------|
| `{wiki_root}` cannot be resolved from `sb-os.json` | Halt before step 1; surface error. No writes. |
| `<question>` empty | Halt at step 1; ask the user to provide a question. No writes. |
| `{wiki_root}/questions.md` malformed at Step 0 (unreadable, invalid frontmatter, or no parseable H2 entries) | WARN and proceed with an EMPTY question set. NEVER abort the query. The Step 6m register offer still fires on a genuine miss; an accepted register CREATES a fresh `questions.md` (overwriting an unreadable file is NOT done — surface the conflict instead and skip the write). (Absent `questions.md` is NOT a failure — Step 0 loads it empty and Step 6m creates it on first capture.) |
| Step 2 leaf index file missing for a `candidate-type` | Skip that leaf for indexed scoring; rely on the Karpathy fallback in step 3. Capture in answer if no other leaves contribute matches. |
| Step 3 returns zero hits across both retrieval tiers AND `raw/` | Proceed to step 5 with the empty-evidence answer template ("No wiki pages match this question — answer cannot be synthesized from the current wiki content."). Step 6 still presents the file-back menu; if the user files-back, step 7 writes a stub-shaped page (no inline citations). Step 6m ALSO fires here (genuine miss) — offer to register the question as an open `questions.md` entry. |
| `sb-wiki-search.py` unavailable (missing, non-zero exit, runtime error) | Drop to the grep floor silently per Retrieval Tiers. NEVER abort the query. |
| `VOYAGE_API_KEY` unset | The helper runs in FTS5-only keyword mode — still a valid tier; no behavior change in this workflow. |
| `ripgrep` (`rg`) not installed | Fall back to `grep -r` for the step 3 floor. Both must be exhausted before declaring zero hits. |
| Wikilink target in step 4 missing (broken link) | Skip the expansion silently; do NOT halt. The page is consulted only if it exists. |
| User response at step 6 file-back menu ambiguous | Re-prompt with the same menu. Do NOT default to skip. |
| Step 7 slug collision (slug already exists at `wiki/{type}/`) | Halt at step 7b; surface conflict. No writes. The user may rename or merge manually. |
| Step 7 forbidden type collision (concept ↔ topic or entity ↔ topic) | Halt at step 7b; surface forbidden collision. No writes. |
| `sb-wiki-create-topic` skill fails mid-step-7a | Surface the failure; no page was filed and the log is untouched. The user may retry the topic creation manually via intent. |
