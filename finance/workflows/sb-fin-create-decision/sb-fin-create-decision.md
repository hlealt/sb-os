---
name: sb-fin-create-decision
description: Create a single investment decision page in the finance-extended wiki layer. Two invocation modes — deliberate user-intent authoring (single confirmation checkpoint) and investor-orchestrated authoring (no separate checkpoint).
---

# sb-fin-create-decision

Author a single `decision` page — a dated record of ONE investment action (buy / sell / trim / add / hold / pass / reject / pause / review / rebalance) and the reasoning held at the time. Decision pages are authored DELIBERATELY, NEVER auto-created by ingest. Invocation is intent-driven — no slash command. Two invocation modes are supported:

1. **User-intent-driven** — Claude Code auto-fires this workflow when the user expresses decision-recording intent (e.g., "record my decision to sell X", "log that I'm holding Y", "write a decision page for passing on Z"). SINGLE confirmation checkpoint on the proposed `Decision` + filled sections before writing.
2. **Investor-orchestrated** — The `sb-investor` agent invokes this workflow when the user elects to record a decision the agent reasoned through (B5 decision mode). NO separate checkpoint — the investor's own present-and-confirm step covers this invocation; proceed through steps 1-5 without re-prompting. The named entry point for this mode is **investor-orchestrated invocation** (Invocation Inputs below).

A decision page differs from a thesis page in two ways that this workflow MUST honor:

- **No `active`-gating.** A `thesis` cannot reach `status: active` without `Evidence against` + `Invalidation criteria`. A `decision` has NO `status` field and NO such gate — it is a dated record, written once. Never apply or check a status gate here.
- **Reasoning only — never transaction data.** The page records the action and the reasoning behind it (context, rationale, what was believed, what would prove it wrong, risks, sources, review trigger). The transaction's price and quantity live in the bookkeeper ledger and are NEVER duplicated on the page.

This workflow loads only when `finance` is registered in `sb-os.json` → `wiki_extensions`. It mirrors the `sb-fin-create-thesis` 5-step flow, adapted to the `decision` page type defined in the finance wiki extension.

## Path Symbols, Extension Files, Cross-Link and Leaf-Index Procedures

Read and follow `../shared/scribe-shared.md` for: path-symbol resolution (`{wiki_root}`, `{sb_os_path}`), extension data files (the three `wiki-ext/` files + base wiki conventions), the Step 3 cross-link procedure, and the Step 5 leaf-index procedure.

This scribe's parameters for the shared procedures:

| Parameter | Value |
|-----------|-------|
| Page tree | `{wiki_root}/wiki/decisions/` |
| Leaf index | `{wiki_root}/wiki/decisions/decisions.md` |
| Cross-link targets (Step 3) | `{wiki_root}/wiki/theses/`, `{wiki_root}/wiki/entities/organizations/`, `.../assets/` |
| Extension files step map | `page-types.ext.md` → steps 1, 2; `frontmatter-schemas.ext.md` → steps 1, 2; `section-menus.ext.md` → step 2 |
| Leaf-index Description | One-line summary combining the action and subject (≤280 chars; e.g., `Sell Petrobras — dividend thesis weakened by reinvestment shift`) |

## Invocation Inputs

| Mode | Caller | Inputs passed in |
|------|--------|------------------|
| User-intent | Claude Code auto-fire | The action (`buy \| sell \| trim \| add \| hold \| pass \| reject \| pause \| review \| rebalance`), the asset-or-thesis the decision concerns, and the user's stated reasoning. Workflow derives the slug, filename, and `decision_type`. |
| Investor-orchestrated | `sb-investor` agent | The action, the decision date, the asset-or-thesis subject, the resolved reasoning for each required section, the related thesis/asset/company wikilinks, and the source filenames cited. The investor passes these from its B5 present-and-confirm step. |

## Flow

### Step 1 — Resolve filename and gather inputs

1. Determine the action — one value from the `decision_type` enum in `{sb_os_path}/finance/wiki-ext/frontmatter-schemas.ext.md`: `buy | sell | trim | add | hold | pass | reject | pause | review | rebalance`. If invoked by user intent, infer it from the phrasing; if investor-orchestrated, the caller passes it in.
2. Determine the decision date — today (`YYYY-MM-DD`) unless the caller or user specifies the date the decision was made.
3. Build the filename per the convention in `frontmatter-schemas.ext.md`: `YYYY-MM-DD-<action>-<asset-or-thesis>.md`, where `<action>` is the enum value from substep 1 and `<asset-or-thesis>` is the lowercase-kebab slug of the subject per `{sb_os_path}/wiki/workflows/shared/naming-convention.md` (e.g., `2026-05-28-sell-petrobras.md`). A decision is a dated record — multiple decisions on the same subject coexist as distinct dated files.
4. Verify the filename does NOT already exist at `{wiki_root}/wiki/decisions/{filename}`. If it exists, halt and surface the conflict to the user — do NOT overwrite. (A same-day same-action collision on the same subject means the decision is already recorded; resolve with the user rather than clobbering.) Do NOT run a semantic scope-overlap check — decision pages are dated records, not deduplicated theses; same-subject decisions on different dates are expected and MUST coexist.
5. Resolve the related entity/thesis links the decision concerns: `related_thesis` (the thesis page this decision acts on, if any), `related_asset`, `related_company`. If investor-orchestrated, the caller passes these; if user-intent, derive them from the subject and confirm at the checkpoint.
6. Read `{sb_os_path}/finance/wiki-ext/page-types.ext.md` to confirm the `decision` definition: a dated record of ONE investment action and the reasoning at the time. There is NO `status` field and NO `active`-gating. `decisions/` is NOT an operational log — recurring scope/preference choices belong in `research-policy.md`, never a decision page.

