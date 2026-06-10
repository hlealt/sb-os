---
name: scribe-shared
description: Shared structural procedures for both finance-wiki scribes (sb-fin-create-thesis and sb-fin-create-decision). Both scribes read this file at the steps that invoke these procedures — never inline the procedures here in each scribe.
---

# Scribe Shared Procedures

Shared structural procedures for `sb-fin-create-thesis` and `sb-fin-create-decision`. Both scribes reference this file; the per-scribe parameters are tabulated below.

## Path Resolution

Both scribes resolve `{wiki_root}` and `{sb_os_path}` identically:

| Symbol | Resolution |
|--------|------------|
| `{wiki_root}` | Read from `sb-os.json` at vault root → `wiki_root` field. Never hardcode. |
| `{sb_os_path}` | Read from `sb-os.json` → `sb_os_path` field. Never hardcode. |

Per-scribe paths derived from these symbols:

| Scribe | Page tree | Leaf index | Cross-link targets |
|--------|-----------|------------|--------------------|
| `sb-fin-create-thesis` | `{wiki_root}/wiki/theses/` | `{wiki_root}/wiki/theses/theses.md` | `{wiki_root}/wiki/entities/organizations/`, `.../assets/`, `.../countries/`, `.../sectors/` |
| `sb-fin-create-decision` | `{wiki_root}/wiki/decisions/` | `{wiki_root}/wiki/decisions/decisions.md` | `{wiki_root}/wiki/theses/`, `{wiki_root}/wiki/entities/organizations/`, `.../assets/` |

## Extension Data Files

Both scribes load the same three extension files (step numbers vary per scribe). Load only the file relevant to the active step.

| File | Thesis steps | Decision steps |
|------|-------------|----------------|
| `{sb_os_path}/finance/wiki-ext/page-types.ext.md` | 1, 2 | 1, 2 |
| `{sb_os_path}/finance/wiki-ext/frontmatter-schemas.ext.md` | 2 | 1, 2 |
| `{sb_os_path}/finance/wiki-ext/section-menus.ext.md` | 2 | 2 |

Base wiki conventions apply to both scribes: read `{sb_os_path}/wiki/workflows/shared/naming-convention.md` (slug), `{sb_os_path}/wiki/workflows/shared/citation-format.md` (footnotes), and `{sb_os_path}/wiki/workflows/shared/folder-structure.md` (lazy folder creation).

## Cross-Link Procedure (Step 3 in both scribes)

For each link field populated in the page's frontmatter, execute these substeps. Per-scribe link fields and target paths are in the Path Resolution table above.

1. Read the target page in full at its scribe-specific path (see Path Resolution table).
2. Locate or create a `Related` section on that page.
3. Append the new wikilink: `- [[<new-page-slug>.md]]`. Before appending, verify the wikilink is not already present — never duplicate an existing cross-link.
4. Update `last-touched: <today>` in the target page's frontmatter.

If a related target page does not exist, skip the cross-link silently for that link and continue with the others. Never create the missing page from within a scribe.

## Leaf-Index Procedure (Step 5 in both scribes)

Update the scribe's leaf index (paths in the Path Resolution table):

1. If the index does not exist, create it with standard `type: index` frontmatter and a `| File | Description |` header (lint owns full leaf-index maintenance; this defensive creation fires only when the index is absent).
2. Append a row for the new page:
   - `File`: `[[<slug-or-filename>.md]]`
   - `Description`: one-line summary (≤280 chars; truncate with ellipsis if longer). For thesis: a summary of the `Claim`. For decision: the action and subject combined (e.g., `Sell Petrobras — dividend thesis weakened by reinvestment shift`).
3. If the index exists with a user-customized column layout, preserve the user's columns and append the new row matching the existing format — fill `File` and the closest equivalent of `Description`; leave other columns blank for lint to populate.

For the `extend` entry point of `sb-fin-create-thesis`: update the existing row's `Description` ONLY if the extend sharpened the `Claim`; otherwise leave the index untouched. Never append a new row for an extend.
