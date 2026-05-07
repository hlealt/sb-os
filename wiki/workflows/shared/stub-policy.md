# Wiki Stub Policy

Rules for when to create stubs during ingest and how lint detects stub-state.

## Page Granularity (apply BEFORE stub creation, at ingest step 3)

Cluster candidate names into page-level units before deciding how many stubs to create. The mechanical fire rule (Stub Creation §) operates on the cluster representative, NOT on every constituent name. Bullet writers in step 2 must name entities/concepts at page-cluster granularity — sub-cluster names appear in prose without wikilinks.

### Decision tests (apply in order, per pair of candidates)

| # | Test | If YES | If NO |
|---|------|--------|-------|
| 1 | Are they instances of the same family/series differing only in a parameter (version, size, generation, edition, phase, period, era)? | ONE parent page covering variants. A variant gets its own stub ONLY when the source treats it as a standalone subject (≥1 dedicated paragraph or named section). | Continue to test 2. |
| 2 | Is one a whole/system and the other a property/parameter/part that cannot stand independently of the whole? | ONE page (property becomes a section of the whole). | Continue to test 3. |
| 3 | Are they co-members of a group (siblings) co-mentioned but not co-substantive in this source? | ONE group page. Per-member only when standalone treatment exists. | Continue to test 4. |
| 4 | Is one a producer/maintainer/author and the other its product/work? | TWO pages — distinct identities. | TWO pages — independent. |

### Domain-neutral examples

| Test | Source-domain example | Decision |
|------|----------------------|----------|
| 1 (variants) | Two vintages of the same wine | One wine page |
| 1 (variants) | Three editions of the same book | One book page |
| 1 (variants) | Early/middle/late period of one philosopher, artist, or company | One person/company page |
| 1 (variants) | Two model variants of the same architecture family | One model-family page |
| 2 (whole+part) | An architectural style + its load-bearing principle | One style page |
| 2 (whole+part) | A musical form + its required cadence | One form page |
| 2 (whole+part) | An economic indicator + its composition rule | One indicator page |
| 2 (whole+part) | A neural architecture + a structural ratio defining it | One architecture page |
| 3 (siblings) | Three members of one school co-mentioned in passing | One school page (per-member only with standalone treatment) |
| 4 (producer+work) | Author + their novel | Two pages |
| 4 (producer+work) | Company + their product | Two pages |

The clustering decision is the AGENT'S RESPONSIBILITY upstream of mechanical fire. Step 2 substance-bullet writers must respect the cluster set: name only page-level entities/concepts; sub-cluster names go in prose without wikilinks.

## Stub Creation (ingest)

The agent auto-creates a stub Concept or Entity page when the cluster representative appears in EITHER of the two mechanical branches OR fires the Notable-Quote discretion branch:

1. **A `Substance` bullet** (the agent's own output from step 2) — MECHANICAL fire on the cluster representative.
2. **Source title/headline** — fires only when the title name ALSO appears in a `Substance` bullet (see "Title-Branch Rule" below). Title-only names go to discretion.
3. **An extracted Notable Quote** — DISCRETIONARY (see "Notable Quote Stub Creation" below).

If none of the three branches fire, log a `candidate-mention` entry in `log.md` for periodic review by lint. Do NOT create a page.

## Title-Branch Rule

The source title alone does NOT compel a stub. A title hook ("One X and you...", "How Y changed everything", "Z is the new W") often names something the source merely USES rather than discusses. Apply the same relevance heuristic as Notable Quotes for any name that appears ONLY in the title (not in any `Substance` bullet):

| Question | If YES | If NO |
|----------|--------|-------|
| Would this stub plausibly become a real concept/entity page given the source's actual content (recurrence, framing weight, the user's known interests)? | Create the stub | Log `candidate-mention` instead |

Names that appear in BOTH the title AND a `Substance` bullet remain mechanical fire — the bullet branch carries them.

## Notable Quote Stub Creation (agent discretion)

The Notable-Quote branch is **agent discretion**, NOT mechanical extraction. A passing mention surfaced inside a Notable Quote does NOT compel a stub.

For each entity/concept name surfaced ONLY by a Notable Quote (not by source title and not by a `Substance` bullet), apply the relevance heuristic before creating a stub:

| Question | If YES | If NO |
|----------|--------|-------|
| Would this stub plausibly become a real concept/entity page given the source context (recurrence, framing weight, the user's known interests)? | Create the stub | Log `candidate-mention` instead |

**Trade-off.** Discretion risks under-stubbing — a stub that would have grown into a real page is deferred to a `candidate-mention`. Mechanical extraction risks bloat — every name dropped inside a quote becomes a shallow stub that never matures.

Discretion wins because lint can later catch missing entity references via broken-wikilink detection (an under-stubbed name surfaces the moment another page tries to link to it), but lint cannot easily prune mass-produced shallow stubs without false positives.

The `Substance`-bullet branch remains mechanical — those artifacts are short, agent-curated, and high-signal by construction (and now subject to the page-granularity heuristic upstream). The Title and Notable Quote branches carry discretion.

## Stub State (lint detection)

A page is detected as a stub structurally:

| Condition | Stub? |
|-----------|-------|
| Frontmatter + brief preamble (≤2 sentences) + Sources section, but main content sections empty or absent | YES |
| At least 1 main content section has substantive content (>50 words) | NO |

Stubs created via ingest match this definition by construction.

Lint flags stubs aged >30 days.

## User-Half Exemption

Empty user-half sections on Source pages do NOT count toward stub-state. Source pages are stubs only if their agent-half (`Substance` / `Notable quotes` / `Connections`) is empty.

## Append-Only Protection (ingest step 4)

When updating an existing page, NEVER overwrite a main content section that already contains substantive content (>50 words). User-fleshed content is authoritative. Permitted modifications:

- Append a new section when adding a perspective the page does not yet cover
- Add bullets to an existing list section ONLY if the list itself is under 50 words OR explicitly bullet-shaped
- Add `[^N]: [[<raw-filename>]]` footnote definitions to the `Sources` section
- Write a NEW sibling section (e.g., `## How it works — Code Mode perspective`) instead of editing an existing section that exceeds 50 words
