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
| `My take` | Agent (derived from source page) | Populated at Stage 2 (step 11) if the user fills the source page; refreshed by lint on each pass |

- `My take` stays BLANK until the user fills the source page's `My take` section. The source page is canonical; the index entry is derived. The user NEVER writes the index manually.
- Stale-by-7d acceptable for skim purpose. Agents may fall back to reading the source page if deeper signal is needed.
- If the index file does not exist at ingest step 8, create it with the header row and add the first entry.

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
| `Title` | Lint | On index creation |
| `Date` | Lint | On index creation |
| `Wiki` | Agent (ingest sets `Yes`; rollback sets `No`) | Updated during ingest step 7; downgraded to `Partial` if downstream pages are rejected at Stage 1 |

- Raw index creation and maintenance is lint's job. Ingest defensively adds a missing row but does NOT create the index file if it is absent (logs a warning for lint).
- `Wiki` values: `No` (default), `Yes` (source page created), `Partial` (source page created but some downstream pages rejected).
