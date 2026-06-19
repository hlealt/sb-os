---
name: sb-wiki-ingest-healing
description: Heal a thin or lossy already-ingested wiki source by re-reading the source and EDITING its page in place to the reconstruction standard — augment the agent-authored sections, preserve My take + every human edit byte-identical, never delete or rebuild — then propagate to the graph (concept/entity/topic pages) and strip #reingest. No delete, no rebuild, no AI judge, no no-worse gate.
---

# sb-wiki-ingest-healing

Heals an ALREADY-ingested wiki source: an agent re-reads the source and **edits the existing source page in place** to recover dropped detail and deepen thin sections, then **propagates the recovered substance to the whole graph the source feeds** (its concept, entity, and topic pages). Healing AUGMENTS — it never deletes the page, never rebuilds from scratch, and never discards old content; so there is no old-vs-new regression to gate and **no AI judge, no OD-6 no-worse gate, and no thin-page detector** anywhere in the path. For a PDF source, healing reads the **original PDF** (not the extracted text twin), so it recovers what extraction dropped (e.g. a borderless table the twin could not grid). The healing pass IS the quality check.

This file holds ONLY the healing orchestration. The per-source distillation standard, the existing-page update protocol, the topic-update tiers, the stub-creation rule, and the candidate-topic triggers are `/sb-wiki-ingest`'s — this command RE-RUNS that same machinery additively against the deepened page and NEVER forks a parallel graph builder. The missed-topic-update reconciliation is `/sb-wiki-update-backfill`'s.

## When healing fires

| Trigger | Mode | Owner review |
|---------|------|--------------|
| A **PDF-format** source finishes its FIRST ingest (the auto-heal hook in `/sb-wiki-ingest`) | Automatic, hands-off (PROBATIONARY — see below) | None — rides the first-ingest run's commit |
| The owner runs this command on a chosen page (`/sb-wiki-ingest-healing [targets]`) | On-demand | PREVIEWS the proposed edits before committing |

**PDF auto-heal is PROBATIONARY (owner, 2026-06-19).** `marker` OCR (a table extractor pulled into the FIRST-ingest twin) may make a second automatic healing pass redundant for table recovery. The automatic PDF heal stays ON for now; it is **NECESSARY** if healing consistently recovers material the marker-improved first ingest still drops (borderless tables `marker` cannot grid, chart/figure numbers, whole dropped sections — measurable via the kept calibration/gold set), and **UNNECESSARY → demote to on-demand** (like non-PDF sources) if marker-improved first ingests are consistently faithful. Evaluate during the first real PDF ingests (Batch 5) and the backfill. **Non-PDF sources NEVER auto-fire** — they heal on-demand only (text extraction is lossless, so the first pass is reliable; auto-healing them would cost without gain). This is the only auto-firing behavior; the on-demand path is unaffected.

## Path Resolution

| Symbol | Resolution |
|--------|------------|
| `{wiki_root}` | Read from `sb-os.json` at vault root → `wiki_root` field. Never hardcode. |
| `{sb_os_path}` | Read from `sb-os.json` → `sb_os_path` field. Never hardcode. |
| `{user_context_root}` | Read from `sb-os.json` → `user_context_root`. Never hardcode. |
| `python` | The active interpreter. On this machine system Python is `py -3.12`. |

## Invocation

`/sb-wiki-ingest-healing [origin | file | path …]`.

| Argument shape | Targets resolved |
|----------------|------------------|
| none | Every `#reingest`-tagged page under `{wiki_root}/wiki/sources/**` (Step 1 collects them). A tagged LEAF INDEX (`{origin}.md`) → the whole origin; a tagged SOURCE PAGE → just that file. |
| one bare token naming an origin folder | That origin's sources (run `classify_targets` → `origin` mode). |
| one-or-more raw filenames/paths, or `origin/file`, or ≥2 tokens | Exactly those files (`classify_targets` → `files` mode). |

Target classification is the SAME deterministic `classify_targets` the ingest-all manifest uses — never pre-decide the mode yourself; forward what the user typed.

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
| No judge, no gate, no detector, no LLM-API | There is NO adversarial judge, NO OD-6 no-worse gate, NO thin-page detector, and NO `anthropic`/HTTP/SDK LLM call in this path. Healing is performed by the in-session workflow agent reasoning over the page + source — the healing pass itself is the sole quality check. |
| Commit ownership | An on-demand heal owns its OWN single git commit (it does NOT delegate to `/sb-wiki-ingest-all`). A PDF auto-heal rides the first-ingest run's commit (it is part of that ingest — the auto-heal hook commits nothing of its own). |
| Same-origin serialization | When healing multiple same-origin sources, process them SEQUENTIALLY (one source at a time, exactly as `/sb-wiki-ingest-all` serializes) so two heals never parallel-write a shared concept/entity/topic page. |

## Flow

### Step 1 — Resolve targets

Run from the vault root with the active interpreter. The manifest script CLASSIFIES the targets and reports which are ingested (so you know which pages exist to heal):

