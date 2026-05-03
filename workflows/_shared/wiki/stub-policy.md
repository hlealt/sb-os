# Wiki Stub Policy

Rules for when to create stubs during ingest and how lint detects stub-state.

## Stub Creation (ingest)

The agent auto-creates a stub Concept or Entity page when the entity/concept name appears in EITHER:

1. **Source title/headline**, OR
2. **An extracted Notable Quote OR a `Substance` bullet** (the agent's own output from step 2 of the ingest workflow)

This rule is deterministic — tied to artifacts the agent has already produced, not to recounting the source. The Notable Quote branch is qualified by agent discretion (see "Notable Quote stub creation" below).

**If the stub rule does NOT fire:** log a `candidate-mention` entry in `log.md` for periodic review by lint. Do NOT create a page.

## Notable Quote Stub Creation (agent discretion)

The Notable-Quote branch of the stub-creation rule is **agent discretion**, NOT mechanical extraction. A passing mention surfaced inside a Notable Quote does NOT compel a stub.

For each entity/concept name surfaced ONLY by a Notable Quote (not by source title and not by a `Substance` bullet), apply the relevance heuristic before creating a stub:

| Question | If YES | If NO |
|----------|--------|-------|
| Would this stub plausibly become a real concept/entity page given the source context (recurrence, framing weight, the user's known interests)? | Create the stub | Log `candidate-mention` instead |

**Trade-off.** Discretion risks under-stubbing — a stub that would have grown into a real page is deferred to a `candidate-mention`. Mechanical extraction risks bloat — every name dropped inside a quote becomes a shallow stub that never matures.

Discretion wins because lint can later catch missing entity references via broken-wikilink detection (an under-stubbed name surfaces the moment another page tries to link to it), but lint cannot easily prune mass-produced shallow stubs without false positives.

The source-title branch and the `Substance`-bullet branch remain mechanical — those artifacts are short, agent-curated, and high-signal by construction. Only the Notable Quote branch carries discretion.

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
