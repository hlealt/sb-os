# Thin-page detector — calibration / validation harness

The keystone the detector calibrates on (OD-1). Built by task **p2-1**; consumed by
**p2-2** (typed-retention), **p2-3** (density + chunked recall), **p2-4**
(escalation ladder + worst-first ranking + AI verifier).

> A weak or unstratified set makes every downstream threshold wobble (OD-1 keystone
> risk, spanning OD-4/5/6/7). Do NOT calibrate any threshold on the held-out **test**
> split — it is the final precision/recall measurement only.

## What's here

| File | Role |
|------|------|
| `silver_ablation.py` | Generator: turns a faithful (page, raw) pair into KNOWN-THIN fixtures by deleting real failure-mode signal classes, emitting exact ground truth. Graded (5/25/50%). |
| `build_gold_set.py` | Validates the hand-checked gold set and merges it into the manifest; reports stratification. |
| `load_manifest.py` | Consumer-side loader for p2-2/2-3/2-4 — read the manifest through this, not by hand. |
| `data/gold-set.yaml` | The hand-checked real gold labels (source of truth for the gold half). |
| `data/ablation-batch.txt` | The faithful pages used as ablation sources. |
| `data/ground-truth-manifest.json` | **The single artifact downstream tasks consume** (ablations + gold). |
| `data/ablated/*.md` | The generated thin fixtures (provenance-stamped; never ingest). |

## The manifest format (`data/ground-truth-manifest.json`)

```jsonc
{
  "schema": "silver-ablation/1",
  "ablations": [ AblationRecord, ... ],   // synthetic thin pages, exact ground truth
  "gold":      [ GoldRecord,      ... ]    // real hand-checked pages
}
```

### `AblationRecord` — a synthetic thin page with exact deleted-signal ground truth

| Field | Type | Meaning |
|-------|------|---------|
| `kind` | `paper\|article\|podcast` | source kind (stratification) |
| `origin` | string | raw origin folder |
| `source_page` | path | the FAITHFUL page that was ablated (vault-relative) |
| `raw_path` | path \| null | the raw the source page derives from |
| `grade` | float | fraction of eligible items deleted (`0.05` / `0.25` / `0.50`) |
| `ablated_page` | path | the produced thin fixture (vault-relative) |
| `source_sha256` | string | sha of the original page bytes (provenance / drift check) |
| `deleted` | list | the ground truth: every deleted item — `{cls, text, section, span:[start,end], note}` |
| `class_counts` | object | per class: `{eligible, deleted}` |
| `label` | `"thin"` | ablated fixtures are thin by construction |

`deleted[].cls` ∈ `numeric` (T2) · `table_row` (T3) · `rule_label` (T4) ·
`named_entity` (T5) · `caveat` (T6) · `reasoning_chain` (an **unmeasured** class —
see OD-6 below). `span` is the `[start, end)` char offset of the deleted text in the
ORIGINAL page (`source_page`). `section` ∈ the compare-set
(`Substance` / `Counterpoints` / `Methodology` / `Notable quotes`).

**How a detector task uses it:** run your detector on `ablated_page`; for each item in
`deleted`, your detector should report that `text` (of class `cls`) is missing. Recall =
fraction of `deleted` items your detector flags. Because grades are strictly monotone
(a higher grade is a strict superset of a lower one — verified per page), the
`uncovered`/severity score MUST increase with `grade` (OD-7 worst-first ranking).

### `GoldRecord` — a real hand-checked page

| Field | Type | Meaning |
|-------|------|---------|
| `page` | path | the real source page (vault-relative) |
| `raw` | path | its raw counterpart |
| `kind` | `paper\|article\|podcast` | source kind |
| `label` | `thin\|faithful` | the hand-checked verdict |
| `split` | `cal\|test` | **calibration** (tune here) vs **test** (HELD OUT — never tune here) |
| `check` | `deep\|signal` | `deep` = page+raw read in full; `signal` = page read + raw structure scanned |
| `missing` | list | (thin) the specific load-bearing items the page dropped vs its raw |
| `retained` | list | (faithful, optional) load-bearing items the page correctly kept |
| `note` | string | optional free-text rationale |

**How a detector task uses it:** run your detector on each gold `page`; a `thin` page
should be FLAGGED, a `faithful` page should NOT. Compute precision/recall on the gold
set; report the **test**-split numbers separately and never tune on them. The `missing`
list is the human-verified target for what a `thin` page's packet should surface.

## Reproduce

```bash
cd <vault-root>
# regenerate the silver fixtures + their ground truth
python 3-resources/tools/sb-os/wiki/scripts/calibration/silver_ablation.py ablate-batch \
  --batch    3-resources/tools/sb-os/wiki/scripts/calibration/data/ablation-batch.txt \
  --grades   0.05,0.25,0.50 \
  --out-dir  3-resources/tools/sb-os/wiki/scripts/calibration/data/ablated \
  --manifest 3-resources/tools/sb-os/wiki/scripts/calibration/data/ground-truth-manifest.json

# validate + merge the hand-checked gold labels, print stratification
python 3-resources/tools/sb-os/wiki/scripts/calibration/build_gold_set.py \
  --gold     3-resources/tools/sb-os/wiki/scripts/calibration/data/gold-set.yaml \
  --manifest 3-resources/tools/sb-os/wiki/scripts/calibration/data/ground-truth-manifest.json

# inspect what one page exposes (no writes)
python 3-resources/tools/sb-os/wiki/scripts/calibration/silver_ablation.py classes \
  --page <a faithful source page>.md
```

## Design notes (read before extending)

- **Compare-set only.** Ablation deletes ONLY from `Substance` + `Counterpoints` +
  `Methodology` + `Notable quotes` (wiki-schema.md), so the ground truth matches what a
  detector reading the same compare-set sees. Frontmatter, the lead paragraph, `My take`,
  and `Sources` are excluded.
- **Real failure-mode classes, never random sentences** (OD-1 guardrail). Numeric atoms,
  table rows, rule/framework labels, named entities, author caveats, and reasoning chains
  — the classes real thin pages actually drop.
- **Thinness signature differs by kind** (OD-1 finding, encoded in `gold-set.yaml`):
  papers go thin by dropping SPECIFIC NUMBERS; podcasts by collapsing NAMED FRAMEWORKS /
  DEFINITIONS / CONTRARIAN TAKES; articles by dropping CONCRETE IMPLEMENTATION DETAIL.
  The gold set carries faithful AND thin examples of every kind so a detector cannot pass
  by learning the kind instead of the omission (the two faithful podcasts —
  `kenneth-berger`, `naomi-gleit` — preserve the exact 6-category structure the thin
  podcasts drop, and are the anti-shortcut anchors).
- **`reasoning_chain` is an UNMEASURED class on purpose** (OD-6 guardrail). The typed-
  retention detector (T2–T6) does not measure reasoning-chain retention; the ablation set
  deletes it anyway (31 deletions across the set) so task 2.2/2.4 can demonstrate the
  OD-6 "a re-do can be worse on an unmeasured class and still pass the mechanical gate"
  case — and ADD a measure for it. It is the bait that proves the mechanical gate's
  measure-list is incomplete.
- **Fixtures are NOT corpus.** They carry a `<!-- SILVER-ABLATION FIXTURE -- DO NOT
  INGEST -->` first line and live only under `data/ablated/`. The generator REFUSES to
  write under `{wiki_root}/wiki/` or `{wiki_root}/raw/`.
- **`data/` is derived calibration data**, not an installed component and not wiki
  content. The sb-os installer never touches it; `/sb-wiki-lint` never walks it.
