---
name: sb-wiki-reingest
description: Cleanly re-ingest an already-ingested wiki source — preview-gated delete of its source page, rebuild through /sb-wiki-ingest-all, OD-6 no-worse gate, entity re-evaluation, then strip #reingest.
---

# sb-wiki-reingest

Re-ingests an ALREADY-ingested wiki source cleanly — something `/sb-wiki-ingest` and `/sb-wiki-ingest-all` deliberately refuse (they skip any source whose page already exists). This thin command LIFTS that restriction for a chosen target by deleting its source page so the unchanged ingest pipeline re-runs on it, then GATES the result so a re-do may only replace the old page when it is no worse.

This file holds ONLY the re-ingest orchestration. The per-source distillation is `/sb-wiki-ingest`'s and the per-run sequencing + lint + commit are `/sb-wiki-ingest-all`'s — NEVER restated or overridden here. The mechanical no-worse decision is `thin_detector_reingest_gate.py`'s — this command CONSUMES it.

## Path Resolution

| Symbol | Resolution |
|--------|------------|
| `{wiki_root}` | Read from `sb-os.json` at vault root → `wiki_root` field. Never hardcode. |
| `{sb_os_path}` | Read from `sb-os.json` → `sb_os_path` field. Never hardcode. |
| `{user_context_root}` | Read from `sb-os.json` → `user_context_root`. Never hardcode. |
| `python` | The active interpreter. On this machine system Python is `py -3.12`. |

## Invocation

`/sb-wiki-reingest [origin | file | path …]`.

| Argument shape | Targets resolved |
|----------------|------------------|
| none | Every `#reingest`-tagged page under `{wiki_root}/wiki/sources/**` (Step 1 collects them). A tagged LEAF INDEX (`{origin}.md`) → the whole origin; a tagged SOURCE PAGE → just that file. |
| one bare token naming an origin folder | That origin's sources (run `classify_targets` → `origin` mode). |
| one-or-more raw filenames/paths, or `origin/file`, or ≥2 tokens | Exactly those files (`classify_targets` → `files` mode). |

Target classification is the SAME deterministic `classify_targets` the ingest-all manifest uses — never pre-decide the mode yourself; forward what the user typed.

## Contracts

| Contract | Rule |
|----------|------|
| Per-target destructive step = DELETE the source page ONLY | The only file removed per target is its source page `{wiki_root}/wiki/sources/{origin}/{stem}.md`. NEVER delete the raw file, the origin leaf index, or any concept/entity/topic page. The ingest-all manifest keys on source-PAGE existence — once the source page is gone, `/sb-wiki-ingest-all <target>` re-ingests that file (Step 1.7 duplicate guard will NOT false-fire after the delete). |
| Preview-gated | NEVER delete anything before showing the owner the exact delete + re-ingest list AND receiving explicit confirmation. This command deletes files. |
| No own lint, no own commit | `/sb-wiki-ingest-all` ALREADY runs the final `/sb-wiki-lint` heal and makes the run's SINGLE git commit. This command MUST NOT add its own lint pass or any git commit. |
| Re-evaluate, never blindly preserve | Linked concept/entity pages from the first ingest are PRESERVED on disk through the delete (only the source page is removed) but MUST be RE-EVALUATED against the rebuilt page — a thin or wrong first-ingest entity is corrected, not propagated. |
| Gate before replace | A re-done page is accepted only when `thin_detector_reingest_gate.py` accepts it (≥ old on every measured retention class + `uncovered_mass`, clears the per-kind min-delta; papers/borderline need the AI no-loss confirm). A re-do that fails is SURFACED, never silently shipped. |
| Corpus + index discipline | Detection/gate runs NEVER populate the live search index — pass a SCRATCH `--db` for any embeddings-on run. The gate's typed-retention layer is embedding-free and needs none. |

## Flow

### Step 1 — Resolve targets

Run from the vault root with the active interpreter. The manifest script both CLASSIFIES the targets and reports which of them are still ingested (so you know what the delete will hit):

