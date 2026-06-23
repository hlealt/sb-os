# Wiki Index Formats

Formats for the two index types maintained in the wiki. Ownership and maintenance rules are included.

## Wiki Sources Index

**File:** `{wiki_root}/wiki/sources/{origin}/{origin}.md`

**Format:**

```markdown
| File | What it says | My take |
|------|--------------|---------|
| [[YYYY-MM-DD-slug.md]] | 1-sentence factual summary (≤280 chars). | 1-sentence opinion: why I cared. |
```

**Ownership rules:**

| Column | Written by | When |
|--------|-----------|------|
| `File` | Agent | During ingest (step 8) |
| `What it says` | Agent | During ingest (step 8) — factual derivative of the source page's `Substance` section |
| `My take` | Agent (derived from source page) | Populated at optional post-commit Stage 2 (step 11) if the user fills the source page; refreshed by lint on each pass per the three-state rule below |

- The source page is canonical; the index entry is derived. The user NEVER writes the index manually.
- Stale-by-7d acceptable for skim purpose. Agents may fall back to reading the source page if deeper signal is needed.
- If the index file does not exist at ingest step 8, create it with the header row and add the first entry.
- `What it says` is judgment-bearing. Scripts MUST NOT create or overwrite it from filenames, headings, or excerpts. If a source-index row is missing, scripts report it as `judgment_needed`; the LLM reads the source page and writes a 1-sentence factual summary.

### `My take` Cell — Three States (NEVER blank)

The `My take` cell encodes one of three explicit states. **Blank is BANNED** as a state marker — every row carries one of the three values below. The two empty states (`pending` and `—`) have different downstream behaviors and different remediations from the user's standpoint; blank conflates them.

| State | Token in cell | Meaning | Source page state |
|-------|---------------|---------|-------------------|
| Pre-reflect | `pending` | Stage 2 was skipped, ignored, or never reached — source page's `My take` body is an empty shell awaiting user action | `My take` heading present, body empty |
| Post-reflect-empty | `—` (em-dash, U+2014) | Stage 2 ran and the user explicitly recorded reflection content without a take. Finalized. | `My take` heading present, body empty while `Open questions` or `Dive deeper` has substantive content |
| Reflected | 1-sentence opinion derived from the source page's `My take` section (≤280 chars; truncate with ellipsis) | The user filled `My take` on the source page | `My take` heading present, body has substantive content |

**Table-safety (reflected previews).** A preview cell MUST never split the 3-column row: flatten wikilinks to their display text BEFORE truncating (a cut mid-`[[target\|alias]]` leaks a raw `|`), then escape any remaining literal `|` as `\|`. Applies to every writer of the cell — agent and script alike.

**Write rules.**

| Trigger | Cell value to write |
|---------|---------------------|
| Ingest step 8 (initial row creation, before Stage 2) | `pending` |
| Stage 2 (step 11) — user declined, ignored, or produced no routed content | `pending` (no change) |
| Stage 2 (step 11) — routed reflection filled `My take` | 1-sentence reflected preview |
| Stage 2 (step 11) — routed reflection filled `Open questions` or `Dive deeper` while `My take` stayed empty (Stage 2 finalization rule) | `—` |
| Lint step 6 re-sync — source page's `My take` body has substantive content | 1-sentence reflected preview (overwrite prior cell value) |
| Lint step 6 re-sync — source page's `My take` body empty AND cell currently reads `—` | Preserve `—` (final, do not age out) |
| Lint step 6 re-sync — source page's `My take` body empty AND cell currently reads `pending` | Preserve `pending` |
| Lint step 6 re-sync — source page's `My take` body empty AND cell currently reads anything else (legacy blank, stray content) | Write `pending` (default to action-pending; safer to over-prompt than to over-finalize) |

**Staleness behavior.** The 7-day staleness rule applies to `pending` rows ONLY. `—` rows are final and do NOT age out. Reflected rows are refreshed every lint pass.

## Raw Index

**File:** `{wiki_root}/raw/{origin}/{origin}.md` (and `{wiki_root}/raw/studies/studies.md`)

**Format:**

```markdown
| File | Title | Date | Wiki |
|------|-------|------|------|
| [[YYYY-MM-DD-slug.md]] | Source title | YYYY-MM-DD | No |
```

**Ownership rules:**

