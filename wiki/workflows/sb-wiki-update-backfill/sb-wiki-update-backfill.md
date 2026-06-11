---
name: sb-wiki-update-backfill
description: Retroactive backfill — scan for missed topic updates and optionally apply accepted ones.
---

# sb-wiki-update-backfill

Retroactive backfill over the already-ingested corpus. Evaluates every source page against current topic pages with the forward-wiring detection, emits a reviewable proposal set with a stated total count. Nothing auto-applies.

## Invocation

| Form | Behavior |
|------|----------|
| `/sb-wiki-update-backfill scan` | Run gather → LLM confirmation bar → draft proposal rows → write/merge `pending-topic-updates.md` + state total count. **Propose-only: zero writes under `wiki/`.** |
| `/sb-wiki-update-backfill apply` | Owner marks `Decision` cells in the artifact; apply `accept` rows through Step 4.5 append-only semantics; ledger `reject` rows. |

## Schema Source

The canonical authorities this workflow implements live in `{sb_os_path}/wiki/docs/wiki-schema.md`:

| Authority | What it defines |
|-----------|-----------------|
| Operations table row `/sb-wiki-update-backfill <mode>` | Registers the command (one row — NOT a step spec). |
| § "Existing topic updates" → Firm tier + "Semantic tier (source-level)" | The detection bars, dedupe chain, and cap the gather + this workflow reuse. |
| § "Existing topic updates" → "Update behavior on user accept (append-only)" | The apply-semantics table (citation/section/last-touched/never-overwrite) APPLY mode follows. |
| § "Existing topic updates" → "The artifact — pending-topic-updates.md" | The pending-rows + rejected-ledger shape this workflow reads and writes. |

There is no "/sb-wiki-update-backfill" sub-section in the schema — the row above is the only schema registration; the behavior authorities are the "Existing topic updates" subsections.

## Path Resolution

| Symbol | Resolution |
|--------|------------|
| `{wiki_root}` | Read from `sb-os.json` at vault root → `wiki_root` field. |
| `{sb_os_path}` | Read from `sb-os.json` → `sb_os_path` field. |

## Detection Authority

This workflow reuses the SAME detection the forward wiring (`sb-wiki-ingest.md` § Step 3·7 / 7d) lands on — one authority, two call sites. The backfill NEVER forks its own confidence bar. The gather subcommand (`update-backfill-gather` in `sb-wiki-lint-deterministic.py`) performs the deterministic sweep; the LLM performs the semantic confirmation bar and proposal drafting in SCAN mode.

**Firm tier (gather-side, no LLM):** EXACTLY the three forward firm match types — slug match (topic slug in source title or a `Substance` bullet), key-concept/entity overlap (`Substance` wikilink ∩ the topic's `Key concepts`/`Key entities` links), related-frontmatter overlap (`Substance` wikilink ∩ the topic's `related:` links). Wikilinks anywhere else on the topic page (Sources, Timeline, prose) are dropped — there is NO bare "wikilink-overlap" arm.