```bash
python {sb_os_path}/wiki/scripts/sb-wiki-ingest-all-manifest.py --report {wiki_root}/reingest-manifest.json [targets…]
```

- **No args (`#reingest` mode):** do NOT call the manifest with empty targets yet. First collect every page under `{wiki_root}/wiki/sources/**` whose frontmatter `tags:` contains `reingest` (grep the sources tree for `#reingest` OR a `reingest` tag entry). For each hit: a LEAF INDEX (`{origin}.md`) contributes its whole origin (pass the bare origin name); a SOURCE PAGE contributes its own `origin/stem.md`. De-dup, then pass the union as positional targets to the manifest script. Record the set of tagged leaf indexes — Step 6 strips their marks. If zero `#reingest` marks exist, STOP: "no `#reingest` targets".
- **Explicit args:** forward them VERBATIM as positional targets.

If the script exits non-zero it printed an actionable error (origin/file collision, unresolvable target, bare name matching multiple files). Surface it and STOP — never guess.

Read the JSON. The targets to re-ingest are the raw sources behind the resolved set; the source pages to DELETE are the ones that CURRENTLY EXIST. A target whose source page is already ABSENT is skipped with a note (ingest-all will ingest it as a normal-missing source — nothing to delete). A `#reingest` origin that resolves to 0 source pages → no-op note.

For each target that WILL be re-ingested, capture the OLD source page text NOW (read `{wiki_root}/wiki/sources/{origin}/{stem}.md` into memory before any delete) — the OD-6 gate (Step 4) compares it against the re-done page.

### Step 2 — PREVIEW + require confirmation

Present a single PREVIEW block listing, per target: the source page to be `git rm`'d, the raw source it re-ingests from, and (for context) the linked concept/entity pages that will be re-evaluated (read the OLD page's `[[wikilinks]]`). State plainly: "These source pages will be DELETED and rebuilt through the ingest pipeline. Concept/entity/topic pages are NOT deleted — they are re-evaluated. Nothing happens until you confirm."

Require an explicit `confirm` (or `yes`). On anything else — decline, silence, `abort` — STOP and change NOTHING (no delete, no ingest). This is the destructive-action gate; do not proceed unconfirmed.

### Step 3 — Delete the source pages

On confirmation, for each target with an existing source page:

```bash
git rm {wiki_root}/wiki/sources/{origin}/{stem}.md
```

