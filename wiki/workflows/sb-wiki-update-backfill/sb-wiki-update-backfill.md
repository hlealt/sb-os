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
| 4 | **Draft proposal rows:** For each confirmed candidate (all firm + confirmed semantic), draft: source page, target topic, signal, proposed section, proposed bullet + citation. Section routing per schema § "Existing topic updates" Update behavior table (debate → Key positions/Angles; evolution → Timeline; other → Key concepts/Key entities). | Agent |
| 5 | **Citation-dedupe (belt-and-braces):** The gather ALREADY suppresses pairs whose topic cites the source. Re-check here only as a safety net against staleness between the gather run and now: for each proposal, if the topic page's `Sources` already cites the source (raw or source-page wikilink), drop the row. | Agent |
| 6 | **Merge into `pending-topic-updates.md`:** Read the existing artifact if present. Merge new proposal rows keyed by (source, topic) pair identity — no duplicate rows. Preserve existing `Decision` cells (owner marks remain intact). Write the merged artifact. **Zero writes under `wiki/`** — the artifact is the only output. | Agent |
| 7 | **State the total count:** Output the total number of proposal rows in the artifact. | Agent |

**SCAN mode invariant:** propose-only — no topic page edits, no raw edits, no wiki writes. The only file written is the `pending-topic-updates.md` artifact at its canonical location outside the `wiki/` tree.

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
| `semantic_count` | Semantic-tier rows confirmed |
| `applied_count` | Rows applied (apply mode only) |
| `rejected_count` | Rows ledgered (apply mode only) |
| `artifact_path` | Path to `pending-topic-updates.md` |
