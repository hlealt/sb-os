# Candidate-Topic Triggers

Three triggers the ingest agent evaluates during step 6. A fired trigger produces a `candidate-topic` log entry and a Stage-1 PROPOSED TOPIC **only when it clears the Granularity Gate below**; below the bar the tension is captured at lower granularity (a Disputed callout or a home-page citation) and NO candidate is logged. Agent NEVER auto-creates topic pages — all topic creation flows through the `sb-wiki-create-topic` skill.

## Trigger Table

| Trigger | Fire condition | Status |
|---------|---------------|--------|
| **Contradiction** | Claims from the new source conflict with claims on an existing wiki page on the same entity/concept AND the scope classification is `same-scope-opposing` | Active day 1 |
| **Evolution** | ≥2 sources with DIFFERENT read/publish dates make divergent claims about the SAME concept/entity | Active day 1 |
| **Cross-application** | Phrase pattern "X for Y" / "X-powered Y" / "using X to do Y" where BOTH X and Y are existing wiki pages (exact wikilink match required, no fuzzy semantic matching) AND ≥2 sources reference the same X-for-Y pairing | Defined; expected low fire-rate until wiki has ≥10 pages |

## Granularity Gate — topic vs. lower-granularity capture

Bias: GENERAL, durable topics (a broad conversation that accretes over time) over narrow one-off clashes whose substance a single existing page already holds. A fired trigger logs a `candidate-topic` ONLY when it clears the durability bar; below the bar it is captured at lower granularity and logged as NO candidate. (Canonical spec: `../../../docs/wiki-schema.md` § "Topic creation rules" → "Granularity gate".)

**Durability bar — log a `candidate-topic` when ANY ONE holds:**

| # | Condition | How to count (mechanical) |
|---|-----------|---------------------------|
| 1 | **Accretion ≥3 sources** — ≥3 distinct sources have engaged the tension (a multi-voice debate / landscape / trajectory), not a 2-source one-off | Count distinct SOURCES engaging the tension, NOT the number of sides — a binary debate carried by many sources clears (e.g. a 30-source "is X true?" debate), a 2-source clash does not. Per trigger: **Contradiction** → the sources cited on the affected page for the opposing claims, plus the new source(s); **Evolution** → the distinct dated sources in the trajectory; **Cross-application** → the distinct sources referencing the X-for-Y pairing. ≥3 → clears. |
| 2 | **Question-anchored** (escape hatch) | The tension answers a registered `{wiki_root}/questions.md` entry. |
| 3 | **Owner-requested** (escape hatch) | The owner explicitly asks for that specific topic. |

**Below the bar → NO `candidate-topic`. Lower-granularity capture (unconditional — added regardless of the gate):**

| Trigger | Lower-granularity capture |
|---------|---------------------------|
| Contradiction | The `> [!warning] Disputed` callout on the affected concept/entity page. |
| Evolution | Both dated sources cite the home concept/entity page (firm-tier topic-update or the page's own `Substance`). No new marker. |
| Cross-application | No candidate; the two pages cite their sources normally. The X-for-Y pairing re-detects on the next ingest. |

**Graduation is automatic at ingest.** The callout/citation is the live record; when a later source pushes the distinct-source count to ≥3 (bar #1), the trigger re-fires on that ingest and proposes the topic THEN — no owner presence and no separate lint pass needed (batch-safe). This applies to all three triggers: a 2-source contradiction, a 2-source evolution, and a 2-source cross-application each wait for their 3rd distinct source.

## Trigger Details

### Contradiction

**Scope classification** — classify every conflict into one of 4 scopes before deciding whether to fire:

| Scope | Meaning | Fire candidate? |
|-------|---------|----------------|
| `same-scope-opposing` | Both claims address the same scope, directly contradict | Add Disputed callout ALWAYS; log a candidate-topic ONLY if the Granularity Gate clears |
| `different-scope` | Claims address different scopes, not directly comparable | NO — log informationally only |
| `temporal-shift` | Claims represent the same entity at different points in time | NO — log informationally only |
| `partial-overlap` | Claims overlap but are not fully opposing | NO — log informationally only |

**On `same-scope-opposing` fire:**
1. Add a `> [!warning] Disputed` callout to the affected concept/entity page (see `../shared/section-menus.md` for callout format) — ALWAYS, independent of the gate.
2. Apply the **Granularity Gate** (bar #1 counts distinct SOURCES engaging the tension on the affected page — a many-sourced binary debate clears; a 2-source clash does not). Clears (≥3 distinct sources, OR question-anchored, OR owner-requested) → log a `candidate-topic` (quote BOTH claims verbatim in the `claim A` / `claim B` fields) and record it for the Stage 1 PROPOSED TOPICS block. Below the bar → the callout is the complete capture; log NO candidate.

### Evolution

**Fire condition:** BOTH required:
- ≥2 sources with DIFFERENT read/publish dates, AND
- Divergent claims about the SAME concept/entity

**Do NOT fire** on single-source temporal phrases alone ("future of X", "next-gen"). The second dated source with a divergent claim is required.

**On fire, apply the Granularity Gate.** Clears at ≥3 distinct DATED datapoints on the concept (counting those the page already cites, plus this source) — OR question-anchored OR owner-requested → log a `candidate-topic`. A bare 2-point change does NOT clear it: both sources cite the home page (no new marker) and NO candidate is logged; the 3rd dated datapoint graduates it.

### Cross-application

**Fire condition:** ALL required:
- Phrase pattern: "X for Y", "X-powered Y", or "using X to do Y"
- BOTH X and Y are existing wiki pages — exact wikilink match required (no fuzzy semantic matching)
- ≥2 sources reference the same X-for-Y pairing

Expected low fire-rate until the wiki has ≥10 pages with cross-pollination. **On fire, apply the Granularity Gate** (bar #1): log a `candidate-topic` ONLY when ≥3 distinct sources reference the X-for-Y pairing — a 2-source pairing is suppressed (no candidate) and re-detected when a 3rd source lands. The pairing's two pages X and Y are definitional, not a durability signal — cross-application earns a topic by source accretion, like the other triggers.

## Disputed Callout Protocol

When Contradiction fires `same-scope-opposing`, the agent ALSO adds a `> [!warning] Disputed` callout to the affected concept/entity page BEFORE the user promotes the candidate (this happens regardless of the Granularity Gate). Read `../shared/section-menus.md` for the exact callout format.

## Studies Workflow Note

Studies (`/tutor` outputs and multi-source notes) flow `raw/studies/` → source page → distilled into entity/concept/topic pages by ingest. A single study source may produce multiple wiki page types in one ingest run and may fire any of the 3 triggers. There is no separate "user-study trigger" — the 3 triggers above already detect patterns within and across study sources.
