---
name: sb-fin-create-thesis
description: Create or extend a single investment thesis page in the finance-extended wiki layer. Invoked ONLY by the `sb-investor` agent (investor-orchestrated, no separate checkpoint) via two named entry points — authoring a new thesis (`/sb-investor thesis`) and a named `extend` entry point that updates an existing thesis by slug (`/sb-investor review`).
---

# sb-fin-create-thesis

Author a single `thesis` page — a falsifiable investment argument with explicit evidence and invalidation criteria. Thesis pages are authored DELIBERATELY (like topics via `sb-wiki-create-topic`), NEVER auto-created by ingest. This workflow is the `sb-investor` agent's persistence helper — the agent reasons, this workflow persists. It is invoked ONLY in its investor-orchestrated mode; it does NOT auto-fire on standalone user intent ("create a thesis for X"). `/sb-investor thesis` is the sole front door for thesis authoring — that intent routes there, where the agent reasons the thesis and then invokes this workflow. Two named entry points are supported, both investor-orchestrated (Invocation Inputs below):

1. **Authoring (new)** — `/sb-investor thesis` invokes this workflow to persist a NEW thesis the user reasoned through with the agent (optionally promoting a `proposed-new-thesis` entry the agent surfaced). Runs the full create flow (steps 1-5). NO separate checkpoint — the investor's own present-and-confirm step covers the invocation; proceed through the steps without re-prompting. The one carve-out is the Step 1 scope-overlap prompt (the single allowed interrupt — see Step 1).
2. **`extend` (update existing)** — `/sb-investor review` (or any caller that already KNOWS the target page) invokes this workflow to UPDATE an EXISTING thesis by slug: append evidence-against, sharpen invalidation criteria, and bump `status` / `conviction` / `last_reviewed`. The caller passes the existing thesis slug, so this entry point targets that page directly and MUST SKIP the Step 1 scope-overlap discovery prompt (the page is already identified — there is nothing to disambiguate). It appends in place and NEVER creates a new page. NO separate checkpoint. Follow the Step-by-step deltas marked **(extend)** below.

This workflow loads only when `finance` is registered in `sb-os.json` → `wiki_extensions`. It mirrors the `sb-wiki-create-topic` 5-step flow, adapted to the `thesis` page type defined in the finance wiki extension.

## Path Symbols, Extension Files, Cross-Link and Leaf-Index Procedures

Read and follow `../shared/scribe-shared.md` for: path-symbol resolution (`{wiki_root}`, `{sb_os_path}`), extension data files (the three `wiki-ext/` files + base wiki conventions), the Step 3 cross-link procedure, and the Step 5 leaf-index procedure.

This scribe's parameters for the shared procedures:

| Parameter | Value |
|-----------|-------|
| Page tree | `{wiki_root}/wiki/theses/` |
| Leaf index | `{wiki_root}/wiki/theses/theses.md` |
| Cross-link targets (Step 3) | `{wiki_root}/wiki/entities/organizations/`, `.../assets/`, `.../countries/`, `.../sectors/` |
| Extension files step map | `page-types.ext.md` → steps 1, 2; `frontmatter-schemas.ext.md` → step 2; `section-menus.ext.md` → step 2 |
| Leaf-index Description | One-line summary of the `Claim` (≤280 chars; truncate with ellipsis if longer) |

Additional path local to this scribe (not in `scribe-shared.md`):

| Symbol | Resolution |
|--------|------------|
| `{wiki_root}/logs/theses.md` | Thesis-log actionable queue — holds `proposed-new-thesis` and `speculative-thesis-update` entries (investor path). Sibling logs `logs/topics.md` / `logs/mentions.md` hold the base `candidate-topic` / `candidate-mention` entries. |

## Invocation Inputs

| Entry point | Caller | Inputs passed in |
|-------------|--------|------------------|
| Authoring (new) | `sb-investor` agent (`/sb-investor thesis`) | Proposed thesis slug, `proposed-new-thesis` entry timestamp (if promoting one), the shared claim, source filenames, and the investment entity(ies). Workflow resolves the candidate from `logs/theses.md` when a timestamp is passed. |
| `extend` (update existing) | `sb-investor` agent (`/sb-investor review`) | The EXISTING thesis slug (the page to update — this is the named target, NOT a candidate to disambiguate); the new evidence-against items with their source filenames; the sharpened invalidation criteria; the confirmed `status` / `conviction` / `last_reviewed` values. The caller already identified the page, so the scope-overlap discovery prompt is SKIPPED for this entry point. |

## Flow

### Step 1 — Resolve thesis slug and load candidate

**(extend) Mode gate — run FIRST when invoked in the investor-orchestrated `extend` entry point.** The caller passed an EXISTING thesis slug as the named target. Read `{wiki_root}/wiki/theses/{slug}.md` in full — it MUST exist; if it does NOT, halt and surface the conflict (the caller named a page that is absent — never create one here, this entry point only updates). SKIP substeps 2 and 3 entirely: the collision halt is inverted (the page existing is the expected, required state, never a conflict) and the scope-overlap discovery prompt MUST NOT fire (the caller already identified the target — there is nothing to disambiguate). Skip substep 4 (no candidate resolution — the update payload is supplied directly). Proceed to substep 5, then to the **(extend)** deltas in Steps 2-5. For the authoring (new) entry point, ignore this gate and run substeps 1-5 in order.