| Column | Written by | When |
|--------|-----------|------|
| `File` | Lint (creates rows) — ingest may add defensively | Lint sweep; ingest may add missing rows |
| `Title` | Lint | On index creation when deterministic from frontmatter or H1; otherwise LLM judgment pass |
| `Date` | Lint | On index creation — ALWAYS the capture date (the filename's `YYYY-MM-DD` prefix), NEVER the source's publication date; LLM judgment pass only when no filename date exists |
| `Wiki` | Agent (ingest sets `Yes`; rollback sets `No`; silent content-duplicate fire sets `Duplicate (of [[<existing-raw>]])`) | Updated during ingest step 7; downgraded to `Partial` if downstream pages are rejected at Stage 1; set to `Duplicate (…)` at step 1.7 (silent) |

- Raw index creation and maintenance is lint's job. Ingest defensively adds a missing row but does NOT create the index file if it is absent (logs a warning for lint).
- `Wiki` values: `No` (default), `Yes` (source page created), `Partial` (source page created but some downstream pages rejected), `Duplicate (of [[<existing-raw>]])` (confirmed content-duplicate of an already-ingested raw — never ingested, skipped by `/sb-wiki-ingest-all` discovery; disposition of the file is the user's call).
- Missing rows are script-safe only when `Title` and `Date` are deterministic. Scripts MUST NOT fill `Title` from a slug guess. Non-deterministic rows are reported as `judgment_needed` for the LLM.

### Row layout authority — `Wiki` is the row's final cell

The raw row's `Wiki` flag is ALWAYS the LAST cell of the row, for BOTH recognized layouts: the 4-col canonical `File|Title|Date|Wiki` and the 3-col legacy `File|Description|Wiki`. Every writer locates `Wiki` by the MATCHED ROW's own width — `len(row) - 1` — NEVER by the header's `index("Wiki")`. This is the locator invariant: a 4-col data row appended under a 3-col legacy header is flipped at its own index 3, never the header's Wiki index 2 (which is the Date cell of the wider row). A row whose width is neither 3 nor 4 is unrecognized — the writer REFUSES to flip it and reports it, never guessing a position. The producer sizes each appended row to the index's ACTUAL header (a legacy 3-col header gets a 3-col row), never a hard-coded 4-col under any header.

### D1 — a PDF source's canonical row keys on the `.pdf`

For a PDF source the raw row keys on the **`.pdf`** (the immutable original); the regenerable `.md` twin (the page rendered by `sb-wiki-pdf-twin.py`, carrying `twin_extractor:` frontmatter, or a legacy `Original PDF:` reference, alongside a same-stem `.pdf`) gets **NO separate row** and is EXCLUDED from the row-adding sweep. Forward invariant: a `Wiki=Yes` PDF row implies a same-named `.md` twin exists. A coexisting `.pdf`+`.md` twin pair is collapsed to the `.pdf` row by lint reconciliation. A dated CLIP `.md` (no `twin_extractor:` / `Original PDF:` and no same-stem `.pdf`, e.g. caiso/engie-brasil daily clips) is NOT a twin and keeps its own row.

### One writer (U2b)

All raw-index structural mutations route through ONE schema-parameterized, name-keyed writer (`build_raw_row` / `set_raw_row_wiki` / `raw_row_wiki_index` / `repair_raw_row_width` in `sb-wiki-index-transaction.py`). The two matchers (`find_row_by_link`, `ingested_raw_filenames`) read the same authority. The writer owns STRUCTURE only (header, row presence, File/Title/Date/Wiki placement, width-correct sizing); judgment cells stay delegated — the leaf-index `Description` derivation helper (`sb-wiki-fill-index-descriptions.py`) remains the companion that derives those cells, and `What it says` / `My take` / `Description` / `Scope` are never written from a slug guess.

## Wiki Leaf Indexes

**Files:** `{wiki_root}/wiki/concepts/concepts.md`, `{wiki_root}/wiki/entities/entities.md`, `{wiki_root}/wiki/topics/topics.md`

**Formats:**

```markdown
| File | Description |
|------|-------------|
| [[concept.md]] | 1-sentence description. |
```

```markdown
| File | Scope |
|------|-------|
| [[topic.md]] | 1-sentence scope. |
```

`Description` and `Scope` are judgment-bearing. Scripts MAY create missing headers and report missing page rows. Scripts MUST NOT add rows with blank `Description` or `Scope`. The LLM reads each page and writes the semantic cell.

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
