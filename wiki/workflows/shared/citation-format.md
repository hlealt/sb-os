# Wiki Citation Format

Rules for inline citations and Sources section format. Validated canonical format (p1-3 confirmed Obsidian indexes footnote definitions containing wikilinks in the graph).

## Layers

| Layer | Format | Maintained by |
|-------|--------|---------------|
| Inline in body | `[^N]` at point of claim | Agent (during ingest) |
| Sources section | `[^N]: [[YYYY-MM-DD-slug.md]]` | Agent (during ingest; renumbered by lint) |
| Frontmatter `sources:` | NOT USED | — |

## Citation Targets

- Footnote definitions MUST cite wiki pages — NEVER raw files.
- Concept, entity, and topic pages cite **source pages** (`wiki/sources/`).
- Raw files are referenced ONLY by their 1:1 source page: the `raw:` frontmatter field and that source page's own Sources footnote. No other page links a raw file.

## Footnote Rules

- **One footnote per source** — never merge multiple sources into one footnote definition.
- **Multi-source claims** — multiple markers on the same sentence: `...claim X[^1][^2][^3]`.
- **User prose preservation** — if the user manually added prose context within a footnote definition (e.g., `[^1]: [[file.md]] — note: this is the original`), lint preserves the user prose and only renumbers.
- **Stale removal is REPORT-ONLY** — lint NEVER auto-removes a footnote definition. A definition with no inline reference is mechanically indistinguishable from stub provenance: stubs are born with defs and no inline markers, and later ingests append inline-cited sections while the original def stays unreferenced (the standard stub-then-append shape — 49 live pages at the 2026-06-04 run). Auto-removal strips the page's only graph edge to that source. Lint reports unreferenced defs; removal is a human/LLM hand-reconciliation against the cited sources.
- **Stub-provenance shape** — a page whose definitions have ZERO inline markers is the ingest-built stub shape (frontmatter + preamble + Sources): not a finding at all, NEVER touched.
- **Set mismatches** — inline markers without a matching definition (or duplicate definitions) are content defects: report in the LINT REPORT, never auto-repair.

## Sources Section Format

```markdown
## Sources

[^1]: [[YYYY-MM-DD-slug.md]]
[^2]: [[YYYY-MM-DD-slug.md]]
```

Each `[^N]` definition is a wikilink on its own line. Obsidian indexes wikilinks in footnote definitions in the graph — this is the canonical format (no fallback needed).

## Numbering

Number footnotes locally per page (start from `[^1]` on each page). Lint renumbers across pages as part of its index-sync pass — agents do not need to maintain global numbering.
