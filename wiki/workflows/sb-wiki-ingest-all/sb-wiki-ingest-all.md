---
name: sb-wiki-ingest-all
description: Backfill the wiki — ingest every not-yet-ingested raw source (Markdown + PDF) by dispatching one sub-agent per source (Sonnet for small sources, Opus for sources at or above 5k tokens) that each run /sb-wiki-ingest non-interactively, strictly sequentially, then auto-run /sb-wiki-lint. A bare `large`/`small` keyword scopes the run by size.
---

# sb-wiki-ingest-all

Orchestrator that backfills the entire wiki: it finds every raw source with no wiki page yet and ingests all of them through subagents. This file holds ONLY orchestration logic — discovery, ordering, sequential dispatch, and a final lint pass. Every per-source ingestion instruction lives in `/sb-wiki-ingest` and is NEVER restated here.

## Relationship to /sb-wiki-ingest

Each subagent runs the unmodified `sb-wiki-ingest` workflow per source. This orchestrator adds nothing to how a single source is distilled. It only decides WHICH sources run and in WHAT order, then runs lint to heal the result. If ingestion behavior must change, change `/sb-wiki-ingest` — never this file.

## Path Resolution

| Symbol | Resolution |
|--------|------------|
| `{wiki_root}` | Read from `sb-os.json` at vault root → `wiki_root` field. Resolve via `install/manifest.py` (`manifest.read(vault_root)`). Never hardcode. |
| `{user_context_root}` | Read from `sb-os.json` → `user_context_root`. Never hardcode. |
| `{sb_os_path}` | Read from `sb-os.json` → `sb_os_path` field. Never hardcode. |

## Invocation

`/sb-wiki-ingest-all [origin | file …] [large | small]`. The manifest script (Step 1) classifies the argument(s) deterministically — forward whatever the user typed as positional targets; NEVER pre-decide the mode yourself.

| Argument shape | Run mode (`mode` field in the manifest) |
|----------------|------------------------------------------|
| none | `all` — every not-yet-ingested source across every origin |
| one bare token naming an origin folder (no `.md`/`.pdf` extension, no path separator), e.g. `lennys-podcast` | `origin` — scope to that origin's missing sources |
| one-or-more raw filenames/paths (`.md`/`.pdf`, `origin/file`, or a path), or two-or-more tokens | `files` — ingest exactly those files; already-ingested ones are skipped |

**Size scope (optional).** A bare `large` or `small` keyword anywhere in the arguments scopes the run by source size — it is pulled out of the targets before mode classification, so it composes with any of the modes above:

| Keyword | Scopes the run to |
|---------|-------------------|
| `large` | only sources Opus would ingest — `token_estimate` ≥ `OPUS_TOKEN_THRESHOLD` (default 5,000) or un-estimable |
| `small` | only the Sonnet bucket — `token_estimate` < `OPUS_TOKEN_THRESHOLD` |

Examples: `large` → all missing ≥5k sources; `small` → all missing <5k sources; `every large` → only `every`'s ≥5k sources. The size boundary is the SAME number as the model split, so `large` is always the Opus set and `small` the Sonnet set.

A single bare token naming BOTH an origin folder AND a raw-file stem, an unresolvable target, a bare name matching multiple raw files, two size keywords, or a size keyword that collides with an origin folder of that name (use `--origin <name>` for the origin) → the script exits non-zero with an actionable message and ingests nothing. Surface the message and STOP — never guess.

## Contracts

