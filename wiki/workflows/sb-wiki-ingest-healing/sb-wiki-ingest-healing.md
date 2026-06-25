---
name: sb-wiki-ingest-healing
description: Heal a thin or lossy already-ingested wiki source by re-reading the source and EDITING its page in place to the reconstruction standard — augment the agent-authored sections, preserve My take + every human edit byte-identical, never delete or rebuild — then propagate to the graph (concept/entity/topic pages) and flip the source's heal-index row to heal=no. ONE target heals in-session (with preview); TWO OR MORE (or `heal all` — the heal-index heal=yes rows) dispatch one sub-agent per source, strictly sequentially at the ingest-all Sonnet/Opus split, each running the same healing flow. A `scan`/`check` mode refreshes the heal-index. No delete, no rebuild, no AI judge, no no-worse gate.
---

# sb-wiki-ingest-healing

Heals an ALREADY-ingested wiki source: an agent re-reads the source and **edits the existing source page in place** to recover dropped detail and deepen thin sections, then **propagates the recovered substance to the whole graph the source feeds** (its concept, entity, and topic pages). Healing AUGMENTS — it never deletes the page, never rebuilds from scratch, and never discards old content; so there is no old-vs-new regression to gate and **no AI judge, no OD-6 no-worse gate, and no thin-page detector** anywhere in the path. For a PDF source, healing reads the **original PDF** (not the extracted text twin), so it recovers what extraction dropped (e.g. a borderless table the twin could not grid). The healing pass IS the quality check.

This file holds ONLY the healing orchestration. The per-source distillation standard, the existing-page update protocol, the topic-update tiers, the stub-creation rule, and the candidate-topic triggers are `/sb-wiki-ingest`'s — this command RE-RUNS that same machinery additively against the deepened page and NEVER forks a parallel graph builder. The missed-topic-update reconciliation is `/sb-wiki-update-backfill`'s.

## When healing fires

| Trigger | Mode | Owner review |
|---------|------|--------------|
| A **PDF-format** source finishes its FIRST ingest (the auto-heal hook in `/sb-wiki-ingest`) | Automatic, hands-off (PROBATIONARY — see below) | None — rides the first-ingest run's commit |
| The owner runs this command (`/sb-wiki-ingest-healing [targets]`) | On-demand — self-heal for 1 target, orchestrated for ≥2 / `heal all` (the heal-index `heal=yes` rows) | Self-heal PREVIEWS before committing; orchestrated runs hands-off (no per-target preview) |
| The owner runs `/sb-wiki-ingest-healing scan` (or `check`) | Scan-only — refresh the metrics sidecar + merge new sources into the heal-index as `heal=no`, then report (no healing) | None — reports only; writes no wiki page |

**PDF auto-heal is PROBATIONARY (owner, 2026-06-19).** `marker` OCR (a table extractor pulled into the FIRST-ingest twin) may make a second automatic healing pass redundant for table recovery. The automatic PDF heal stays ON for now; it is **NECESSARY** if healing consistently recovers material the marker-improved first ingest still drops (borderless tables `marker` cannot grid, chart/figure numbers, whole dropped sections — measurable via the kept calibration/gold set), and **UNNECESSARY → demote to on-demand** (like non-PDF sources) if marker-improved first ingests are consistently faithful. Evaluate during the first real PDF ingests (Batch 5) and the backfill. **Non-PDF sources NEVER auto-fire** — they heal on-demand only (text extraction is lossless, so the first pass is reliable; auto-healing them would cost without gain). This is the only auto-firing behavior; the on-demand path is unaffected.

## Path Resolution

| Symbol | Resolution |
|--------|------------|
| `{wiki_root}` | Read from `sb-os.json` at vault root → `wiki_root` field. Never hardcode. |
| `{sb_os_path}` | Read from `sb-os.json` → `sb_os_path` field. Never hardcode. |
| `{user_context_root}` | Read from `sb-os.json` → `user_context_root`. Never hardcode. |
| `python` | The active interpreter. On this machine system Python is `py -3.12`. |

## Invocation

`/sb-wiki-ingest-healing [scan | check | origin | source-page | path …]`. Healing targets SOURCE PAGES (under `{wiki_root}/wiki/sources/**`), resolved by the manifest's `--healing` mode in the SOURCE-PAGE namespace — a page's stem need NOT match its raw filename, so targets are never resolved against `raw/`.