**Semantic tier (gather-side, tier-gated):** ONE probe per source (`search "<title> — <digest>" --type topic --k 5 --no-sync`); arm OFF when the tier is unavailable (no token fallback — D11). The gather applies the dedupe chain ONLY (firm-wins → rejected-ledger → citation-dedupe) and emits UNconfirmed candidates — it carries **NO token-overlap signal**. The LLM confirmation bar (a citable factual claim extending the topic's scope) runs in SCAN mode Step 3, never in the gather.

**Cap:** the gather caps semantic candidates at **2 per source** (ranked by helper score, descending) — the source's probe is the ingest-equivalent unit, so the forward per-ingest cap of 2 applies per source. Firm candidates are uncapped (mechanical, total-coverage). Overflow drops silently — re-detected by future ingests or a later backfill.

## Flow

### SCAN mode (`/sb-wiki-update-backfill scan`)

| Step | Operation | Owner |
|------|-----------|-------|
| 1 | Run the gather subcommand: `python {sb_os_path}/wiki/scripts/sb-wiki-lint-deterministic.py update-backfill-gather --vault-root <vault_root> --output <scratch_path>` (pass `--vault-root` with the VAULT root, not the wiki root — the gather resolves `wiki_root` internally). Add `--skip-semantic` for a firm-only run. The gather is read-only and stateless — it writes ONLY the scratch JSON. | Script |
| 2 | Parse the JSON output. If `firm_count` + `semantic_count` = 0 → write an explicit "0 proposals" artifact to the output path and return. The JSON's `tier_available` / `semantic_skipped` flags tell you whether the semantic arm ran (firm-only when false/true respectively). | Agent |
| 3 | **LLM confirmation bar (semantic candidates only):** Each semantic candidate is UNconfirmed — the gather emitted it post-dedupe with no token filter. Read the target topic page's `Scope` + section headings (≤5 bounded partial reads) and confirm whether the source's `Substance` carries a **citable factual claim that extends that topic's scope**. Thematic resemblance with no citable claim → drop. Firm candidates skip this bar (mechanical fires are self-confirming). | Agent |
| 4 | **Draft proposal rows:** For each confirmed candidate (all firm + confirmed semantic), draft: source page, target topic, signal, proposed section, proposed bullet + citation, **`Match`, `Rel`** (firm rows — read each firm candidate's `relevance` field from the gather JSON; see "Native relevance columns" below). Section routing per schema § "Existing topic updates" Update behavior table (debate → Key positions/Angles; evolution → Timeline; other → Key concepts/Key entities). **Drafting cap (per-subagent ≤10 sources):** if you fan drafting out to subagents, each subagent's source list MUST be ≤10 sources — large per-topic source lists caused a silent ~107/351 firm-row drop on the first real run (2026-06-10). Pass paths byte-exact from a machine-written list (copy-not-retype); a read failure is NEVER evidence the file is missing — retry and report READ-FAIL with the exact path. | Agent |
| 5 | **Coverage gate (DETERMINISTIC — firm tier is total-coverage):** After drafting, BEFORE writing the artifact, reconcile drafted firm rows against the gather's firm candidate set: `python {sb_os_path}/wiki/scripts/sb-wiki-lint-deterministic.py update-backfill-reconcile --vault-root <vault_root> --gather <gather scratch JSON> --artifact <drafted artifact (scratch)> --output <coverage report scratch>`. The subcommand emits a coverage report and EXITS NON-ZERO if ANY firm pair is neither drafted nor citation-accounted (a topic that now cites the source — staleness between gather and draft). On a non-zero exit: re-draft the `gap_pairs` it lists (in ≤10-source chunks) and re-run the gate until `coverage_total: true`. NEVER write the artifact while an unexplained firm gap stands. Semantic rows are NOT gated (default-reject, cap-limited — not total-coverage). | Script + Agent |
| 6 | **Citation-dedupe (belt-and-braces):** The gather ALREADY suppresses pairs whose topic cites the source, and Step 5's gate accounts staleness. Re-check here only as a final net: for each proposal, if the topic page's `Sources` already cites the source (raw or source-page wikilink), drop the row. | Agent |
| 7 | **Merge into `pending-topic-updates.md`:** Read the existing artifact if present. Merge new proposal rows keyed by (source, topic) pair identity — no duplicate rows. **Sort firm rows strongest→weakest within each topic** (ascending `relevance.min_df`; unscored slug/related-only rows last). Preserve existing `Decision` cells (owner marks remain intact). Write the merged artifact. **Zero writes under `wiki/`** — the artifact is the only output. | Agent |
| 8 | **State the total count:** Output the total number of proposal rows in the artifact, plus the firm/weak split (`firm_count`, `firm_weak_count` from the gather JSON). | Agent |

**SCAN mode invariant:** propose-only — no topic page edits, no raw edits, no wiki writes. The only file written is the `pending-topic-updates.md` artifact at its canonical location outside the `wiki/` tree.

### Native relevance columns (`Match` / `Rel`) — firm rows

The gather computes firm-match relevance natively (adopted per the p3-checkpoint2 ADX-8 ruling): each firm candidate in the gather JSON carries a `relevance` object — `match_concept` (the rarest shared concept between the source's `## Substance` wikilinks and the topic's `## Key concepts` / `## Key entities` links), `match_df` (how many source pages mention that concept — its document frequency), `min_df` (the sort key), and `weak` (true when `min_df >= --weak-threshold`, default 25; a hub-concept match is incidental). Render two columns from it:

| Column | Value |
|--------|-------|
| `Match` | `match_concept` + ` (` + `match_df` + `)` — e.g. `agentic-coding (3)`. A firm row with no key-concept overlap (pure slug-match or related-frontmatter-only) shows `—`. |
| `Rel` | `weak` when `relevance.weak` is true, else `specific`. **ADVISORY ONLY — a `weak` row is NEVER dropped or auto-rejected** (total-coverage invariant). The flag pre-triages the owner's review; it does not gate coverage. |

Semantic rows carry no firm relevance — their `Match`/`Rel` cells show `—` (the `signal` cell already carries `semantic: <score>`). The relevance-computation home is the gather subcommand, not a separate script (decisions.md 2026-06-11 p4-8 entry).

### APPLY mode (`/sb-wiki-update-backfill apply`)

| Step | Operation | Owner |
|------|-----------|-------|
| 1 | Read `{wiki_root}/pending-topic-updates.md`. Parse all rows. | Agent |
| 2 | For each row with `Decision` = `accept`: apply the staged change through the Step 4.5 append-only semantics (schema § "Existing topic updates" → Update behavior table): append `[^N]: [[<source-page>]]` to `Sources`; append body bullet under the topic-shape-appropriate section with inline `[^N]`; bump `last-touched`. Append-only protection per `../shared/stub-policy.md` — NEVER overwrite existing prose. | Agent |
| 3 | For each row with `Decision` = `reject`: append the (source, topic) pair to the rejected ledger section of the artifact. Applied pairs need no ledger entry (citation-dedupe self-suppresses them on future runs). | Agent |
| 4 | Rows with blank `Decision` remain pending — untouched. | Agent |
| 5 | Write the updated artifact (reflecting applied/rejected disposition). | Agent |
| 6 | Report: count of applied, rejected, and remaining pending rows. | Agent |

## Edge Cases

| Case | Handling |
|------|----------|
| Interrupted scan → re-run | Regenerate/merge idempotently — no duplicate rows (pair-keyed identity) |
| Topic created after source ingest | Covered — scan runs against CURRENT topic pages |
| Raw immutability | Scan writes only the artifact; apply writes only to topic pages via sanctioned surfaces |
| Empty result | Explicit "0 proposals" artifact, never silence |
| Speculative tier | Structurally absent — its subject is "a stub created in THIS ingest run", which a scan never creates |

## Return

| Field | Content |
|-------|---------|
| `mode` | `scan` or `apply` |
| `proposal_count` | Total rows in the artifact after the run |
| `firm_count` | Firm-tier rows detected |
| `firm_weak_count` | Firm rows flagged `weak` (hub-concept match; advisory, never dropped) |
| `semantic_count` | Semantic-tier rows confirmed |
| `coverage_total` | `true` when the Step-5 coverage gate passed (every firm pair drafted or citation-accounted) |
| `applied_count` | Rows applied (apply mode only) |
| `rejected_count` | Rows ledgered (apply mode only) |
| `artifact_path` | Path to `pending-topic-updates.md` |
