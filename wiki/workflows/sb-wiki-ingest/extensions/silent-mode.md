# Ingest extension — Silent mode (contract + Step 1/1.5/1.7/10/11 overrides)

JIT extension loaded by `sb-wiki-ingest.md` ONLY when the `silent` keyword is present at invocation. The main flow loads this file AT BOOT — before Step 1 — so every silent-override clause below is in context BEFORE any halt-capable step (Steps 1, 1.5, 1.7, 10, 11) is reached; a silent-mode subagent never halts mid-batch for lack of an override. When the `silent` keyword is ABSENT, the main flow never reads this file and NONE of these clauses apply — the workflow behaves EXACTLY as the default-mode body specifies.

## Silent Mode contract

When the `silent` keyword is present, this run is non-interactive — it emits NO checkpoint prompts and NEVER awaits user input. A caller (an orchestrator subagent, the research-mode auto-ingest, or `/sb-wiki-ingest-all`) invokes it to ingest one source end-to-end and parse a machine-readable result. The schema doc § "/sb-wiki-ingest" subsection "Silent (non-interactive) mode" is the canonical spec — follow it.

The mode changes ONLY four things; everything else (clustering, stub rules, append-only protection, citation discipline, candidate-trigger detection) runs EXACTLY as the default flow:

| Branch point | Silent behavior |
|--------------|-----------------|
| Step 1 — slug resolution | A multi-match `<slug>` ERRORS — NEVER prompts. See step 1 silent clause. |
| Step 1.5 — title-conformance collision | A `{title-slug}.pdf` collision ERRORS — `failed (duplicate raw)`. NEVER prompts. See step 1.5 silent clause. |
| Step 1.7 — content-duplicate fire | A URL/title match against an already-ingested source ERRORS — `failed (content-duplicate)` + raw index row set to `Duplicate (…)`. NEVER prompts. See step 1.7 silent clause. |
| Step 10 — Stage 1 commit gate | Auto-resolve every decision to a fixed default; emit the structured summary; NO prompt, NO mid-flow HALT. See step 10 silent clause. |
| Step 11 — Stage 2 reflection | SKIPPED entirely — never presented, never awaited. See step 11 silent clause. |

## Step 1 silent override

