# Ingest extension — Purpose lens (Step 2 / 3 / 3·7b / 10 modulations)

JIT extension loaded by `sb-wiki-ingest.md` ONLY when the focus lens is ON (`{wiki_root}/purpose.md` present and parseable — decided at Step 0.5 in the main flow). When the lens is OFF (absent or malformed `purpose.md`), the main flow never reads this file: no classification, no band, no modulation — every step behaves EXACTLY as today (optionality guarantee #1). Apply each block below at its named site in the main flow. The lens modulates ONLY discretionary surfaces; it NEVER alters a mechanical branch, NEVER drops content, and NEVER suppresses a detected trigger (guarantees #2/#3). The silent-summary purpose-band field lives in the silent-mode extension (`./silent-mode.md` → "Lens — purpose band in the silent summary"), reached only on a silent run.

## Step 2 — classify the source (lens ON only)

**Lens — classify the source (Step 2 open; lens ON only).** With the raw content (Step 1) and parsed purpose (Step 0.5) both available, classify the source into EXACTLY ONE band, keying off the **primary** subject — not incidental mentions (same discipline as the Tecer-relevance axes). Per the schema § "Regulatory layer — purpose.md" → "Classification model":

| Band | Definition | Effect |
|------|------------|--------|
| **in-focus** | Primary subject matches ≥1 `Focus area` | Dial discretionary treatment **UP** (richer) |
| **peripheral** | Not a focus match, but not noise (or hits a `Down-weight signal`) | Baseline; lean terse on discretionary extras — "down-weight, never below baseline" |
| **off-purpose** | Matches **no** `Focus area` (or appears in `Out of purpose`) | Baseline treatment **+ Stage-1 flag** (Step 10); if the user proceeds, treat as peripheral |

Registered `wiki_extensions` page types (e.g. `thesis`, `decision`) are classified too (key off primary subject); `purpose.md` SHOULD cover active-extension domains so extension sources are not spuriously flagged off-purpose. Hold the band for Steps 5, 3·7b, and 10. Lens OFF → no classification; skip this block entirely.

## Step 2 — `Substance` depth dial (lens ON only)

**Lens — `Substance` depth dial (discretionary; lens ON only).** Modulate the discretionary depth/granularity of the `Substance` section and optional-section inclusion by band — the mechanical branches downstream are untouched:

| Band | Discretionary treatment |
|------|-------------------------|
| **in-focus** | Finer granularity, fuller `Substance`; include warranted optional sections (`Notable quotes` / `Methodology` / `Counterpoints`); apply `Quality bar` editorial preferences |
| **peripheral** | Baseline granularity; optional sections only if clearly warranted — never coarsen clustering below baseline (guarantee #4) |
| **off-purpose** | Baseline (becomes peripheral once the user proceeds at Step 10) |

This shapes only the discretionary inputs; the Substance-bullet stub branch (Step 5), trigger detection (Step 6), citations, and indexes are mechanical and untouched (their outputs may shift only as a bounded consequence of these inputs). Lens OFF → write `Substance` and select optional sections exactly as today.

## Step 3 clause 5b — discretionary stub branches (lens ON only)

**Lens — discretionary stub branches (lens ON only; these are the "Step 5 — Create stubs" discretionary branches per the schema's per-step table).** Bias ONLY the relevance heuristic of the two DISCRETIONARY branches above (Title-only, Notable-Quote) by the source's band from Step 2 — the MECHANICAL `Substance`-bullet branch is UNTOUCHED and fires exactly as today:

| Band | Title-only / Notable-Quote heuristic bias |
|------|-------------------------------------------|
| **in-focus** | Lean **fire** (create the stub); apply finer cluster granularity |
| **peripheral** | Lean **demote** to `candidate-mention` |
| **off-purpose** | As peripheral |

The bias only tilts the existing yes/no heuristic — it NEVER fires the mechanical branch differently, NEVER drops a Substance-bullet stub, and NEVER coarsens peripheral clustering below baseline (guarantee #4). A demoted name still lands in `mention-only` (logged `candidate-mention`), so nothing is dropped. Lens OFF → apply the heuristic exactly as clause 5 specifies, no bias.

**Connectivity guard (live-structure promotion) — overrides a lean-demote.** A discretionary stub the band leaned to demote to `candidate-mention` is rescued when it connects to live topic structure. Evaluated at the clause 5c → 6 boundary, reusing the near-duplicate probe clause 5c already ran for EVERY candidate (its topic-page hits are HELD for clause 7b — NO new helper call):

- **Solid topic match → CREATE.** If the name's HELD clause-5c probe hits include an existing TOPIC page at SOLID semantic membership (not weak token overlap), sort the name into `stub-candidates` (create the stub) instead of `mention-only` — it extends live structure. One shared solid-match threshold — tunable; err LOW (keep signal over losing it), above noise level.
- **Orphan floor.** After the guard runs over every discretionary stub of this source, if the source page would STILL land with 0 wiki links, CREATE the single strongest stub anyway (highest topic-match score; else the strongest by the base relevance heuristic). NEVER orphan a source page.
- **Mechanical → batch-safe.** No owner gesture — applies in silent / `ingest-all` mode too, erring toward creation (the safeguard against silent signal loss where no owner can override). Creates only concept/entity stubs, never a topic page.
- **Tier-gated.** Semantic tier unavailable → clause 5c gate 3 was skipped (no held topic hits), so the topic-match rescue is OFF (demote as the band specifies); the orphan floor still fires via the base heuristic's strongest candidate.

## Step 3·7b — speculative ranking (lens ON only)

**Lens — speculative ranking (discretionary; lens ON only).** When the lens is ON, re-rank the qualifying candidates by **focus overlap** (overlap with the source's classified `Focus area`) WITHIN the existing TOP-2 cap: focus overlap orders the list and breaks ties when signal strengths are equal. The firing rules (token overlap ≥2, tier-gated semantic fire, firm-dedupe), the cap of 2, and the silent-drop of overflow are UNCHANGED — the lens only reorders the kept set, never widens it. Lens OFF → rank exactly as above (token fires first by count, semantic-only fires by score).

## Step 10 — Stage 1 presentation (lens ON only)

**Lens — Stage 1 presentation (discretionary; lens ON only).** When the lens is ON, the presentation carries the source's band from Step 2 — the controls, the file-changes table, and trigger DETECTION (Step 6) are all UNCHANGED:

1. **Classification line** — append the band to the preview header: `INGEST PREVIEW — <slug>   [purpose: in-focus | peripheral | ⚠ off-purpose]`.
2. **Off-purpose banner** — when the band is `off-purpose`, prepend the advisory banner below ABOVE the file-changes table. It is ADVISORY only: all standard controls (`accept-all` / `reject N` / `abort`, plus topic decisions) remain available; it NEVER auto-aborts and NEVER suppresses any change.
3. **Trigger presentation priority** — in the PROPOSED TOPICS block, surface in-focus-overlapping triggers FIRST and tag them `focus`; peripheral/off-purpose triggers are surfaced untagged. NO fire is suppressed or reordered out of the list — priority annotation only (the Step 6 detection set is unchanged).

Lens OFF (no `purpose.md`) → NO classification line, NO banner, NO `focus` tags — the preview is IDENTICAL to today.

The `INGEST PREVIEW` verbatim format block stays in the main flow's Step 10 (lens ON appends ` [purpose: …]` to the header line; lens OFF omits it).