### Step 2 — Write decision page

Write `{wiki_root}/wiki/decisions/{filename}`. Create the `{wiki_root}/wiki/decisions/` folder only if absent (lazy creation per `{sb_os_path}/wiki/workflows/shared/folder-structure.md`).

Frontmatter per `{sb_os_path}/finance/wiki-ext/frontmatter-schemas.ext.md` Decision schema — the base common block plus the decision additions:

```yaml
---
type: decision
created: <today YYYY-MM-DD>
last-touched: <today YYYY-MM-DD>
related:
  - "[[<related-thesis-or-entity>.md]]"
tags: [decision]
date: <decision date YYYY-MM-DD>
decision_type: buy | sell | trim | add | hold | pass | reject | pause | review | rebalance
related_thesis: "[[<thesis-slug>.md]]"
related_asset: "[[<asset-slug>.md]]"
related_company: "[[<company-slug>.md]]"
---
```

`decision_type` MUST match the `<action>` in the filename. Populate `related_thesis` / `related_asset` / `related_company` with the `[[<slug>.md]]` wikilink each concerns; leave any that do not apply blank. There is NO `status`, `conviction`, `time_horizon`, or `watchlist` field — those are thesis-only. NEVER add a `price`, `qty`, `quantity`, or `amount` field — transaction data lives in the bookkeeper ledger.

Section structure per `{sb_os_path}/finance/wiki-ext/section-menus.ext.md` Decision Page entry.

- **Required sections (all nine, in this order):** `Context`, `Decision`, `Related thesis`, `Rationale`, `What I believed at the time`, `What would prove me wrong`, `Acknowledged risks`, `Data and sources used`, `Review trigger`.
- **No optional menu** — the decision page type has none; all nine sections are required and MUST be substantive (never empty placeholders).

Body composition rules:

1. `Context` states the situation that prompted the action; `Decision` states the single action taken (the `decision_type`) in one falsifiable sentence.
2. `Related thesis` links the thesis this decision acts on (`[[<thesis-slug>.md]]`) and one line on how the decision follows from or departs from it; write `None` if the decision is not thesis-anchored.
3. `Rationale` is the reasoning for the action; `What I believed at the time` records the belief state so a future review can audit it against outcomes; `What would prove me wrong` records the falsifier; `Acknowledged risks` records the risks accepted.
4. Record reasoning ONLY. NEVER record the transaction's price, quantity, fees, or position size — they live in the bookkeeper ledger and duplicating them here is a violation.
5. Cite every factual claim with inline `[^N]` markers per `{sb_os_path}/wiki/workflows/shared/citation-format.md`. Append matching `[^N]: [[<source-filename>.md]]` definitions in the `Data and sources used` section. A decision cites the same source pages and entity `## Financials` rows the reasoning rested on.
6. `Review trigger` states the event or date that should reopen this decision (e.g., next earnings, a price level, a thesis-invalidation criterion tripping).

### Step 3 — Run the transition script (bookkeeping)

The mechanical bookkeeping from the previous Steps 3–5 (cross-links + `last-touched` bumps, log-entry resolution, leaf-index row) is performed by a single atomic script call. For the behavioral semantics of each operation, read `../shared/scribe-shared.md`.