- **Silent mode override:** Multiple matches → do NOT prompt. RETURN the structured summary with per-file status `failed (slug ambiguous: N matches)` and ingest nothing. Zero matches → RETURN `failed (slug not found)`. (Both per the schema's silent return contract.)

## Step 1.5 silent override

Collision — `raw/{origin}/{title-slug}.pdf` already exists → this raw duplicates an already-ingested paper. **Silent mode:** do NOT halt — RETURN `failed (duplicate raw: {title-slug}.pdf exists)` and ingest nothing.

## Step 1.7 silent override

Content-duplicate fire (URL or title matches an already-ingested source) → do NOT halt — RETURN `failed (content-duplicate: duplicate of <existing-raw>)` and ingest nothing, with EXACTLY ONE permitted write: set THIS raw's index row (`raw/{origin}/{origin}.md`) to `Wiki = Duplicate (of [[<existing-raw>]])` so re-runs and `/sb-wiki-ingest-all` discovery skip it durably (row missing → create it; index file missing → log a warning, skip the write). NEVER create a source page, stub, or "anchor" page for a duplicate. NEVER delete the duplicate raw — disposition is the user's call, surfaced via the caller's report.

## Step 10 silent override

**Silent mode override (step 10).** Do NOT present the Stage 1 preview. Do NOT prompt. Do NOT HALT mid-flow. Auto-resolve EVERY decision point to its fixed default, then RETURN the structured summary.

**Bucket by ORIGIN, not by internal set (read before applying).** A firm `candidate-topic-updates` entry staged by Step 3·7c (an answer to a topic's `Open questions` line) lives in the SAME firm set as a genuine firm topic update, but it is an ANSWER. Bucket every firm-set entry by how it was staged: a genuine firm topic update (Step 3 firm-tier detection) auto-APPLIES below; an answer-origin entry (Step 3·7c — surfaced in `PROPOSED ANSWERS`, suppressed from `PROPOSED TOPIC UPDATES` per Step 4.5 EXCEPTION) is a PROPOSED ANSWER and auto-REJECTS below. NEVER auto-apply an answer-origin entry — doing so violates the `PROPOSED ANSWERS → reject` rule and mis-buckets the counts.

| Decision point | Silent resolution |
|----------------|-------------------|
| Stage 1 file changes | Commit per `accept-all` — commit every staged file change. NEVER `reject` any row. NEVER `abort`. |
| Proposed topics (PROPOSED TOPICS) | `defer` ALL — every `candidate-topic` log entry persists. NEVER invoke `sb-wiki-create-topic` mid-run. |
| Firm topic updates (PROPOSED TOPIC UPDATES — genuine firm-tier entries ONLY, answer-origin entries excluded) | **`accept` ALL — apply each via the staged Step 4.5 update** (Step 4.5 owns the apply-semantics — sole authority). Write ONE audit record per applied update into the summary `Flags` field (see Audit records below). This is the v5 silent-mode change — interactive mode still defaults to reject. |
| Speculative topic updates (SPECULATIVE TOPIC UPDATES) | `reject` ALL. Write ONE audit record per rejected speculative update into `Flags`. NEVER apply unattended. |
| Proposed answers (PROPOSED ANSWERS — both homes; INCLUDES answer-origin firm entries) | `reject` ALL. Write ONE audit record per rejected proposed answer into `Flags`. NEVER apply unattended (no `questions.md` `answer:` accretion; no topic-home strike-and-fold). |

Only the FIRM tier of genuine topic updates auto-applies. Speculative updates and proposed answers (including answer-origin firm entries) NEVER auto-apply. For proposed topics and file changes these resolutions are IDENTICAL to the default-omission / `accept-all` behavior above. After committing, RETURN the structured summary the caller parses, per the schema § "/sb-wiki-ingest" subsection "Silent (non-interactive) mode" → "Return — structured summary (silent)". The summary's per-file status MUST be `committed` when all staged changes commit; `partial (<reason>)` ONLY when the source page committed but ≥1 staged change failed mid-commit (`<reason>` names what failed); `failed (<reason>)` when nothing committed (slug-resolution outcome from step 1, or an abort cause). NEVER emit `partial`/`failed` for a skipped step — clustering, trigger detection, and append-only protection all run in full. The mode NEVER writes a topic page and NEVER runs `/sb-wiki-lint`.

**Audit records (silent firm-apply + rejections).** Each applied firm update and each rejected speculative-update / proposed-answer is recorded in the structured summary's `Flags` field (the existing caller-facing channel that already carries `deferred candidate-topic` flags — NO new log entry type, NO parallel log; the `topic-updated` type is retired and the queues hold no accretion/history entries per `../../shared/log-entry-shapes.md`). One `Flags` line per record, each naming the topic page (or question), the action, and the citing source:

| Record | `Flags` line shape |
|--------|--------------------|
| Firm update applied | `topic-update applied: [[<topic-slug>.md]] ← [[<raw-filename>]] (section "<section-name>")` |
| Speculative update rejected | `speculative-update rejected: [[<topic-slug>.md]] (tokens: <t1>, <t2>)` — or, for a semantic fire: `speculative-update rejected: [[<topic-slug>.md]] (semantic: <score>)` |
| Proposed answer rejected | `proposed-answer rejected: <home> — <question brief> ← [[<raw-filename>]]` |

These `Flags` lines are what `/sb-wiki-ingest-all` aggregates into its final-report counts. The applied topic page itself is the durable record of its own updated content (per `../../shared/log-entry-shapes.md` — pages record their own updates); `Flags` is the per-run audit trail the caller surfaces.

**Lens — purpose band in the silent summary (lens ON only).** Silent mode shows NO Stage-1 banner. Instead, when the lens is ON, the structured summary INCLUDES the source's purpose band (`in-focus` | `peripheral` | `off-purpose`) from Step 2 — so `/sb-wiki-ingest-all` can list every off-purpose ingest in its final report for human review. The band is INFORMATIONAL: silent mode NEVER auto-aborts on `off-purpose` (per schema § "Off-purpose flag (Step 10)" → "Silent / bulk mode"). Lens OFF → omit the band field (summary identical to today).

| Field | Content (added when lens ON) |
|-------|------------------------------|
| Purpose band | EXACTLY ONE of: `in-focus` \| `peripheral` \| `off-purpose`. Informational only — never changes the commit outcome. |

## Step 11 silent override

**Silent mode override (step 11).** SKIP this step entirely — never present the prompt, never await a response. The source page user-half stays empty shells; the wiki sources index `My take` cell stays `pending` (set at step 8). The structured summary was already returned at step 10.
