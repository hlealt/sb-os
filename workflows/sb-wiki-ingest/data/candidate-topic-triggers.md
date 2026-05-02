# Candidate-Topic Triggers

Three triggers the ingest agent evaluates during step 6. Each trigger that fires produces a `candidate-topic` log entry and surfaces a PROPOSED TOPIC at the Stage 1 checkpoint. Agent NEVER auto-creates topic pages — all topic creation flows through the `sb-wiki-create-topic` skill.

## Trigger Table

| Trigger | Fire condition | Status |
|---------|---------------|--------|
| **Contradiction** | Claims from the new source conflict with claims on an existing wiki page on the same entity/concept AND the scope classification is `same-scope-opposing` | Active day 1 |
| **Evolution** | ≥2 sources with DIFFERENT read/publish dates make divergent claims about the SAME concept/entity | Active day 1 |
| **Cross-application** | Phrase pattern "X for Y" / "X-powered Y" / "using X to do Y" where BOTH X and Y are existing wiki pages (exact wikilink match required, no fuzzy semantic matching) AND ≥2 sources reference the same X-for-Y pairing | Defined; expected low fire-rate until wiki has ≥10 pages |

## Trigger Details

### Contradiction

**Scope classification** — classify every conflict into one of 4 scopes before deciding whether to fire:

| Scope | Meaning | Fire candidate? |
|-------|---------|----------------|
| `same-scope-opposing` | Both claims address the same scope, directly contradict | YES — fire candidate-topic AND add Disputed callout |
| `different-scope` | Claims address different scopes, not directly comparable | NO — log informationally only |
| `temporal-shift` | Claims represent the same entity at different points in time | NO — log informationally only |
| `partial-overlap` | Claims overlap but are not fully opposing | NO — log informationally only |

**On `same-scope-opposing` fire:**
1. Quote BOTH claims verbatim in the candidate-topic log entry (`claim A` and `claim B` fields).
2. Add a `> [!warning] Disputed` callout to the affected concept/entity page (see `../_shared/wiki/section-menus.md` for callout format).
3. Record the candidate for Stage 1 PROPOSED TOPICS block.

### Evolution

**Fire condition:** BOTH required:
- ≥2 sources with DIFFERENT read/publish dates, AND
- Divergent claims about the SAME concept/entity

**Do NOT fire** on single-source temporal phrases alone ("future of X", "next-gen"). The second dated source with a divergent claim is required.

### Cross-application

**Fire condition:** ALL required:
- Phrase pattern: "X for Y", "X-powered Y", or "using X to do Y"
- BOTH X and Y are existing wiki pages — exact wikilink match required (no fuzzy semantic matching)
- ≥2 sources reference the same X-for-Y pairing

Expected low fire-rate until the wiki has ≥10 pages with cross-pollination.

## Disputed Callout Protocol

When Contradiction fires `same-scope-opposing`, the agent ALSO adds a `> [!warning] Disputed` callout to the affected concept/entity page BEFORE the user promotes the candidate. Read `../_shared/wiki/section-menus.md` for the exact callout format.

## Studies Workflow Note

Studies (`/tutor` outputs and multi-source notes) flow `raw/studies/` → source page → distilled into entity/concept/topic pages by ingest. A single study source may produce multiple wiki page types in one ingest run and may fire any of the 3 triggers. There is no separate "user-study trigger" — the 3 triggers above already detect patterns within and across study sources.
