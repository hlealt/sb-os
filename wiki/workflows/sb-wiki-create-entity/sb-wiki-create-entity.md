---
name: sb-wiki-create-entity
description: Create an entity stub from a proposed mention — write the routed `wiki/entities/` page, cite the seed source, remove the resolved `candidate-mention` entries, update the entities leaf index. User-intent invocation with a single confirmation checkpoint. No slash command.
---

# sb-wiki-create-entity

Create a single entity stub in the Karpathy-style wiki layer from a proposed mention (slug + seed source). Implements the 5-step flow defined in the wiki schema. Invocation is intent-driven — no slash command.

**User-intent** — Claude Code auto-fires this workflow when the user expresses entity-creation intent ("create an entity for X", "promote the {slug} entity") OR pastes a dashboard dispatch (`/sb-wiki-create-entity {slug}`, including a space-separated batch). Single confirmation checkpoint before writing.

Ingest stub creation is unchanged and does NOT invoke this skill. `/sb-wiki-query` Step 7b file-back is unchanged. Agent NEVER auto-creates a page from a `candidate-mention`.

## Schema Source

Read `3-resources/tools/sb-os/wiki/docs/wiki-schema.md` — Operations § "sb-wiki-create-entity" — for canonical step definitions. This workflow body implements that spec verbatim. Schema deviations require updating the schema first.

## Path Resolution

| Symbol | Resolution |
|--------|------------|
| `{wiki_root}` | Read from `sb-os.json` at vault root → `wiki_root` field. Resolve via `install/manifest.py` (`manifest.read(vault_root)`). Never hardcode. |
| `{sb_os_path}` | Read from `sb-os.json` → `sb_os_path` field. Never hardcode. |
| `{wiki_root}/wiki/entities/` | Entity page tree. Per-kind subfolders when the parent routing table lists the kind. |
| `{wiki_root}/wiki/entities/entities.md` | Entities leaf index, or router after subdivision. |
| `{wiki_root}/wiki/entities/CLAUDE.md` | Marker-block routing table. Absent → every page lands at the type-folder root. |
| `{wiki_root}/logs/mentions.md` | Actionable queue holding `candidate-mention` entries — the source of the mention this workflow resolves. |

## Shared Data Files

Load only the files relevant to the active step.

| File | Used by step |
|------|--------------|
| `../shared/page-types.md` | 1 |
| `../shared/frontmatter-schemas.md` | 1, 2 |
| `../shared/section-menus.md` | 2 |
| `../shared/citation-format.md` | 2 |
| `../shared/naming-convention.md` | 1, 2 |
| `../shared/folder-structure.md` | 2, 5 |
| `../shared/stub-policy.md` | 2 |
| `../shared/index-formats.md` | 5 |
| `../shared/log-entry-shapes.md` | 4 |

## Invocation Inputs

| Caller | Inputs passed in |
|--------|------------------|
| User intent or dashboard dispatch | Entity slug, or user phrasing ("create an entity for X"). A batch (`/sb-wiki-create-entity slug-a slug-b`) is ONE invocation of this workflow PER slug, each with its own confirmation. Optional seed-source filenames when the log entry has none. |

## Flow

### Step 1 — Resolve entity name and load the mention