| Contract | Rule |
|----------|------|
| One source per sub-agent | Each not-yet-ingested source is dispatched to its OWN sub-agent — sources are NEVER batched together. A fresh, undiluted context per source is the whole point: a multi-source context thins the synthesis of dense sources. |
| Strictly sequential | Sub-agents run ONE AT A TIME — never two concurrently. The orchestrator dispatches the next source only after the current one finishes. This removes every cross-worker write collision (no two workers ever touch the same entity/concept/topic page at once) and every duplicate-stub race. |
| Non-interactive ingest | Subagents invoke `/sb-wiki-ingest silent <slug>` per file; that mode owns every checkpoint auto-resolution. NO subagent ever pauses for user input. |
| Model | Per file, from the manifest plan: **sonnet** for small sources, **opus** when that file's `token_estimate` reaches or exceeds the script's `OPUS_TOKEN_THRESHOLD` (default 5,000) or is unknown. The script computes this — NEVER override it by judgment. The same threshold defines the `large`/`small` size buckets (Size scope below). |
| No mid-run topic pages | Subagents NEVER create topic pages mid-run — every proposed topic is deferred (the `candidate-topic` persists for the final lint pass). Topic-UPDATE resolution is owned by `/sb-wiki-ingest silent` (firm updates auto-apply append-only; speculative updates and proposed answers reject — see that mode's silent override); this caller NEVER re-states or overrides those defaults. Topic-page creation and cross-origin duplicate healing happen after, via the final lint pass. |
| Single git commit | NO git command runs during ingestion — subagents NEVER git-commit, and the orchestrator NEVER commits per source or per file. The orchestrator creates EXACTLY ONE git commit at the end of the run (step 6). Per-file status `committed` means staged FILE changes written to disk, never git. |

## Flow

> **Run `/sb-wiki-lint` before `/sb-wiki-ingest-all`.** Discovery (Step 1) identifies not-yet-ingested sources by reading each raw index row's `Wiki` cell. A freshly-imported source's `Wiki` cell flips from `No` to `Yes` only when `/sb-wiki-lint` runs (its `heal_raw_wiki_cells` pass). Until lint runs after a fresh import, `/sb-wiki-ingest-all` will re-offer that source as not yet ingested.

### Step 1 — Discover non-ingested sources + dispatch plan

Run from the vault root with the active Python interpreter, forwarding the user's argument(s) VERBATIM as positional targets (an origin name, or one-or-more filenames/paths — the script classifies them; see Invocation):

```bash
python {sb_os_path}/wiki/scripts/sb-wiki-ingest-all-manifest.py --report {wiki_root}/ingest-all-manifest.json [targets…]
```

If the script exits non-zero, it printed an actionable error to stderr (origin/file collision, unresolvable target, or a bare name matching multiple files). Surface that message and STOP — do NOT dispatch. Otherwise read the JSON:

- `mode` — `all` | `origin` | `files`, the classification the script applied. Echo it in the run's opening status so the user sees what was targeted.
- `totals` + `origins{}` — discovery counts. If `totals.missing` is 0, STOP: report "wiki fully ingested" (`all`/`origin` mode) or "all listed files already ingested" (`files` mode — `skipped_ingested[]` names them); note `totals.duplicates` if non-zero. Raw files whose index row is `Wiki = Duplicate (…)` are already excluded by the script (`duplicate_files[]` lists them — surface the list in the final report).
- `skipped_ingested[]` (`files` mode only) — listed files already having a wiki page, dropped from this run. Echo the count in the opening status.
- `plan.files[]` — the flat, ordered, ONE-file-per-sub-agent dispatch list. Each entry carries `index`, `origin`, `filename`, `path`, `token_estimate`, and `model` (`sonnet`, or `opus` when `token_estimate` ≥ 5,000 or is unknown). Dispatch these in order, one at a time.
- `size_filter` — `large` | `small` | `null`, echoing any size keyword applied. When set, `totals.size_excluded` is the count of missing sources the keyword dropped from this run; echo the scope in the opening status.

### Step 2 — Adopt the plan

Use `plan.files` VERBATIM, in order — the file ordering and per-file model are the script's mechanical outputs; the orchestrator re-orders or re-models NOTHING.

### Step 3 — (folded into the plan)

There is no batching or wave scheduling — the plan is a flat, ordered file list. Nothing to do here.

### Step 4 — Dispatch subagents

For each entry in `plan.files`, IN ORDER: dispatch ONE sub-agent (using the dispatch prompt below with that file's planned `model`), WAIT for it to finish, then dispatch the next. NEVER run two sub-agents at once — the run is strictly sequential. Collect each sub-agent's per-file status and the slugs it created. A `failed (content-duplicate: …)` status is EXPECTED behavior, not an error — the source's raw-index row is now `Duplicate (…)` and re-runs skip it; carry it into the final report's duplicates line.

### Step 5 — Heal with lint

After the last source's ingest, run `/sb-wiki-lint` by reading and executing `{sb_os_path}/wiki/workflows/sb-wiki-lint/sb-wiki-lint.md`. Lint dedupes any cross-origin duplicate stubs, renumbers footnotes, creates/repairs indexes, prunes the log, and surfaces aging candidates. Surface lint's report to the user.

### Step 6 — Final report

Tally the silent-mode `Flags` lines collected from every subagent (per the dispatch prompt) into run-wide counts: firm topic-updates applied, speculative updates rejected, and proposed answers rejected. Graduations are always 0 in silent mode (subagents NEVER promote topics — the final lint pass owns graduation); surface the lint pass's graduation count if its report emitted one, else `0`.

Present a summary VERBATIM:

```
INGEST-ALL COMPLETE

Sources ingested: <N> committed | <P> partial | <F> failed (of <missing> targeted)
Origins: <list with per-origin committed/total>
Failures (if any): <origin>/<filename> — <reason>
Duplicates (skipped or newly detected, if any): <origin>/<filename> — duplicate of <existing-raw>; awaiting user disposition
Cross-origin duplicate slugs (lint-healed, if any): <slug list, or "none">
Questions layer: <U> firm topic-updates applied | <S> speculative updates rejected | <A> proposed answers rejected | <G> graduations (lint)
Lint: <one-line outcome — see LINT REPORT above>
Tail steps: lint <ran | SKIPPED> | commit <ran | BLOCKED — <N> page(s) failed citation gate: <page list> | SKIPPED — <N> paths uncommitted> | manifest cleanup <ran | SKIPPED — ingest-all-manifest.json present>
```

The `Questions layer` line reflects silent-mode auto-resolution: only FIRM topic updates auto-apply (append-only); speculative updates and proposed answers (both homes, including answer-origin firm entries) are rejected and recorded. When the questions layer is OFF for every source (no `questions.md`) and no firm/speculative topic-update fired, all four counts are `0`. Omit the line entirely only if every count is `0`.

Delete `{wiki_root}/ingest-all-manifest.json` after the report (transient artifact).

Apply the **citation-integrity hard-gate (U7) BEFORE the single commit**:

```bash
python {sb_os_path}/wiki/scripts/sb-wiki-lint-deterministic.py check-pages --vault-root <vault-root> <page> [<page> ...]
```

Pass EVERY page the run wrote or edited (every ingested source page + every concept/entity stub slug created in Step 4 + every page lint touched/repaired in Step 5). **Read the exit code off the UN-PIPED process** — never `| tee`/`| head` (a pipe reports the pipe's status, masking a real failure). **HARD-GATE — the single commit is BLOCKED while the exit code is non-zero:**

- **Exit 0** → proceed to the commit.
- **Exit ≠ 0** → the gate's JSON `failures[]` NAMES each failing page and its issue (e.g. `def without inline ref: 20,21` = an orphan footnote def). Repair each listed failure NOW (place the missing inline `[^N]` marker on the sentence the source backs, or add the missing `[^N]:` definition — NEVER by deleting a `[^N]:` definition; stale-removal is report-only per `{sb_os_path}/wiki/workflows/shared/citation-format.md`) and RE-RUN `check-pages` until it exits 0. The run does NOT commit while the gate fails — a non-zero exit blocks the commit and the named pages MUST be fixed first.

Only after `check-pages` exits 0, create the run's SINGLE git commit, covering every change this run produced (source pages, stubs, indexes, log entries, lint heals). Skip when the vault root is not a git repository. This is the ONLY git commit of the entire run — never commit per source or per file.

**Tail-steps close-out (interrupted runs).** If the orchestrator session ends before reaching this step, any conductor resuming the run MUST execute the three tail steps manually before declaring the run complete:

1. **Heal-lint** — run `/sb-wiki-lint` as in Step 5.
2. **Single commit** — apply the citation-integrity hard-gate (U7) BEFORE committing: run `python {sb_os_path}/wiki/scripts/sb-wiki-lint-deterministic.py check-pages --vault-root <vault-root> <page> [<page> ...]` over every page the run wrote or edited; read the exit code off the UN-PIPED process. Exit ≠ 0 → BLOCK the commit, repair each failure named in `failures[]` (place the missing inline `[^N]` marker or add the missing `[^N]:` definition — NEVER by deleting a definition; per `{sb_os_path}/wiki/workflows/shared/citation-format.md`), and re-run until exit 0. Only after exit 0, create the run's git commit covering all uncommitted changes (source pages, stubs, indexes, log entries, lint heals).
3. **Manifest cleanup** — delete `{wiki_root}/ingest-all-manifest.json` if it is still present.

A conductor verifies the close-out by checking: (a) git shows no uncommitted wiki changes; (b) `{wiki_root}/ingest-all-manifest.json` is absent. Any skipped tail step MUST be reported with its reason in the `Tail steps:` line of the INGEST-ALL COMPLETE summary.

## Subagent dispatch prompt

Fill `<file>` with the single source filename and dispatch with `subagent_type: general-purpose`, `model:` the file's planned model from the plan (`sonnet`, or `opus` for ≥5k-token sources):

```
Ingest this one raw wiki source:
<file>   (origin: <origin>)

1. If `{user_context_root}/sb-wiki-ingest/sb-wiki-ingest.yaml` exists, read it and apply its `context:` entries BEFORE ingesting (you do not inherit workspace rules — load it yourself).
2. Run `/sb-wiki-ingest silent <slug>` with this file as `<slug>` by reading and executing `{sb_os_path}/wiki/workflows/sb-wiki-ingest/sb-wiki-ingest.md` in its silent mode. Follow it EXACTLY — it is the sole authority on how a source is distilled and on every checkpoint auto-resolution. PDFs (`.pdf`) are valid slugs; the workflow resolves and reads them natively.
3. Fully complete the file — every staged change written to disk — before returning.

Do NOT run /sb-wiki-lint. Do NOT create topic pages. Do NOT touch files outside this source's ingest. NEVER run any git command (add/commit/push) — the orchestrator makes the run's single git commit at the end.

Report back the FULL structured summary silent mode returns: status `committed` | `partial (reason)` | `failed (reason)`; the list of NEW concept/entity page slugs created (filename stems); and the `Flags` lines verbatim (deferred candidate-topics, applied firm topic-updates, rejected speculative updates, rejected proposed answers). The orchestrator tallies the `Flags` into the final-report counts — do NOT drop or summarize them.
```

## Failure Modes

| Failure | Behavior |
|---------|----------|
| `{wiki_root}` or `{sb_os_path}` unresolvable from `sb-os.json` | Halt before step 1; surface error. No dispatch. |
| Manifest script reports `missing = 0` | Report "wiki fully ingested"; STOP. |
| A subagent fails on a file | Record the failure; continue with the next file and the run. Surface all failures in step 6. The source's raw-index `Wiki` stays `No`, so a re-run retries it. |
| A subagent returns `failed (content-duplicate: …)` | NOT an error — the silent step-1.7 fire marked the raw-index row `Duplicate (…)`; re-runs skip it. List it on the report's Duplicates line for user disposition (delete the raw vs. re-point). |
| A source's subagent errors out | Mark that file `failed`; continue with the next file in the plan. Re-running the command re-targets only the still-missing sources. |
| User scoped to an `[origin]` with no missing sources | Report "nothing to ingest for `<origin>`"; STOP. |
| Script exits non-zero — target collision (a bare name is both an origin and a file), unresolvable target, or a bare name matching multiple raw files | The script printed an actionable message to stderr and ingested nothing. Surface it and STOP — never guess the intended target. |
| File list where every listed file is already ingested (`missing = 0`, `skipped_ingested[]` populated) | Report "all listed files already ingested"; STOP. |
| The pre-commit citation-integrity gate (`check-pages`) exits non-zero | Repair each listed failure (place the missing inline `[^N]` marker or add the missing `[^N]:` definition — NEVER by deleting a definition) and re-run until exit 0. The run does NOT commit while the gate fails. |