| Argument shape | Targets resolved |
|----------------|------------------|
| a lone `scan` or `check` token | Scan mode — refresh the heal-index, NO healing (Step 0). Resolves no heal targets. |
| none, or a lone `all` token | Every heal-index `heal=yes` row (Step 1's sweep) — the "heal all". Each row's `wiki` path is one source page to heal. |
| one bare token naming an origin folder | That origin's source pages (`--healing` → `origin` mode). |
| one-or-more `origin/stem[.md]` source-page refs, or ≥2 tokens | Exactly those pages (`--healing` → `files` mode); a bare origin token among them expands to its pages. A ref resolving to no page lands in `skipped_not_ingested` and NEVER halts the run. |

Forward what the user typed — never pre-decide the mode. (A lone `all` = the no-args heal-index `heal=yes` sweep, NOT a file target; if an origin folder is literally named `all`, qualify it `--origin all`. A lone `scan`/`check` is the scan mode, NOT a heal target.)

**Size scope (optional).** A bare `large` or `small` keyword anywhere in the arguments scopes the heal to one model bucket — exactly as `/sb-wiki-ingest-all`: `large` = the Opus set (`token_estimate` ≥ 5,000 or un-estimable), `small` = the Sonnet set. The manifest pulls it out before mode resolution, so it composes with any target set: `<origin> large`, `<pages> small`, or — with NO other positional target — the heal-index `heal=yes` sweep filtered to that bucket (`heal large` = heal the large ones in the queue). A size keyword ALONE never means heal-everything: the manifest rejects an empty `--healing`, and the command's no-target path always resolves the heal-index `heal=yes` set first. The count switch (self-heal vs orchestrated) then runs on the POST-FILTER count.

## Run mode — by resolved-target count

After Step 1 resolves the targets, the COUNT of source pages to heal selects the path. NEVER pre-decide it — count first.

| Resolved heal targets | Mode | Path |
|-----------------------|------|------|
| Exactly 1 | **Self-heal** | The in-session workflow agent heals it directly (Steps 2–3), then previews before its own single commit. No sub-agent dispatch. |
| 2 or more (incl. the `heal all` sweep) | **Orchestrated** | Dispatch one sub-agent per source — strictly sequential, model-routed at the ingest-all Sonnet/Opus split — each running this SAME healing flow (Steps 2–3) on its one source. Then one final lint + one git commit (Step 3.5 → 4 → 5). Hands-off, no per-target preview. |

The orchestrated path IS the ingest-all orchestration shell (one sub-agent per source, strict sequencing, per-file model from the manifest plan, final lint, single commit) with the healing flow as the per-source payload instead of `/sb-wiki-ingest`. It is a delta layer on ingest-all, never a fork of it.

## The reconstruction standard healing heals TO

A page is healed to the SAME bar a faithful first ingest must meet: `/sb-wiki-ingest` Step 2 **Substance coverage discipline** — a reader of the page, WITHOUT the source, can reconstruct every load-bearing claim, decision rule, quantified fact, distinction, and author caveat the source makes (the signal classes there are illustrative, not a closed checklist; density over length). Healing closes the gap between the page as it stands and that bar — recovering dropped signal and deepening thin sections until the page reconstructs the source.

## Contracts

| Contract | Rule |
|----------|------|
| EDIT IN PLACE — never delete, never rebuild | Healing edits the existing source page on disk. It NEVER deletes the source page, the raw file, the leaf index, or any concept/entity/topic page, and NEVER regenerates a page from scratch. Old content is KEPT and added to. (This is the healing advantage the delete-rebuild path lacked.) |
| AUGMENT the agent half ONLY | Healing deepens ONLY the agent-authored sections — `Substance`, `Connections`, `Counterpoints`, `Methodology`, `Notable quotes`. It appends recovered detail and expands thin sections to the reconstruction standard; it never thins or reorders what is already faithful. |
| PRESERVE the user half + every human edit byte-identical | The `My take` section and ANY hand edit anywhere on the page are preserved BYTE-IDENTICAL through the heal. Healing never rewrites, summarizes, reorders, or touches human content — it only augments agent sections + the graph. |
| Read the ORIGINAL source — never fabricate | Healing re-reads the actual source (for a PDF, the **original PDF** natively; for a markdown raw, the raw file). If the source (raw / PDF) is MISSING, healing HALTS and surfaces it — it cannot improve a page against an absent source and NEVER invents content. |
| Heal the WHOLE graph | Recovered substance propagates: existing concept/entity pages are re-evaluated + augmented (append-only), new concept/entity stubs the recovered detail warrants are created, and topic updates + candidate-topic triggers are reconciled — INCLUDING re-judging the topic suggestions the first ingest emitted. Reuse `/sb-wiki-ingest` Steps 4 / 4.5 / 5 / 6 and `/sb-wiki-update-backfill`; never fork a parallel graph builder. |
| No judge, no gate, no detector | There is NO adversarial judge, NO OD-6 no-worse gate, and NO thin-page detector in this path — the healing pass itself is the sole quality check. |
| Mode by target count | The resolved-target COUNT picks the path: 1 → self-heal in-session; ≥2 (incl. the `heal all` sweep) → orchestrated sub-agent-per-source. Never pre-decide — count first (Run mode above). |
| Orchestrated workers run THIS healing flow | Each dispatched sub-agent runs Steps 2–3 of THIS workflow on its ONE source — re-read the source, edit the page in place, augment agent sections only, preserve the human half byte-identical, propagate the graph. A worker NEVER runs `/sb-wiki-ingest` (that CREATES a page; healing EDITS an existing one). |
| Model routing | Per source, from the manifest's `--healing` plan: the SAME Sonnet/Opus split as ingest-all (Opus at `token_estimate` ≥ 5,000 or un-estimable, Sonnet below). The script computes it — NEVER override by judgment. |
| Commit ownership | A SELF-HEAL (1 target) owns its OWN single git commit. An ORCHESTRATED run (≥2) makes EXACTLY ONE git commit at the end covering every healed page + graph edit — sub-agents NEVER git-commit (exactly as `/sb-wiki-ingest-all`). A PDF auto-heal rides the first-ingest run's commit (the hook commits nothing of its own). Neither path delegates its commit to `/sb-wiki-ingest-all`. |
| Serialization | The ORCHESTRATED path runs sub-agents STRICTLY sequentially — one at a time, exactly as `/sb-wiki-ingest-all` serializes — so two heals never parallel-write a shared concept/entity/topic page. Self-heal (1 target) is inherently serial. |
| Heal-index is the queue | Multi-target / `heal all` selection reads the heal-index `3-resources/knowledge-base/heal-index.md` and takes the `heal=yes` rows (each row's `wiki` path = a source page to heal). At close-out a healed source's row is flipped to `heal=no` (whole-table rewrite — never a single-cell edit) so the source leaves the queue. The scan/check mode (Step 0) MERGE-refreshes the heal-index: new sources appended as `heal=no`, existing `heal` values never overwritten. |
| Durable healed stamp | Every successful heal (INCLUDING a no-op heal) stamps `healed: <date>` on the SOURCE PAGE frontmatter (Step 2) — the durable "already healed, don't heal again" fact. The heal-triage dashboard reads it (via the scan sidecar) and filters healed pages out of the queue by default. The heal-index `heal` column stays BINARY `yes`/`no` — `healed` is a PAGE field, NEVER a heal-index value (two binary parsers coerce any third heal-column value back to `no`). A HALTED heal does NOT stamp. |

## Flow

### Step 0 — Scan mode (`scan` / `check`)

ONLY when the sole argument is `scan` or `check`. Run the depth-scan script from the vault root with the active interpreter — it refreshes the metrics sidecar and MERGE-updates the heal-index (new sources appended as `heal=no`; existing `heal` values never overwritten):

```bash
python 3-resources/tools/sb-os/wiki/scripts/sb-wiki-heal-scan.py
```

Then report what the scan found — newly-discovered candidate sources added to the heal-index this run, the total source count scanned, and the current `heal=yes` count in the heal-index. Scan mode resolves NO heal targets and writes NO wiki page; it ends after the report. Do NOT proceed to Step 1.

### Step 1 — Resolve targets + pick mode

Run from the vault root with the active interpreter. The `--healing` flag INVERTS the manifest's selection to the ALREADY-ingested sources (those with a source page) and returns a model-routed `plan.files[]` over them — the SAME Sonnet/Opus split as ingest-all. Forward any `large`/`small` size keyword VERBATIM (the manifest pulls it out and scopes the plan to that bucket); after removing it, if no positional targets remain, run the heal-index sweep below:

```bash
python {sb_os_path}/wiki/scripts/sb-wiki-ingest-all-manifest.py --healing --report {wiki_root}/healing-manifest.json [targets…] [large|small]
```

- **No args / lone `all` (the heal-index sweep):** do NOT call the manifest empty. First read the heal-index `3-resources/knowledge-base/heal-index.md` and collect every row with `heal=yes`. Each such row's `wiki` path is one source page to heal; pass each as a positional `{origin}/{stem}.md` target (resolve `{origin}` and `{stem}` from the `wiki` path under `wiki/sources/`). De-dup the list. Record which sources were `heal=yes` — Step 5 flips each healed row to `heal=no`. If zero `heal=yes` rows exist, STOP: "no `heal=yes` targets in the heal-index".
- **Explicit args:** forward them VERBATIM as positional targets.

If the script exits non-zero it printed an actionable error (e.g. `{wiki_root}` unresolvable, or both positional targets and `--origin` given). Surface it and STOP. Unresolvable individual page refs do NOT halt — they land in `skipped_not_ingested`.

Read the JSON. `plan.files[]` is the ordered heal list — each entry carries `origin`, `filename`, `path` (the SOURCE-PAGE path the worker edits), `token_estimate`, and `model`. `skipped_not_ingested[]` lists any ref with NO page to heal — surface each as "no page to heal; ingest it first with `/sb-wiki-ingest`". An origin that resolves to 0 source pages → no-op note.

**Pick the mode by `len(plan.files)`:**

| Count | Path |
|-------|------|
| 0 | STOP — nothing to heal (report any skipped/duplicate notes). |
| 1 | **Self-heal** — run Steps 2–3 in-session on that one source, then Step 4 (preview path) + Step 5. |
| ≥2 | **Orchestrated** — Step 3.5 dispatches one sub-agent per `plan.files[]` entry (each runs Steps 2–3 on its source), then Step 4 (hands-off path) + Step 5. |

For each source you heal IN-SESSION (self-heal), read its existing source page in full NOW and capture its current `[[wikilinks]]` and the EXACT byte span of its `My take` section (and any other human-edited region) — Step 3 diffs links and Step 4 verifies the human half survived byte-identical. In orchestrated mode each sub-agent does this capture for its own source.

### Step 2 — Heal the source page in place (per-source unit)

Steps 2–3 are the PER-SOURCE heal unit: in self-heal mode the in-session agent runs them on the one target; in orchestrated mode each sub-agent runs them on its assigned source (Step 3.5). When a single agent heals more than one source in-session, process each fully before the next (serialization). Resolve the raw source from the source page's `raw:` frontmatter and the PDF (if any) from the `Original PDF: [[…]]` body line.

1. **Re-read the source.** Read the actual source in full:
   - **PDF source** → read the **original PDF** natively (the Read tool renders PDF pages; read every page, issuing successive page-range requests when the file exceeds the per-request page limit). The original PDF is the authority — read it, NOT the text twin, so you recover what extraction dropped (borderless tables, chart/figure numbers, whole dropped sections).
   - **Markdown raw source** → read the raw file in full.
   - **Source MISSING** (neither raw nor PDF resolves on disk) → HALT for this target and surface it (never fabricate). Continue with the remaining targets.
2. **Diagnose the gap.** Compare the existing page's agent sections against the source under the reconstruction standard (above). Identify every load-bearing claim, decision rule, quantified fact, tradeoff/comparison table, distinction, named pattern, and author caveat the source carries that the page DROPPED or rendered too thin to reconstruct.
3. **Augment in place — agent sections only.** Edit the existing page to recover the gaps:
   - Deepen `Substance` to the reconstruction standard — add the dropped signal classes in compact form (numbers AS numbers, a comparison kept AS a small table or one-line-per-option list, decision criteria kept AS the rule). Add one Substance unit per major section for a broad multi-section source. Density over length.
   - Route author-flagged limitations / "needs validation" / low-confidence claims to `Counterpoints`; add recovered method/dataset/sample detail to `Methodology`; add recovered verbatim quotations to `Notable quotes`; add recovered cross-links to `Connections` (each with its one-clause *why*).
   - **Append, never overwrite faithful content.** Keep everything already on the page; ADD the recovered detail. Emit inline `[^N]` markers at every newly-written claim and append the matching `[^N]: [[<raw-filename>]]` definitions in `Sources` per `{sb_os_path}/wiki/workflows/shared/citation-format.md` (number locally; lint renumbers).
   - Bump `last-touched: <today>` in frontmatter, AND add (or update) `healed: <today>` — the durable healed stamp marking this page as healed so the heal-triage dashboard filters it out of the queue by default; its absence means never healed. A no-op heal (the page already reconstructs the source) STILL stamps `healed:` — the page went through a heal pass. A HALTED heal (source missing / human half unpreservable) does NOT stamp.
4. **PRESERVE the human half byte-identical.** Do NOT touch `My take` or any hand-edited region — verify (Step 4) that the `My take` byte span captured in Step 1 is unchanged after your edits. If a heal finds nothing to add (the page already reconstructs the source), make a no-op + note rather than a forced edit — no harm.
5. **Re-link discipline.** Confirm every `[[…]]` the healed page emits resolves to an existing page; re-point a link that now dangles at the correct page (the retained re-link discipline) — never leave a link broken.

### Step 3 — Propagate to the graph (additive — reuse the ingest machinery)

The recovered substance must reach the whole graph the source feeds. Re-run the SAME `/sb-wiki-ingest` graph stages against the HEALED page (read and follow `{sb_os_path}/wiki/workflows/sb-wiki-ingest/sb-wiki-ingest.md` for each stage's exact protocol — never restate or override it here), additively:

1. **Existing concept/entity pages — re-evaluate + augment (Step 4, append-only).** Diff the OLD page's `[[wikilinks]]` (captured Step 1) against the HEALED page's. For each linked concept/entity page, check it against the healed page's recovered substance: where the first-ingest page is thin or wrong relative to what the source now says, augment it append-only (never overwrite human prose) — a thin/wrong first-ingest entity must not propagate. This is the SEMANTIC re-evaluation lint does not do.
2. **New concept/entity stubs (Step 5).** The recovered detail may surface entities/concepts the first pass missed. Run the Step-3 cluster + stub-creation rule (mechanical `Substance`-bullet branch + discretionary title/quote branches + the near-duplicate probe) over the HEALED page's new Substance, and CREATE the stubs it warrants at the schema-routed path.
3. **Topic updates + candidate-topic triggers (Steps 4.5 + 6).** Run the firm / speculative / semantic topic-update tiers and the three candidate-topic triggers over the HEALED page, INCLUDING **re-judging the topic suggestions the first ingest emitted** (the recovered substance may now confirm or extend a suggestion the first pass deferred). Apply firm updates append-only; surface speculative/semantic per their default-reject postures (on-demand: in the preview; auto-heal: auto-resolve to the silent defaults).
4. **Reconcile missed topic updates.** Run `/sb-wiki-update-backfill scan` (read and execute `{sb_os_path}/wiki/workflows/sb-wiki-update-backfill/sb-wiki-update-backfill.md`) scoped to the healed source(s) to catch any topic update the per-page stages missed — it is propose-only (zero writes under `wiki/`); apply accepted rows through its append-only apply path.

Append-only protection (`{sb_os_path}/wiki/workflows/shared/stub-policy.md` § "Append-Only Protection") governs every graph edit — NEVER overwrite existing prose on any page.

### Step 3.5 — Orchestrated dispatch (≥2 targets / `heal all`)

ONLY when `len(plan.files) ≥ 2`. Dispatch one sub-agent per `plan.files[]` entry, IN ORDER, ONE AT A TIME — wait for each to finish before the next (strict serialization; never two at once, so no two workers parallel-write a shared concept/entity/topic page). Use each entry's `model`. Collect each worker's structured return. A worker that HALTS a target (source missing, or human half not preservable byte-identical) is EXPECTED handling, not a crash — carry it into the report; it never blocks the rest.

Resolve `{sb_os_path}` and `{user_context_root}` to real workspace paths BEFORE dispatching (the worker does not inherit them). Dispatch each worker with this prompt (`<file>` = the entry's `path`, the SOURCE-PAGE path the worker reads + edits; `<origin>` = its `origin`; `subagent_type: general-purpose`, `model:` the entry's planned model):

```
Heal this one ALREADY-INGESTED wiki source — EDIT its existing page in place, do NOT re-create it:
<file>   (origin: <origin>)

1. If `{user_context_root}/sb-wiki-ingest/sb-wiki-ingest.yaml` exists, read it and apply its `context:` entries BEFORE healing (you do not inherit workspace rules — load it yourself).
2. Invoke the healing flow and follow it EXACTLY: read and execute `{sb_os_path}/wiki/workflows/sb-wiki-ingest-healing/sb-wiki-ingest-healing.md`, running ONLY its per-source unit — Step 2 (heal the page in place) and Step 3 (propagate to the graph) — on this one source. A PDF source: read the ORIGINAL PDF natively, never the text twin.
3. Honor every healing contract: EDIT IN PLACE (never delete/rebuild); AUGMENT the agent-authored sections ONLY; PRESERVE `My take` + every human edit BYTE-IDENTICAL (capture the byte span first, verify after — if you cannot preserve it, HALT this source and surface it; NEVER commit a changed human section); READ the original source (HALT if missing, never fabricate).
4. Fully complete the page — every staged change written to disk — before returning.

Do NOT run /sb-wiki-lint. Do NOT touch the heal-index (the orchestrator flips healed rows to heal=no at close-out). Do NOT touch files outside this source's heal + its graph pages. NEVER run any git command (add/commit/push) — the orchestrator makes the run's single commit at the end.

Report back: status `healed` | `no-op (already reconstructs source)` | `halted (reason)`; what was recovered (which agent sections deepened, which signal classes); the concept/entity pages augmented + new stubs created; the topic updates proposed/applied; and any human-half HALT verbatim.
```

### Step 4 — Preview / commit boundary

**Self-heal, on-demand (1 target, owner present) → PREVIEW before any commit.** Present a single PREVIEW block listing, per target: the source page edited + a precise summary of what was augmented (which agent sections deepened, which signal classes recovered), the concept/entity pages augmented, the new stubs created, and the topic updates proposed (firm/speculative/semantic in their posture blocks, exactly as `/sb-wiki-ingest` Stage 1 surfaces them). State plainly: "These are edits IN PLACE — no page is deleted or rebuilt; `My take` and every human edit are preserved untouched. Nothing commits until you confirm." Require an explicit `confirm` (or `yes`); on decline / silence / `abort`, STOP and change NOTHING. **Before committing, VERIFY the human half survived:** diff each healed page's `My take` (and captured hand-edited regions) against the Step-1 byte span and confirm BYTE-IDENTICAL — a heal that altered the human half is a defect; revert that region and re-surface. On confirm, run the post-commit citation-integrity gate (`sb-wiki-lint-deterministic.py check-pages`) over every page the heal wrote or edited, per the `/sb-wiki-ingest` Step-10 gate; repair to exit 0.

**Self-heal index write (U4 — run immediately after `check-pages` exits 0, before the git commit).** For every concept/entity/topic stub page created by this heal's Step 3.2, write its leaf-index row immediately so it appears in the wiki index without waiting for the next `/sb-wiki-lint` run:

1. Collect the list of stub pages Step 3.2 created (paths under `{wiki_root}/wiki/`).
2. For each stub, read the page and derive a 1-sentence description (the first sentence of the page body, or the `Definition` / `What it is` section's lead sentence — the same judgment cell `/sb-wiki-fill-index-descriptions.py` would derive). This cell MUST NOT be blank or a slug guess.
3. Resolve the stub's leaf-index path: for a page at `{wiki_root}/wiki/{type}/{slug}.md` the leaf index is `{wiki_root}/wiki/{type}/{type}.md`; for a subdivided subfolder page at `{wiki_root}/wiki/{type}/{subfolder}/{slug}.md` the leaf index is `{wiki_root}/wiki/{type}/{subfolder}/{subfolder}.md`.
4. Call the deterministic writer once per stub:

```bash
python {sb_os_path}/wiki/scripts/sb-wiki-index-transaction.py leaf-index \
  --vault-root <vault-root> \
  --leaf-index-path <absolute-path-to-leaf-index.md> \
  --page-file <stub-filename.md> \
  --description "<1-sentence description>"
```

   - If the leaf index file does not exist yet (lint has not created it), the writer prints a WARNING and exits 0 — do NOT abort the heal; lint will create the file and pick up the stub on its next run.
   - If the row already exists (idempotent), the writer reports "ALREADY recorded" and exits 0.

5. After ALL writer calls exit 0 (warnings are non-fatal), print this BANNER verbatim:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INDEX NOTE — run /sb-wiki-lint to complete the index
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
New stubs created by this heal have their leaf-index row
written above (deterministic, scoped).  A full /sb-wiki-lint
run is still needed to:
  • renumber footnotes across the wiki
  • deduplicate cross-origin stubs
  • repair any other index drift
Run /sb-wiki-lint when ready.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

6. Make this command's OWN single git commit covering every healed page + graph edit + leaf-index rows (when the vault is a git repo).

If Step 3.2 created NO new stubs, skip steps 1–4 (no writer calls needed) but still print the BANNER and commit.

**No automatic full-lint run.** The owner runs `/sb-wiki-lint` when ready (the banner above reminds them). This path NEVER calls `/sb-wiki-lint` automatically — the owner's standing "detection signals the human, no auto-run" principle (#33).

**Orchestrated run (≥2 targets / `heal all`) → HANDS-OFF, no per-target preview.** After every sub-agent finishes (Step 3.5): run `/sb-wiki-lint` (read and execute `{sb_os_path}/wiki/workflows/sb-wiki-lint/sb-wiki-lint.md`) to dedupe cross-origin stubs, renumber footnotes, and repair indexes; then apply the **citation-integrity hard-gate (U7) BEFORE the single commit**:

```bash
python {sb_os_path}/wiki/scripts/sb-wiki-lint-deterministic.py check-pages --vault-root <vault-root> <page> [<page> ...]
```

Pass EVERY page the run wrote or edited (every healed source page + every graph page augmented/created + every lint-touched page). **Read the exit code off the UN-PIPED process** — never `| tee`/`| head` (a pipe reports the pipe's status, masking a real failure). **HARD-GATE — the single commit is BLOCKED while the exit code is non-zero:**

- **Exit 0** → proceed to the commit.
- **Exit ≠ 0** → the gate's JSON `failures[]` NAMES each failing page and its issue (e.g. `def without inline ref: 20,21` = an orphan footnote def). Repair each listed failure NOW (place the missing inline `[^N]` marker on the sentence the source backs, or add the missing `[^N]:` definition — NEVER by deleting a `[^N]:` definition; stale-removal is report-only per `{sb_os_path}/wiki/workflows/shared/citation-format.md`) and RE-RUN `check-pages` until it exits 0. The run does NOT commit while the gate fails — a non-zero exit blocks the commit and the named pages MUST be fixed first.

Only after `check-pages` exits 0, make the run's EXACTLY ONE git commit covering every healed page + graph edit + lint heal (when the vault is a git repo). A worker that HALTED a target committed NOTHING for it — surface those in the report; never auto-retry. This path commits without owner preview (the price of the ingest-all-style bulk run), but every worker still HARD-VERIFIED its source's human half byte-identical and refused to write a changed human section, AND the bulk commit is hard-gated on `check-pages` exit 0 so no orphan footnote rides the single commit.

**PDF auto-heal (hands-off, fired by the `/sb-wiki-ingest` hook) → NO preview, NO checkpoint.** The healing pass runs the per-source unit (Steps 2–3) against the just-written page + the original PDF, auto-resolves every decision point to the silent defaults (firm topic updates auto-apply append-only; speculative/semantic/proposed-answers default-reject), still verifies the human half byte-identical, and makes NO commit of its own — its edits ride the first-ingest run's single commit. The owner does not review it (the price of fully hands-off paper ingestion).

### Step 5 — Flip healed rows to `heal=no` + close-out

Flip every healed source's heal-index row to `heal=no`, so healed sources leave the heal queue. For each source healed this run, set its row's `heal` cell to `no` in the heal-index `3-resources/knowledge-base/heal-index.md`, keyed by the `wiki` path. Rewrite the WHOLE table from an in-memory array (read all rows, set the healed ones to `heal=no`, write the whole table back) — NEVER a fragile single-cell edit.

The heal-index `heal` column is the mutable QUEUE state (binary `yes`/`no`); the durable "already healed, don't heal again" fact lives on each page's `healed:` frontmatter stamp (written in Step 2), which the heal-triage dashboard reads (via the scan sidecar) to filter healed pages out of the queue by default. Step 5 owns ONLY the heal-index row flip; the page stamp is Step 2's. Do NOT write `healed` into the heal-index `heal` column — two binary parsers (the dashboard and the scan) coerce any non-`yes`/`no` value back to `no`.

This applies on BOTH no-args (heal-index-sweep) and explicit-arg runs — an explicit-arg heal of a source the owner marked in the dashboard must still flip its row. The PDF auto-heal run is the ONLY exception: it heals a just-ingested page whose row is already `heal=no` (or absent) and commits nothing of its own — skip the flip for it.

A source the run HALTED (source missing, human half unpreservable) keeps its `heal=yes` row — only healed sources flip — so a re-run re-targets it. The dashboard reads the heal-index directly, so the flipped rows appear without re-running any generator.

On any on-demand run (self-heal or orchestrated), delete `{wiki_root}/healing-manifest.json` after the report (transient artifact; the PDF auto-heal never writes it).

Report: pages healed (with what each recovered), any targets skipped (no page to heal / source missing) or worker HALTs, the graph pages augmented + stubs created + topic updates applied, and the single commit. A PDF auto-heal reports its trace into the first-ingest run's return; it adds no second commit.

## Edge Cases & Error Behavior

| Case | Behavior |
|------|----------|
| Human-curated page (`My take`, manual `Counterpoints`, hand edits) | Preserved untouched, byte-identical — healing augments ONLY the agent-authored sections + the graph. A delete-rebuild would have clobbered this; healing does not. |
| A PDF whose twin was already faithful | Auto-heal still fires (you cannot cheaply know in advance it was fine; cost is bounded; papers are the highest-value sources). A heal that finds nothing to add makes a no-op edit + a note — no harm. |
| A PDF whose text twin dropped content (the `twin_fidelity: false` case) | The heal, reading the ORIGINAL PDF, recovers that content into the page — the recovery the retired judge could only flag. |
| Same-origin sources reusing entities | Process sequentially (one source at a time) — healing never parallel-writes a shared concept/entity page. |
| Broken links after augmenting | Re-point each `[[…]]` at the correct page (the re-link discipline, Step 2.5) — never leave a link broken. |
| Source (raw / PDF) missing | HALT for that target and surface it — healing cannot improve a page against an absent source and NEVER fabricates. Continue with the other targets. |
| Target whose source page is absent | Nothing to heal in place — surface "no page to heal; ingest it first with `/sb-wiki-ingest`". |
| An origin with 0 source pages | No-op note; nothing to heal, no row to flip. |
| Owner declines at the on-demand preview | Change NOTHING — no edit commits. The run ends clean. |
| `heal all` / a multi-target arg resolves to exactly 1 page | Self-heal that one page in-session (the count switch) — no dispatch overhead, and the owner still gets the preview. |
| Orchestrated worker HALTS a target (source missing / human half unpreservable) | Expected handling — carry it into the report, continue the rest. Its heal-index row stays `heal=yes` (Step 5 flips only healed pages), so a re-run re-targets it. |

## Failure Modes

| Failure | Behavior |
|---------|----------|
| `{wiki_root}` / `{sb_os_path}` unresolvable from `sb-os.json` | Halt before Step 1; surface the error. No edit. |
| Manifest script exits non-zero (collision / unresolvable / multi-match) | Surface its stderr message and STOP — never guess the target. No edit. |
| The source page to heal does not exist on disk | Surface "no page to heal; ingest it first"; skip that target. |
| The source (raw / PDF) the page derives from is missing | HALT for that target and surface it; never fabricate. Continue with the rest. |
| `My take` / a human-edited region differs after the heal | A defect — revert that region to its Step-1 byte span, re-surface, and do NOT commit until the human half is byte-identical. |
| The post-commit citation-integrity gate (`check-pages`) exits non-zero | Repair each listed failure (place the missing inline `[^N]` marker or add the missing `[^N]:` definition) and re-run until exit 0 — never by deleting a definition. The heal is not complete while the gate fails. |
| An orchestrated sub-agent errors out or `halted`s on its source | Record it; continue with the next `plan.files[]` entry. The page keeps its `heal=yes` heal-index row (Step 5 flips only healed pages), so a re-run re-targets only the still-unhealed sources. Surface all in the final report. |
| Manifest `--healing` returns 0 `plan.files` | Nothing to heal — STOP and report any `skipped_not_ingested`/duplicate notes. No edit, no dispatch. |
