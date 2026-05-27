---
name: create-thesis
description: Create a single investment thesis page in the finance-extended wiki layer. Two invocation modes — deliberate user-intent authoring (single confirmation checkpoint) and investor-orchestrated authoring (no separate checkpoint).
---

# create-thesis

Author a single `thesis` page — a falsifiable investment argument with explicit evidence and invalidation criteria. Thesis pages are authored DELIBERATELY (like topics via `sb-wiki-create-topic`), NEVER auto-created by ingest. Invocation is intent-driven — no slash command. Two invocation modes are supported:

1. **User-intent-driven** — Claude Code auto-fires this workflow when the user expresses thesis-authoring intent (e.g., "create a thesis for X", "write an investment thesis about Y", "promote the {candidate-thesis} candidate"). SINGLE confirmation checkpoint on the proposed `Claim` + selected sections before writing.
2. **Investor-orchestrated** — The `investor` agent invokes this workflow when the user elects to author a thesis from a `candidate-thesis` trigger it surfaced. NO separate checkpoint — the investor's own present-and-confirm step covers this invocation; proceed through steps 1-5 without re-prompting.

This workflow loads only when `finance` is registered in `sb-os.json` → `wiki_extensions`. It mirrors the `sb-wiki-create-topic` 5-step flow, adapted to the `thesis` page type defined in the finance wiki extension.

## Path Resolution

| Symbol | Resolution |
|--------|------------|
| `{wiki_root}` | Read from `sb-os.json` at vault root → `wiki_root` field. Never hardcode. |
| `{sb_os_path}` | Read from `sb-os.json` → `sb_os_path` field. Never hardcode. |
| `{wiki_root}/wiki/theses/` | Thesis page tree. |
| `{wiki_root}/wiki/theses/theses.md` | Theses leaf index. |
| `{wiki_root}/wiki/entities/` | Entity pages cross-linked via `related_*` (companies under `organizations/`; assets, countries, sectors under their lazy subkind folders). |
| `{wiki_root}/log.md` | Actionable queue — holds `candidate-thesis` entries (investor path) alongside base `candidate-topic` / `candidate-mention` entries. |

## Extension Data Files

These finance-extension files codify the thesis frontmatter and sections. Load only the file relevant to the active step.

| File | Used by step |
|------|--------------|
| `{sb_os_path}/finance/wiki-ext/page-types.ext.md` | 1, 2 |
| `{sb_os_path}/finance/wiki-ext/frontmatter-schemas.ext.md` | 2 |
| `{sb_os_path}/finance/wiki-ext/section-menus.ext.md` | 2 |

The base wiki conventions still apply: read `{sb_os_path}/wiki/workflows/shared/naming-convention.md` (slug), `{sb_os_path}/wiki/workflows/shared/citation-format.md` (footnotes), and `{sb_os_path}/wiki/workflows/shared/folder-structure.md` (lazy folder creation) for the conventions shared with the base wiki.

## Invocation Inputs

| Mode | Caller | Inputs passed in |
|------|--------|------------------|
| User-intent | Claude Code auto-fire | Thesis slug or user phrasing ("create a thesis for X" / "promote the {candidate-thesis} candidate"). Workflow resolves the candidate from `log.md` if the user references one. |
| Investor-orchestrated | `investor` agent | Proposed thesis slug, candidate-thesis timestamp, the shared claim, source filenames, and the investment entity(ies) the candidate-thesis recorded. |

## Flow

### Step 1 — Resolve thesis slug and load candidate

1. Determine the thesis slug per `{sb_os_path}/wiki/workflows/shared/naming-convention.md` — `lowercase-kebab.md`. If invoked via user intent and the phrasing is non-kebab (e.g., "Petrobras dividend thesis"), derive the slug (e.g., `petrobras-dividend-thesis`). If invoked by the investor, the slug is passed in by the caller.
2. Verify the slug does NOT already exist as a thesis page at `{wiki_root}/wiki/theses/{slug}.md`. If it exists, halt and surface the conflict to the user — do NOT overwrite.
3. **Scope-overlap check (semantic, not slug).** Read `{wiki_root}/wiki/theses/theses.md`. For every existing row, compare its `Description` cell to the proposed `Claim`. If overlap is plausible — same investment entity, same directional claim, same mispricing argument, or the proposed thesis could be framed as a refinement/sibling of an existing one — halt and present three options:
   - `extend N` — append to or revise the existing thesis page (e.g., a new `Hypotheses` line, an additional `Evidence for` item, or a sharpened `Claim`) rather than create a new one. Skill exits without writing a new page; if invoked user-intent, performs the append directly using the source signals already gathered; if investor-orchestrated, emits an `extend` directive the investor acts on.
   - `new` — proceed with a new thesis page; the existing thesis and the new one cross-link as siblings (each lists the other in `related:` frontmatter). Investor-orchestrated invocation defaults to `new` only if the candidate-thesis entry recorded an overlap check.
   - `abort` — no writes.
   This check fires for BOTH invocation modes. User-intent: surface before the user-intent confirmation checkpoint. Investor-orchestrated: surface as an inline prompt before commit. Skipping this check is a workflow violation.