```bash
python {sb_os_path}/wiki/scripts/sb-wiki-ingest-all-manifest.py --report {wiki_root}/healing-manifest.json [targets…]
```

- **No args (`#reingest` mode):** do NOT call the manifest with empty targets. First collect every page under `{wiki_root}/wiki/sources/**` whose frontmatter `tags:` contains `reingest` (grep the sources tree for `#reingest` OR a `reingest` tag entry). For each hit: a LEAF INDEX (`{origin}.md`) contributes its whole origin (pass the bare origin name); a SOURCE PAGE contributes its own `origin/stem.md`. De-dup, then pass the union as positional targets to the manifest script. Record the set of tagged leaf indexes — Step 5 strips their marks. If zero `#reingest` marks exist, STOP: "no `#reingest` targets".
- **Explicit args:** forward them VERBATIM as positional targets.

If the script exits non-zero it printed an actionable error (origin/file collision, unresolvable target, bare name matching multiple files). Surface it and STOP — never guess.

Read the JSON. The targets to heal are the source PAGES that CURRENTLY EXIST (a heal edits an existing page in place). A target whose source page is ABSENT cannot be healed — surface it: "no page to heal; ingest it first with `/sb-wiki-ingest`". A `#reingest` origin that resolves to 0 source pages → no-op note. For EACH target to heal, read its existing source page in full NOW and capture its current `[[wikilinks]]` and the EXACT byte span of its `My take` section (and any other human-edited region you can identify) — Step 3 diffs links and Step 4 verifies the human half survived byte-identical.

### Step 2 — Heal the source page in place

For EACH resolved target, process it fully before the next (same-origin serialization). Resolve the raw source from the source page's `raw:` frontmatter and the PDF (if any) from the `Original PDF: [[…]]` body line.

1. **Re-read the source.** Read the actual source in full:
   - **PDF source** → read the **original PDF** natively (the Read tool renders PDF pages; read every page, issuing successive page-range requests when the file exceeds the per-request page limit). The original PDF is the authority — read it, NOT the text twin, so you recover what extraction dropped (borderless tables, chart/figure numbers, whole dropped sections).
   - **Markdown raw source** → read the raw file in full.
   - **Source MISSING** (neither raw nor PDF resolves on disk) → HALT for this target and surface it (never fabricate). Continue with the remaining targets.
2. **Diagnose the gap.** Compare the existing page's agent sections against the source under the reconstruction standard (above). Identify every load-bearing claim, decision rule, quantified fact, tradeoff/comparison table, distinction, named pattern, and author caveat the source carries that the page DROPPED or rendered too thin to reconstruct.
3. **Augment in place — agent sections only.** Edit the existing page to recover the gaps:
   - Deepen `Substance` to the reconstruction standard — add the dropped signal classes in compact form (numbers AS numbers, a comparison kept AS a small table or one-line-per-option list, decision criteria kept AS the rule). Add one Substance unit per major section for a broad multi-section source. Density over length.
   - Route author-flagged limitations / "needs validation" / low-confidence claims to `Counterpoints`; add recovered method/dataset/sample detail to `Methodology`; add recovered verbatim quotations to `Notable quotes`; add recovered cross-links to `Connections` (each with its one-clause *why*).
   - **Append, never overwrite faithful content.** Keep everything already on the page; ADD the recovered detail. Emit inline `[^N]` markers at every newly-written claim and append the matching `[^N]: [[<raw-filename>]]` definitions in `Sources` per `{sb_os_path}/wiki/workflows/shared/citation-format.md` (number locally; lint renumbers).
   - Bump `last-touched: <today>` in frontmatter.
4. **PRESERVE the human half byte-identical.** Do NOT touch `My take` or any hand-edited region — verify (Step 4) that the `My take` byte span captured in Step 1 is unchanged after your edits. If a heal finds nothing to add (the page already reconstructs the source), make a no-op + note rather than a forced edit — no harm.
5. **Re-link discipline.** Confirm every `[[…]]` the healed page emits resolves to an existing page; re-point a link that now dangles at the correct page (the retained re-link discipline) — never leave a link broken.

### Step 3 — Propagate to the graph (additive — reuse the ingest machinery)

