# Wiki Index Formats

Formats for the two index types maintained in the wiki. Ownership and maintenance rules are included.

## Wiki Sources Index

**File:** `{wiki_root}/wiki/sources/{origin}/{origin}.md`

**Format (U11 — unified `File | Description`):**

```markdown
| File | Description |
|------|-------------|
| [[YYYY-MM-DD-slug.md]] | 1-sentence factual summary (≤280 chars). |
```

**Ownership rules:**

| Column | Written by | When |
|--------|-----------|------|
| `File` | Agent | During ingest (step 8) |
| `Description` | Agent | During ingest (step 8) — factual derivative of the source page's `Substance` section |

- The source page is canonical; the index entry is derived. The user NEVER writes the index manually.
- Stale-by-7d acceptable for skim purpose. Agents may fall back to reading the source page if deeper signal is needed.
- If the index file does not exist at ingest step 8, create it with the header row and add the first entry.
- `Description` is judgment-bearing. Scripts MUST NOT create or overwrite it from filenames, headings, or excerpts. If a source-index row is missing, scripts report it as `judgment_needed`; the LLM reads the source page and writes a 1-sentence factual summary.

**My take is NOT an index column (U11).** The user's reflection lives canonically in the source PAGE BODY `## My take` section (created/offered by ingest step 2; filled at Stage 2 or later in Obsidian). The wiki sources index carries NO `My take` column — it was a derived preview with no programmatic reader (~2.7% of rows ever carried an authored take), so it was dropped. The source-page body section is untouched.

**Migration (U11, lint-owned).** A legacy 3-column `| File | What it says | My take |` index is migrated to the 2-column `| File | Description |` by `/sb-wiki-lint`: the header and separator become the 2-col form, each data row's `What it says` text is preserved verbatim as `Description`, and the `My take` cell is dropped. Migration is idempotent — a row already in the 2-col form is left byte-stable. A user-customized / bespoke leaf-index layout (one that is neither the canonical 3-col legacy nor the 2-col unified shape) is REPORTED, never force-rewritten.

**Table-safety.** A `Description` cell MUST never split the row: flatten wikilinks to their display text, then escape any remaining literal `|` as `\|`. Applies to every writer of the cell — agent and script alike.

## Raw Index

**File:** `{wiki_root}/raw/{origin}/{origin}.md` (and `{wiki_root}/raw/studies/studies.md`)

**Format (ADX-9/ADX-10 — `File | Wiki`):**

```markdown
| File | Wiki |
|------|------|
| [[YYYY-MM-DD-slug.md]] | No |
```

The summary column (the `Title` of the old 4-col `File|Title|Date|Wiki`, the `Description` of the legacy 3-col `File|Description|Wiki`) AND the `Date` column are both DROPPED — neither had any programmatic reader, the `Date` duplicated the filename's `YYYY-MM-DD` prefix, and the publish date already lives in source-page frontmatter post-ingest.

**Ownership rules:**

| Column | Written by | When |
|--------|-----------|------|
| `File` | Lint (creates rows) — ingest may add defensively | Lint sweep; ingest may add missing rows |
| `Wiki` | Agent (ingest sets `Yes`; rollback sets `No`; silent content-duplicate fire sets `Duplicate (of [[<existing-raw>]])` for a markdown re-clip, or `Original (twin: [[<existing-raw>]])` for a kept PDF original) | Updated during ingest step 7; downgraded to `Partial` if downstream pages are rejected at Stage 1; set to `Duplicate (…)`/`Original (twin: …)` at step 1.7 (silent) |