4. Determine if invocation is from a candidate or fresh:
   - **From candidate-thesis** — the investor provides the candidate-thesis timestamp, OR the user references an existing `candidate-thesis` log entry. Read `{wiki_root}/log.md`, locate the `candidate-thesis` entry by timestamp + slug/entity. Extract: trigger type (Recurring Claim / Mispricing Signal / Thesis Invalidation), source filenames, the shared claim, and the investment entity(ies).
   - **Fresh proposal** — no candidate exists. The caller (or user) supplies the claim, source filenames, and related entities directly.
5. Read `{sb_os_path}/finance/wiki-ext/page-types.ext.md` to confirm the `thesis` definition and the `status` rule: a thesis cannot reach `status: active` without `Evidence against` and `Invalidation criteria`. A fresh or candidate-derived thesis defaults to `status: seed` unless the user/investor specifies otherwise.

### Step 2 — Write thesis page

Write `{wiki_root}/wiki/theses/{slug}.md`. The `{wiki_root}/wiki/theses/` folder already exists (its index `theses.md` is present); create it only if absent (lazy creation per `{sb_os_path}/wiki/workflows/shared/folder-structure.md`).

Frontmatter per `{sb_os_path}/finance/wiki-ext/frontmatter-schemas.ext.md` Thesis schema — the base common block plus the thesis additions:

```yaml
---
type: thesis
created: <today YYYY-MM-DD>
last-touched: <today YYYY-MM-DD>
related:
  - "[[<sibling-thesis-or-triggering-page>.md]]"
tags: []
status: seed | developing | active | rejected | archived
conviction: low | medium | high
time_horizon: short | medium | long
last_reviewed: <today YYYY-MM-DD>
related_companies: []
related_assets: []
related_sectors: []
related_countries: []
related_positions: []
watchlist: false
---
```

Populate `related_companies` / `related_assets` / `related_sectors` / `related_countries` with `[[<entity-slug>.md]]` wikilinks to the matching entity kinds the thesis touches. Leave `related_positions` empty unless the user maps owned positions (by ledger id/ticker). `watchlist` defaults `false`.

Section structure per `{sb_os_path}/finance/wiki-ext/section-menus.ext.md` Thesis Page entry.

- **Required sections (all eight):** `Claim`, `Hypotheses`, `Causal mechanism`, `Evidence for`, `Evidence against`, `Risks`, `Invalidation criteria`, `Sources`.
- **Optional menu (select per the thesis argument and source signals — do NOT include all by default):** `What the market may be mispricing`, `What is consensus`, `Related companies/assets/sectors/countries`, `Relation to portfolio`, `Next questions`.

Body composition rules:

1. Write the `Claim` first — the single falsifiable statement the thesis defends.
2. `Evidence against` and `Invalidation criteria` are MANDATORY and MUST be substantive (never empty placeholders) — they gate `status: active` per `page-types.ext.md`.
3. Cite every claim with inline `[^N]` markers per `{sb_os_path}/wiki/workflows/shared/citation-format.md`. Append matching `[^N]: [[<source-filename>.md]]` definitions in the `Sources` section. A thesis cites entity `## Financials` rows and source pages as evidence via these footnotes.
4. For a candidate-thesis derived from the **Thesis Invalidation** trigger, frame `Evidence against` around the contradicting source the candidate recorded.
5. If the optional `Related companies/assets/sectors/countries` section is included, its wikilinks MUST mirror the `related_*` frontmatter exactly.

### Step 3 — Cross-link related entity pages

For each entity wikilink placed in `related_companies` / `related_assets` / `related_sectors` / `related_countries`:

