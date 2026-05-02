# Wiki Stub Policy

Rules for when to create stubs during ingest and how lint detects stub-state.

## Stub Creation (ingest)

The agent auto-creates a stub Concept or Entity page when the entity/concept name appears in EITHER:

1. **Source title/headline**, OR
2. **An extracted Notable Quote OR a `Substance` bullet** (the agent's own output from step 2 of the ingest workflow)

This rule is deterministic — tied to artifacts the agent has already produced, not to recounting the source.

**If the stub rule does NOT fire:** log a `candidate-mention` entry in `log.md` for periodic review by lint. Do NOT create a page.

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
