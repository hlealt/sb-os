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

`/sb-wiki-ingest-all [origin]`. No argument → every origin. Optional `[origin]` → scope the run to a single raw origin (e.g. `lennys-podcast`) for a smaller test run before backfilling everything.

## Contracts

| Contract | Rule |
|----------|------|
| Token budget | A subagent's batch MUST NOT exceed **50,000** estimated source tokens (sum of `token_estimate` across its files). A single source whose estimate alone exceeds 50,000 becomes its own batch — a source is NEVER split across subagents. |
| Same-origin serialization | Batches of the SAME origin run STRICTLY sequentially — never two at once. Same-source files reuse the same entities/concepts; concurrent ingestion would create duplicate stubs. |
| Cross-origin parallelism | Batches of DIFFERENT origins MAY run in parallel, capped at **5** concurrent subagents per wave. |
| Non-interactive ingest | Subagents auto-resolve every `/sb-wiki-ingest` checkpoint (see dispatch prompt). NO subagent ever pauses for user input. |
| Model | Subagents run on **opus** (user-requested for ingest quality). |
| No mid-run topic pages | Subagents DEFER all topics and REJECT all topic updates. Topic creation and cross-origin duplicate healing happen after, via the final lint pass. |

## Flow

### Step 1 — Discover non-ingested sources

Run from the vault root with the active Python interpreter:

```bash
python {sb_os_path}/wiki/scripts/sb-wiki-ingest-all-manifest.py --report {wiki_root}/ingest-all-manifest.json
```

Append `--origin <origin>` when the user scoped the run. Read the JSON: `items[]` (each with `path`, `origin`, `filename`, `is_pdf`, `title`, `token_estimate`) and `origins{}` (per-origin `missing` + `token_sum`). A `token_estimate` of `null` means the PDF text could not be extracted — treat such a file as its own batch. If `totals.missing` is 0, report "wiki fully ingested" and STOP.

### Step 2 — Build batches per origin

For each origin independently:

1. Order the origin's `items` by filename.
2. Greedily pack consecutive items into batches whose cumulative `token_estimate` ≤ 50,000.
3. Any single item with `token_estimate` > 50,000 (or `null`) is its own batch.
4. Number the origin's batches `0, 1, 2, …`.

A batch is a list of source filenames plus its origin. Batching is purely mechanical packing — no topical judgment.

### Step 3 — Schedule waves

Build waves so that same-origin batches are serialized and different-origin batches parallelize:

1. **Wave K** collects batch index `K` from every origin that has one. All batches in a wave are from distinct origins → safe to run together.
2. If a wave holds more than 5 batches, split it into consecutive sub-waves of ≤5 batches each (still all distinct origins).
3. Waves run in order; within a wave, batches run in parallel.

This guarantees: no two batches of the same origin ever run concurrently, and no wave exceeds the concurrency cap.

### Step 4 — Dispatch subagents

For each wave, dispatch one Opus subagent per batch IN PARALLEL (multiple Agent calls in a single message), using the dispatch prompt below. Wait for every subagent in the wave to finish before starting the next wave. Collect each subagent's per-file status and the slugs it created.

### Step 5 — Heal with lint

After the final wave, run `/sb-wiki-lint` by reading and executing `{sb_os_path}/wiki/workflows/sb-wiki-lint/sb-wiki-lint.md`. Lint dedupes any cross-origin duplicate stubs, renumbers footnotes, creates/repairs indexes, prunes the log, and surfaces aging candidates. Surface lint's report to the user.

### Step 6 — Final report

Present a summary VERBATIM:

```
INGEST-ALL COMPLETE

Sources ingested: <N> committed | <P> partial | <F> failed (of <missing> targeted)
Origins: <list with per-origin committed/total>
Failures (if any): <origin>/<filename> — <reason>
Cross-origin duplicate slugs created by ≥2 batches: <slug list, or "none">
Lint: <one-line outcome — see LINT REPORT above>
```

Delete `{wiki_root}/ingest-all-manifest.json` after the report (transient artifact).

## Subagent dispatch prompt

Fill `<files>` with the batch's source filenames and dispatch with `subagent_type: general-purpose`, `model: opus`:

```
Ingest these raw wiki sources, one at a time, in this exact order:
<files>   (origin: <origin>)

For EACH file, in order:
1. If `{user_context_root}/sb-wiki-ingest/sb-wiki-ingest.yaml` exists, read it and apply its `context:` entries BEFORE ingesting (you do not inherit workspace rules — load it yourself).
2. Invoke the `sb-wiki-ingest` workflow by reading and executing `{sb_os_path}/wiki/workflows/sb-wiki-ingest/sb-wiki-ingest.md` with this file as `<slug>`. Follow it EXACTLY — it is the sole authority on how a source is distilled. PDFs (`.pdf`) are valid slugs; the workflow resolves and reads them natively.
3. You are NON-INTERACTIVE. At the Stage 1 checkpoint (step 10) respond `accept-all`, DEFER all proposed topics, and REJECT all topic updates (firm and speculative). SKIP the Stage 2 reflection checkpoint (step 11) entirely — never wait for input.
4. Fully complete and commit one file before starting the next. Never run two ingests at once.

Do NOT run /sb-wiki-lint. Do NOT create topic pages. Do NOT touch files outside this batch.

Report back, per file: `committed` | `partial (reason)` | `failed (reason)`, and the list of NEW concept/entity page slugs you created (filename stems).
```

## Failure Modes

| Failure | Behavior |
|---------|----------|
| `{wiki_root}` or `{sb_os_path}` unresolvable from `sb-os.json` | Halt before step 1; surface error. No dispatch. |
| Manifest script reports `missing = 0` | Report "wiki fully ingested"; STOP. |
| A subagent fails on a file | Record the failure; continue the batch's remaining files and the run. Surface all failures in step 6. The source's raw-index `Wiki` stays `No`, so a re-run retries it. |
| A whole batch's subagent errors out | Mark every file in that batch `failed`; continue other waves. Re-running the command re-targets only the still-missing sources. |
| User scoped to an `[origin]` with no missing sources | Report "nothing to ingest for `<origin>`"; STOP. |
