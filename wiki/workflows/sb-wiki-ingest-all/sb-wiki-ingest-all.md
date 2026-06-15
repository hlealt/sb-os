---
name: sb-wiki-ingest-all
description: Backfill the wiki — ingest every not-yet-ingested raw source (Markdown + PDF) by dispatching Opus subagents that each run /sb-wiki-ingest non-interactively, batched by origin with a per-subagent token budget, then auto-run /sb-wiki-lint.
---

# sb-wiki-ingest-all

Orchestrator that backfills the entire wiki: it finds every raw source with no wiki page yet and ingests all of them through subagents. This file holds ONLY orchestration logic — discovery, batching, scheduling, dispatch, and a final lint pass. Every per-source ingestion instruction lives in `/sb-wiki-ingest` and is NEVER restated here.

## Relationship to /sb-wiki-ingest

Each subagent runs the unmodified `sb-wiki-ingest` workflow per source. This orchestrator adds nothing to how a single source is distilled. It only decides WHICH sources run, in WHAT batches, and in WHAT order, then runs lint to heal the result. If ingestion behavior must change, change `/sb-wiki-ingest` — never this file.

## Path Resolution

| Symbol | Resolution |
|--------|------------|
| `{wiki_root}` | Read from `sb-os.json` at vault root → `wiki_root` field. Resolve via `install/manifest.py` (`manifest.read(vault_root)`). Never hardcode. |
| `{user_context_root}` | Read from `sb-os.json` → `user_context_root`. Never hardcode. |
| `{sb_os_path}` | Read from `sb-os.json` → `sb_os_path` field. Never hardcode. |

## Invocation

`/sb-wiki-ingest-all [origin | file …]`. The manifest script (Step 1) classifies the argument(s) deterministically — forward whatever the user typed as positional targets; NEVER pre-decide the mode yourself.

| Argument shape | Run mode (`mode` field in the manifest) |
|----------------|------------------------------------------|
| none | `all` — every not-yet-ingested source across every origin |
| one bare token naming an origin folder (no `.md`/`.pdf` extension, no path separator), e.g. `lennys-podcast` | `origin` — scope to that origin's missing sources |
| one-or-more raw filenames/paths (`.md`/`.pdf`, `origin/file`, or a path), or two-or-more tokens | `files` — ingest exactly those files; already-ingested ones are skipped |

A single bare token naming BOTH an origin folder AND a raw-file stem, an unresolvable target, or a bare name matching multiple raw files → the script exits non-zero with an actionable message and ingests nothing. Surface the message and STOP — never guess.

## Contracts

