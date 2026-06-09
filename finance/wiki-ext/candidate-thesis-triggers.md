# Candidate-Thesis Triggers

> [!info] Investor-Path Triggers — General Ingest Wiring Deferred
> This file defines candidate-thesis triggers for the **investor path only**. The investor path (`/sb-investor research` B2 + `/sb-investor review` B3) is the intended consumer — these triggers are evaluated when the investor processes raw sources. The investor path is BUILT and wired to evaluate them; end-to-end liveness is pending live verification of the research/review pipelines. Wiring into **general ingest** is **DEFERRED** — it is an open question per spec §12 whether candidate-thesis detection belongs in general ingest or exclusively in the investor path. This file is **NOT part of the Step 0 merge list** (general ingest/lint merge only `page-types.ext.md`, `frontmatter-schemas.ext.md`, `section-menus.ext.md`, and `lint-rules.ext.md`). General ingest does NOT fire these triggers; the investor path does.

Four triggers the investor path evaluates when processing raw sources. Each trigger that fires WRITES a thesis-log entry to `{wiki_root}/logs/theses.md` and surfaces it to the user. The four triggers map to the TWO thesis-log entry types (`proposed-new-thesis` / `speculative-thesis-update`) per the Entry-type column below; emit each entry in the canonical shape defined in `{sb_os_path}/wiki/workflows/shared/log-entry-shapes.md` § Entry Shapes. The investor path NEVER auto-creates thesis pages — all thesis creation/extension flows through the `sb-fin-create-thesis` capability (see `./page-types.ext.md` for the `thesis` page type definition).

## Trigger Table

| Trigger | Fire condition | Entry type written | Status |
|---------|---------------|--------------------|--------|
| **Recurring Claim** | ≥2 dated sources (different read/publish dates) assert a directional claim about the SAME investment entity (asset/company/sector/country) AND the claim is falsifiable and specific (not a general observation) | `proposed-new-thesis` | Wired (investor path) — pending live verification |
| **Mispricing Signal** | A source explicitly frames a price divergence as a mispricing AND at least one prior source or wiki page establishes a reference valuation for the same entity — both dated | `proposed-new-thesis` | Wired (investor path) — pending live verification |
| **Thesis Invalidation** | A source contradicts or materially weakens a claim in an EXISTING `thesis` page (i.e., a document in `theses/`) with direct, dated evidence — not a routine price move or news item without causal framing | `speculative-thesis-update` | Wired (investor path) — pending live verification |
| **Thesis-Shaped Page Created** | An ingest pass on the investor path creates or updates a CONCEPT page carrying `kind: thesis` AND no existing `type: thesis` page in `theses/` covers the claim | `proposed-new-thesis` | Added 2026-06-04 — pending live verification |

A `proposed-new-thesis` entry's H2 `<brief>` MUST be the proposed thesis page slug (lint resolves/prunes it by filename against `wiki/theses/` pages — resolution = page exists). A `speculative-thesis-update` carries NO filename-prune contract; its `- target thesis:` wikilink identifies the existing thesis page the proposed change applies to, and lint NEVER auto-prunes it (it ages + surfaces it as awaiting an investor decision). Use the SAME timestamp for sibling entries emitted in one processing run.

## Trigger Details

### Recurring Claim

**Fire condition — ALL required:**
- ≥2 sources with DIFFERENT read/publish dates
- Both address the SAME investment entity (exact entity match — wiki-link level, no fuzzy matching)
- The shared claim is directional and falsifiable (e.g., "X is undervalued", "Y sector will benefit from Z"), not a general survey or definition

**Do NOT fire** on a single-source temporal phrase alone ("X is expected to grow"), on generic market commentary, or on claims about different entities that happen to share a topic.

**On fire:** WRITE a `proposed-new-thesis` entry to `{wiki_root}/logs/theses.md` — H2 `<brief>` = the proposed thesis page slug; `- thesis:` the shared claim (one line); `- trigger: recurring-claim`; `- sources:` the two-or-more source wikilinks; `- promote via: sb-fin-create-thesis`. Present as a PROPOSED THESIS candidate. The user decides whether to initiate thesis authoring via `sb-fin-create-thesis`.

### Mispricing Signal

**Fire condition — ALL required:**
- A source uses explicit mispricing framing ("undervalued", "overvalued", "price dislocated from fundamentals", or equivalent)
- At least one prior source OR an existing wiki entity page already references a valuation anchor (e.g., P/E range, NAV estimate, analyst target) for the SAME entity
- Both items are dated (the signal source AND the reference valuation source)

**Do NOT fire** on valuation opinions without a reference anchor, or on macro commentary framing an entire asset class without a specific entity. A news item alone is never a mispricing signal — it requires the valuation anchor.

**On fire:** WRITE a `proposed-new-thesis` entry to `{wiki_root}/logs/theses.md` — H2 `<brief>` = the proposed thesis page slug; `- thesis:` the mispricing claim and direction (one line); `- trigger: mispricing-signal`; `- sources:` the signal source AND the reference-valuation source wikilinks; `- promote via: sb-fin-create-thesis`. Present as a PROPOSED THESIS candidate.

### Thesis Invalidation

**Fire condition — ALL required:**
- An existing `thesis` page exists in `theses/` for the same entity
- The new source contains direct, dated evidence that contradicts or materially weakens a specific claim in that thesis
- The contradiction is causal or evidential — not a routine price move or a news item without explanatory framing connecting it to the thesis claim

**Do NOT fire** on price volatility alone, on news unrelated to the thesis's stated invalidation criteria, or when the source merely updates a data point without challenging the thesis logic.

**On fire:** WRITE a `speculative-thesis-update` entry to `{wiki_root}/logs/theses.md` — H2 `<brief>` = the existing thesis slug; `- target thesis:` the wikilink to that existing thesis page; `- trigger: thesis-invalidation`; `- change:` the specific claim challenged / proposed change (one line); `- source:` the contradicting source wikilink; `- apply via: sb-fin-create-thesis extend`. Present as a PROPOSED THESIS INVALIDATION — a speculative update that NEVER auto-applies and that lint NEVER auto-prunes. The user decides whether to update, demote, or archive the thesis.

### Thesis-Shaped Page Created

**Fire condition — ALL required:**
- An ingest pass on the investor path creates or updates a CONCEPT page carrying `kind: thesis` (a thesis-shaped claim filed as a concept — detected from the ingest sub-agent summaries / post-ingest report)
- No existing `type: thesis` page in `theses/` already covers the claim — when one does, do NOT fire; suggest a cross-link instead

**Do NOT fire** on `type: thesis` pages themselves, or on concept pages without `kind: thesis`.

**On fire:** WRITE a `proposed-new-thesis` entry to `{wiki_root}/logs/theses.md` — H2 `<brief>` = the proposed thesis page slug; `- thesis:` the claim from the page's Definition (one line); `- trigger: thesis-shaped-page-created`; `- sources:` the page's cited source filenames as wikilinks (also note the originating `kind: thesis` concept page wikilink); `- promote via: sb-fin-create-thesis`. Present as a PROPOSED THESIS candidate. The user decides whether to promote via `sb-fin-create-thesis` — the concept page is NEVER hand-migrated; promotion authors a proper thesis page through the scribe, which cross-links and reconciles the concept page.

## Studies Workflow Note

Investment sources flowing through `raw/` → source page → ingest may produce any of these triggers when the investor path is active. A single investment-focused study source may fire more than one trigger in a single processing run. These triggers are investment-domain analogues of the base `candidate-topic-triggers.md` — they do not replace or extend the base triggers; both sets coexist when the finance extension is loaded and wired.