- Raw index creation and maintenance is lint's job. Ingest defensively adds a missing row but does NOT create the index file if it is absent (logs a warning for lint).
- `Wiki` values: `No` (default), `Yes` (source page created), `Partial` (source page created but some downstream pages rejected), `Duplicate (of [[<existing-raw>]])` (confirmed content-duplicate of an already-ingested raw — never ingested, skipped by `/sb-wiki-ingest-all` discovery; disposition of the file is the user's call), `Original (twin: [[<existing-raw>]])` (a KEPT original whose content is already in the wiki via a non-same-stem twin — e.g. a source PDF ingested as a separate dated `.md` twin; never re-ingested, never treated as deletable, skipped by `/sb-wiki-ingest-all` discovery, and — distinct from `Duplicate` — needs NO user disposition). The two are deliberately distinct words: a sweep keying on "duplicate" must NOT match a kept original.
- A new row is always `| [[file]] | No |` — fully deterministic (File + Wiki only), so there is no `judgment_needed` path for a missing raw row.
- **Legacy migration (lint-owned).** `/sb-wiki-lint` migrates a legacy 4-col `File|Title|Date|Wiki` or 3-col `File|Description|Wiki` raw index to the 2-col `File|Wiki`: header + separator become the 2-col form, each row collapses to `| [[file]] | <Wiki-value> |` (the `Wiki` value — the LAST cell — preserved verbatim; the summary + date cells dropped). Idempotent — a 2-col index is left byte-stable. A bespoke/garbled header, or a row whose last cell is not a recognized `Wiki` value, is REPORTED, never force-rewritten.

### Row layout authority — `Wiki` is the row's final cell

The raw row's `Wiki` flag is ALWAYS the LAST cell of the row, for ALL recognized layouts: the 2-col canonical `File|Wiki`, the 4-col legacy `File|Title|Date|Wiki`, and the 3-col legacy `File|Description|Wiki`. Every writer locates `Wiki` by the MATCHED ROW's own width — `len(row) - 1` — NEVER by the header's `index("Wiki")`. This is the locator invariant: a legacy 4-col data row appended under a 3-col header is flipped at its own index 3, never the header's Wiki index 2 (the Date cell of the wider row); a 2-col row flips at index 1. A row whose width is none of 2/3/4 is unrecognized — the writer REFUSES to flip it and reports it, never guessing a position. The producer sizes each appended row to the index's ACTUAL header, never a hard-coded width under any header.

### D1 — a PDF source's canonical row keys on the `.pdf`

For a PDF source the raw row keys on the **`.pdf`** (the immutable original); the regenerable `.md` twin (the page rendered by `sb-wiki-pdf-twin.py`, carrying `twin_extractor:` frontmatter, or a legacy `Original PDF:` reference, alongside a same-stem `.pdf`) gets **NO separate row** and is EXCLUDED from the row-adding sweep. Forward invariant: a `Wiki=Yes` PDF row implies a same-named `.md` twin exists. A coexisting `.pdf`+`.md` twin pair is collapsed to the `.pdf` row by lint reconciliation. A dated CLIP `.md` (no `twin_extractor:` / `Original PDF:` and no same-stem `.pdf`, e.g. caiso/engie-brasil daily clips) is NOT a twin and keeps its own row.

**Non-same-stem PDF twin (the kept-original case).** When a source PDF's content was ingested as a SEPARATE, NON-same-stem `.md` twin (a dated `.md` with its own `Wiki=Yes` row and no `twin_extractor:` marker — so D1 auto-collapse does not recognize the pair), the `.pdf` keeps its OWN row marked `Wiki = Original (twin: [[<the .md twin>]])`. Both rows coexist: the twin `.md` carries `Yes`, the `.pdf` carries `Original (twin: …)`. This marks the PDF as a kept original — never re-ingested, never deletable — WITHOUT calling it a `Duplicate`. Lint preserves both cells (it never flips a non-`No` cell). Migrating such a pair to canonical D1 form (rename the twin same-stem, add the `twin_extractor:` marker, flip the `.pdf` to `Yes`, drop the twin row, repoint citations) is a manual call, not automatic — it may break source-page citations that name the twin filename.

### One writer (U2b)

All raw-index structural mutations route through ONE schema-parameterized, name-keyed writer (`build_raw_row` / `set_raw_row_wiki` / `raw_row_wiki_index` / `repair_raw_row_width` in `sb-wiki-index-transaction.py`). The two matchers (`find_row_by_link`, `ingested_raw_filenames`) read the same authority. The writer owns STRUCTURE only (header, row presence, File/Wiki placement — and the legacy Title/Date/Description cells it still recognizes for migration, width-correct sizing); judgment cells stay delegated — the leaf-index `Description` derivation helper (`sb-wiki-fill-index-descriptions.py`) remains the companion that derives those cells, and `Description` (the unified sources/topics/concepts/entities judgment cell, U11) is never written from a slug guess.

## Wiki Leaf Indexes

**Files:** `{wiki_root}/wiki/concepts/concepts.md`, `{wiki_root}/wiki/entities/entities.md`, `{wiki_root}/wiki/topics/topics.md`

**Format (U11 — `File | Description` for all four leaf-index families):**

```markdown
| File | Description |
|------|-------------|
| [[concept.md]] | 1-sentence description. |
```

`Description` is judgment-bearing. Scripts MAY create missing headers and report missing page rows. Scripts MUST NOT add rows with a blank `Description`. The LLM reads each page and writes the semantic cell.

**Topics migration (U11, lint-owned).** The topics leaf index (`topics.md`) was formerly `| File | Scope |`. `/sb-wiki-lint` migrates it to `| File | Description |`: the header/separator become the `Description` form and each row's `Scope` text is preserved verbatim as `Description`. Idempotent — an already-migrated topics index is left byte-stable. The topic PAGE's required `Scope` section (schema § "Topic page") is unchanged — only the INDEX column renames.

## Type-Folder Router Index (post-subdivision)

When a type folder (`wiki/concepts/` or `wiki/entities/`) has at least one per-kind subfolder, the parent index `{type}.md` is rewritten as a ROUTER pointing to the subfolder leaf indexes plus a flat-pages section. Per-kind subfolders are created by `/sb-wiki-lint` per schema § "Folder subdivision".

**File:** `{wiki_root}/wiki/{type}/{type}.md` (e.g., `wiki/entities/entities.md`).

**Format:**

```markdown
---
type: index
tags: [wiki, entities]
---

# entities

Wiki entity pages — specific named things. Subfolders below group pages by `kind:` per schema § "Folder subdivision". Filenames `lowercase-kebab.md`.

## Subfolders

| Subfolder | Holds | Index |
|-----------|-------|-------|
| [[ai-models]] | `kind: model` | [[ai-models.md]] |
| [[persons]] | `kind: person` | [[persons.md]] |
| [[organizations]] | `kind: company` | [[organizations.md]] |

## Flat pages

Pages whose `kind:` has not graduated to a subfolder (count <10).

| File | Description |
|------|-------------|
| [[json.md]] | JSON is a text-based structured data interchange format. |
| [[toon.md]] | TOON is a JSON-compatible notation for LLM token reduction. |
```

**Ownership rules:**

| Section | Written by | When |
|---------|-----------|------|
| Subfolders table | Lint | At step 7.5 subdivision execution; rewritten on every subsequent lint pass to reflect current subfolder set |
| Flat pages table | Lint | Same — rebuilt every lint pass; rows for kinds without subfolders |

Pre-subdivision, the type-folder index keeps the simple `| File | Description |` (or `| File | Scope |`) format from § "Wiki Leaf Indexes" above. The router format above replaces it ONLY after the first per-kind subfolder is created.

## Type-Folder Managed CLAUDE.md (post-subdivision)

When subdivision occurs, `/sb-wiki-lint` creates or updates `{wiki_root}/wiki/{type}/CLAUDE.md` with marker-block routing rules. Inside `<!-- sb:start v=1 -->...<!-- sb:end -->` is sb-os-managed (rewritten every lint pass); outside the markers is preserved verbatim.

**File:** `{wiki_root}/wiki/{type}/CLAUDE.md` (e.g., `wiki/entities/CLAUDE.md`).

**Format:**

```markdown
[User-authored content here is preserved across lint passes.]

<!-- sb:start v=1 -->
# entities/

Per-kind subfolders host pages whose `kind:` has crossed the subdivision threshold (≥10 pages). Pages below the threshold stay flat at this folder's root.

## Subfolder routing

| Subfolder | Holds (`kind:` value) | Note |
|-----------|----------------------|------|
| `ai-models/` | `model` | Domain prefix — "models" is generic across domains |
| `persons/` | `person` | — |
| `organizations/` | `company` | Renamed from `companies/` for inclusivity |

## Flat pages

Pages with kinds not listed above (count <10) stay at this folder's root.

## Indexes

- `entities.md` — router (this folder); points to each subfolder's leaf index.
- `{subfolder}/{subfolder}.md` — leaf index per subfolder (`| File | Description |`).

## Ingest routing

`/sb-wiki-ingest` step 5 reads this routing table to decide where new stubs go. Kinds with a subfolder write to `{type}/{subfolder}/{slug}.md`; other kinds write to `{type}/{slug}.md`.
<!-- sb:end -->
```

**Ownership rules:**

| Region | Written by | Updated when |
|--------|-----------|--------------|
| Inside markers (`<!-- sb:start v=1 -->...<!-- sb:end -->`) | Lint | Every subdivision execution; rebuilt on each lint pass to reflect current subfolders |
| Outside markers | The user | Never touched by sb-os |

The marker-block content is REGENERATED on every lint pass — direct edits inside the markers are lost. To customize, edit outside the markers.