1. Determine the thesis slug per `{sb_os_path}/wiki/workflows/shared/naming-convention.md` — `lowercase-kebab.md`. The investor passes the slug in; if it arrives non-kebab (e.g., "Petrobras dividend thesis"), derive it (e.g., `petrobras-dividend-thesis`).
2. Verify the slug does NOT already exist as a thesis page at `{wiki_root}/wiki/theses/{slug}.md`. If it exists, halt and surface the conflict to the user — do NOT overwrite. **(extend)** SKIPPED — the named page MUST exist; the `extend` mode gate above already loaded it.
3. **Scope-overlap check (semantic, not slug).** Read `{wiki_root}/wiki/theses/theses.md`. For every existing row, compare its `Description` cell to the proposed `Claim`. When the semantic tier is available (base schema § "Retrieval tiers — hybrid search"), ALSO run `python {sb_os_path}/wiki/scripts/sb-wiki-search.py search "<proposed Claim>" --type thesis --k 5` from the vault root and treat returned thesis pages as overlap candidates the `Description`-cell comparison may have missed (tier unavailable → the cell comparison alone is the check; a helper failure NEVER halts this workflow). If overlap is plausible — same investment entity, same directional claim, same mispricing argument, or the proposed thesis could be framed as a refinement/sibling of an existing one — halt and present three options: **(extend)** SKIPPED — the caller already identified the exact target page, so no disambiguation runs.
   - `extend N` — append to or revise the existing thesis page (e.g., a new `Hypotheses` line, an additional `Evidence for` item, or a sharpened `Claim`) rather than create a new one. The skill exits without writing a new page and emits an `extend` directive the investor acts on.
   - `new` — proceed with a new thesis page; the existing thesis and the new one cross-link as siblings (each lists the other in `related:` frontmatter). Defaults to `new` only if the `proposed-new-thesis` entry recorded an overlap check.
   - `abort` — no writes.
   This check fires for the authoring (new) path — NEVER for the `extend` entry point, which already names its target. Surface it as an inline prompt before commit. Skipping this check on the authoring (new) path is a workflow violation.
4. Determine if invocation is from a candidate or fresh:
   - **From a `proposed-new-thesis` entry** — the investor provides the entry's timestamp. Read `{wiki_root}/logs/theses.md`, locate the `proposed-new-thesis` entry by timestamp + slug (its H2 `<brief>` IS the thesis page slug). Extract: trigger (`recurring-claim` / `mispricing-signal` / `thesis-shaped-page-created`), source filenames, the shared claim, and the investment entity(ies). For a `thesis-shaped-page-created` candidate, ALSO cross-link the originating `kind: thesis` concept page in `related:` and reconcile it (the concept page stays a concept; the new thesis page is the falsifiable record). The `Thesis Invalidation` trigger does NOT arrive here — it produces a `speculative-thesis-update`, which the **(extend)** path resolves, never the authoring path.
   - **Fresh proposal** — no candidate exists. The investor supplies the claim, source filenames, and related entities directly.
5. Read `{sb_os_path}/finance/wiki-ext/page-types.ext.md` to confirm the `thesis` definition and the `status` rule: a thesis cannot reach `status: active` without `Evidence against` and `Invalidation criteria`. A fresh or candidate-derived thesis defaults to `status: seed` unless the user/investor specifies otherwise.

### Step 2 — Write thesis page

Write `{wiki_root}/wiki/theses/{slug}.md`. The `{wiki_root}/wiki/theses/` folder already exists (its index `theses.md` is present); create it only if absent (lazy creation per `{sb_os_path}/wiki/workflows/shared/folder-structure.md`).

**(extend) — update the existing page in place; never rewrite it from scratch.** The page was loaded in the Step 1 mode gate. Apply ONLY the supplied update payload: APPEND each new evidence-against item to the existing `Evidence against` section (preserve every prior item); REVISE the `Invalidation criteria` section with the sharpened criteria; SET `status` / `conviction` / `last_reviewed` in frontmatter to the confirmed values; SET `last-touched: <today>`. Add a citation footnote for each new source per the Body composition rules below. PRESERVE every other section, frontmatter field, and footnote unchanged. The `status: active` gate below still applies — `status: active` requires non-empty `Evidence against` + `Invalidation criteria` (both are guaranteed present on an extended page). Skip the create-only frontmatter block and section-menu selection that follow — they govern authoring a NEW page; the existing page already has its structure.

Frontmatter per `{sb_os_path}/finance/wiki-ext/frontmatter-schemas.ext.md` Thesis schema — the base common block plus the thesis additions:

```yaml
---
type: thesis
created: <today YYYY-MM-DD>
last-touched: <today YYYY-MM-DD>
related:
  - "[[<sibling-thesis-or-triggering-page>.md]]"
tags: [thesis]
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
4. For a `speculative-thesis-update` derived from the **Thesis Invalidation** trigger (the **(extend)** path), frame `Evidence against` around the contradicting source the entry recorded.
5. If the optional `Related companies/assets/sectors/countries` section is included, its wikilinks MUST mirror the `related_*` frontmatter exactly.

### Step 3 — Run the transition script (bookkeeping)

The mechanical bookkeeping from the previous Steps 3–5 (cross-links + `last-touched` bumps, log-entry resolution, leaf-index row) is performed by a single atomic script call. For the behavioral semantics of each operation, read `../shared/scribe-shared.md`.

**Assemble the payload JSON file** (write to a temp file, e.g. `/tmp/scribe_payload.json`):

For **`thesis-new`** (authoring path):

```json
{
  "mode": "thesis-new",
  "slug": "<thesis-slug>",
  "entities": [
    {"kind": "<organizations|assets|countries|sectors>", "slug": "<entity-slug>"},
    ...
  ],
  "log_ref": {"timestamp": "<timestamp>", "slug": "<slug>"},
  "description": "<one-line Claim summary ≤280 chars>"
}
```

- `entities`: one entry per wikilink in `related_companies` / `related_assets` / `related_sectors` / `related_countries`. Omit the array (or pass `[]`) when there are none.
- `log_ref`: include ONLY when promoted from a `proposed-new-thesis` entry; omit for fresh proposals.
- `description`: the one-line summary of the `Claim` for the leaf index row.

For **`thesis-extend`** (extend path):

```json
{
  "mode": "thesis-extend",
  "slug": "<thesis-slug>",
  "new_entities": [
    {"kind": "<organizations|assets|countries|sectors>", "slug": "<entity-slug>"},
    ...
  ],
  "log_ref": {"target_thesis": "<thesis-slug>"},
  "updated_description": "<updated Claim summary ≤280 chars>"
}
```

- `new_entities`: ONLY entities newly introduced by this update payload; omit (or pass `[]`) if none.
- `log_ref`: include ONLY when closing a specific `speculative-thesis-update` entry (identified by its `- target thesis:` wikilink); omit otherwise.
- `updated_description`: include ONLY if the extend sharpened the `Claim`; omit otherwise (index row stays unchanged).

**Run the script** (from the vault root — no `--vault-root` flag needed):

```
python {sb_os_path}/finance/scripts/investimentos/scribe_transition.py --payload /tmp/scribe_payload.json
```

**Read the UN-PIPED exit code.** Do NOT pipe the output (e.g., `… | tee log`) — piping masks the real exit code. Capture stdout separately if needed.

- **Exit 0** — success. Relay the script's report to the user (edits performed + any skips).
- **Exit nonzero** — HALT immediately. Surface the script's error report to the user. NEVER hand-perform the bookkeeping steps silently as a fallback. The user decides how to proceed.

## User Checkpoint

Both entry points are investor-orchestrated: NO separate checkpoint at the scribe. The investor's own present-and-confirm step (in `/sb-investor thesis` for authoring, `/sb-investor review` for extend) covers the invocation. Proceed through steps 1-5 without prompting. The single allowed interrupt is the Step 1 scope-overlap prompt on the authoring (new) path (the `extend` entry point skips it). The investor surfaces that prompt's `extend N` / `new` / `abort` outcome to the user and acts on the choice — it is the scribe's structural authority, never a second checkpoint.

## Failure Modes

| Failure | Behavior |
|---------|----------|
| `{wiki_root}` or `{sb_os_path}` cannot be resolved from `sb-os.json` | Halt before step 1; surface error. No writes. |
| Thesis slug already exists at `{wiki_root}/wiki/theses/{slug}.md` (authoring (new) path) | Halt at step 1; surface conflict. No writes. Does NOT apply to the `extend` entry point — there the page MUST exist. |
| Scope overlap detected with an existing thesis (authoring (new) path) | Halt at step 1; present `extend N` / `new` / `abort`. No writes until the user resolves. The `extend` entry point SKIPS this check (the target is already named). |
| `proposed-new-thesis` timestamp referenced but not found in `logs/theses.md` | Halt at step 1; surface to user — the candidate may have been pruned or never logged. No writes. |
| `extend` entry point invoked but the named thesis page does not exist at `{wiki_root}/wiki/theses/{slug}.md` | Halt at the step 1 mode gate; surface the conflict. No writes — this entry point only updates an existing page, never creates one. |
| Caller attempts `status: active` without `Evidence against` or `Invalidation criteria` | Halt at step 2; require both sections before writing an active thesis (per `page-types.ext.md`). |
| Related entity page named does not exist | Skip cross-link for that entity silently in step 3; continue with the others. |
| `{wiki_root}/wiki/theses/theses.md` index exists with non-standard columns | Preserve user's columns at step 5; append row matching existing format with `File` and closest-equivalent `Description` filled. |
| Script exits nonzero at step 3 | Halt immediately; surface the script's error report to the user. NEVER hand-perform the bookkeeping (cross-links, log resolution, index row) as a silent fallback. The user decides how to proceed. |
| User rejects at the investor's present-and-confirm step | The investor halts before invoking the scribe. No writes. End run. |