| Contract | Rule |
|----------|------|
| Token budget | A subagent's batch MUST NOT exceed **50,000** estimated source tokens (sum of `token_estimate` across its files). A single source whose estimate alone exceeds 50,000 becomes its own batch — a source is NEVER split across subagents. |
| Same-origin serialization | Batches of the SAME origin run STRICTLY sequentially — never two at once. Same-source files reuse the same entities/concepts; concurrent ingestion would create duplicate stubs. |
| Cross-origin parallelism | Batches of DIFFERENT origins MAY run in parallel, capped at **5** concurrent subagents per wave. |
| Non-interactive ingest | Subagents invoke `/sb-wiki-ingest silent <slug>` per file; that mode owns every checkpoint auto-resolution. NO subagent ever pauses for user input. |
| Model | Per batch, from the manifest plan: **sonnet** when the batch's source-token sum ≤ 15,000 and every file has a non-null estimate; **opus** otherwise. The script computes this — NEVER override it by judgment. |
| No mid-run topic pages | Subagents NEVER create topic pages mid-run — every proposed topic is deferred (the `candidate-topic` persists for the final lint pass). Topic-UPDATE resolution is owned by `/sb-wiki-ingest silent` (firm updates auto-apply append-only; speculative updates and proposed answers reject — see that mode's silent override); this caller NEVER re-states or overrides those defaults. Topic-page creation and cross-origin duplicate healing happen after, via the final lint pass. |
| Single git commit | NO git command runs during ingestion — subagents NEVER git-commit, and the orchestrator NEVER commits per source, per batch, or per wave. The orchestrator creates EXACTLY ONE git commit at the end of the run (step 6). Per-file status `committed` means staged FILE changes written to disk, never git. |

## Flow

### Step 1 — Discover non-ingested sources + dispatch plan

Run from the vault root with the active Python interpreter, forwarding the user's argument(s) VERBATIM as positional targets (an origin name, or one-or-more filenames/paths — the script classifies them; see Invocation):

```bash
python {sb_os_path}/wiki/scripts/sb-wiki-ingest-all-manifest.py --report {wiki_root}/ingest-all-manifest.json [targets…]
```

If the script exits non-zero, it printed an actionable error to stderr (origin/file collision, unresolvable target, or a bare name matching multiple files). Surface that message and STOP — do NOT dispatch. Otherwise read the JSON:

- `mode` — `all` | `origin` | `files`, the classification the script applied. Echo it in the run's opening status so the user sees what was targeted.
- `totals` + `origins{}` — discovery counts. If `totals.missing` is 0, STOP: report "wiki fully ingested" (`all`/`origin` mode) or "all listed files already ingested" (`files` mode — `skipped_ingested[]` names them); note `totals.duplicates` if non-zero. Raw files whose index row is `Wiki = Duplicate (…)` are already excluded by the script (`duplicate_files[]` lists them — surface the list in the final report).
- `skipped_ingested[]` (`files` mode only) — listed files already having a wiki page, dropped from this run. Echo the count in the opening status.
- `plan.batches{origin: [batch…]}` — each batch carries `origin`, `index`, `files[]`, `token_sum`, and `model` (`sonnet` | `opus`, per the script's threshold). Same-origin batches packed by filename order, ≤50,000 tokens; a lone file over the cap (or `null` estimate) is its own batch.
- `plan.waves[]` — ordered list of waves, each a list of `{origin, index}` refs (≤5 per wave, distinct origins within a wave, same-origin batches serialized across waves).

### Step 2 — Adopt the plan

Use `plan.batches` and `plan.waves` VERBATIM — batching, wave scheduling, and per-batch model are the script's mechanical outputs; the orchestrator re-packs or re-schedules NOTHING.

### Step 3 — (folded into the plan)

Wave scheduling is computed by the script (see Step 1). Nothing to do here.

### Step 4 — Dispatch subagents

For each wave, dispatch one subagent per batch IN PARALLEL (multiple Agent calls in a single message), using the dispatch prompt below with the batch's planned `model` (`sonnet` or `opus`). Wait for every subagent in the wave to finish before starting the next wave. Collect each subagent's per-file status and the slugs it created. A `failed (content-duplicate: …)` status is EXPECTED behavior, not an error — the source's raw-index row is now `Duplicate (…)` and re-runs skip it; carry it into the final report's duplicates line.

### Step 5 — Heal with lint

After the final wave, run `/sb-wiki-lint` by reading and executing `{sb_os_path}/wiki/workflows/sb-wiki-lint/sb-wiki-lint.md`. Lint dedupes any cross-origin duplicate stubs, renumbers footnotes, creates/repairs indexes, prunes the log, and surfaces aging candidates. Surface lint's report to the user.

### Step 6 — Final report

Tally the silent-mode `Flags` lines collected from every subagent (per the dispatch prompt) into run-wide counts: firm topic-updates applied, speculative updates rejected, and proposed answers rejected. Graduations are always 0 in silent mode (subagents NEVER promote topics — the final lint pass owns graduation); surface the lint pass's graduation count if its report emitted one, else `0`.

Present a summary VERBATIM:

```
INGEST-ALL COMPLETE

Sources ingested: <N> committed | <P> partial | <F> failed (of <missing> targeted)
Origins: <list with per-origin committed/total>
Failures (if any): <origin>/<filename> — <reason>
Duplicates (skipped or newly detected, if any): <origin>/<filename> — duplicate of <existing-raw>; awaiting user disposition
Cross-origin duplicate slugs created by ≥2 batches: <slug list, or "none">
Questions layer: <U> firm topic-updates applied | <S> speculative updates rejected | <A> proposed answers rejected | <G> graduations (lint)
Lint: <one-line outcome — see LINT REPORT above>
Tail steps: lint <ran | SKIPPED> | commit <ran | SKIPPED — <N> paths uncommitted> | manifest cleanup <ran | SKIPPED — ingest-all-manifest.json present>
```

The `Questions layer` line reflects silent-mode auto-resolution: only FIRM topic updates auto-apply (append-only); speculative updates and proposed answers (both homes, including answer-origin firm entries) are rejected and recorded. When the questions layer is OFF for every source (no `questions.md`) and no firm/speculative topic-update fired, all four counts are `0`. Omit the line entirely only if every count is `0`.

Delete `{wiki_root}/ingest-all-manifest.json` after the report (transient artifact).

Then create the run's SINGLE git commit, covering every change this run produced (source pages, stubs, indexes, log entries, lint heals). Skip when the vault root is not a git repository. This is the ONLY git commit of the entire run — never commit per source, per batch, or per wave.

**Tail-steps close-out (interrupted runs).** If the orchestrator session ends before reaching this step, any conductor resuming the run MUST execute the three tail steps manually before declaring the run complete:

1. **Heal-lint** — run `/sb-wiki-lint` as in Step 5.
2. **Single commit** — create the run's git commit covering all uncommitted changes (source pages, stubs, indexes, log entries, lint heals).
3. **Manifest cleanup** — delete `{wiki_root}/ingest-all-manifest.json` if it is still present.

A conductor verifies the close-out by checking: (a) git shows no uncommitted wiki changes; (b) `{wiki_root}/ingest-all-manifest.json` is absent. Any skipped tail step MUST be reported with its reason in the `Tail steps:` line of the INGEST-ALL COMPLETE summary.

## Subagent dispatch prompt

Fill `<files>` with the batch's source filenames and dispatch with `subagent_type: general-purpose`, `model:` the batch's planned model (`sonnet` | `opus`):

```
Ingest these raw wiki sources, one at a time, in this exact order:
<files>   (origin: <origin>)

For EACH file, in order:
1. If `{user_context_root}/sb-wiki-ingest/sb-wiki-ingest.yaml` exists, read it and apply its `context:` entries BEFORE ingesting (you do not inherit workspace rules — load it yourself).
2. Run `/sb-wiki-ingest silent <slug>` with this file as `<slug>` by reading and executing `{sb_os_path}/wiki/workflows/sb-wiki-ingest/sb-wiki-ingest.md` in its silent mode. Follow it EXACTLY — it is the sole authority on how a source is distilled and on every checkpoint auto-resolution. PDFs (`.pdf`) are valid slugs; the workflow resolves and reads them natively.
3. Fully complete one file — every staged change written to disk — before starting the next. Never run two ingests at once.

Shared-page writes — re-read-and-reapply (you do NOT inherit workspace rules): other workers in this wave may edit the SAME existing entity/concept/topic page (ingest Step 4 / 4.5). If an Edit to such a page is rejected because the file changed since you read it, RE-READ the page and RE-APPLY ONLY your own addition to the fresh content — NEVER restore the page from your earlier read. The candidate logs and the semantic-update queue are already collision-safe (the ingest routes those through the lock-guarded sb-wiki-shared-append.py), so this applies only to the shared-page edits.

Do NOT run /sb-wiki-lint. Do NOT create topic pages. Do NOT touch files outside this batch. NEVER run any git command (add/commit/push) — the orchestrator makes the run's single git commit at the end.

Report back, per file, the FULL structured summary silent mode returns: per-file status `committed` | `partial (reason)` | `failed (reason)`; the list of NEW concept/entity page slugs created (filename stems); and the `Flags` lines verbatim (deferred candidate-topics, applied firm topic-updates, rejected speculative updates, rejected proposed answers). The orchestrator tallies the `Flags` into the final-report counts — do NOT drop or summarize them.
```

## Failure Modes

| Failure | Behavior |
|---------|----------|
| `{wiki_root}` or `{sb_os_path}` unresolvable from `sb-os.json` | Halt before step 1; surface error. No dispatch. |
| Manifest script reports `missing = 0` | Report "wiki fully ingested"; STOP. |
| A subagent fails on a file | Record the failure; continue the batch's remaining files and the run. Surface all failures in step 6. The source's raw-index `Wiki` stays `No`, so a re-run retries it. |
| A subagent returns `failed (content-duplicate: …)` | NOT an error — the silent step-1.7 fire marked the raw-index row `Duplicate (…)`; re-runs skip it. List it on the report's Duplicates line for user disposition (delete the raw vs. re-point). |
| A whole batch's subagent errors out | Mark every file in that batch `failed`; continue other waves. Re-running the command re-targets only the still-missing sources. |
| User scoped to an `[origin]` with no missing sources | Report "nothing to ingest for `<origin>`"; STOP. |
| Script exits non-zero — target collision (a bare name is both an origin and a file), unresolvable target, or a bare name matching multiple raw files | The script printed an actionable message to stderr and ingested nothing. Surface it and STOP — never guess the intended target. |
| File list where every listed file is already ingested (`missing = 0`, `skipped_ingested[]` populated) | Report "all listed files already ingested"; STOP. |