1. Determine the slug per `../shared/naming-convention.md` — `lowercase-kebab.md`. If the user phrasing is non-kebab (e.g., "Jeff Hawkins"), derive `jeff-hawkins`. A dashboard dispatch passes the slug already.
2. Read `{wiki_root}/logs/mentions.md`. Collect every `candidate-mention` H2 whose brief (the token after `|`) equals the slug. Read `name:`, `classification:`, `reason:`, and every `seeded-by:` wikilink (`[[<source>.md]]`). Live entries carry `seeded-by:`; the schema example omits it — accept both.
3. If the classification line carries an `OR` between entity and concept, resolve at the checkpoint; a confirmed concept/entity proceeds in THIS workflow. Otherwise classification must be entity (the token after `classification:` starts with `entity`). If it is `concept`, halt and point the user at `sb-wiki-create-concept`. No writes.
4. Kind hint: the leading kind word of the classification parenthetical, with or without the literal `kind:` prefix (`entity (kind: person — …)` and `entity (person — …)` both yield `person`). It MUST be one of the entity enum in `frontmatter-schemas.md` as merged by installed wiki-exts (finance adds `asset` / `country` / `sector` — `finance/wiki-ext/page-types.ext.md`) before step 2 writes. A hint outside that enum (e.g. `organization`) is shown at the checkpoint; the user picks an enum value. Do NOT write a non-enum kind.
5. Seed sources: the deduped `seeded-by:` wikilinks, else filenames the caller passed. If neither exists, halt and ask for one seed source. A stub is born cited — do NOT write an uncited page.
6. **From mention** — at least one matching entry. **Fresh proposal** — no entry; the caller supplies slug, kind, and seed source directly.

### Step 1.5 — Collision and same-referent check

1. Verify the slug does NOT already exist as an entity page anywhere under `{wiki_root}/wiki/entities/` (flat or subfolder). If it exists, halt and surface the conflict — do NOT overwrite. The existing page is the record; offer `use existing` (delete the matching mention entries, step 4 only) or `abort`.
2. Verify the slug does NOT collide with `topics/{slug}.md` or `wiki/theses/{slug}.md`. Per `../shared/naming-convention.md`, same slug in `entities/` and `topics/` is FORBIDDEN. Same slug in `concepts/` and `entities/` is allowed. A forbidden collision halts with no writes.
3. **Same-referent check (semantic, not slug).** When the semantic tier is available (schema § "Retrieval tiers — hybrid search"), run `python {sb_os_path}/wiki/scripts/sb-wiki-search.py search "<name> — <reason or planned sentence>" --type concept,entity,topic --k 8` from the vault root. A helper failure NEVER halts this workflow — the filename checks above are the floor. If a hit denotes the SAME referent (synonym, alias, spelling variant), do NOT create a page. Surface `use existing` or `abort`. A merely related hit, or an uncertain one, proceeds — when in doubt, create (schema § "Near-duplicate probe").

### Step 2 — Write the entity stub

Write the page. Create the destination folder if it does not exist (lazy creation per `../shared/folder-structure.md`).

**Folder placement.** Read the marker block in `{wiki_root}/wiki/entities/CLAUDE.md` (§ "Subfolder routing"). If the confirmed `kind:` is listed as a subfolder's Holds value, write `{wiki_root}/wiki/entities/{subfolder}/{slug}.md`. Otherwise write `{wiki_root}/wiki/entities/{slug}.md`. Absent or unreadable routing table → type-folder root. Validate the kind against that table BEFORE writing (schema § "Ingest routing" and "Near-duplicate probe") — a `kind: tool` must not land in `organizations/`.

Frontmatter per `../shared/frontmatter-schemas.md` (common + entity `kind`):

```yaml
---
type: entity
kind: <enum value>
created: <today YYYY-MM-DD>
last-touched: <today YYYY-MM-DD>
related: []
tags: [entity]
---
```

Section structure per `../shared/section-menus.md` Entity Page. Required only: `What it is`, `Sources`. Do NOT add optional sections — stub-state per `../shared/stub-policy.md`.

Body:

1. `What it is` is ONE factual sentence derived from the mention `name:` and `reason:` (not invented beyond what the mention and its seed source support). It ends with inline `[^N]` markers, one per seed source, per `../shared/citation-format.md`. This sentence is the page lead — do not add a second uncited preamble.
2. `Sources` holds the matching definitions, one footnote per seed source: `[^N]: [[<source-filename>.md]]`. Cite wiki source pages, NEVER raw files.

### Step 3 — Do not edit the seed source