Use `git rm` (git-aware) when the vault is a git repo; fall back to a filesystem delete only when it is not. Delete ONLY source pages — never the raw, leaf index, or any downstream page. Do NOT commit here (the commit is ingest-all's single end-of-run commit).

### Step 4 — Rebuild + gate each re-done page

Dispatch `/sb-wiki-ingest-all` on the SAME targets by reading and executing `{sb_os_path}/wiki/workflows/sb-wiki-ingest-all/sb-wiki-ingest-all.md` with the resolved targets as its arguments. It re-ingests one-sub-agent-per-source (sequential), through the improved capture pipeline + PDF twin, runs the final lint heal, and makes the single commit. Adopt its plan and report verbatim — add NOTHING to how a single source is distilled.

After ingest-all rebuilds a target's source page, run the OD-6 no-worse gate on it BEFORE trusting the replacement. The new page now lives at `{wiki_root}/wiki/sources/{origin}/{stem}.md`; the OLD text was captured in Step 1; the raw reference is the re-summarized source's structured input (the raw `.md` twin for the target, `{wiki_root}/raw/{origin}/{stem}.md` — for a PDF, its regenerated text twin).

Resolve the page KIND for the gate (`paper` | `article` | `podcast`): a PDF source, or one whose origin/frontmatter marks it a paper → `paper`; a podcast-origin transcript → `podcast`; else `article`.

Pick `--min-delta` by kind: **paper → `0.25`**, **article/podcast → `0.15`** (OD-6: "don't replace for a marginal gain"; papers carry the densest signal so a stricter bar avoids replacing a faithful page for noise. The gate ALSO rejects ANY measured-class regression regardless of delta — min-delta only gates marginal positive gains, never lets a worse page through).

Derive `--loss-class` from the first-ingest-vs-re-do DIFF: if the diff shows the re-do dropped a known signal class the typed layer does not measure (e.g. `reasoning_chain`), pass `--loss-class <class>` (repeatable) so the OD-6 unmeasured-class guardrail fires. Absent a known loss, pass none.

Pass `--uncovered-old`/`--uncovered-new` EXPLICITLY when you have Layer-1b uncovered_mass for both pages (the standalone composite's uncovered_mass arm is dormant for `sources/`-page raw refs — they sit outside the embeddable `raw/` tree — so the gate cannot derive it itself; supply it or omit the arm). To obtain them, run the composite detector under embeddings-on against a SCRATCH `--db` for old and new; when you parse `composite detect --json` under embeddings-on, STRIP the leading `sb-wiki-search.sync_raw` "embedding N raw chunks…" STDOUT progress line before the JSON (it is not part of the JSON). If embeddings are unavailable, omit the two flags — the gate skips that arm.

Run the gate (un-piped — read the EXIT CODE off the process directly, never through a pipe):

```bash
python {sb_os_path}/wiki/scripts/thin_detector_reingest_gate.py gate \
  --old <OLD-page-copy>.md --new {wiki_root}/wiki/sources/{origin}/{stem}.md \
  --raw {wiki_root}/raw/{origin}/{stem}.md \
  --kind <kind> --min-delta <0.25|0.15> \
  [--loss-class <class> …] [--uncovered-old <f> --uncovered-new <f>] \
  --json-out <scratch>/gate-{stem}.json
```

(The OLD page no longer exists on disk after Step 3 — write the in-memory OLD text from Step 1 to a scratch file and point `--old` at it.)

Interpret the exit code:

| Exit | Meaning | Action |
|------|---------|--------|
| 0 | ACCEPT (mechanical) | The re-do is no worse and clears the delta. If `verdict.needs_ai_confirm` is true, go to the AI no-loss confirm below before declaring final accept. |
| 1 | REJECT (mechanical) | The re-do is worse on ≥1 measured class or fails the delta. SURFACE it — do not ship silently. The old page is already gone; offer the owner: restore the old page from git history (`git checkout HEAD -- <path>` / `git restore`), keep the new page despite the regression (owner override), or re-run the re-ingest. |
| 5 | REJECT — unmeasured-class regression (OD-6 guardrail fired) | A declared loss on a class the mechanical set cannot score. Same surfacing as exit 1; the owner decides. |
| 2 | usage / bad input | A wiring error (missing file, bad arg). Fix and re-run; do not interpret as accept. |

**AI no-loss confirm (papers / borderline / surfaced unmeasured class).** When the gate returns `needs_ai_confirm: true`, the adversarial AI judge is required before a TRUE accept. Drive it through the composite's judge interface (`thin_detector_composite.py` `packet` → `judge --judge anthropic`), feeding the missing-atom packet + native PDF for papers.

> **No-key degradation (NEVER a silent pass).** The real judge needs an Anthropic key AND `pip install anthropic`, and `claude-opus-4-8` + `output_config.json_schema` + `thinking:adaptive` validated against the live SDK. When the key or SDK is ABSENT (the judge CLI exits 2 with `{error, fallback→stub}`), DO NOT run the stub as if it confirmed and DO NOT silently accept. Degrade to: the MECHANICAL gate verdict + an explicit note `AI no-loss confirm DEFERRED (no Anthropic key / anthropic SDK not installed)`. Surface the page to the owner as **conditionally accepted — AI confirm deferred**; the owner decides acceptance. A paper that mechanically accepts but cannot run the AI confirm is NEVER auto-shipped as confirmed.

### Step 5 — Re-evaluate linked concept/entity pages

For each rebuilt target, RE-EVALUATE (do not blindly preserve) the concept/entity pages the OLD page linked and the ones the NEW page links:

1. Diff the OLD page's `[[wikilinks]]` against the NEW page's. The delete removed ONLY the source page, so every previously-linked concept/entity page still exists on disk.
2. For each linked concept/entity page, check it against the rebuilt page's content: if the first-ingest stub/page is thin or wrong relative to what the rebuilt source now says, correct it (a wrong first-ingest entity must not propagate). The lint heal that ingest-all already ran renumbers footnotes and dedupes stubs; this re-evaluation is the SEMANTIC check lint does not do.
3. Confirm no broken links: every `[[…]]` the rebuilt page emits resolves to an existing page (re-link to the rebuilt page where a target moved). A link that now dangles is repaired by re-pointing it at the rebuilt page, never by leaving it broken.

This is a re-evaluation pass, not a delete pass — concept/entity/topic pages are preserved through the run and only their CONTENT is corrected where the rebuild proved them thin/wrong.

### Step 6 — Strip `#reingest` + close-out

For every leaf index that carried a `#reingest` mark consumed this run (the `#reingest`-mode set from Step 1), remove the `#reingest` tag from its frontmatter `tags:` (and any inline `#reingest`). Explicit-arg runs have no marks to strip — skip this for them.

Tell the owner to re-run the triage generator so the dashboard reflects the cleared marks: `python {wiki_root or dashboards path}/wiki-reingest-triage.gen.py` (the triage source of `#reingest` marks is `3-resources/obsidian-dashboards/wiki-reingest-triage.md`; if its generator is not present yet, just note that the marks were stripped).

Report: targets re-ingested (with each gate verdict — accept / reject / conditionally-accepted-AI-deferred), any source pages skipped (already absent), the re-evaluated downstream pages, and the ingest-all run's own summary (sources ingested, lint outcome, the single commit). Do NOT add a second commit.

## Edge Cases & Error Behavior

| Case | Behavior |
|------|----------|
| Target whose source page is already absent | Skip with a note; ingest-all ingests it as a normal-missing source. Nothing to delete, no OLD page to gate against. |
| A `#reingest` origin with 0 source pages | No-op note; strip the mark anyway (Step 6) so it does not re-fire. |
| Same-origin sources reuse entities | ingest-all already serializes them (sequential one-per-source) — no concurrent-write collision. |
| A PDF target | The re-ingest regenerates its structured text twin (PDF capture) and re-summarizes from it; gate `--kind paper`, raw reference = the regenerated twin. |
| Owner declines at the preview | Change NOTHING — no delete, no ingest. The run ends clean. |
| Gate rejects (exit 1/5) after the delete already happened | The old page is gone; surface the rejection + the restore option (`git restore`/`git checkout HEAD -- <path>` recovers the pre-delete page from history). Never silently keep a worse page. |

## Failure Modes

| Failure | Behavior |
|---------|----------|
| `{wiki_root}` / `{sb_os_path}` unresolvable from `sb-os.json` | Halt before Step 1; surface the error. No delete. |
| Manifest script exits non-zero (collision / unresolvable / multi-match) | Surface its stderr message and STOP — never guess the target. No delete. |
| Owner does not confirm at the preview | STOP; change nothing. |
| `thin_detector_reingest_gate.py` exits 2 (usage/bad input) | A wiring error — fix the args (missing file, wrong path) and re-run the gate; NEVER treat exit 2 as accept. |
| Anthropic key / `anthropic` SDK absent when `needs_ai_confirm` | Degrade to mechanical verdict + explicit `AI confirm deferred (no key)` note; surface as conditionally-accepted. NEVER silent-pass, NEVER run the stub as confirmation. |
| ingest-all reports a re-ingest failure for a target | Carry its failure into this command's report; that target's source page stays missing (re-running re-targets it). Do not gate a page that was never rebuilt. |