1. Read the entity page in full at `{wiki_root}/wiki/entities/organizations/{slug}.md` (companies) or `{wiki_root}/wiki/entities/{assets|countries|sectors}/{slug}.md` (assets / countries / sectors).
2. Locate or create a `Related` section on that page.
3. Append the new thesis wikilink: `- [[<thesis-slug>.md]]`.
4. Update `last-touched: <today>` in the entity page's frontmatter.

If a related entity page does not exist, skip the cross-link silently for that entity. Do NOT create the missing entity page from this workflow — entity-page creation is `/sb-wiki-ingest`'s responsibility.

### Step 4 — Resolve the candidate-thesis in the log

The log is an actionable queue; resolution = the thesis page now exists. Do NOT write a `thesis-created` entry.

- **Promoted from a candidate-thesis** — DELETE the matching `candidate-thesis` entry (header + body) from `{wiki_root}/log.md`. Locate it by the timestamp + slug/entity resolved in step 1. The newly created thesis page is now the record.
- **Fresh proposal (no candidate)** — nothing to remove; the log is untouched.

Never write any other entry type.

### Step 5 — Update theses leaf index

Update `{wiki_root}/wiki/theses/theses.md`:

1. The index already exists with a `| File | Description |` header. If it is missing, create it with that header and the standard `type: index` frontmatter (lint owns full leaf-index maintenance; this workflow defensively creates the index if absent).
2. Append a row for the new thesis:
   - `File`: `[[<slug>.md]]`
   - `Description`: a one-line summary of the `Claim` written in step 2 (≤280 chars; truncate with ellipsis if longer).

If the index exists with a user-customized column layout, preserve the user's columns and append the new row matching the existing format — fill `File` and the closest equivalent of `Description`; leave other columns blank for lint to populate.

## User Checkpoint

| Mode | Checkpoint behavior |
|------|---------------------|
| User-intent-driven | SINGLE confirmation checkpoint between step 1 and step 2. Present the proposed `Claim` + selected optional sections + related entities to cross-link. The user accepts (proceed to step 2), edits (revise then proceed), or aborts (no writes). |
| Investor-orchestrated | NO separate checkpoint. The investor's own present-and-confirm step covers this invocation. Proceed through steps 1-5 without prompting. |

### User-intent confirmation format

```
THESIS PREVIEW — <slug>

Claim: <one-sentence falsifiable claim>

Status: <seed | developing | active>   Conviction: <low | medium | high>   Horizon: <short | medium | long>

Proposed sections:
- Claim (required)
- Hypotheses (required)
- Causal mechanism (required)
- Evidence for (required)
- Evidence against (required)
- Risks (required)
- Invalidation criteria (required)
- <optional section, if any>
- Sources (required)

Related entities to cross-link:
- [[<entity-1>.md]]
- [[<entity-2>.md]]

Sources to cite:
- [[<source-1>.md]]
- [[<source-2>.md]]

Confirm: accept | edit claim | edit sections | abort
```

User response handling:

| Response | Behavior |
|----------|----------|
| `accept` | Proceed to step 2. Commit all writes through step 5. |
| `edit claim` | Prompt the user for the revised claim. Re-display the preview. Loop until accept or abort. |
| `edit sections` | Prompt the user for which optional sections to add/remove. Re-display the preview. Loop until accept or abort. |
| `abort` | Halt. No writes. End run. |

## Failure Modes

| Failure | Behavior |
|---------|----------|
| `{wiki_root}` or `{sb_os_path}` cannot be resolved from `sb-os.json` | Halt before step 1; surface error. No writes. |
| Thesis slug already exists at `{wiki_root}/wiki/theses/{slug}.md` | Halt at step 1; surface conflict. No writes. |
| Scope overlap detected with an existing thesis | Halt at step 1; present `extend N` / `new` / `abort`. No writes until the user resolves. |
| Candidate-thesis timestamp referenced but not found in `log.md` | Halt at step 1; surface to user — the candidate may have been pruned or never logged. No writes. |
| User attempts `status: active` without `Evidence against` or `Invalidation criteria` | Halt at step 2; require both sections before writing an active thesis (per `page-types.ext.md`). |
| Related entity page named does not exist | Skip cross-link for that entity silently in step 3; continue with the others. |
| `{wiki_root}/wiki/theses/theses.md` index exists with non-standard columns | Preserve user's columns at step 5; append row matching existing format with `File` and closest-equivalent `Description` filled. |
| User aborts at user-intent confirmation checkpoint | Halt before step 2. No writes. End run. |
