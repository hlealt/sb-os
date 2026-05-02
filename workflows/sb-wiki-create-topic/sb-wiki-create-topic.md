---
name: sb-wiki-create-topic
description: Create a topic page from a candidate or freshly-proposed topic — write `wiki/topics/{slug}.md`, cross-link from triggering pages, append `topic-created` log entry, update topics leaf index. Two invocation modes: mid-ingest acceptance (no separate checkpoint) and user-intent-driven auto-fire (single confirmation checkpoint).
---

# sb-wiki-create-topic

Create a single topic page in the Karpathy-style wiki layer. Implements the 5-step flow defined in the wiki schema. Invocation is intent-driven — no slash command. Two invocation modes are supported:

1. **Mid-ingest acceptance** — Parent `/sb-wiki-ingest` Stage 1 user accepts a PROPOSED TOPIC; ingest invokes this workflow with the proposed topic name. No separate user checkpoint — Stage 1 acceptance covers it.
2. **User-intent-driven auto-fire** — Claude Code auto-fires this workflow when the user expresses topic-creation intent (e.g., "create a topic for X", "promote the {candidate} topic"). Single confirmation checkpoint on proposed sections + scope sentence before writing.

## Schema Source

Read `3-resources/tools/sb-os/docs/wiki-schema.md` — Operations § "sb-wiki-create-topic" — for canonical step definitions. This workflow body implements that spec verbatim. Schema deviations require updating the schema first.

## Path Resolution

| Symbol | Resolution |
|--------|------------|
| `{wiki_root}` | Read from `sb-os.json` at vault root → `wiki_root` field. Resolve via `admin/install/manifest.py` (`manifest.read(vault_root)`). Never hardcode. |
| `{user_context_root}` | Read from `sb-os.json` → `user_context_root`. Never hardcode. |
| `{wiki_root}/wiki/topics/` | Topic page tree. |
| `{wiki_root}/wiki/topics/topics.md` | Topics leaf index. |
| `{wiki_root}/log.md` | Single append-only event log. |

## Shared Data Files

These files codify rules referenced across multiple `sb-wiki-*` workflows. Load only the files relevant to the active step.

| File | Used by step |
|------|--------------|
| `../_shared/wiki/page-types.md` | 1 |
| `../_shared/wiki/frontmatter-schemas.md` | 2 |
| `../_shared/wiki/section-menus.md` | 2 |
| `../_shared/wiki/citation-format.md` | 2 |
| `../_shared/wiki/naming-convention.md` | 2 |
| `../_shared/wiki/folder-structure.md` | 2, 5 |
| `../_shared/wiki/index-formats.md` | 5 |
| `../_shared/wiki/log-entry-shapes.md` | 4 |

## Invocation Inputs

| Mode | Caller | Inputs passed in |
|------|--------|------------------|
| Mid-ingest | `/sb-wiki-ingest` Stage 1 | Proposed topic slug, trigger type, source filenames, claim A + claim B (Contradiction only), parent ingest timestamp |
| User-intent | Claude Code auto-fire | Topic slug or user phrasing ("create a topic for X" / "promote the {candidate} topic"). Workflow resolves the candidate from `log.md` if user references one. |

## Flow

### Step 1 — Resolve topic name and load candidate

1. Determine the topic slug per `../_shared/wiki/naming-convention.md` — `lowercase-kebab.md`. If invoked via user intent and the user phrasing is non-kebab (e.g., "MCP debate"), derive the slug as `mcp-debate`. If invoked mid-ingest, the slug is passed in by the caller.
2. Verify the slug does NOT already exist as a topic page at `{wiki_root}/wiki/topics/{slug}.md`. If it exists, halt and surface the conflict to the user — do NOT overwrite.
3. Verify the slug does NOT collide with an existing `concepts/{slug}.md` or `entities/{slug}.md`. Per `../_shared/wiki/naming-convention.md`, same slug in `concepts/` and `topics/` is FORBIDDEN (and `entities/` and `topics/` is FORBIDDEN). If a collision exists, halt and surface — the user may rename or retire the old slug.
4. Determine if invocation is from a candidate or fresh:
   - **From candidate** — caller provides the parent ingest timestamp OR the user references an existing `candidate-topic` log entry. Read `{wiki_root}/log.md`, locate the `candidate-topic` entry by timestamp + slug. Extract: trigger type, source filenames, claim A + claim B (Contradiction only), parent ingest timestamp.
   - **Fresh proposal** — no candidate exists. Caller (or user) supplies trigger type and source filenames directly. No claim A / claim B unless explicitly provided.
5. Classify the topic shape per `../_shared/wiki/page-types.md` Topic discriminator: `debate` | `comparison` | `landscape` | `decision-frame` | `evolution`. Drives optional section selection in step 2.

### Step 2 — Write topic page

Write `{wiki_root}/wiki/topics/{slug}.md`. Create the `wiki/topics/` folder if it does not exist (lazy creation per `../_shared/wiki/folder-structure.md`).

Frontmatter per `../_shared/wiki/frontmatter-schemas.md` Topic schema (common only — no Topic-specific additions):

```yaml
---
type: topic
created: <today YYYY-MM-DD>
last-touched: <today YYYY-MM-DD>
related:
  - "[[<triggering-page-1>.md]]"
  - "[[<triggering-page-2>.md]]"
tags: []
---
```

Section structure per `../_shared/wiki/section-menus.md` Topic Page entry. Required sections: `Scope`, `Sources`. Optional sections: pick per the topic shape determined in step 1 (debate / comparison / landscape / decision-frame / evolution) using the "When to include" mapping in the shared file.

Body composition rules:

1. Write the `Scope` sentence first. For Contradiction-derived topics, frame the scope around the dispute (e.g., "When MCP earns its complexity vs. when it doesn't"). For Evolution-derived topics, frame around the divergence over time. For Cross-application-derived topics, frame around the X-for-Y pairing.
2. Select optional sections per topic shape from `../_shared/wiki/section-menus.md` Topic Page entry — agent picks per shape AND per source signal. Do NOT include all optional sections by default.
3. Cite every claim with inline `[^N]` markers per `../_shared/wiki/citation-format.md`. Append matching `[^N]: [[<source-filename>.md]]` definitions in the `Sources` section.
4. For Contradiction-derived topics, include claim A and claim B verbatim in the `Key positions / Angles` section, each cited to its source.

### Step 3 — Cross-link from triggering pages

For each triggering concept/entity page (sources of the candidate, or pages explicitly named in the user's intent):

1. Read the page in full at `{wiki_root}/wiki/concepts/{slug}.md` or `{wiki_root}/wiki/entities/{slug}.md`.
2. Locate or create a `Related` section per `../_shared/wiki/section-menus.md` (Concept and Entity optional menus both include `Related`).
3. Append the new topic wikilink: `- [[<topic-slug>.md]]`.
4. Update `last-touched: <today>` in the page's frontmatter.

If a triggering page does not exist (rare — usually the topic emerges from existing pages, but possible for user-intent invocations naming a not-yet-created concept), skip the cross-link silently for that page. Do NOT create the missing page from this workflow — page creation is `/sb-wiki-ingest`'s responsibility.

### Step 4 — Append `topic-created` log entry

Append a `topic-created` entry to `{wiki_root}/log.md` per `../_shared/wiki/log-entry-shapes.md`. Entry is an H2 heading: `## [YYYY-MM-DD HH:MM] topic-created | <slug>`.

Required body fields:

| Field | Value |
|-------|-------|
| `page` | `[[<slug>.md]]` |
| `framing` | The `Scope` sentence written in step 2 |
| `resolves` | `candidate from <YYYY-MM-DD HH:MM>` — ONLY if invoked from a candidate; omit for fresh proposals |
| `from-ingest` | Parent ingest timestamp — ONLY if invoked mid-ingest; omit for user-intent-driven invocations |

Sibling rule per `../_shared/wiki/log-entry-shapes.md`:
- **Mid-ingest invocation** — use the SAME `[YYYY-MM-DD HH:MM]` timestamp as the parent `ingest` entry so cross-references resolve cleanly.
- **User-intent-driven invocation** — use the current timestamp; the entry stands alone (no parent ingest sibling).

### Step 5 — Update topics leaf index

Update `{wiki_root}/wiki/topics/topics.md`:

1. If the index file does not exist, create it with the standard wiki index header row. Topic index format follows the wiki convention (lint owns full leaf-index maintenance, but this workflow defensively creates the index if missing). Use a 2-column format: `| File | Scope |`.
2. Append a row for the new topic:
   - `File`: `[[<slug>.md]]`
   - `Scope`: the `Scope` sentence written in step 2 (≤280 chars; truncate with ellipsis if longer)

If the index file exists with a different column layout (user-customized), preserve the user's columns and append the new row matching the existing format — fill `File` and the closest equivalent of `Scope`; leave other columns blank for lint to populate.

## User Checkpoint

| Mode | Checkpoint behavior |
|------|---------------------|
| Mid-ingest | NO separate checkpoint. Parent `/sb-wiki-ingest` Stage 1 acceptance covers this invocation. Proceed through steps 1-5 without prompting. |
| User-intent-driven | SINGLE confirmation checkpoint between step 1 and step 2. Present the proposed `Scope` sentence + selected optional sections to the user. The user accepts (proceed to step 2), edits (revise then proceed), or aborts (no writes). |

### User-intent confirmation format

```
TOPIC PREVIEW — <slug>

Scope: <one-sentence scope statement>

Proposed sections:
- Scope (required)
- <optional section 1>
- <optional section 2>
- ...
- Sources (required)

Triggering pages to cross-link:
- [[<page-1>.md]]
- [[<page-2>.md]]

Sources to cite:
- [[<source-1>.md]]
- [[<source-2>.md]]

Confirm: accept | edit scope | edit sections | abort
```

User response handling:

| Response | Behavior |
|----------|----------|
| `accept` | Proceed to step 2. Commit all writes through step 5. |
| `edit scope` | Prompt the user for the revised scope sentence. Re-display the preview. Loop until accept or abort. |
| `edit sections` | Prompt the user for which optional sections to add/remove. Re-display the preview. Loop until accept or abort. |
| `abort` | Halt. No writes. End run. |

## Failure Modes

| Failure | Behavior |
|---------|----------|
| `{wiki_root}` cannot be resolved from `sb-os.json` | Halt before step 1; surface error. No writes. |
| Topic slug already exists at `{wiki_root}/wiki/topics/{slug}.md` | Halt at step 1; surface conflict. No writes. |
| Topic slug collides with an existing `concepts/{slug}.md` or `entities/{slug}.md` | Halt at step 1; surface forbidden collision. No writes. |
| Candidate timestamp referenced but not found in `log.md` | Halt at step 1; surface to user — the candidate may have been pruned or never logged. No writes. |
| Triggering page named in user intent does not exist | Skip cross-link for that page silently in step 3; continue with other pages. |
| `{wiki_root}/wiki/topics/topics.md` index file exists with non-standard columns | Preserve user's columns at step 5; append row matching existing format with `File` and closest-equivalent `Scope` filled. |
| User aborts at user-intent confirmation checkpoint | Halt before step 2. No writes. End run. |