The recovered substance must reach the whole graph the source feeds. Re-run the SAME `/sb-wiki-ingest` graph stages against the HEALED page (read and follow `{sb_os_path}/wiki/workflows/sb-wiki-ingest/sb-wiki-ingest.md` for each stage's exact protocol — never restate or override it here), additively:

1. **Existing concept/entity pages — re-evaluate + augment (Step 4, append-only).** Diff the OLD page's `[[wikilinks]]` (captured Step 1) against the HEALED page's. For each linked concept/entity page, check it against the healed page's recovered substance: where the first-ingest page is thin or wrong relative to what the source now says, augment it append-only (never overwrite human prose) — a thin/wrong first-ingest entity must not propagate. This is the SEMANTIC re-evaluation lint does not do.
2. **New concept/entity stubs (Step 5).** The recovered detail may surface entities/concepts the first pass missed. Run the Step-3 cluster + stub-creation rule (mechanical `Substance`-bullet branch + discretionary title/quote branches + the near-duplicate probe) over the HEALED page's new Substance, and CREATE the stubs it warrants at the schema-routed path.
3. **Topic updates + candidate-topic triggers (Steps 4.5 + 6).** Run the firm / speculative / semantic topic-update tiers and the three candidate-topic triggers over the HEALED page, INCLUDING **re-judging the topic suggestions the first ingest emitted** (the recovered substance may now confirm or extend a suggestion the first pass deferred). Apply firm updates append-only; surface speculative/semantic per their default-reject postures (on-demand: in the preview; auto-heal: auto-resolve to the silent defaults).
4. **Reconcile missed topic updates.** Run `/sb-wiki-update-backfill scan` (read and execute `{sb_os_path}/wiki/workflows/sb-wiki-update-backfill/sb-wiki-update-backfill.md`) scoped to the healed source(s) to catch any topic update the per-page stages missed — it is propose-only (zero writes under `wiki/`); apply accepted rows through its append-only apply path.

Append-only protection (`{sb_os_path}/wiki/workflows/shared/stub-policy.md` § "Append-Only Protection") governs every graph edit — NEVER overwrite existing prose on any page.

### Step 4 — Preview / commit boundary

**On-demand run (owner present) → PREVIEW before any commit.** Present a single PREVIEW block listing, per target: the source page edited + a precise summary of what was augmented (which agent sections deepened, which signal classes recovered), the concept/entity pages augmented, the new stubs created, and the topic updates proposed (firm/speculative/semantic in their posture blocks, exactly as `/sb-wiki-ingest` Stage 1 surfaces them). State plainly: "These are edits IN PLACE — no page is deleted or rebuilt; `My take` and every human edit are preserved untouched. Nothing commits until you confirm." Require an explicit `confirm` (or `yes`); on decline / silence / `abort`, STOP and change NOTHING. **Before committing, VERIFY the human half survived:** diff each healed page's `My take` (and captured hand-edited regions) against the Step-1 byte span and confirm BYTE-IDENTICAL — a heal that altered the human half is a defect; revert that region and re-surface. On confirm, make this command's OWN single git commit covering every healed page + graph edit (when the vault is a git repo). Run the post-commit citation-integrity gate (`sb-wiki-lint-deterministic.py check-pages`) over every page the heal wrote or edited, per the `/sb-wiki-ingest` Step-10 gate; repair to exit 0.

**PDF auto-heal (hands-off, fired by the `/sb-wiki-ingest` hook) → NO preview, NO checkpoint.** The healing pass runs the same Steps 1–3 against the just-written page + the original PDF, auto-resolves every decision point to the silent defaults (firm topic updates auto-apply append-only; speculative/semantic/proposed-answers default-reject), still verifies the human half byte-identical, and makes NO commit of its own — its edits ride the first-ingest run's single commit. The owner does not review it (the price of fully hands-off paper ingestion).

### Step 5 — Strip `#reingest` + close-out

For every leaf index that carried a `#reingest` mark consumed this run (the `#reingest`-mode set from Step 1), remove the `#reingest` tag from its frontmatter `tags:` (and any inline `#reingest`). Explicit-arg and auto-heal runs have no marks to strip — skip this for them.

Tell the owner to re-run the triage generator so the dashboard reflects the cleared marks: `python {wiki_root or dashboards path}/wiki-reingest-triage.gen.py` (the triage source of `#reingest` marks is `3-resources/obsidian-dashboards/wiki-reingest-triage.md`; if its generator is not present yet, just note that the marks were stripped).

Report: pages healed (with what each recovered), any targets skipped (no page to heal / source missing), the graph pages augmented + stubs created + topic updates applied, and (on-demand) the single commit. A PDF auto-heal reports its trace into the first-ingest run's return; it adds no second commit.

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
| A `#reingest` origin with 0 source pages | No-op note; strip the mark anyway (Step 5) so it does not re-fire. |
| Owner declines at the on-demand preview | Change NOTHING — no edit commits. The run ends clean. |

## Failure Modes

| Failure | Behavior |
|---------|----------|
| `{wiki_root}` / `{sb_os_path}` unresolvable from `sb-os.json` | Halt before Step 1; surface the error. No edit. |
| Manifest script exits non-zero (collision / unresolvable / multi-match) | Surface its stderr message and STOP — never guess the target. No edit. |
| The source page to heal does not exist on disk | Surface "no page to heal; ingest it first"; skip that target. |
| The source (raw / PDF) the page derives from is missing | HALT for that target and surface it; never fabricate. Continue with the rest. |
| `My take` / a human-edited region differs after the heal | A defect — revert that region to its Step-1 byte span, re-surface, and do NOT commit until the human half is byte-identical. |
| The post-commit citation-integrity gate (`check-pages`) exits non-zero | Repair each listed failure (place the missing inline `[^N]` marker or add the missing `[^N]:` definition) and re-run until exit 0 — never by deleting a definition. The heal is not complete while the gate fails. |