**Source-queue entries (script-resolved):** If the user or investor referenced a `{wiki_root}/source-queue.md` entry (e.g., a `gated_pending_access` source the user finally read and acted on), JUDGE agent-side whether the entry is now spent (per that file's own rule — an entry is spent once its wiki source page exists). When spent, do NOT delete it by hand — pass a `source_queue_ref` in the payload and the script retires the entry atomically with the rest of the bookkeeping. Identify the entry by its `url` (authoritative) or, for an entry without a usable URL, its exact `title`. The judgment stays here; only the mechanical deletion is delegated.

**Assemble the payload JSON file** (write to a temp file, e.g. `/tmp/scribe_payload.json`):

```json
{
  "mode": "decision",
  "filename": "<YYYY-MM-DD-action-subject.md>",
  "links": [
    {"kind": "theses", "slug": "<thesis-slug>"},
    {"kind": "organizations", "slug": "<company-slug>"},
    {"kind": "assets", "slug": "<asset-slug>"}
  ],
  "log_ref": {"timestamp": "<timestamp>", "slug": "<slug>"},
  "source_queue_ref": {"url": "<source-queue entry url>"},
  "description": "<action + subject summary ≤280 chars>"
}
```

- `links`: one entry per wikilink in `related_thesis` / `related_asset` / `related_company`. Use `kind: "theses"` for thesis cross-links; `kind: "organizations"` or `kind: "assets"` for entity cross-links. Omit the array (or pass `[]`) when there are none.
- `log_ref`: include ONLY when closing a referenced `{wiki_root}/logs/theses.md` thesis entry; omit otherwise. Supported shapes: `{"timestamp": "...", "slug": "..."}` for a `proposed-new-thesis` / thesis-queue entry, or `{"target_thesis": "..."}` for a `speculative-thesis-update`.
- `source_queue_ref`: include ONLY when retiring a referenced `{wiki_root}/source-queue.md` entry the user acted on; omit otherwise. Supported shapes: `{"url": "<entry url>"}` (authoritative — matched URL-normalized) or `{"title": "<exact entry title>"}` (for an entry without a usable URL). The script deletes the matching H2 block; a not-found ref aborts with no writes. Independent of `log_ref` — both may appear in one payload.
- `description`: the one-line action + subject summary (≤280 chars; e.g., `Sell Petrobras — dividend thesis weakened by reinvestment shift`).

**Run the script** (from the vault root — no `--vault-root` flag needed):

```
python {sb_os_path}/finance/scripts/investimentos/scribe_transition.py --payload /tmp/scribe_payload.json
```

**Read the UN-PIPED exit code.** Do NOT pipe the output (e.g., `… | tee log`) — piping masks the real exit code. Capture stdout separately if needed.

- **Exit 0** — success. Relay the script's report to the user (edits performed + any skips).
- **Exit nonzero** — HALT immediately. Surface the script's error report to the user. NEVER hand-perform the bookkeeping steps silently as a fallback. The user decides how to proceed.

## User Checkpoint

| Mode | Checkpoint behavior |
|------|---------------------|
| User-intent-driven | SINGLE confirmation checkpoint between step 1 and step 2. Present the proposed `Decision`, the filename, the `decision_type`, the filled required sections, and the related thesis/entities to cross-link. The user accepts (proceed to step 2), edits (revise then proceed), or aborts (no writes). |
| Investor-orchestrated | NO separate checkpoint. The investor's own present-and-confirm step covers this invocation. Proceed through steps 1-5 without prompting. |

### User-intent confirmation format

```
DECISION PREVIEW — <filename>

Decision: <one-sentence action — e.g., "Sell the full Petrobras position">

Type: <buy | sell | trim | add | hold | pass | reject | pause | review | rebalance>   Date: <YYYY-MM-DD>

Sections (all required):
- Context
- Decision
- Related thesis
- Rationale
- What I believed at the time
- What would prove me wrong
- Acknowledged risks
- Data and sources used
- Review trigger

Related to cross-link:
- thesis: [[<thesis-slug>.md]]
- asset:  [[<asset-slug>.md]]
- company:[[<company-slug>.md]]

Sources to cite:
- [[<source-1>.md]]
- [[<source-2>.md]]

Note: price/qty are NOT recorded here — they live in the bookkeeper ledger.

Confirm: accept | edit decision | edit sections | abort
```

User response handling:

| Response | Behavior |
|----------|----------|
| `accept` | Proceed to step 2. Commit all writes through step 5. |
| `edit decision` | Prompt the user for the revised action/subject. Re-display the preview. Loop until accept or abort. |
| `edit sections` | Prompt the user for the revised section content. Re-display the preview. Loop until accept or abort. |
| `abort` | Halt. No writes. End run. |

## Failure Modes

| Failure | Behavior |
|---------|----------|
| `{wiki_root}` or `{sb_os_path}` cannot be resolved from `sb-os.json` | Halt before step 1; surface error. No writes. |
| Decision filename already exists at `{wiki_root}/wiki/decisions/{filename}` | Halt at step 1; surface conflict. No writes — do NOT overwrite a recorded decision. |
| Action does not match the `decision_type` enum | Halt at step 1; require a valid enum value before building the filename. |
| `decision_type` frontmatter and `<action>` in the filename disagree | Halt at step 2; reconcile to the same enum value before writing. |
| Any required section would be an empty placeholder | Halt at step 2; require substantive content in all nine sections before writing. |
| Caller attempts to record price / qty / fees / position size | Reject the transaction data at step 2; record reasoning only — transaction data lives in the bookkeeper ledger. |
| Related entity or thesis page named does not exist | Skip cross-link for that link silently in step 3; continue with the others. |
| `{wiki_root}/wiki/decisions/decisions.md` index exists with non-standard columns | Preserve user's columns at step 5; append row matching existing format with `File` and closest-equivalent `Description` filled. |
| Script exits nonzero at step 3 | Halt immediately; surface the script's error report to the user. NEVER hand-perform the bookkeeping (cross-links, log resolution, index row) as a silent fallback. The user decides how to proceed. |
| User aborts at user-intent confirmation checkpoint | Halt before step 2. No writes. End run. |