The citation on the new page is the link to the seed source. Do NOT edit the seed source page, and do NOT create any missing page from this workflow. Page creation of anything other than this one entity stub is `/sb-wiki-ingest`'s responsibility.

### Step 4 — Resolve the mention in the log

The log is an actionable queue; resolution = the entity page now exists. Do NOT write an `entity-created` entry.

- **Promoted from a mention** — DELETE every matching `candidate-mention` H2 (header + body) in `{wiki_root}/logs/mentions.md` whose brief equals the slug AND whose classification is entity (or was confirmed entity at the checkpoint). Leave concept-classified entries for the same slug untouched.
- **Fresh proposal (no entry)** — the log is untouched.
- **`use existing`** — the page already existed; still delete the matching entity mention entries (resolution = page exists). No other write.

Never write any other entry type. Per `../shared/log-entry-shapes.md`, only `candidate-topic` and `candidate-mention` are active wiki types.

### Step 5 — Update the entities leaf index

Append a row to the leaf index of the folder the page landed in:

| Page path | Index |
|-----------|-------|
| `wiki/entities/{subfolder}/{slug}.md` | `wiki/entities/{subfolder}/{subfolder}.md` |
| `wiki/entities/{slug}.md` and the parent index is a router (`## Flat pages`) | the `## Flat pages` table in `wiki/entities/entities.md` |
| `wiki/entities/{slug}.md` and the parent index is a flat leaf index | `wiki/entities/entities.md` |

1. If that index file does not exist, create it with frontmatter `type: index` / `tags: [index]` and the header `| File | Description |` (per `../shared/index-formats.md`). Lint owns full leaf-index maintenance; this workflow defensively creates the index if missing.
2. Append `| [[<slug>.md]] | <Description> |`. `Description` is the `What it is` sentence with the `[^N]` marker stripped, wikilinks flattened to display text, literal `|` escaped as `\|`, truncated to ≤280 chars.
3. If the index exists with a different column layout, preserve the user's columns and fill `File` plus the closest equivalent of `Description`; leave other columns blank for lint.

## User Checkpoint

SINGLE confirmation checkpoint between step 1.5 and step 2. Step 1.5's same-referent prompt, when it fires, is a separate prompt before this one.

### Confirmation format

```
ENTITY PREVIEW — <slug>

Kind: <enum value>
Destination: wiki/entities/<path>

What it is: <one sentence>

Seed sources to cite:
- [[<source>.md]]

Mention entries to remove: <N>

Confirm: accept | edit kind | edit sentence | abort
```

| Response | Behavior |
|----------|----------|
| `accept` | Proceed to step 2. Commit all writes through step 5. |
| `edit kind` | User picks an enum value. Re-resolve the destination folder. Re-display. Loop until accept or abort. |
| `edit sentence` | User supplies the revised sentence. Re-display. Loop until accept or abort. |
| `abort` | Halt. No writes. End run. |

## Failure Modes

| Failure | Behavior |
|---------|----------|
| `{wiki_root}` cannot be resolved from `sb-os.json` | Halt before step 1. No writes. |
| Slug already exists under `wiki/entities/` | Halt at step 1.5. Offer `use existing` (step 4 only) or `abort`. Do NOT overwrite. |
| Slug collides with `topics/{slug}.md` or a thesis page | Halt at step 1.5. No writes. |
| Mention classification is concept | Halt at step 1. Point at `sb-wiki-create-concept`. No writes. |
| No seed source on the mention and none passed in | Halt at step 1. Ask for one. No writes. |
| Kind hint is outside the entity enum | Do not write until the checkpoint picks an enum value. |
| Routing table missing | Write at `wiki/entities/{slug}.md`. Continue. |
| Semantic-search helper fails | Filename checks alone are the step 1.5 floor. Continue. |
| User aborts at the confirmation checkpoint | Halt before step 2. No writes. |
